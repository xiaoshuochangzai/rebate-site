# -*- coding: utf-8 -*-
"""单条测试：取一条含券长链的线报单独转链，验证 3.cn 券短链 + originalContext 是否拿到。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("JD_CONV_DELAY", "5")
import incremental
import jd_convert_browser as jc

deals = incremental.load_json("site/deals.json", [])
target = None
for d in deals:
    if any("coupon.m.jd.com" in (it.get("coupon_url") or "") for it in d.get("list", [])):
        target = d
        break
if not target:
    print("没有含券长链的线报可测")
    sys.exit(0)

print(f"测试对象: {target['id']} | {target.get('time')}")
out, stats = jc.convert_all_browser([target])
print("结果:", stats)

data = target
print("promotionUrl:", next((it.get("url") for it in data["list"] if it.get("url")), ""))
print("failedUrlList 相关 - coupon_url 现状:")
for it in data.get("list", []):
    cu = it.get("coupon_url") or ""
    if cu:
        print("  ", cu[:100])
ctx = data.get("_originalContext", "")
print("originalContext:", (ctx[:300] + "...") if ctx else "(空)")

# 写回这一条
for i, d in enumerate(deals):
    if d["id"] == target["id"]:
        deals[i] = target
        break
incremental.save_json("site/deals.json", deals)
print("已写回 deals.json（仅此一条被更新）")
