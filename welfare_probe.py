# -*- coding: utf-8 -*-
"""探测 activity_items 7 个标签：条数/翻页/字段里有没有推广链接"""
import json, urllib.request, urllib.parse, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

CODE = "G0SQxQ"
CATS = [("324","消灭小红包"),("433","双11付定享礼"),("65","吃喝玩乐1折起"),
        ("430","直播精选"),("1","全网实时热榜"),("4","今日值得买"),("5","猫超福利")]

def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
        "Referer": "https://hdkc272.kzurl01.cn/"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

LINK_KEYS = [k for k in []]  # fill later
report = {}
for cid, name in CATS:
    # 第一页
    u = "https://v2.api.haodanku.com/activity_items?" + urllib.parse.urlencode(
        {"cat_id": cid, "min_id": 1, "cs": 1, "code": CODE})
    d = get(u)
    data = d.get("data") or []
    if isinstance(data, dict):
        items = data.get("items") or data.get("list") or []
    else:
        items = data
    total_pages = d.get("total_page") or d.get("data_total_page")
    # 字段分析
    keys = set()
    link_vals = []
    for it in items:
        keys.update(it.keys())
        for k, v in it.items():
            if isinstance(v, str) and ("http" in v or "tb.cn" in v):
                link_vals.append((k, v[:90]))
    report[name] = {"cat_id": cid, "page1_count": len(items), "total_page": total_pages,
                    "keys": sorted(keys), "link_samples": link_vals[:8]}
    # 翻页第2页探一下
    if len(items) > 0:
        u2 = "https://v2.api.haodanku.com/activity_items?" + urllib.parse.urlencode(
            {"cat_id": cid, "min_id": 2, "cs": 1, "code": CODE})
        d2 = get(u2)
        data2 = d2.get("data") or []
        items2 = data2 if isinstance(data2, list) else []
        report[name]["page2_count"] = len(items2)

print(json.dumps(report, ensure_ascii=False, indent=1))
with open("welfare_probe.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
