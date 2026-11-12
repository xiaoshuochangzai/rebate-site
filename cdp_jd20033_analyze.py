# -*- coding: utf-8 -*-
"""分析 20033 unionSearchRecommend 响应体的字段结构。"""
import json
import os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jd20033_bodies")


def load(fn):
    raw = open(os.path.join(BASE, fn), encoding="utf-8").read()
    body = raw.split("\n\n", 1)[1]
    return json.loads(body)


def find_list(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                first = v[0]
                if any(x in first for x in ("skuId", "skuName", "sku_id", "wareId", "materialUrl", "itemId")):
                    return v
            r = find_list(v)
            if r:
                return r
    elif isinstance(obj, list):
        for it in obj:
            r = find_list(it)
            if r:
                return r
    return None


for fn in ("resp13.json", "resp17.json"):
    print("\n========== %s ==========" % fn)
    try:
        j = load(fn)
    except Exception as e:
        print("解析失败:", e)
        continue
    print("TOP KEYS:", list(j.keys()) if isinstance(j, dict) else type(j))
    # 逐层找商品
    items = find_list(j)
    if not items:
        # 尝试直接 data/list
        if isinstance(j, dict):
            for k in j:
                v = j[k]
                if isinstance(v, dict):
                    for k2 in v:
                        if isinstance(v[k2], list) and v[k2] and isinstance(v[k2][0], dict):
                            print("候选数组 %s.%s 长度 %d, 首条 keys: %s" % (
                                k, k2, len(v[k2]), list(v[k2][0].keys())[:30]))
        print("未直接定位商品数组，TOP 样例:")
        print(json.dumps(j, ensure_ascii=False)[:800])
        continue
    print("商品数组长度:", len(items))
    one = items[0]
    print("首条全部字段:")
    for k, v in one.items():
        s = json.dumps(v, ensure_ascii=False)
        print("  %s = %s" % (k, s[:120]))
    # 统计自营/包邮/补贴
    owners = {}
    freeship = 0
    subsidy = 0
    for it in items:
        ow = it.get("owner") or it.get("selfSell") or it.get("shopInfo", {}).get("owner") or "?"
        owners[ow] = owners.get(ow, 0) + 1
        fs = it.get("freeShip") or it.get("freeShipping") or it.get("freeShipment")
        if fs in (True, 1, "1", "true"):
            freeship += 1
        if any("subsid" in str(kk).lower() or "补贴" in str(kk) for kk in it.keys()):
            subsidy += 1
    print("owner 分布:", owners)
    print("包邮标记命中:", freeship, "/ 补贴标记命中:", subsidy)
