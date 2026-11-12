# -*- coding: utf-8 -*-
"""验证 20033 商品（含京喜）的折京客转链：试多种链接格式，看哪个能通；
同时统计 skuTagList 标签分布（是否全是京喜/超补）。"""
import json
import re
import requests

c = json.load(open("ztk_config.json", encoding="utf-8"))
raw = open("jd20033_bodies/resp13.json", encoding="utf-8").read().split("\n\n", 1)[1]
j = json.loads(raw)
items = j["result"]["goodsSynopsisList"]


def conv(mid):
    s = requests.Session()
    s.trust_env = False
    p = {"appkey": c["appkey"], "materialId": mid, "unionId": c.get("unionId", ""),
         "chainType": c.get("chainType", 2)}
    try:
        r = s.get("http://api.zhetaoke.com:20000/api/open_jing_union_open_promotion_byunionid_get.ashx",
                  params=p, timeout=25).json()
    except Exception as e:
        return "ERR " + str(e)[:40]
    inner = (r.get("jd_union_open_promotion_byunionid_get_response") or {}).get("result")
    d = json.loads(inner) if isinstance(inner, str) else (inner or {})
    data = d.get("data") or {}
    if data.get("shortURL"):
        return "OK shortURL=" + str(data.get("shortURL"))[:40] + " | comm=" + str(
            data.get("commissionShare") or (data.get("commissionInfo") or {}).get("commissionShare"))
    return "FAIL status=%s msg=%s" % (r.get("status"), str(r.get("content"))[:40])


print("=== 标签分布（前20）===")
tags = {}
for it in items:
    for t in (it.get("skuTagList") or []):
        tags[t.get("name")] = tags.get(t.get("name"), 0) + 1
print(tags)

print("\n=== 前5个商品 多格式转链测试 ===")
for it in items[:5]:
    sid = re.search(r"(\d{8,})", it["skuUrl"]).group(1)
    base = it["skuUrl"]
    for label, mid in (("m站", base),
                       ("PC", "https://item.jd.com/%s.html" % sid),
                       ("jx", "https://jx.jd.com/%s.html" % sid)):
        print("[%s] %s -> %s" % (label, sid, conv(mid)))
