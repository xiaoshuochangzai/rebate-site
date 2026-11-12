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



def _filter_rank(kind="sell"):
    """按 Boss 口径过滤单榜：佣金率>10% + 统一价格门槛（券后 ≤100 元；
    佣金高（佣金额≥10 元）放宽上浮 10% 至 ≤110）。
    返回 dtk 原始条目（含 commission_rate/d_title 等全字段）。"""
    import dtk_bitui
    import price_cap
    lst = dtk_bitui.fetch_rank(kind)
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


def _filter_rank_all(log=_log):
    """Boss 2026-11-12：低价好物上站源 = 三优势榜并集（2h热销上榜/今日热销榜上榜/
    热推榜上榜 = dtk_bitui 的 sell2/sell/tui）+ 同款归一（标题前10字留券后价最低）。
    线报轮动池 lp_candidates 仍走 _filter_rank("sell") 单榜，不受影响。"""
    merged, seen = [], set()
    for kind in ("sell2", "sell", "tui"):
        try:
            for it in _filter_rank(kind):
                gid = str(it.get("goodsid") or it.get("id") or "")
                if gid and gid not in seen:
                    seen.add(gid)
                    it["_kind"] = kind
                    merged.append(it)
        except Exception as e:
            log(f"低价好物：{kind} 榜拉取异常 {str(e)[:60]}，跳过该榜")
    if not merged:
        return []
    best = {}
    for it in merged:
        k = (it.get("d_title") or it.get("title") or "")
        import re as _re
        k = _re.sub(r"[\s【】\[\]（）()!！,，。.:：;；\"'“”‘’\-—_/|｜＋+]", "", k)[:10]
        try:
            p = float(it.get("price") or 0)
        except Exception:
            p = 0.0
        cur = best.get(k)
        if cur is None or p < cur[1]:
            best[k] = (it, p)
    out = [x for x, _p in best.values()]
    log(f"低价好物：三榜并集 {len(merged)} 条，同款归一后 {len(out)} 条")
    return out


def fetch_lowprice():
    """上站（tab）用映射：券额/原价算「券后省%」（Boss 2026-11-03：站内禁止佣金字样），
    输出不含任何佣金字段。Boss 2026-11-12：源改三优势榜并集 + sales30（穿插排序权重）。"""
    out = []
    for it in _filter_rank_all():
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
            "sales30": it.get("sales_2h") or it.get("sales_num") or 0,
            "_kind": it.get("_kind") or "sell",
        })
    return out


def lp_candidates():
    """线报登记用候选（Boss 2026-11-03：低价好物纳入线报，池内 40 名额）：
    dtk 原始字段直出（d_title/commission_rate/sales_2h 齐全，供轮动池门槛与综合分）。
    佣金字段仅内部门槛计算用，绝不上站显示。"""
    return _filter_rank()


def run_once(log=_log):
    """Boss 2026-11-12：镜像重建——以本轮三优势榜并集为准，源站消失即下架（无 7 天滚动）；
    新出现的才转链（缓存复用，失败下轮重试、绝不上站）；写盘前按 <20 / >=20 穿插排序。"""
    import welfare_convert
    import cf_kv
    from lowprice_jd_auto import interleave
    cache = _load_cache()
    cand = fetch_lowprice()
    if not cand:
        log("低价好物：榜单拉取为空/失败，本轮跳过（不清空，防误删）")
        return
    try:
        cur = json.load(open(LOWPRICE_PATH, encoding="utf-8"))
        old = {str(x.get("id")): x for x in (cur.get("items") or []) if x.get("link")}
    except Exception:
        old = {}
    items, n_new = [], 0
    for it in cand:
        gid = it.get("goodsid") or ""
        old_it = old.get(it["id"]) or {}
        r = cache.get(gid) or {}
        link = r.get("link") or old_it.get("link") or ""
        tpwd = r.get("tpwd") or old_it.get("tpwd") or ""
        if not link:
            try:
                r = welfare_convert.conv(gid, it.get("t") or "商品")
            except Exception as e:
                log(f"低价好物转链失败 {it['id']}：{str(e)[:60]}，下轮重试（本条不上站）")
                continue
            if not r.get("link"):
                log(f"低价好物转链失败 {it['id']}：无链接，下轮重试（本条不上站）")
                continue
            cache[gid] = r
            link, tpwd = r["link"], (r.get("tpwd") or "")
            time.sleep(GAP)
            n_new += 1
        it["link"] = link
        it["tpwd"] = tpwd
        it["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        items.append(it)
    items = interleave(items, log)[:MAX_ITEMS]
    _save_cache(cache)
    data = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "total": len(items), "items": items}
    md5 = hashlib.md5(json.dumps(data["items"], ensure_ascii=False).encode("utf-8")).hexdigest()
    try:
        json.dump(data, open(LOWPRICE_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        log(f"低价好物落盘失败：{str(e)[:60]}")
    if md5 != _log_state["md5"]:
        _log_state["md5"] = md5
        try:
            cf_kv.put_lowprice(data)
            log(f"低价好物已写 KV（{len(items)} 条，新转 {n_new}）")
        except Exception as e:
            log(f"低价好物写 KV 失败：{str(e)[:80]}")


if __name__ == "__main__":
    while True:
        try:
            run_once()
        except Exception as e:
            _log(f"低价好物一轮异常：{str(e)[:90]}")
        time.sleep(600)
