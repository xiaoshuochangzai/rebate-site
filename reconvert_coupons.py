# -*- coding: utf-8 -*-
"""一次性重转：把 site/deals.json 里含 coupon.m.jd.com 券长链的线报重新转链，
拿到 3.cn 券短链 + originalContext 完整转换文案，写回并部署。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import incremental
import jd_convert_browser as jc

deals = incremental.load_json("site/deals.json", [])
targets = [d for d in deals
           if any("coupon.m.jd.com" in ((it.get("coupon_url") or ""))
                  for it in d.get("list", []))]
print(f"共 {len(deals)} 条，其中含券长链待重转 {len(targets)} 条：{[d['id'] for d in targets]}")
if not targets:
    sys.exit(0)

# 旧缓存里的数据没有短链字段，备份后绕开，重转完再合并回去
cache_bak = "link_cache.json"
merged = {}
if os.path.exists(cache_bak):
    merged = json.load(open(cache_bak, encoding="utf-8"))
    os.rename(cache_bak, "link_cache.json.bak")

out, stats = jc.convert_all_browser(targets)
print("重转结果:", stats)

# 合并缓存：新条目覆盖旧条目（同 md5 的新数据优先）
new_cache = json.load(open(cache_bak, encoding="utf-8")) if os.path.exists(cache_bak) else {}
merged.update(new_cache)
json.dump(merged, open(cache_bak, "w", encoding="utf-8"), ensure_ascii=False)
print(f"缓存合并完成：{len(merged)} 条")

incremental.save_json("site/deals.json", deals)
print("已写回 site/deals.json")
