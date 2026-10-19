# -*- coding: utf-8 -*-
"""双11福利清单：拉 7 个标签的商品 → site/welfare.json（免登录裸调）"""
import json, urllib.request, urllib.parse, io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

CODE = "G0SQxQ"
CATS = [("324","消灭小红包"),("433","双11付定享礼"),("65","吃喝玩乐1折起"),
        ("430","直播精选"),("1","全网实时热榜"),("4","今日值得买"),("5","猫超福利")]
MAX_PAGES = 10

def get_items(cid, mid):
    u = "https://v2.api.haodanku.com/activity_items?" + urllib.parse.urlencode(
        {"cat_id": cid, "min_id": mid, "cs": 1, "code": CODE})
    req = urllib.request.Request(u, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        "Referer": "https://hdkc272.kzurl01.cn/"})
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.loads(r.read().decode("utf-8"))
    data = d.get("data") or []
    return data if isinstance(data, list) else []

def conv(it):
    coupon = it.get("couponmoney") or ""
    try:
        coupon = float(coupon)
        if coupon == int(coupon):
            coupon = int(coupon)
        coupon = "%.0f" % coupon if coupon == int(coupon) else ("%.1f" % coupon)
    except Exception:
        coupon = ""
    def _p(k):
        try:
            v = float(it.get(k) or 0)
            return ("%.0f" % v) if v == int(v) else ("%.2f" % v).rstrip("0").rstrip(".")
        except Exception:
            return ""
    link = (it.get("couponurl") or "").strip()
    return {
        "t": it.get("itemshorttitle") or it.get("itemtitle") or "",
        "pic": (it.get("itempic") or "").split("_310x310")[0] + "_400x400.jpg" if it.get("itempic") else "",
        "price": _p("itemprice"),
        "end": _p("itemendprice"),
        "coupon": coupon,
        "sale": it.get("itemsale2") or it.get("itemsale") or "",
        "link": link,
    }

out = {"cats": []}
total = 0
for cid, name in CATS:
    items, seen = [], set()
    for p in range(1, MAX_PAGES + 1):
        try:
            batch = get_items(cid, p)
        except Exception as e:
            print(name, "page", p, "ERR", e)
            break
        if not batch:
            break
        for it in batch:
            iid = it.get("itemid") or (it.get("itemtitle") or "") + (it.get("itempic") or "")
            if iid in seen:
                continue
            seen.add(iid)
            c = conv(it)
            if c["t"] and c["link"]:
                items.append(c)
        time.sleep(0.4)
    out["cats"].append({"id": cid, "name": name, "items": items})
    total += len(items)
    print(name, "->", len(items), "items")

with open("site/welfare.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
import os
print("TOTAL", total, "size", os.path.getsize("site/welfare.json"))
