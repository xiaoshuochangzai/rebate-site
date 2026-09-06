# -*- coding: utf-8 -*-
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_convert_browser as jd_convert

DEALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site", "deals.json")

all_deals = json.load(open(DEALS_FILE, encoding="utf-8"))
print(f"载入 {len(all_deals)} 条线报")

targets = [d for d in all_deals if d["id"] in ("1595788", "1595787")]
print(f"待转链：{[d['id'] for d in targets]}")

out, stats = jd_convert.convert_all_browser(targets)
print("转链结果：", stats)

# convert_all_browser 已就地修改 targets（即 all_deals 中的同一批对象）
ok_ids = [d["id"] for d in targets if any(it.get("url") for it in d.get("list", []))]
print("已成功写入 url 的 id：", ok_ids)

json.dump(all_deals, open(DEALS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已写回", DEALS_FILE)
