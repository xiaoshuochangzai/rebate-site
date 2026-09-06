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
import os
import subprocess
import sys
import time

import build_site
import jp_convert as jd_convert  # 精品库转链引擎（drop-in 替换京东联盟版）

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.join(BASE_DIR, "site")
SEEN_FILE = os.path.join(BASE_DIR, "seen_ids.json")
PENDING_FILE = os.path.join(BASE_DIR, "pending.json")
STATE = {"ok": 0, "fail": 0, "skipped": 0}
DEBOUNCE = 45  # 防抖窗口：有新货先落盘，攒够 45s 没有新线报再合并推送一次
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
    """防抖到期（或 force）就合并推送一次；推送失败则重置窗口下轮重试。"""
    if not DIRTY["flag"]:
        return
    waited = time.time() - DIRTY["since"]
    if not force and waited < DEBOUNCE:
        log(f"防抖中：{int(DEBOUNCE - waited)}s 后合并推送")
        return
    if git_push(DIRTY["note"]):
        log(f"合并推送上线（防抖 {int(waited)}s，备注：{DIRTY['note']}）")
        DIRTY["flag"] = False
    else:
        DIRTY["since"] = time.time()
        log("推送失败，已重置防抖窗口，下轮重试")


def has_link(deal):
    """判定线报是否含商品/券链接。纯文字、无任何链接的（如「促销取消了，先忽略」）
    对导购无意义，应忽略且不收录。"""
    for it in deal.get("list", []) or []:
        for key in ("item_id", "coupon_url", "content"):
            v = it.get(key) or ""
            if isinstance(v, str) and v.startswith("http"):
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


def main():
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
                        deals.insert(0, conv)
                        have_ids.add(wid)
                        deploy(deals, f"data: new wire {wid}")
                        log(f"  已转链并上线 {wid}")
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
                        deals.insert(0, conv)
                        have_ids.add(wid)
                        pending = [p for p in pending if str(p.get("id")) != wid]
                        save_json(PENDING_FILE, pending)
                        log(f"补转成功并上线 {wid}")
                        deploy(deals, f"fix: 补转 {wid}")
                    else:
                        pending = pending[1:] + [pending[0]]
                        save_json(PENDING_FILE, pending)
                        log(f"补转仍失败 {wid}（队列轮转，共 {len(pending)} 条待转）")
                except Exception as e:
                    log(f"补转异常 {wid}：{str(e)[:80]}")
        except Exception as e:
            log(f"本轮异常：{str(e)[:150]}")

        if once:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
