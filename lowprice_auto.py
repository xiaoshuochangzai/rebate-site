# -*- coding: utf-8 -*-
"""低价好物榜自动更新（Boss 2026-11-03 明令：大淘客 top_sell 榜，佣金率>10%；
价格走 price_cap 统一门槛：券后≤100 元、佣金高放宽至 ≤110，Boss 2026-11-05 明令）。

一轮 = dtk_bitui.fetch_rank("sell") 拉榜 → 过滤（price_cap 统一门槛 & commission_rate>10）→
与 lp_conv_cache.json 对比 → 新商品走 ratesurl v3 转链（复用 welfare_convert.conv）→
lowprice.json 本地落盘（首屏兜底）→ cf_kv.put_lowprice 整包写 KV（前端 /api/lowprice 实时读）。
数据无变化不写 KV（省额度）。只上站不推送（Boss 未要求进群）。

调度：由 incremental.py 的福利清单线程同节奏（每 600s）调 run_once()；
独立运行（python lowprice_auto.py）则自循环，供手动测试。
"""
import json
import os
import sys
import time
import hashlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

LOWPRICE_PATH = os.path.join("site", "lowprice.json")
CACHE = "lp_conv_cache.json"
MAX_ITEMS = 200          # 滚动保留条数
MIN_RATE = 10.0          # Boss 明令：佣金率 >10%
GAP = 0.8                # 转链条间间隔（防风控）

_log_state = {"md5": ""}


def _log(msg):
    try:
        print(time.strftime("[%H:%M:%S] ") + msg)
    except Exception:
        pass


def _load_cache():
    try:
        return json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(c):
    try:
        json.dump(c, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass



def _filter_rank():
    """拉 top_sell 榜并按 Boss 口径过滤：佣金率>10% + 统一价格门槛
    （券后 ≤100 元；佣金高（佣金额≥10 元）放宽上浮 10% 至 ≤110。
    佣率>10% 时价格 >100 元佣金额必然 >10，故放宽段自动生效）。
    返回 dtk 原始条目（含 commission_rate/d_title 等全字段），供上下两路各自映射。"""
    import dtk_bitui
    import price_cap
    lst = dtk_bitui.fetch_rank("sell")
    out = []
    for it in lst:
        try:
            price = float(it.get("price") or 0)
            rate = float(it.get("commission_rate") or 0)
        except Exception:
            continue
        if rate <= MIN_RATE:
            continue
        if not price_cap.price_ok(price, price * rate / 100.0):
            continue
        out.append(it)
    return out


def fetch_lowprice():
    """上站（tab）用映射：券额/原价算「券后省%」（Boss 2026-11-03：站内禁止佣金字样），
    输出不含任何佣金字段。"""
    out = []
    for it in _filter_rank():
        price = float(it.get("price") or 0)
        try:
            quan = float(it.get("coupon_amount") or 0)
            oprice = float(it.get("original_price") or 0)
        except Exception:
            quan, oprice = 0.0, 0.0
        out.append({
            "id": str(it.get("id") or ""),
            "goodsid": it.get("goodsid") or "",
            "t": it.get("d_title") or "",
            "price": ("%.1f" % price).rstrip("0").rstrip("."),
            "quan": ("%.1f" % quan).rstrip("0").rstrip("."),
            "oprice": ("%.1f" % oprice).rstrip("0").rstrip("."),
            "pic": it.get("main_pic") or "",
            "sales_2h": it.get("sales_2h") or 0,
            "_kind": it.get("_kind") or "sell",
        })
    return out


def lp_candidates():
    """线报登记用候选（Boss 2026-11-03：低价好物纳入线报，池内 40 名额）：
    dtk 原始字段直出（d_title/commission_rate/sales_2h 齐全，供轮动池门槛与综合分）。
    佣金字段仅内部门槛计算用，绝不上站显示。"""
    return _filter_rank()


def run_once(log=_log):
    import welfare_convert
    import cf_kv
    cache = _load_cache()
    cand = fetch_lowprice()
    if not cand:
        log("低价好物：榜单拉取为空/失败，本轮跳过")
        return
    # 载入现有数据（保留旧条目，新的插头部）
    try:
        cur = json.load(open(LOWPRICE_PATH, encoding="utf-8"))
        items = cur.get("items") or []
    except Exception:
        items = []
    have_ids = {str(x.get("id")) for x in items}
    fresh = [it for it in cand if it["id"] and it["id"] not in have_ids]
    if fresh:
        log(f"低价好物：候选 {len(cand)} 条，新增 {len(fresh)} 条，开始转链（0.8s/条）")
    for it in fresh:
        iid = it.get("goodsid") or ""
        if not iid:
            continue
        if iid in cache and cache[iid].get("link"):
            r = cache[iid]
        else:
            try:
                r = welfare_convert.conv(iid, it.get("t") or "商品")
                cache[iid] = r
                time.sleep(GAP)
            except Exception as e:
                # 红线：没转上链的绝不上站——转链失败直接丢弃该条，不留原链
                log(f"低价好物转链失败 {it['id']}：{str(e)[:60]}，丢弃")
                continue
        if not r.get("link"):
            continue
        it["link"] = r["link"]
        it["tpwd"] = r.get("tpwd") or ""
        it["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        items.insert(0, it)
    # 滚动保留
    items = items[:MAX_ITEMS]
    _save_cache(cache)
    data = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "total": len(items), "items": items}
    # 无变化不写（省 KV 额度）
    md5 = hashlib.md5(json.dumps(data["items"], ensure_ascii=False).encode("utf-8")).hexdigest()
    if fresh:
        try:
            json.dump(data, open(LOWPRICE_PATH, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception as e:
            log(f"低价好物落盘失败：{str(e)[:60]}")
    if md5 != _log_state["md5"]:
        _log_state["md5"] = md5
        try:
            cf_kv.put_lowprice(data)
            log(f"低价好物已写 KV（{len(items)} 条）")
        except Exception as e:
            log(f"低价好物写 KV 失败：{str(e)[:80]}")


if __name__ == "__main__":
    while True:
        try:
            run_once()
        except Exception as e:
            _log(f"低价好物一轮异常：{str(e)[:90]}")
        time.sleep(600)
