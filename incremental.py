# -*- coding: utf-8 -*-
"""好单库京东线报「增量刷新」常驻脚本。

策略：
- 只在好单库接口上轮询最新线报，**只处理没见过的新线报**
- 来一条就转链一条、落盘一条、部署一条（不做整批重建）
- 首次运行会把当前能抓到的线报 id 存为基线，避免把历史线报全量补一遍

用法：
    python incremental.py            # 常驻轮询（默认 3 分钟一轮）
    python incremental.py --once     # 只跑一轮
    python incremental.py --init     # 重建基线（把当前线报标记为已见，不入库）
    python incremental.py --interval 120
"""
import json
import atexit
import os
import subprocess
import sys
import time

import build_site
import cf_kv
import jp_convert as jd_convert  # 精品库转链引擎（drop-in 替换京东联盟版）

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.join(BASE_DIR, "site")
SEEN_FILE = os.path.join(BASE_DIR, "seen_ids.json")
PENDING_FILE = os.path.join(BASE_DIR, "pending.json")
DTK_SEEN_FILE = os.path.join(BASE_DIR, "seen_dtk.json")
DTK_PENDING_FILE = os.path.join(BASE_DIR, "pending_dtk.json")
LOCK_FILE = os.path.join(BASE_DIR, "monitor.lock")
STATE = {"ok": 0, "fail": 0, "skipped": 0}
DEBOUNCE = 20  # 防抖窗口：KV 直写便宜又即时，20s 内的变更合并成一次写
MAX_DEALS = 6000  # 站上最多保留条数（7天×约800条/天，防数据无限膨胀的最终闸门）
RETAIN_DAYS = 7  # 保留最近 7 天（Boss 2026-09-07：如 1-7 号的数据，在 8 号那天清掉 1 号的）
DIRTY = {"flag": False, "since": 0.0, "note": ""}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def git_push(tag):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    cmds = [
        ["git", "add", "-A"],
        ["git", "commit", "-m", tag],
    ]
    for c in cmds:
        subprocess.run(c, cwd=BASE_DIR, capture_output=True, env=env)
    # 三路重试：直连 → 50111 → 7890
    for proxy in (None, "http://127.0.0.1:50111", "http://127.0.0.1:7890"):
        c = ["git", "push", "origin", "main"]
        if proxy:
            c = ["git", "-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}",
                 "push", "origin", "main"]
        r = subprocess.run(c, cwd=BASE_DIR, capture_output=True, env=env)
        if r.returncode == 0:
            return True
    return False


def persist(deals):
    """只生成本地页面与数据文件（不推送）。"""
    cfg = load_json(os.path.join(BASE_DIR, "config.json"), {})
    html = build_site.build_html(deals, cfg, STATE)
    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    save_json(os.path.join(SITE_DIR, "deals.json"), deals)


def mark_dirty(note):
    """标记有待推送的变更；首次标记时开始计防抖窗口。"""
    if not DIRTY["flag"]:
        DIRTY["since"] = time.time()
        DIRTY["note"] = note
    DIRTY["flag"] = True


def flush_if_due(force=False):
    """防抖到期（或 force）就 KV 直写一次（即时生效，免 CF 构建）；
    KV 失败退回 git 推送兜底。"""
    if not DIRTY["flag"]:
        return
    waited = time.time() - DIRTY["since"]
    if not force and waited < DEBOUNCE:
        log(f"防抖中：{int(DEBOUNCE - waited)}s 后合并推送")
        return
    deals = load_json(os.path.join(SITE_DIR, "deals.json"), [])
    ok, msg = cf_kv.put_deals(deals)
    if ok:
        log(f"KV 直写上线（防抖 {int(waited)}s，共 {len(deals)} 条）")
        DIRTY["flag"] = False
        return
    log(f"KV 直写失败：{msg}，尝试 git 兜底")
    if git_push(f"fallback: kv fail {DIRTY['note']}"):
        log("git 兜底推送成功")
        DIRTY["flag"] = False
    else:
        DIRTY["since"] = time.time()
        log("KV 与 git 都失败，已重置防抖窗口，下轮重试")


def poll_dtk(deals, have_ids):
    """大淘客淘宝线报：抓页面新线报 → 转链（红线：转不上不上站）→ 返回插入条数。

    注：失败直接放弃、不重试——页面客户端会缓存「已转链」状态（isLoad），
    点过的卡再点不再调转链 API（缓存秒弹「文案复制成功」），重试必失败；
    且 Boss 明令旧的不要，页面卡池也只留最新 12 张。"""
    import dtk_convert
    dtk_seen = set(load_json(DTK_SEEN_FILE, []))
    first_run = not dtk_seen
    inserted = 0
    d = None
    try:
        # 首选纯 API：页面 DOM 的自动刷新会被 Chrome 冻结（断连 30s 标签即冻结，
        # 再连上 DOM 还是旧的）导致淘宝「假死」；xb-list 接口裸调即可用，永不冻结
        tips = dtk_convert.fetch_tips_api()
        if tips is None:
            d = dtk_convert.Dtk()
            tips = d.fetch_tips()
        if not tips:
            return 0

        def key_of(t):
            return dtk_convert.to_deal(t, None)["id"]

        # 首次运行（Boss 明令）：页面上现存的全部记为基线跳过，只上之后新出的
        if first_run:
            for t in tips:
                dtk_seen.add(key_of(t))
            save_json(DTK_SEEN_FILE, sorted(dtk_seen))
            log(f"淘宝基线已建立：现存 {len(tips)} 条全部跳过，只收之后新出的")
            return 0

        fresh = [t for t in tips if key_of(t) not in dtk_seen and key_of(t) not in have_ids]
        # v4 纯 API 直调版：转链不发页面请求，无需 reload（列表自动更新，只读不写，
        # 屏幕上不会再出现大淘客页面反复刷新）
        fresh = fresh[:3]  # 单轮上限：转链队列慢（实测 5~45s/条），防单轮过久饿着京东

        def handle(t):
            """转链并入库；成功返回 True。"""
            nonlocal inserted
            out = dtk_convert.convert_tip(t)
            if not out:
                return False
            deal = dtk_convert.to_deal(t, out)
            deal["_addedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")  # 入站时间，前端用它算「X分钟前」
            deals.insert(0, deal)
            have_ids.add(deal["id"])
            dtk_seen.add(deal["id"])
            inserted += 1
            log(f"淘宝线报已转链落盘 {deal['id']} | {deal['list'][0]['content'][:26]}")
            return True

        for t in fresh:
            k = key_of(t)
            if k in dtk_seen:
                continue
            log(f"新淘宝线报 {k} | {t['title'][:30]}")
            if not handle(t):
                log("  淘宝转链失败，放弃（不上站，旧线报不重试）")
            save_json(DTK_SEEN_FILE, sorted(dtk_seen))
            time.sleep(3)  # 单条间隔，防风控

        save_json(DTK_SEEN_FILE, sorted(dtk_seen))
    except Exception as e:
        log(f"淘宝线报本轮异常：{str(e)[:120]}")
    finally:
        if d:
            d.close()
    return inserted


def has_link(deal):
    """判定线报是否含商品/券链接。纯文字、无任何链接的（如「促销取消了，先忽略」）
    对导购无意义，应忽略且不收录。淘宝线报（淘口令形态）没有 http 链接，放行：
    只要带 _originalContext（转链成品）就有效。"""
    for it in deal.get("list", []) or []:
        for key in ("item_id", "coupon_url", "content"):
            v = it.get(key) or ""
            if isinstance(v, str) and v.startswith("http"):
                return True
    if deal.get("_originalContext") or deal.get("_formatContext"):
        return True
    return False


def fetch_latest(cfg, pages=2):
    """抓最新若干页，返回 [(wire_id, normalize后的deal)]，按时间正序。"""
    out, seen = [], set()
    for p in range(1, pages + 1):
        try:
            items = build_site.fetch_page(cfg, p)["data"].get("items") or []
        except Exception as e:
            log(f"第{p}页抓取失败: {e}")
            break
        for it in items:
            wid = str(it.get("wire_id"))
            if not wid or wid in seen:
                continue
            seen.add(wid)
            d = build_site.normalize(it)
            # 只要京东，且必须带链接（纯文字无链接的直接忽略）
            if str(d.get("platform")) == "2" and has_link(d):
                out.append(d)
        time.sleep(0.4)
    out.sort(key=lambda d: d.get("time", ""))
    return out


def acquire_single_instance():
    """单实例锁：已有监控在跑时本实例直接退出（防双开互踩覆盖 deals.json）。"""
    import psutil
    if os.path.exists(LOCK_FILE):
        try:
            old = int(open(LOCK_FILE, encoding="utf-8").read().strip())
            if old != os.getpid():
                p = psutil.Process(old)
                if p.is_running() and "python" in (p.name() or "").lower():
                    log(f"已有监控实例在跑（PID {old}），本实例退出")
                    sys.exit(0)
        except (psutil.NoSuchProcess, ValueError, ProcessLookupError):
            pass  # 旧实例已死，锁过期，接管
        except Exception:
            pass
    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(LOCK_FILE) and os.remove(LOCK_FILE))


def main():
    acquire_single_instance()
    args = sys.argv[1:]
    once = "--once" in args
    do_init = "--init" in args
    interval = 180
    if "--interval" in args:
        try:
            interval = int(args[args.index("--interval") + 1])
        except Exception:
            pass

    cfg = load_json(os.path.join(BASE_DIR, "config.json"), {})
    cfg.setdefault("crawl", {}).setdefault("page_size", 20)

    seen = set(load_json(SEEN_FILE, []))

    if do_init or not seen:
        latest = fetch_latest(cfg)
        seen = {str(d["id"]) for d in latest}
        save_json(SEEN_FILE, sorted(seen))
        log(f"基线已建立：当前 {len(seen)} 条记为已见，不入库。之后只处理新出现的线报。")
        if do_init:
            return

    log(f"开始轮询：间隔 {interval}s，只处理新线报（每轮从磁盘重新载入，保留已转链结果）")
    while True:
        try:
            # 每轮从磁盘重新载入，确保 convert_two.py / deploy 写回的转链结果不被覆盖
            deals = [d for d in load_json(os.path.join(SITE_DIR, "deals.json"), []) if has_link(d)]
            have_ids = {str(d.get("id")) for d in deals}
            latest = fetch_latest(cfg)
            fresh = [d for d in latest if str(d["id"]) not in seen and str(d["id"]) not in have_ids]
            if fresh:
                log(f"发现 {len(fresh)} 条新线报")
            for d in fresh:
                wid = str(d["id"])
                seen.add(wid)
                save_json(SEEN_FILE, sorted(seen))
                title = next((x.get("content") for x in d.get("list", []) if x.get("content")), "")
                log(f"新线报 {wid} | {title[:30]}")

                # Boss 红线：没转上链的绝不上站。先转链，成功才入库部署
                try:
                    out, st = jd_convert.convert_all_browser([d], cfg)
                    for k, v in st.items():
                        STATE[k] = STATE.get(k, 0) + v
                    conv = out[0] if out else d
                    if conv.get("_originalContext") or conv.get("_formatContext") or any(it.get("converted") for it in conv.get("list", [])):
                        conv["_addedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")  # 入站时间，前端用它算「X分钟前」
                        deals.insert(0, conv)
                        have_ids.add(wid)
                        persist(deals)
                        mark_dirty(f"new wire {wid}")
                        log(f"  已转链并落盘 {wid}（待合并推送）")
                    else:
                        pending = load_json(PENDING_FILE, [])
                        if not any(str(p.get("id")) == wid for p in pending):
                            pending.append(d)
                            save_json(PENDING_FILE, pending)
                        log(f"  转链失败，进待转队列（{len(pending)} 条），不上站")
                except Exception as e:
                    pending = load_json(PENDING_FILE, [])
                    if not any(str(p.get("id")) == wid for p in pending):
                        pending.append(d)
                        save_json(PENDING_FILE, pending)
                    log(f"  转链异常，进待转队列：{str(e)[:80]}")

            # 自动补转：每轮从待转队列取 1 条重试，转上链才入库部署
            pending = load_json(PENDING_FILE, [])
            if pending:
                d = pending[0]
                wid = str(d.get("id"))
                try:
                    out, st = jd_convert.convert_all_browser([d], cfg)
                    conv = out[0] if out else d
                    if conv.get("_originalContext") or conv.get("_formatContext") or any(it.get("converted") for it in conv.get("list", [])):
                        conv["_addedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")  # 入站时间，前端用它算「X分钟前」
                        deals.insert(0, conv)
                        have_ids.add(wid)
                        pending = [p for p in pending if str(p.get("id")) != wid]
                        save_json(PENDING_FILE, pending)
                        log(f"补转成功并落盘 {wid}（待合并推送）")
                        persist(deals)
                        mark_dirty(f"fix: 补转 {wid}")
                    else:
                        pending = pending[1:] + [pending[0]]
                        save_json(PENDING_FILE, pending)
                        log(f"补转仍失败 {wid}（队列轮转，共 {len(pending)} 条待转）")
                except Exception as e:
                    log(f"补转异常 {wid}：{str(e)[:80]}")
            # 京东的变更先推上 KV（淘宝转链一条要 1~2 分钟，不能让它压着京东的更新）
            flush_if_due(force=True)

            # 大淘客淘宝线报（与京东共用机器人浏览器，串行执行）
            try:
                n = poll_dtk(deals, have_ids)
                if n:
                    persist(deals)
                    mark_dirty(f"dtk x{n}")
            except Exception as e:
                log(f"淘宝轮询异常：{str(e)[:100]}")

            # 滚动窗口：只保留最近 RETAIN_DAYS 天（按线报发布时间）
            cutoff = time.strftime("%Y-%m-%d 00:00:00",
                                   time.localtime(time.time() - (RETAIN_DAYS - 1) * 86400))
            pruned = [x for x in deals if str(x.get("time") or "") >= cutoff]
            if len(pruned) != len(deals):
                log(f"清理 {len(deals) - len(pruned)} 条 {RETAIN_DAYS} 天前的旧线报（保留 {cutoff[:10]} 起）")
                deals = pruned
                persist(deals)
                mark_dirty("prune old")

            # 只保留最新 MAX_DEALS 条，防数据无限膨胀
            if len(deals) > MAX_DEALS:
                deals = deals[:MAX_DEALS]

        except Exception as e:
            log(f"本轮异常：{str(e)[:150]}")

        # 防抖推送：攒够 45s 的变更合并推一次，避免 CF Pages 构建排队
        flush_if_due(force=once)

        if once:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
