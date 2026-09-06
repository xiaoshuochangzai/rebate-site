# -*- coding: utf-8 -*-
"""全量重放：对所有线报跑一遍 convert_all_browser（新 apply_result）。
命中缓存的直接重放（含 3.cn 券短链 + originalContext），未命中的才走接口。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import incremental
import jd_convert_browser as jc

deals = incremental.load_json("site/deals.json", [])
print(f"共 {len(deals)} 条，开始全量重放...")

out, stats = jc.convert_all_browser(deals)
print("重放结果:", stats)

incremental.save_json("site/deals.json", deals)
print("已写回 site/deals.json")

# 快速统计
n_short = sum(1 for d in deals for it in d.get("list", [])
              if "3.cn/" in (it.get("coupon_url") or ""))
n_long = sum(1 for d in deals for it in d.get("list", [])
             if "coupon.m.jd.com" in (it.get("coupon_url") or ""))
n_ctx = sum(1 for d in deals if d.get("_originalContext"))
print(f"券短链 {n_short} | 券长链残留 {n_long} | originalContext {n_ctx}/{len(deals)}")
