# -*- coding: utf-8 -*-
"""离线验证 20033：载入 jd20033_bodies → 解析 → 建项 → qualifies(≤60) → 选 3 条转链 → to_item。"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lowprice_jd_auto as L

bodies_dir = os.path.join(L.BASE_DIR, "jd20033_bodies")
raws = []
for fn in sorted(glob.glob(os.path.join(bodies_dir, "resp*.json"))):
    try:
        txt = open(fn, encoding="utf-8").read().split("\n\n", 1)
        j = json.loads(txt[1] if len(txt) > 1 else txt[0])
        raws.extend(L.parse_20033_response(j))
    except Exception as e:
        print("skip", fn, e)
print("原始商品去重前:", len(raws))

items = L.build_20033_items(raws, log=L._log)
print("建项(可用券):", len(items))
q = {g: it for g, it in items.items() if L.qualifies(it)}
print("qualifies(≤60且券未过期):", len(q))

# 价格分布
prices = sorted(float(it["quanhou_jiage"]) for it in q.values())
print("价区间: %.2f ~ %.2f" % (prices[0], prices[-1]))

# 选 3 条转链验证券链接能出 u.jd.com
import itertools
tested, ok = 0, 0
for gid, it in itertools.islice(q.items(), 8):
    link = L.convert_one(it, log=L._log)
    hit = "u.jd.com" in link
    ok += 1 if hit else 0
    tested += 1
    card = L.to_item(it, link or "(转链失败)")
    print("  [%s] %s | 到手%s | 券%s | 月销%s | %s" % (
        "OK" if hit else "FAIL", card["t"][:18], card["price"],
        card["quan"], card["sales30"], card["link"][:40]))
    if tested >= 5:
        break
print("转链测试: %d/%d 成功" % (ok, tested))
print("OFFLINE 20033 解析/建项/qualifies 通过" if tested and ok else "需检查转链")
