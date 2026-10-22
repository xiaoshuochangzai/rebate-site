# -*- coding: utf-8 -*-
"""双11福利清单自动更新（Boss 2026-10-22 拍板：每 10 分钟）。

一轮 = 裸调 activity_items 7 类 → 与 wf_conv_cache.json 对比 → 新商品走
ratesurl v3 转链（0.8s/条）→ welfare.json 本地落盘（首屏兜底）→ cf_kv.put_welfare
整包写 KV（前端 /api/welfare 实时读）。数据无变化不写 KV（省额度）。

调度：由 incremental.py 每 WELFARE_EVERY 秒调一次 run_once()；
本文件独立运行（python welfare_auto.py）则自循环，供手动测试。
"""
import json, os, sys, time, io, hashlib
import urllib.request, urllib.parse

if __name__ == "__main__" or True:
    pass  # 顶层保持无副作用，import 进监控不重复包 stdout

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

API_ITEMS = "https://v2.api.haodanku.com/activity_items"
API_RATES = "https://v3.api.haodanku.com/ratesurl"
APIKEY = "9AC3C71D776A"
PID = "mm_2130470034_3434000269_116316900171"
TB_NAME = "淘淘淘淘yh"
CODE = "G0SQxQ"
CATS = [("324", "消灭小红包"), ("433", "双11付定享礼"), ("65", "吃喝玩乐1折起"),
        ("430", "直播精选"), ("1", "全网实时热榜"), ("4", "今日值得买"), ("5", "猫超福利")]
MAX_PAGES = 10
GAP = 0.8
CACHE = "wf_conv_cache.json"
WELFARE_PATH = os.path.join("site", "welfare.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

_log_state = {"md5": ""}


def _http_json(url, data=None, enc="utf-8", timeout=20):
    headers = {"User-Agent": UA}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urllib.parse.urlencode(data, encoding=enc).encode("ascii")
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_items(cid, mid):
    d = _http_json(f"{API_ITEMS}?" + urllib.parse.urlencode(
        {"cat_id": cid, "min_id": mid, "cs": 1, "code": CODE}))
    data = d.get("data") or []
    return data if isinstance(data, list) else []


def conv(itemid, title):
    """ratesurl v3 转链：加密串 itemid 也吃。返回 {link, tpwd}；失败抛异常。"""
    d = _http_json(API_RATES, {
        "apikey": APIKEY, "pid": PID, "tb_name": TB_NAME, "get_taoword": "1",
        "title": title, "itemid": itemid})
    if str(d.get("code")) != "1":
        raise RuntimeError("code=%s %s" % (d.get("code"), str(d.get("msg"))[:50]))
    data = d.get("data") or {}
    link = (data.get("link") or "").strip() or (data.get("coupon_click_url") or "").strip()
    return {"link": link, "tpwd": (data.get("taoword") or "").strip()}


def _norm(it):
    """activity 原始条目 → 福利卡字段（与 welfare_fetch.py 一致）。"""

    def _p(k):
        try:
            v = float(it.get(k) or 0)
            return ("%.0f" % v) if v == int(v) else ("%.2f" % v).rstrip("0").rstrip(".")
        except Exception:
            return ""
    pic = it.get("itempic") or ""
    coupon = it.get("couponmoney") or ""
    try:
        c = float(coupon)
        coupon = "%.0f" % c if c == int(c) else ("%.1f" % c)
    except Exception:
        coupon = ""
    return {
        "itemid": it.get("itemid") or "",
        "t": it.get("itemshorttitle") or it.get("itemtitle") or "",
        "pic": (pic.split("_310x310")[0] + "_400x400.jpg") if pic else "",
        "price": _p("itemprice"),
        "end": _p("itemendprice"),
        "coupon": coupon,
        "sale": it.get("itemsale2") or it.get("itemsale") or "",
        "link": (it.get("couponurl") or "").strip(),
    }


def run_once():
    t0 = time.time()
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        cache = {}

    cats, todo = [], {}
    for cid, name in CATS:
        items, seen = [], set()
        for p in range(1, MAX_PAGES + 1):
            try:
                batch = fetch_items(cid, p)
            except Exception as e:
                print(f"[welfare] {name} 第{p}页抓取失败: {e}")
                break
            if not batch:
                break
            for it in batch:
                iid = it.get("itemid") or ""
                if not iid or iid in seen:
                    continue
                seen.add(iid)
                c = _norm(it)
                if c["t"] and c["link"]:
                    items.append(c)
                    todo.setdefault(iid, c)
            time.sleep(0.4)
        cats.append({"id": cid, "name": name, "items": items})

    # 增量转链：只有没转过的新商品走接口
    new_n = 0
    for iid, c in todo.items():
        if iid in cache and cache[iid].get("link"):
            c["link"] = cache[iid]["link"]
            if cache[iid].get("tpwd"):
                c["tpwd"] = cache[iid]["tpwd"]
            continue
        try:
            r = conv(iid, c["t"])
            if r["link"]:
                cache[iid] = r
                c["link"] = r["link"]
                if r.get("tpwd"):
                    c["tpwd"] = r["tpwd"]
                new_n += 1
        except Exception as e:
            print(f"[welfare] 转链失败 {c['t'][:16]}: {e}")
            if "404" in str(e) or "429" in str(e):
                time.sleep(6)
        time.sleep(GAP)
    if new_n:
        json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)

    total = sum(len(c["items"]) for c in cats)
    with open(WELFARE_PATH, "w", encoding="utf-8") as f:
        json.dump({"cats": cats}, f, ensure_ascii=False, separators=(",", ":"))

    # 数据没变不写 KV（免费额度 1000 写/天，省着用）
    payload = json.dumps({"cats": cats}, ensure_ascii=False, separators=(",", ":"))
    md5 = hashlib.md5(payload.encode("utf-8")).hexdigest()
    kv_msg = "数据无变化跳过"
    if md5 != _log_state.get("md5"):
        try:
            import cf_kv
            ok, msg = cf_kv.put_welfare({"cats": cats})
            kv_msg = f"KV {'成功' if ok else '失败:' + msg}"
            if ok:
                _log_state["md5"] = md5
        except Exception as e:
            kv_msg = f"KV 异常 {e}"
    # 红包弹层配置：京东链接按 Boss 规则（每 10 次使用重转）刷新后一并写 KV
    rp_msg = "跳过"
    try:
        import keyword_push
        jd_link = keyword_push._get_redpack_link(log=print)
        rp = {
            "jd": jd_link or "https://u.jd.com/FDFQoBI",
            "tb": {"tpwd": keyword_push.REDPACK_TB_TAIL.split("：")[1].split("（")[0].strip(),
                  "url": keyword_push.REDPACK_TB_TAIL.splitlines()[-1].strip()},
        }
        with open(os.path.join("site", "redpack.json"), "w", encoding="utf-8") as f:
            json.dump(rp, f, ensure_ascii=False, separators=(",", ":"))
        import cf_kv
        ok, msg = cf_kv.put_redpack(rp)
        rp_msg = f"红包KV {'成功' if ok else '失败:' + msg} | 京东 {rp['jd']}"
    except Exception as e:
        rp_msg = f"红包刷新异常 {str(e)[:80]}"

    print(f"[welfare] 一轮完成 {int(time.time()-t0)}s | 商品 {total} | 新转链 {new_n} | {kv_msg} | {rp_msg}")
    return True


if __name__ == "__main__":
    print("[welfare] 独立测试模式：单轮")
    run_once()
