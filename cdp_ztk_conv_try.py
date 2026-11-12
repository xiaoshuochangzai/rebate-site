# -*- coding: utf-8 -*-
"""验证：20033 的 skuUrl 走折京客官方转链，返回里是否含佣金比例（commissionShare）。"""
import json
import requests

c = json.load(open("ztk_config.json", encoding="utf-8"))
raw = open("jd20033_bodies/resp13.json", encoding="utf-8").read().split("\n\n", 1)[1]
j = json.loads(raw)
items = j["result"]["goodsSynopsisList"]
sku = items[0]["skuUrl"]
print("skuUrl:", sku)
s = requests.Session()
s.trust_env = False
p = {"appkey": c["appkey"], "materialId": sku, "unionId": c.get("unionId", ""),
     "chainType": c.get("chainType", 2)}
r = s.get("http://api.zhetaoke.com:20000/api/open_jing_union_open_promotion_byunionid_get.ashx",
          params=p, timeout=25).json()
inner = (r.get("jd_union_open_promotion_byunionid_get_response") or {}).get("result")
d = json.loads(inner) if isinstance(inner, str) else (inner or {})
data = d.get("data") or {}
print("转链 data keys:", list(data.keys()))
for k, v in data.items():
    if any(w in k.lower() for w in ("comm", "rate", "share", "rebate")):
        print("  佣/率字段:", k, "=", v)
print("shortURL:", data.get("shortURL"))
