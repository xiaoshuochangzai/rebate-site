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
import hashlib
import json
import atexit
import os
import queue
import re
import subprocess
import sys
import threading
import time

try:
    import build_site
    import cf_kv
    import jp_convert as jd_convert  # 精品库转链引擎（drop-in 替换京东联盟版）
    import keyword_push
    import yuebai_short  # u.jd.com → 悦拜短链，防扒站（只影响站上展示 _siteContext，企微推送仍用原文）
    try:
        import wecom_ext  # 外部群 RPA 通道（缺失时 2小时热销榜跳过本轮，不标 seen）
    except Exception:
        wecom_ext = None
except Exception:
    # pythonw 无窗口：import 挂了进程会无声消失，不落盘 Boss 永远查不到原因
    import traceback as _tb
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor_err.txt"),
              "a", encoding="utf-8") as _f:
        _f.write(time.strftime("[%Y-%m-%d %H:%M:%S] 监控启动 import 失败：\n") + _tb.format_exc() + "\n")
    raise

# 关键词推送队列：本轮新入库的线报先进这里，轮末统一交给 keyword_push.flush
KW_QUEUE = []
_ROUND = [0]  # 轮询轮数计数（用于周期性打印企微连接状态）

# 淘宝转链后台化（Boss 2026-10-13 明令「先看看B的效果」）：
# 主循环只做发现+入队，慢转链（淘宝 1.5~2s/条）全在守护线程里跑，
# 成品经 TB_DONE 回主线程入库/推送——京东主循环永不被淘宝堵（实测高峰排队 4.5 分钟的根治）。
# 共享状态纪律：deals/KW_QUEUE/seen 只允许主线程动（单写者）；后台线程只碰 _TB_INFLIGHT（加锁）。
TB_JOBS = queue.Queue()   # ("tip", tip) / ("bitui", it) —— 待转链
TB_DONE = queue.Queue()   # ("tip", tip, out) / ("bitui", it, conv) —— 转链成品
_TB_LOCK = threading.Lock()
_TB_INFLIGHT = set()      # 正在后台转链的 id（防重复入队；失败丢弃后允许下轮重试）

_DTK_STATE = {"seen": None}    # 淘宝线报已见集合（主线程专用缓存，落盘 DTK_SEEN_FILE）
_BITUI_STATE = {"seen": None}  # 三榜已见集合（主线程专用缓存，落盘 BITUI_SEEN_FILE）


def _dtk_seen():
    if _DTK_STATE["seen"] is None:
        _DTK_STATE["seen"] = set(load_json(DTK_SEEN_FILE, []))
    return _DTK_STATE["seen"]


def _dtk_seen_save():
    save_json(DTK_SEEN_FILE, sorted(_dtk_seen())[-3000:])


def _bitui_seen():
    if _BITUI_STATE["seen"] is None:
        _BITUI_STATE["seen"] = set(load_json(BITUI_SEEN_FILE, []))
    return _BITUI_STATE["seen"]


def _bitui_seen_save():
    save_json(BITUI_SEEN_FILE, sorted(_bitui_seen())[-3000:])


_PDD_STATE = {"seen": None}
_PDD_COOLDOWN = {"until": 0.0}  # 转链白名单未过审时的冷却截止（epoch 秒，进程内存态）


def _pdd_seen():
    if _PDD_STATE["seen"] is None:
        _PDD_STATE["seen"] = set(load_json(PDD_SEEN_FILE, []))
    return _PDD_STATE["seen"]


def _pdd_seen_save():
    save_json(PDD_SEEN_FILE, sorted(_pdd_seen())[-3000:])


def _tb_inflight_add(k):
    with _TB_LOCK:
        if k in _TB_INFLIGHT:
            return False
        _TB_INFLIGHT.add(k)
        return True


def _tb_inflight_discard(k):
    with _TB_LOCK:
        _TB_INFLIGHT.discard(k)


def _tb_worker():
    """淘宝转链守护线程：逐条转（条间 3s 防风控，沿用原节奏），成品扔回 TB_DONE。
    注意：成功路径不释放 inflight（由 drain 标完 seen 后释放）——否则主循环下一轮
    会因 seen 未标而重复入队，造成同一条转 2~3 遍重复上站（2026-10-13 实锤踩坑）。"""
    import dtk_bitui
    import dtk_convert
    import pdd_hdk
    while True:
        kind, payload = TB_JOBS.get()
        ok_flag = False
        try:
            if kind == "tip":
                k = dtk_convert.to_deal(payload, None)["id"]
                out = dtk_convert.convert_tip(payload)
                if out:
                    TB_DONE.put(("tip", payload, out))
                    ok_flag = True
                else:
                    log(f"淘宝后台转链失败 {k}，本轮放弃（不上站，页面池内期间可重试）")
            elif kind == "pdd":
                k = str(payload.get("goods_id") or payload.get("goods_sign") or "")
                try:
                    link = pdd_hdk.convert_item(payload.get("goods_sign") or "")
                    if link:
                        TB_DONE.put(("pdd", payload, link))
                        ok_flag = True
                    else:
                        log(f"拼多多 {k} 后台转链空链，下轮重试")
                except pdd_hdk.WhitelistError as we:
                    _PDD_COOLDOWN["until"] = time.time() + PDD_COOLDOWN_SEC
                    log(f"拼多多转链未过审（白名单），冷却 1 小时后自动重试：{we}")
            else:
                k = str(payload.get("id") or "")
                conv = dtk_bitui.convert_item(payload)
                if conv and conv.get("tpwd"):
                    if kind == "refill":  # 高佣补位：成品回流独立分支，不走 sell2 的外部群链路
                        TB_DONE.put(("refill", payload, conv))
                    elif kind == "refill_mc":  # 猫超轮播：直发主群，同样独立回流
                        TB_DONE.put(("refill_mc", payload, conv))
                    else:
                        TB_DONE.put((("sell2" if kind == "sell2" else "bitui"), payload, conv))
                    ok_flag = True
                else:
                    log(f"{('高佣补位' if kind == 'refill' else ('猫超轮播' if kind == 'refill_mc' else '三榜'))} {k} 后台转链失败（无淘口令），下轮重试")
        except Exception as e:
            log(f"淘宝后台转链异常：{str(e)[:100]}")
        finally:
            if not ok_flag:  # 失败才释放（允许下轮重试）；成功交给 drain 释放
                if kind == "tip":
                    try:
                        _tb_inflight_discard(dtk_convert.to_deal(payload, None)["id"])
                    except Exception:
                        pass
                elif kind == "pdd":
                    _tb_inflight_discard(str(payload.get("goods_id") or payload.get("goods_sign") or ""))
                else:
                    _pid = str(payload.get("id") or "")
                    if kind == "refill":
                        _tb_inflight_discard("rf_" + _pid)
                    elif kind == "refill_mc":
                        _tb_inflight_discard("mcr_" + _pid)
                    else:
                        _tb_inflight_discard(_pid)
            TB_JOBS.task_done()
        time.sleep(3)  # 条间间隔防风控（沿用原 poll 节奏）


def start_tb_worker():
    t = threading.Thread(target=_tb_worker, daemon=True, name="tb-convert")
    t.start()
    log("淘宝后台转链线程已启动（京东主循环不再被淘宝转链堵塞）")


def drain_tb_done(deals, have_ids):
    """主线程收后台转链成品：入库/进推送队列（保持主线程单写者）。返回 (tip数, bitui数, pdd数)。"""
    import dtk_bitui
    import dtk_convert
    import pdd_hdk
    n_tip = n_bit = n_pdd = n_s2 = 0
    while True:
        try:
            kind, payload, out = TB_DONE.get_nowait()
        except queue.Empty:
            break
        if kind == "tip":
            k = dtk_convert.to_deal(payload, None)["id"]
            try:
                deal = dtk_convert.to_deal(payload, out)
                if not str(deal["list"][0]["content"]).strip():
                    _dtk_seen().add(k)  # 剔除京东链接后无内容 → 丢弃且不再重试
                    log(f"淘宝线报 {k} 剔除京东链接后为空，丢弃")
                else:
                    deal["_addedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    deals.insert(0, deal)
                    have_ids.add(k)
                    _dtk_seen().add(k)
                    n_tip += 1
                    log(f"淘宝线报已转链落盘 {k} | {deal['list'][0]['content'][:26]}")
            except Exception as e:
                log(f"淘宝成品入库异常 {k}：{str(e)[:80]}")
            finally:
                _tb_inflight_discard(k)
                _dtk_seen_save()
        elif kind == "pdd":
            gid = str(payload.get("goods_id") or payload.get("goods_sign") or "")
            try:
                if out:
                    deal = pdd_hdk.to_deal(payload, out)
                    deal["_addedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    deals.insert(0, deal)
                    have_ids.add(str(deal["id"]))
                    _pdd_seen().add(gid)
                    _pdd_seen_save()
                    n_pdd += 1
                    log(f"拼多多已转链落盘 pdd_{gid} | {str(payload.get('goodsname') or '')[:24]}")
                else:
                    log(f"拼多多 {gid} 成品空链，下轮重试")
            except Exception as e:
                log(f"拼多多成品处理异常 {gid}：{str(e)[:80]}")
            finally:
                _tb_inflight_discard(gid)
        elif kind == "sell2":
            # 2小时热销榜（双11 期间外部群专属）：只入外部群队列，不进主群 KW_QUEUE
            gid = str(payload.get("id") or "")
            try:
                if out and out.get("tpwd"):
                    text = dtk_bitui.build_text(payload, out)
                    if wecom_ext is not None:
                        # Boss 2026-10-27 明令：猫超佣金膨胀来的标【天猫超市】，其余【淘宝】
                        # （旧主群同步时代自带标签，sell2 接管后由这里补）
                        text = ("【天猫超市】" if payload.get("_maochao") else "【淘宝】") + text
                        # Boss 2026-10-23 明令：外部群淘宝每 2 条带一次站链尾
                        if _bump_sell2_tail() % SELL2_TAIL_EVERY == 0:
                            text += SELL2_TAIL
                        wecom_ext.enqueue(text)   # 外部群 RPA 低频派发
                        _sell2_seen().add(gid)
                        _sell2_seen_save()
                        n_s2 += 1
                        log(f"2小时热销新品已入外部群队列 {gid} | {str(payload.get('d_title') or '')[:24]}")
                        # Boss 2026-10-29 明令：主群淘宝线报源调整为「猫超佣金膨胀 + 2小时热销」，
                        # 双榜成品都同步主群（猫超标【天猫超市】，2h 标【淘宝】）；外部群逻辑不变。
                        # 构造同构 deal 塞 KW_QUEUE，由 keyword_push 按节流/配额/陈旧过滤正常推主群；
                        # _mctag 让主群消息开头标【天猫超市】而不是【淘宝】。
                        mc = bool(payload.get("_maochao"))
                        try:
                            # 跨体系去重：该商品若已从三榜推过主群，这里不再重复推
                            if not _tb_main_gid_add(gid):
                                log(f"跨榜去重：{gid} 已从其他榜推过主群，跳过")
                            else:
                                payload["_kind"] = "mc" if mc else "sell2"  # to_deal 认 _kind 选前缀，否则 KeyError
                                deal_g = dtk_bitui.to_deal(payload, out)
                                deal_g["_addedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
                                deal_g["_mctag"] = 1 if mc else 0
                                KW_QUEUE.append(deal_g)
                                _mc_refill_touch(gid)  # 新品已推主群，轮播池同步刷新防扎堆
                                log(f"{'猫超' if mc else '2小时热销'}新品已同步主群队列 {gid} | {str(payload.get('d_title') or '')[:24]}")
                        except Exception as e:
                            log(f"双榜同步主群异常 {gid}：{str(e)[:80]}")
                    else:
                        log(f"2小时热销 {gid} wecom_ext 未加载，本轮跳过（不标 seen，下轮重试）")
                else:
                    log(f"2小时热销 {gid} 成品无淘口令，下轮重试")
            except Exception as e:
                log(f"2小时热销成品处理异常 {gid}：{str(e)[:80]}")
            finally:
                _tb_inflight_discard(gid)
        elif kind == "refill":
            # Boss 2026-10-29 明令：2小时热销高佣商品间隔式补位主群（猫超供给少）。
            # 只进主群（KW_QUEUE），不上站、不进外部群；id 带时间戳绕开 pushed 去重实现合法重发。
            gid = str(payload.get("id") or "")
            try:
                if out and out.get("tpwd"):
                    deal = dtk_bitui.to_deal(payload, out)  # payload._kind=sell2，取文案与字段
                    deal["id"] = f"rf_{gid}_{int(time.time())}"
                    deal["_addedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")  # 防陈旧过滤误杀
                    deal["_mctag"] = 0  # 补位的是 2h 榜商品，主群标【淘宝】
                    KW_QUEUE.append(deal)
                    log(f"高佣补位已进主群队列 {gid} | {str(payload.get('d_title') or '')[:24]}")
                else:
                    log(f"高佣补位 {gid} 无淘口令，本轮放弃")
            except Exception as e:
                log(f"高佣补位异常 {gid}：{str(e)[:80]}")
            finally:
                _tb_inflight_discard("rf_" + gid)
        elif kind == "refill_mc":
            # Boss 2026-10-29 明令：猫超高佣轮播直发主群（每 5 分钟 3 条，没新货轮播旧的）。
            # 绕过 flush 配额/节流，但夜闸与红包静默照守；不上站、不进外部群（外部群猫超有自己的链路）。
            gid = str(payload.get("id") or "")
            try:
                if out and out.get("tpwd"):
                    hhmm = time.strftime("%H:%M")
                    if keyword_push and hhmm >= keyword_push.NIGHTGATE_HM:
                        log(f"猫超轮播 {gid} 撞夜闸（{hhmm}），本轮放弃")
                    elif keyword_push and keyword_push.redpack_mute():
                        log(f"猫超轮播 {gid} 撞红包静默窗，本轮放弃")
                    else:
                        global _mc_refill_tail_cnt
                        text = dtk_bitui.build_text(payload, out)
                        _mc_refill_tail_cnt += 1
                        if _mc_refill_tail_cnt % 2 == 0:
                            text += SELL2_TAIL  # 与主群淘宝站尾同款，每 2 条一次
                        # Boss 2026-10-30：标签按商品级 is_chaoshi（猫超好货=天猫超市，超级疯狂日等=淘宝）
                        tag_lab = "【天猫超市】" if payload.get("is_chaoshi") else "【淘宝】"
                        ok, msg = keyword_push._send(tag_lab + text, log=log, ext_sync=False)
                        if ok:
                            _mc_refill_touch(gid)  # 轮播成功，刷新时间戳实现游标轮转
                            log(f"猫超轮播已直发主群 {gid} | {str(payload.get('d_title') or '')[:24]}")
                        else:
                            log(f"猫超轮播直发失败 {gid}：{msg[:60]}（时间戳不动，下轮可再选）")
                else:
                    log(f"猫超轮播 {gid} 无淘口令，本轮放弃")
            except Exception as e:
                log(f"猫超轮播异常 {gid}：{str(e)[:80]}")
            finally:
                _tb_inflight_discard("mcr_" + gid)
        else:
            gid = str(payload.get("id") or "")
            try:
                if out and out.get("tpwd"):
                    deal = dtk_bitui.to_deal(payload, out)
                    # 三榜条目的 time 字段是商品入榜时间（可能是几天前），不是入站时间；
                    # 必须补打 _addedAt，否则 keyword_push 的 30 分钟陈旧过滤会把它们
                    # 全部误杀成「积压」（2026-10-13 实锤：26 条只漏推 1 条的根因）
                    deal["_addedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    # 跨体系去重：该商品若已从双榜推过主群，只记 seen 不再入主群队列
                    if _tb_main_gid_add(gid):
                        KW_QUEUE.append(deal)
                        log(f"三榜新品已转链待推 {gid} | {str(payload.get('d_title') or '')[:24]}")
                    else:
                        log(f"跨榜去重：三榜 {gid} 已从双榜推过主群，跳过")
                    _bitui_seen().add(gid)
                    _bitui_seen_save()
                    n_bit += 1
                    log(f"三榜新品已转链待推 {gid} | {str(payload.get('d_title') or '')[:24]}")
                else:
                    log(f"三榜 {gid} 成品无淘口令，下轮重试")
            except Exception as e:
                log(f"三榜成品处理异常 {gid}：{str(e)[:80]}")
            finally:
                _tb_inflight_discard(gid)
    if n_tip or n_pdd:
        persist(deals)
        mark_dirty(f"tb tip x{n_tip}" if not n_pdd else f"pdd x{n_pdd}")
    return n_tip, n_bit, n_pdd, n_s2

# pythonw（无窗口）拉起子进程时，Windows 默认会给他弹一个黑色控制台窗口。
# 监控里 git 兜底推送 / powershell 杀浏览器都会被 Boss 看到「凭空弹窗」，
# 一律加 CREATE_NO_WINDOW 静默执行（Boss 2026-10-08 反馈）。
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

_JD_PRICE_RE = re.compile(r"(?<![满每减立降])(\d+(?:\.\d+)?)元")


def jd_price_of(deal):
    """京东线报价格 = 文案首个『X元』（与前端价格高亮同款规则）。
    满/每/减/立 前缀的是满减门槛不算价；券类无线报价的返回空。"""
    if deal.get("price") or deal.get("_couponAfterPrice"):
        return deal.get("price") or deal.get("_couponAfterPrice")
    for it in deal.get("list", []):
        m = _JD_PRICE_RE.search(it.get("content", "") or "")
        if m:
            return m.group(1)
    return ""

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.join(BASE_DIR, "site")
SEEN_FILE = os.path.join(BASE_DIR, "seen_ids.json")
PENDING_FILE = os.path.join(BASE_DIR, "pending.json")
DTK_SEEN_FILE = os.path.join(BASE_DIR, "seen_dtk.json")
DTK_PENDING_FILE = os.path.join(BASE_DIR, "pending_dtk.json")
BITUI_SEEN_FILE = os.path.join(BASE_DIR, "seen_bitui.json")  # 必推榜已见商品 id（Boss 2026-09-16：只推新进榜）

# 2小时热销榜（top_sell2）独立快照：外部群双11期间只收这个榜，不能与三榜共用 seen
# （外部群用户没收到过三榜内容，同一商品进过三榜也照样要推外部群）
SELL2_SEEN_FILE = os.path.join(BASE_DIR, "seen_sell2.json")
_SELL2_STATE = {"seen": None}
SELL2_MAX_PER_ROUND = 2  # 单轮最多转链几条 2h 榜新品（外部群 RPA 派发慢，防积压）


def _sell2_seen():
    if _SELL2_STATE["seen"] is None:
        _SELL2_STATE["seen"] = set(load_json(SELL2_SEEN_FILE, []))
    return _SELL2_STATE["seen"]


def _sell2_seen_save():
    save_json(SELL2_SEEN_FILE, sorted(_sell2_seen())[-3000:])


# 外部群淘宝线报站链尾（Boss 2026-10-23 明令）：sell2 接管外部群后消息是纯文案入队，
# 丢掉了旧「主群同步」时代带的站链尾 → 恢复「每 2 条带一次」，尾文案与主群 TB_FOOTER 一致。
# 独立计数存 sell2_tail_state.json（不与 keyword_state.json 混用，两边节奏互不干扰）
SELL2_TAIL_FILE = os.path.join(BASE_DIR, "sell2_tail_state.json")
SELL2_TAIL_EVERY = 2
SELL2_TAIL = "\n————\n更多双11破价好物，访问线报网\nhttps://shengqian.cyou/"


def _bump_sell2_tail():
    st = load_json(SELL2_TAIL_FILE, {})
    n = int(st.get("n", 0) or 0) + 1
    save_json(SELL2_TAIL_FILE, {"n": n})
    return n

BITUI_MAX_PER_ROUND = 3  # 单轮最多转链几条必推榜新品（防单轮过久饿着京东）
PDD_SEEN_FILE = os.path.join(BASE_DIR, "seen_pdd.json")  # 拼多多已见商品 goods_id
PDD_MAX_PER_ROUND = 3  # 单轮最多转链几条拼多多新品

# 双11福利清单自动更新（Boss 2026-10-22 拍板：每 10 分钟一轮，独立线程）
WELFARE_EVERY = 600  # 秒


def _welfare_mod():
    import welfare_auto
    return welfare_auto
PDD_POLL_PAGES = 3     # 每轮轮询商品列表前几页 + 热榜三榜（约 40 条源/轮）
PDD_COOLDOWN_SEC = 3600  # 转链权限类报错冷却 1 小时，恢复后自动重试，无需重启监控
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
    """git 兜底推送。2026-10-13 加超时：此前 git push 直连 github（被墙）会挂到
    TCP 超时（实测把主循环堵死 6.5 分钟），京东抓取全程停摆——网站落后几分钟的元凶之一。"""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    cmds = [
        ["git", "add", "-A"],
        ["git", "commit", "-m", tag],
    ]
    for c in cmds:
        try:
            subprocess.run(c, cwd=BASE_DIR, capture_output=True, env=env,
                           creationflags=NO_WINDOW, timeout=30)
        except subprocess.TimeoutExpired:
            return False
    # 三路重试：直连 → 50111 → 7890（每路最多等 45s，挂了就换下一路）
    for proxy in (None, "http://127.0.0.1:50111", "http://127.0.0.1:7890"):
        c = ["git", "push", "origin", "main"]
        if proxy:
            c = ["git", "-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}",
                 "push", "origin", "main"]
        try:
            r = subprocess.run(c, cwd=BASE_DIR, capture_output=True, env=env,
                               creationflags=NO_WINDOW, timeout=45)
        except subprocess.TimeoutExpired:
            continue
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


_LAST_KV = {"hash": None}  # 最近一次「成功」写入 KV 的内容哈希（失败不更新，下次照常重试）


def _kv_hash(deals):
    return hashlib.md5(
        json.dumps(deals, ensure_ascii=False).encode("utf-8")).hexdigest()


def flush_if_due(force=False):
    """防抖到期（或 force）就 KV 直写一次（即时生效，免 CF 构建）；
    内容和上次成功写入完全一致就跳过（静默期不白烧额度/不放大 504 暴露面）；
    KV 失败（含 cf_kv 内部重试 2 次后仍失败）退回 git 推送兜底。"""
    if not DIRTY["flag"]:
        return
    waited = time.time() - DIRTY["since"]
    if not force and waited < DEBOUNCE:
        log(f"防抖中：{int(DEBOUNCE - waited)}s 后合并推送")
        return
    deals = load_json(os.path.join(SITE_DIR, "deals.json"), [])
    h = _kv_hash(deals)
    if h == _LAST_KV["hash"]:
        DIRTY["flag"] = False
        log(f"KV 内容未变，跳过直写（共 {len(deals)} 条）")
        return
    ok, msg = cf_kv.put_deals(deals)
    if ok:
        _LAST_KV["hash"] = h
        log(f"KV 直写上线（防抖 {int(waited)}s，共 {len(deals)} 条）")
        DIRTY["flag"] = False
        return
    log(f"KV 直写失败：{msg}，git 兜底转后台线程（2026-10-13：不再堵主循环）")
    DIRTY["flag"] = False  # 本批已交给后台；之后的新变更会重新置脏触发新一轮 KV 尝试

    def _bg_git():
        try:
            okg = git_push(f"fallback: kv fail {DIRTY['note']}")
            log("git 兜底推送成功" if okg else "git 兜底也失败（KV 下次变更时自动重试）")
        except Exception as e:
            log(f"git 兜底异常：{str(e)[:80]}")

    threading.Thread(target=_bg_git, daemon=True).start()


def poll_dtk(deals, have_ids):
    """大淘客淘宝线报：抓页面新线报 → 入队后台转链（红线：转不上不上站）→ 返回入队数。

    注：失败直接放弃、不重试——页面客户端会缓存「已转链」状态（isLoad），
    点过的卡再点不再调转链 API（缓存秒弹「文案复制成功」），重试必失败；
    且 Boss 明令旧的不要，页面卡池也只留最新 12 张。"""
    import dtk_convert
    dtk_seen = _dtk_seen()
    first_run = not dtk_seen
    enqueued = 0
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
            _dtk_seen_save()
            log(f"淘宝基线已建立：现存 {len(tips)} 条全部跳过，只收之后新出的")
            return 0

        fresh = [t for t in tips if key_of(t) not in _dtk_seen() and key_of(t) not in have_ids]
        # v4 纯 API 直调版：转链不发页面请求，无需 reload（列表自动更新，只读不写，
        # 屏幕上不会再出现大淘客页面反复刷新）
        fresh = fresh[:3]  # 单轮入队上限，防队列堆积

        # Boss 2026-10-13 明令（方案B）：淘宝转链挪后台线程，主循环只发现+入队，
        # 京东不再被淘宝转链（1.5~2s/条）堵塞；成品由 drain_tb_done 回主线程入库
        for t in fresh:
            k = key_of(t)
            if not _tb_inflight_add(k):
                continue  # 已在后台转链中，防重复入队
            log(f"新淘宝线报 {k} | {t['title'][:30]}（已排入后台转链）")
            TB_JOBS.put(("tip", t))
            enqueued += 1
    except Exception as e:
        log(f"淘宝线报本轮异常：{str(e)[:120]}")
    finally:
        if d:
            d.close()
    return enqueued


def poll_bitui():
    """大淘客三榜新品监听（Boss 2026-09-16 淘宝只推必推榜；2026-10-13 明令新增
    热销榜 top-sell + 热推榜 top-hot，三榜一起监听、跨榜去重）。

    新商品进榜 → 转链（get-privilege，0.5s/条）→ 进推送队列；没新品就不推。
    跨榜去重：三榜共用 dataoke 商品 id，seen_bitui.json 全局一份，进过任何一榜
    就不再推（Boss 明令「三个类目都有重复的商品，需要增加去重功能」）。
    首次运行建基线：三榜现存全部记 seen 跳过，防一次性轰炸。
    """
    import dtk_bitui
    seen = _bitui_seen()
    # 依次拉三榜（顺序：必推榜 → 热销榜 → 热推榜），拉取失败跳过该榜本轮不推
    lists = []
    for kind in dtk_bitui.RANK_ORDER:
        lst = dtk_bitui.fetch_rank(kind)
        if lst:
            lists.append(lst)
        else:
            log(f"{dtk_bitui.RANKS[kind][2]} 本轮拉取为空/失败，跳过")
        time.sleep(0.5)  # 榜与榜之间小间隔
    if not lists:
        return 0
    MULTI_MARK = "_multi3"  # 三榜扩容标记：无标记 = 新榜未建基线
    if not seen or MULTI_MARK not in seen:
        # 基线：三榜现存 id 全部并入 seen 跳过，只推之后新进榜的（防一次性轰炸）
        for lst in lists:
            seen.update(str(it.get("id")) for it in lst if it.get("id"))
        seen.add(MULTI_MARK)
        _bitui_seen_save()
        log(f"三榜基线已建立：现存 {len(seen) - 1} 条全部跳过，只推之后新进榜的")
        return 0
    # Boss 2026-10-13 明令（方案B）：三榜转链也挪后台线程，这里只发现+入队；
    # seen 在 drain_tb_done 转链成功后才标（失败的留在池内下轮重试，同原逻辑）
    # Boss 2026-10-29 明令：主群淘宝线报只推双榜（2小时热销 + 猫超佣金膨胀），三榜停推。
    # 三榜新品照常记 seen（防日后恢复三榜时旧货一次性倾泻），但不再转链、不进主群。
    n_new = 0
    for lst in lists:
        for it in lst:
            gid = str(it.get("id"))
            if gid and gid not in seen:
                seen.add(gid)
                n_new += 1
    if n_new:
        _bitui_seen_save()
        log(f"三榜已停推（主群只走双榜）：{n_new} 条新品仅记档跳过")
    return 0
    return got


# ---- 主群跨体系去重（Boss 2026-10-29 反馈「淘宝线报总是重复」）----
# 根因：三榜（bt_/ts_/tt_）与双榜（s2_/mc_）是两套榜单两套 id 前缀，同一商品两边都收时
# keyword_push 按 deal id 去重不命中 → 主群同一商品推两次（2026-10-29 实锤：
# 46434416 韩束护手霜 08:33 从热销榜、08:33:59 从 2小时热销榜各排入一次）。
# 修法：主群侧无论从哪个榜来，同一 dtk 商品 gid 只推一次；外部群不在此列（两群独立）。
TB_MAIN_GID_FILE = os.path.join(BASE_DIR, "tb_main_gid.json")
_tb_main_gid_cache = None


def _tb_main_gid():
    global _tb_main_gid_cache
    if _tb_main_gid_cache is None:
        _tb_main_gid_cache = load_json(TB_MAIN_GID_FILE, {})
    return _tb_main_gid_cache


def _tb_main_gid_add(gid):
    """主群跨体系查重：gid 未推过返回 True 并登记；已推过返回 False。"""
    global _tb_main_gid_cache
    pool = _tb_main_gid()
    gid = str(gid)
    if not gid or gid in pool:
        return False
    now = time.time()
    pool[gid] = now
    if len(pool) > 20000:  # 防无限膨胀：先裁 7 天前的，仍超再砍最旧一半
        cutoff = now - 7 * 86400
        for k in [k for k, v in pool.items() if v < cutoff]:
            pool.pop(k, None)
        if len(pool) > 20000:
            for k, _ in sorted(pool.items(), key=lambda kv: kv[1])[: len(pool) // 2]:
                pool.pop(k, None)
    try:
        save_json(TB_MAIN_GID_FILE, pool)
    except Exception:
        _tb_main_gid_cache = None  # 写盘失败丢弃缓存，下轮重读，宁重复不丢
    return True


def _tb_comm_ok(it):
    """淘宝线报佣金门槛（Boss 2026-10-27 明令起，2026-10-29 提高到 4 元并覆盖主群）：
    预估佣金 >= 4 元才发（主群三榜 + 外部群双榜同一把尺）。
    页面口径：佣金金额 = commission_rate × price / 100（rate 已含膨胀补贴，
    实测 39.9×15.35%=6.12 与大淘客页面显示一致）。字段缺失/解析失败按 0 处理（不发）。"""
    try:
        rate = float(it.get("commission_rate") or 0)
        price = float(it.get("price") or 0)
        return rate * price / 100.0 >= 4.0
    except Exception:
        return False


# ---- 2小时热销高佣补位（Boss 2026-10-29 明令）：猫超供给少，主群用 2h 榜高佣商品
# 间隔式补位（非批量一次性发）——每 REFILL_INTERVAL_SEC 挑佣金最高且过冷却的一条转链推主群。
REFILL_FILE = os.path.join(BASE_DIR, "tb_refill.json")
REFILL_INTERVAL_SEC = 600        # 每 10 分钟最多补位 1 条（间隔式节奏，Boss 可调）
REFILL_COOLDOWN_SEC = 6 * 3600   # 同一商品 6 小时内不重发（防 Boss 刚抱怨过的重复）
REFILL_KEEP_TOP = 60             # 池子只留佣金最高的 60 条，防无限膨胀
_refill_pool_cache = None
_refill_last = 0.0


def _refill_pool():
    global _refill_pool_cache
    if _refill_pool_cache is None:
        _refill_pool_cache = load_json(REFILL_FILE, {})
    return _refill_pool_cache


def _refill_pool_trim_save():
    global _refill_pool_cache
    pool = _refill_pool()
    if len(pool) > REFILL_KEEP_TOP:
        top = sorted(pool.items(), key=lambda kv: kv[1].get("comm", 0), reverse=True)[:REFILL_KEEP_TOP]
        pool.clear()
        pool.update(dict(top))
    save_json(REFILL_FILE, pool)


def refill_tick(log=print):
    """补位调度：到点从池里挑佣金最高且过冷却的一条，排后台转链后推主群。"""
    global _refill_last
    now = time.time()
    if now - _refill_last < REFILL_INTERVAL_SEC:
        return
    _refill_last = now
    pool = _refill_pool()
    cand = []
    for gid, v in pool.items():
        if now - (v.get("ts") or 0) >= REFILL_COOLDOWN_SEC and _tb_inflight_add("rf_" + str(gid)):
            cand.append((gid, v))
    if not cand:
        return  # 池空或全在冷却，本轮跳过
    gid, v = max(cand, key=lambda kv: kv[1].get("comm", 0))
    v["ts"] = now
    _refill_pool_trim_save()
    it = dict(v.get("it") or {})
    it["_kind"] = "sell2"
    TB_JOBS.put(("refill", it))
    log(f"高佣补位调度：{gid} 佣金{v.get('comm', 0):.1f}元 | {(it.get('d_title') or '')[:22]}（每{REFILL_INTERVAL_SEC // 60}分钟最多1条）")


def refill_register(s2_list, log=print):
    """poll_sell2 每轮把 2h 榜过 4 元门槛的商品登记进补位池（不影响新品/seen 逻辑）。"""
    pool = _refill_pool()
    n_new = 0
    for it in s2_list:
        try:
            gid = str(it.get("id") or "")
            if not gid or gid in pool or not _tb_comm_ok(it):
                continue
            it["_kind"] = "sell2"
            comm = float(it.get("commission_rate") or 0) * float(it.get("price") or 0) / 100.0
            pool[gid] = {
                "comm": round(comm, 2), "ts": 0,
                "it": {k: it.get(k) for k in ("id", "goodsid", "d_title", "title", "price",
                                              "original_price", "coupon_amount", "coupon_id",
                                              "main_pic", "shop_name", "add_time",
                                              "commission_rate", "subsidy_rate", "_kind")},
            }
            n_new += 1
        except Exception:
            continue
    if pool:
        _refill_pool_trim_save()
        if n_new:
            log(f"高佣补位池：新增 {n_new} 条（池内 {len(pool)} 条）")


# ---- 猫超高佣轮播（Boss 2026-10-29 明令）：猫超每 5 分钟 3 条高佣，没有新的符合要求的
# 进来就轮播旧的高佣（游标轮转：最久没发的优先、同分取高佣），直发主群不走 flush 配额。
MC_REFILL_FILE = os.path.join(BASE_DIR, "tb_refill_mc.json")
MC_REFILL_INTERVAL_SEC = 300   # 每 5 分钟一轮
MC_REFILL_PER_TICK = 3         # 每轮 3 条
MC_REFILL_KEEP_TOP = 60
_mc_refill_cache = None
_mc_refill_last = 0.0
_mc_refill_tail_cnt = 0        # 轮播站尾计数（每 2 条带一次，内存即可，重启清零无碍）


def _mc_refill_pool():
    global _mc_refill_cache
    if _mc_refill_cache is None:
        _mc_refill_cache = load_json(MC_REFILL_FILE, {})
    return _mc_refill_cache


def _mc_refill_touch(gid, ts=None):
    """商品被轮播（或作为新品推过主群）后刷新时间戳，防扎堆重复。"""
    pool = _mc_refill_pool()
    if str(gid) in pool:
        pool[str(gid)]["ts"] = ts if ts is not None else time.time()


def mc_refill_register(mc_list, log=print):
    """poll_sell2 每轮把猫超榜过 4 元门槛的商品登记进轮播池。"""
    pool = _mc_refill_pool()
    n_new = 0
    for it in mc_list:
        try:
            gid = str(it.get("id") or "")
            if not gid or gid in pool or not _tb_comm_ok(it):
                continue
            it["_kind"] = "mc"
            comm = float(it.get("commission_rate") or 0) * float(it.get("price") or 0) / 100.0
            pool[gid] = {
                "comm": round(comm, 2), "ts": 0, "tag": str(it.get("_tag") or ""),
                "it": {k: it.get(k) for k in ("id", "goodsid", "d_title", "title", "price",
                                              "original_price", "coupon_amount", "coupon_id",
                                              "main_pic", "shop_name", "add_time",
                                              "commission_rate", "subsidy_rate", "is_chaoshi",
                                              "_kind")},
            }
            n_new += 1
        except Exception:
            continue
    if len(pool) > MC_REFILL_KEEP_TOP:
        # 超限砍佣金最低的，保留高佣 + 最久没发的都会因高佣留下
        keep = {gid: v for gid, v in sorted(pool.items(), key=lambda kv: kv[1].get("comm", 0), reverse=True)[:MC_REFILL_KEEP_TOP]}
        pool.clear()
        pool.update(keep)
    if pool:
        save_json(MC_REFILL_FILE, pool)
        if n_new:
            log(f"猫超轮播池：新增 {n_new} 条（池内 {len(pool)} 条）")


def mc_refill_tick(log=print):
    """猫超轮播调度：每 5 分钟挑 3 条（最久没发优先、同分取高佣）排后台转链。"""
    global _mc_refill_last
    now = time.time()
    if now - _mc_refill_last < MC_REFILL_INTERVAL_SEC:
        return
    _mc_refill_last = now
    pool = _mc_refill_pool()
    cand = []
    for gid, v in pool.items():
        if _tb_inflight_add("mcr_" + str(gid)):
            cand.append((gid, v))
    if not cand:
        return  # 池空或全在转链中
    cand.sort(key=lambda kv: (kv[1].get("ts") or 0, -kv[1].get("comm", 0)))
    picked = cand[:MC_REFILL_PER_TICK]
    for gid, v in picked:
        it = dict(v.get("it") or {})
        it["_kind"] = "mc"
        TB_JOBS.put(("refill_mc", it))
        log(f"猫超轮播调度：{gid} 佣金{v.get('comm', 0):.1f}元 | {(it.get('d_title') or '')[:22]}")
    # 池里掉出榜的高佣旧货清理：只保留当前在榜登记过的 + 最近轮播的（自然由 register 刷新，不额外删）


# ---- 专区动态发现（Boss 2026-10-30 明令）：自动跟进大淘客 /xp/1111 专区的新增与删减。
# 白名单初始 = Boss 点名的 猫超好货(28)/超级疯狂日(27)；每 10 分钟拉一次 get-promo-config，
# 白名单外的新专区自动加入（及时补充），白名单内从接口消失的自动移除并清池。
MC_TAGS_FILE = os.path.join(BASE_DIR, "tb_mc_tags.json")
MC_TAGS_DEFAULT = {"28": "猫超好货", "27": "超级疯狂日"}
MC_TAGS_EVERY_SEC = 600
_mc_tags_cache = None
_mc_tags_last = 0.0


def _mc_tags():
    global _mc_tags_cache
    if _mc_tags_cache is None:
        st = load_json(MC_TAGS_FILE, {})
        tags = st.get("tags") if isinstance(st, dict) else None
        if not tags:
            tags = dict(MC_TAGS_DEFAULT)
            save_json(MC_TAGS_FILE, {"tags": tags})
        _mc_tags_cache = {str(k): v for k, v in tags.items()}
    return _mc_tags_cache


def _mc_tags_save():
    save_json(MC_TAGS_FILE, {"tags": _mc_tags()})


def poll_promo_tags(log=print):
    """定期拉 get-promo-config 对比白名单：新专区自动加入、下线专区自动移除并清其轮播池。"""
    global _mc_tags_cache, _mc_tags_last
    now = time.time()
    if now - _mc_tags_last < MC_TAGS_EVERY_SEC:
        return
    _mc_tags_last = now
    import requests as _rq
    import dtk_bitui as _db
    try:
        r = _rq.get(
            "https://dtkapi.ffquan.cn/taobaoapi/get-promo-config?path=/xp/1111",
            headers={"User-Agent": _db.UA, "Referer": "https://www.dataoke.com/xp/1111"},
            timeout=20,
        ).json()
        s = json.dumps(r, ensure_ascii=False)
    except Exception as e:
        log(f"专区发现拉取失败：{str(e)[:60]}")
        return
    import re as _re
    live = {}
    for m in _re.finditer(r'"id"\s*:\s*(\d+)[^{}]*?"name"\s*:\s*"([^"]+)"[^{}]*?"total"\s*:\s*(\d+)', s):
        live[m.group(1)] = (m.group(2), int(m.group(3)))
    if not live:
        log("专区发现：解析到 0 个专区（响应结构变化？），本轮不动")
        return
    tags = _mc_tags()
    added, removed = [], []
    # 白名单外的新专区 → 自动加入（Boss：新增的项目及时补充）
    for pid, (name, total) in live.items():
        if pid not in tags:
            tags[pid] = name
            added.append(f"{name}(tag={pid}, 在榜{total}条)")
    # 白名单内但接口已消失的专区 → 移除并清其轮播池（Boss：删减的项目及时补充/移除）
    pool = _mc_refill_pool()
    dropped_pool = 0
    for pid in list(tags.keys()):
        if pid not in live:
            removed.append(f"{tags[pid]}(tag={pid})")
            for g in [g for g, v in pool.items() if str(v.get("tag")) == pid]:
                pool.pop(g, None)
                dropped_pool += 1
            tags.pop(pid, None)
    if added or removed:
        _mc_tags_save()
        if dropped_pool:
            save_json(MC_REFILL_FILE, pool)
        for a in added:
            log(f"发现新专区，已加入推送白名单：{a}")
        for rm in removed:
            log(f"专区已下线，移除监听：{rm}" + (f"（清轮播池 {dropped_pool} 条）" if dropped_pool else ""))
    else:
        log(f"专区发现：白名单 {len(tags)} 个专区无变化（在榜专区 {len(live)} 个）")


def poll_sell2():
    """大淘客2小时热销榜 + 猫超佣金膨胀双榜（top_sell2 / xp/1111 页面）——双11 期间只推外部群。

    Boss 2026-10-23 明令：双11 期间发到外部群的**淘宝线报**换成 2小时热销榜新品
    （京东照常同步，主群完全不受影响——三榜照旧走主群链路）。
    Boss 2026-10-27 明令：加入「猫超佣金膨胀」专区（tag=21）双榜交叉：
      - 猫超来的商品标注【天猫超市】，2小时热销的保持【淘宝】
      - 同轮两榜都有的商品猫超优先
      - 两榜共享单轮 2 条配额（猫超优先）
      - 佣金门槛：预估佣金 >=4 元才发（_tb_comm_ok，两榜同规则；Boss 2026-10-29 明令从 1 元提高）
    首跑建基线全跳过（防一次性轰炸）；seen_sell2.json 两榜共用一份 id 池
    （同体系 dataoke 商品 id，天然交叉去重）。
    转链复用 dtk_bitui.convert_item（品带超红通路优先，退 get-privilege）。
    过了 SELL2_UNTIL 自动停推，恢复原样。
    """
    import dtk_bitui
    if not dtk_bitui.sell2_active():
        return 0
    seen = _sell2_seen()

    def _pull(kind):
        lst = dtk_bitui.fetch_rank(kind)
        if not lst:
            log(f"{dtk_bitui.RANKS[kind][2]} 本轮拉取为空/失败，跳过")
        return lst or []

    # Boss 2026-10-30 明令：专区动态发现（猫超好货28/超级疯狂日27等），按白名单逐 tag 拉取合并
    tags = _mc_tags()
    mc = []
    for tag, tname in tags.items():
        lst = dtk_bitui.fetch_tag(tag)
        if lst:
            mc.extend(lst)
            log(f"专区[{tname}](tag={tag}) 本轮拉到 {len(lst)} 条")
        else:
            log(f"专区[{tname}](tag={tag}) 本轮拉取为空/失败")
        time.sleep(0.3)
    s2 = _pull("sell2")
    try:
        refill_register(s2, log=log)  # Boss 2026-10-29 明令：2h 高佣商品进间隔补位池
        mc_refill_register(mc, log=log)  # Boss 2026-10-29 明令：猫超高佣进 5 分钟轮播池
    except Exception as e:
        log(f"补位池登记异常：{str(e)[:80]}")
    if not mc and not s2:
        return 0
    MARK = "_s2base"
    if not seen or MARK not in seen:
        seen.update(str(it.get("id")) for it in mc + s2 if it.get("id"))
        seen.add(MARK)
        _sell2_seen_save()
        log(f"外部群双榜基线已建立：猫超 {len(mc)} + 2h热销 {len(s2)}（去重后 {len(seen) - 1}）全部跳过，只推之后新进榜的")
        return 0

    got = 0
    n_low = 0
    mc_ids = set()

    def _try_put(it, maochao):
        nonlocal got, n_low
        if got >= SELL2_MAX_PER_ROUND:
            return
        gid = str(it.get("id"))
        if not gid or gid in seen or gid in mc_ids:
            return
        if not _tb_comm_ok(it):
            n_low += 1  # 佣金<4元不发群；不标 seen（日后佣金膨胀涨过线还能捞起来）
            return
        if not _tb_inflight_add(gid):
            return  # 已在后台转链中，防重复入队
        if maochao:
            it["_maochao"] = 1
            mc_ids.add(gid)
        TB_JOBS.put(("sell2", it))
        got += 1
        tag = "猫超佣金膨胀新品" if maochao else "2小时热销新品"
        log(f"{tag} {gid} | {(it.get('d_title') or '')[:26]}（已排入后台转链→外部群）")

    for it in mc:        # 猫超优先：先专区后 2h，同轮撞车专区先占坑并标注（按商品 is_chaoshi）
        _try_put(it, bool(it.get("is_chaoshi")))
    for it in s2:
        _try_put(it, False)
    if n_low:
        log(f"外部群佣金门槛过滤 {n_low} 条（预估佣金<4元，不发群）")
    return got


def poll_pdd(deals, have_ids):
    """好单库拼多多新品监听（2026-10-18 接入，Boss 提供 apikey）。

    新商品（goods_id 没见过）→ 后台转链（v3 unify_pdditems_link）→ 成品入站第三 tab。
    首跑**不建基线**：拼多多只上站、不进企微推送（Boss 2026-10-18 明令），没有炸群
    风险，首跑现页商品直接转链上站当种子内容（照搬淘宝必推榜的基线逻辑会让站上
    拼多多 tab 一直空窗——2026-10-18 实锤踩坑）。
    转链权限类报错自动冷却 1 小时，恢复后自愈，无需重启监控。
    红线：没转上链的绝不上站（与京东/淘宝同规矩）。只上站，不进企微推送。
    """
    if time.time() < _PDD_COOLDOWN["until"]:
        return 0
    import pdd_hdk
    seen = _pdd_seen()
    items = pdd_hdk.collect_supply(pages=PDD_POLL_PAGES)
    if not items:
        return 0
    got = 0
    for it in items:
        if got >= PDD_MAX_PER_ROUND:
            break
        gid = str(it.get("goods_id") or "")
        if not gid or gid in seen or gid in have_ids or ("pdd_" + gid) in have_ids:
            continue
        if not _tb_inflight_add(gid):
            continue  # 已在后台转链中，防重复入队
        TB_JOBS.put(("pdd", it))
        got += 1
        log(f"拼多多新品 {gid} | {str(it.get('goodsname') or '')[:26]}（已排入后台转链）")
    return got


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


def _ingest_one(d, cfg, deals, have_ids, seen, log=print):
    """新线报入库（主循环与启动补采共用）：转链→悦拜短链→落盘→进推送队列；失败进待转队列。"""
    wid = str(d["id"])
    seen.add(wid)
    save_json(SEEN_FILE, sorted(seen))
    title = next((x.get("content") for x in d.get("list", []) if x.get("content")), "")
    log(f"新线报 {wid} | {title[:30]}")
    try:
        out, st = jd_convert.convert_all_browser([d], cfg)
        for k, v in st.items():
            STATE[k] = STATE.get(k, 0) + v
        conv = out[0] if out else d
        if conv.get("_originalContext") or conv.get("_formatContext") or any(it.get("converted") for it in conv.get("list", [])):
            conv["price"] = jd_price_of(conv)  # 历史价格跟踪需要（精品库引擎不回价格，从文案取）
            conv["_addedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")  # 入站时间，前端用它算「X分钟前」
            try:
                yuebai_short.protect_deal(conv, log=log)  # 站上展示套悦拜短链（_siteContext），防机器人扒 u.jd.com 裸返利链
            except Exception as _ye:
                log(f"  短链保护跳过：{str(_ye)[:60]}")
            deals.insert(0, conv)
            KW_QUEUE.append(conv)  # 关键词推送队列
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


def backfill_recent(cfg, deals, have_ids, seen, log=print):
    """Boss 2026-10-13 明令：启动时补采当天启动前 2 小时内的漏网线报。
    如 7:10 启动 → 把 5:10 之后（且在当天 0 点之后）没入库的京东线报补全（翻页上限 20 页）。"""
    lo = max(time.mktime(time.strptime(time.strftime("%Y-%m-%d 00:00:00"), "%Y-%m-%d %H:%M:%S")),
             time.time() - 2 * 3600)
    lo_s = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(lo))
    log(f"启动补采：扫描 {lo_s} 之后的漏网线报（翻页上限 10 页）")
    got = 0
    for p in range(1, 11):
        try:
            items = build_site.fetch_page(cfg, p)["data"].get("items") or []
        except Exception as e:
            log(f"  补采第{p}页抓取失败: {e}")
            break
        if not items:
            break
        oldest = None
        for it in items:
            t = str(it.get("starttime") or "")
            if oldest is None or t < oldest:
                oldest = t
            wid = str(it.get("wire_id") or "")
            if not wid or not t or t < lo_s or wid in seen:
                continue
            d = build_site.normalize(it)
            if str(d.get("platform")) == "2" and has_link(d):
                _ingest_one(d, cfg, deals, have_ids, seen, log)
                got += 1
        time.sleep(0.4)
        if oldest and oldest < lo_s:
            break   # 本页已越过时间窗，不用再翻
    log(f"启动补采完成：补入 {got} 条漏网线报")
    return got


def acquire_single_instance():
    """单实例锁：已有监控在跑时本实例直接退出（防双开互踩覆盖 deals.json）。
    判定必须核对 cmdline 里真的有 incremental.py——Windows 会快速复用 PID，
    只看 is_running() 会把复用旧 PID 的无关 python 进程误判成监控，
    导致 stop 后 start 的新监控静默退出（Boss 遇到的「重启不生效」根因之一）。"""
    import psutil
    if os.path.exists(LOCK_FILE):
        try:
            old = int(open(LOCK_FILE, encoding="utf-8").read().strip())
            if old != os.getpid():
                p = psutil.Process(old)
                cl = " ".join(p.cmdline() or [])
                if p.is_running() and "incremental.py" in cl:
                    log(f"已有监控实例在跑（PID {old}），本实例退出")
                    sys.exit(0)
                log(f"锁文件里的 PID {old} 不是监控进程（残留锁/PID被复用），直接接管")
        except (psutil.NoSuchProcess, ValueError, ProcessLookupError):
            pass  # 旧实例已死，锁过期，接管
        except Exception:
            pass
    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(LOCK_FILE) and os.remove(LOCK_FILE))


class _Tee:
    """同时写 stdout 和文件（计划任务/pythonw 后台跑时日志落 monitor_log.txt）。"""
    def __init__(self, *fs):
        self.fs = fs

    def write(self, s):
        for f in self.fs:
            try:
                f.write(s)
                f.flush()
            except Exception:
                pass

    def flush(self):
        for f in self.fs:
            try:
                f.flush()
            except Exception:
                pass


def main():
    # 后台运行（计划任务/pythonw 无控制台）：stdout 可能为 None，日志兜底写文件
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    try:
        _logf = open(os.path.join(BASE_DIR, "monitor_log.txt"), "a", encoding="utf-8", buffering=1)
        sys.stdout = _Tee(sys.stdout, _logf)
        sys.stderr = _Tee(sys.stderr, _logf)
    except Exception:
        pass
    def _stamp(fn):
        p = os.path.join(BASE_DIR, fn)
        return time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(p))) if os.path.exists(p) else "?"
    log("=== 监控启动 PID=%d | 代码版本: incremental@%s keyword_push@%s build_site@%s yuebai_short@%s ==="
        % (os.getpid(), _stamp("incremental.py"), _stamp("keyword_push.py"),
           _stamp("build_site.py"), _stamp("yuebai_short.py")))
    acquire_single_instance()
    # 企微智能机器人长连接（关键词推送通道）：后台线程，断了自动重连
    try:
        keyword_push.start()
        print("推送通道=%s" % keyword_push._STATE.get("channel", "?"))
    except Exception as e:
        print("推送模块启动失败：%s" % str(e)[:100])
    start_tb_worker()  # 淘宝转链后台线程（方案B：京东主循环不再被淘宝堵塞）

    # 双11福利清单自动更新（Boss 2026-10-22 拍板：每 10 分钟一轮）
    # 独立 daemon 线程：一轮约 100s（抓取+增量转链+写 KV），不能堵主循环；
    # 与 deals 体系完全隔离（自己的 cache、自己的 KV key），异常只记日志
    def _welfare_loop():
        wa = _welfare_mod()
        while True:
            try:
                wa.run_once()
            except Exception as e:
                print(f"福利清单更新异常：{str(e)[:120]}")
            time.sleep(WELFARE_EVERY)
    threading.Thread(target=_welfare_loop, daemon=True).start()
    print(f"福利清单自动更新线程已启动（每 {WELFARE_EVERY//60} 分钟一轮）")

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

    # Boss 2026-10-13 明令：启动时补采当天启动前 2 小时的漏网线报（如 7:10 启动 → 补 5、6 点的）
    deals0 = [d for d in load_json(os.path.join(SITE_DIR, "deals.json"), []) if has_link(d)]
    have_ids0 = {str(d.get("id")) for d in deals0}
    if not once:
        try:
            backfill_recent(cfg, deals0, have_ids0, seen, log)
        except Exception as e:
            log(f"启动补采异常：{str(e)[:100]}")

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
                _ingest_one(d, cfg, deals, have_ids, seen, log)

            # 自动补转：每轮从待转队列取 1 条重试，转上链才入库部署
            pending = load_json(PENDING_FILE, [])
            if pending:
                d = pending[0]
                wid = str(d.get("id"))
                try:
                    out, st = jd_convert.convert_all_browser([d], cfg)
                    conv = out[0] if out else d
                    if conv.get("_originalContext") or conv.get("_formatContext") or any(it.get("converted") for it in conv.get("list", [])):
                        conv["price"] = jd_price_of(conv)  # 历史价格跟踪需要
                        conv["_addedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")  # 入站时间，前端用它算「X分钟前」
                        try:
                            yuebai_short.protect_deal(conv, log=log)  # 站上展示套悦拜短链（_siteContext），防机器人扒 u.jd.com 裸返利链
                        except Exception as _ye:
                            log(f"  短链保护跳过：{str(_ye)[:60]}")
                        deals.insert(0, conv)
                        KW_QUEUE.append(conv)  # 关键词推送队列
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

            # 大淘客必推榜新品（Boss 2026-09-16：淘宝推送只认这个榜，新进榜才推）
            try:
                poll_bitui()
            except Exception as e:
                log(f"必推榜轮询异常：{str(e)[:100]}")

            # 大淘客2小时热销榜（Boss 2026-10-23：双11期间外部群淘宝线报换成这个榜）
            try:
                poll_sell2()
            except Exception as e:
                log(f"2小时热销榜轮询异常：{str(e)[:100]}")

            # 高佣补位调度（Boss 2026-10-29 明令）：每 10 分钟从补位池挑佣金最高的 1 条转链补主群
            try:
                refill_tick(log)
            except Exception as e:
                log(f"高佣补位调度异常：{str(e)[:80]}")

            # 猫超高佣轮播调度（Boss 2026-10-29 明令）：每 5 分钟 3 条，没新货轮播旧的高佣
            try:
                mc_refill_tick(log)
            except Exception as e:
                log(f"猫超轮播调度异常：{str(e)[:80]}")

            # 专区动态发现（Boss 2026-10-30 明令）：新专区自动加入、下线专区自动移除，每 10 分钟一查
            try:
                poll_promo_tags(log)
            except Exception as e:
                log(f"专区发现异常：{str(e)[:80]}")

            # 好单库拼多多新品（2026-10-18 接入：新商品转链后上站第三 tab）
            try:
                poll_pdd(deals, have_ids)
            except Exception as e:
                log(f"拼多多轮询异常：{str(e)[:100]}")

            # 收淘宝后台转链成品（入库/进推送队列；主线程单写者纪律）
            try:
                n_tip, n_bit, n_pdd, n_s2 = drain_tb_done(deals, have_ids)
                if n_bit or n_s2:
                    mark_dirty(f"bitui x{n_bit}" + (f" sell2 x{n_s2}" if n_s2 else ""))
            except Exception as e:
                log(f"淘宝成品回收异常：{str(e)[:100]}")

            # 关键词订阅推送（企微智能机器人长连接；配置热生效）
            try:
                if KW_QUEUE:
                    keyword_push.flush(KW_QUEUE, log=log)
                    KW_QUEUE.clear()
            except Exception as e:
                log(f"关键词推送异常：{str(e)[:80]}")
            # 23:27 收播公告（Boss 2026-10-16 明令）：必须每轮无条件查——
            # 挂在 flush 里时 23:27 后没新线报就一次都不执行，公告发不出去（10-16 晚踩坑）
            try:
                keyword_push.night_tick(log=log)
            except Exception as e:
                log(f"夜闸检查异常：{str(e)[:80]}")
            # 双11红包场次播报（Boss 2026-10-17 明令）：同样每轮无条件查，到点发官方文案+静默2分钟
            try:
                keyword_push.redpack_tick(log=log)
            except Exception as e:
                log(f"红包场次检查异常：{str(e)[:80]}")
            # 每日点击汇总（Boss 2026-10-25 明令）：每天 23:00 发一次当日点击汇总到主群
            try:
                keyword_push.click_stat_tick(log=log)
            except Exception as e:
                log(f"点击汇总检查异常：{str(e)[:80]}")
            # 每 20 轮（约 10 分钟）打一次推送通道状态，方便排查
            _ROUND[0] += 1
            if _ROUND[0] % 20 == 0 or _ROUND[0] == 1:
                if keyword_push._STATE.get("channel") == "longconn":
                    try:
                        import wecom_push
                        st = wecom_push.status()
                        log(f"企微长连接状态={st['state']} since={st['since']} err={st['last_err'][:60]} 已注册会话={len(wecom_push.known_chatids())}")
                    except Exception:
                        pass

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
