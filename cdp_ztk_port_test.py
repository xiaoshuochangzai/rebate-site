# -*- coding: utf-8 -*-
"""实证 Boss 质疑：折京客转链 :10001 端口（文档"京东转链API-新"）是否支持纯数字 skuId。
对比现有代码用的 :20000 端口。打印完整原始响应，避免解析异常掩盖真相。"""
import json
import requests

c = json.load(open("ztk_config.json", encoding="utf-8"))
SKU = "10238662128233"
URLS = {
    "numeric_skuId": SKU,
    "m_url": "https://item.m.jd.com/product/%s.html?sku=%s" % (SKU, SKU),
    "pc_url": "https://item.jd.com/%s.html" % SKU,
    "jx_url": "https://jx.jd.com/%s.html" % SKU,
}


def conv(port, mid):
    s = requests.Session()
    s.trust_env = False
    p = {"appkey": c["appkey"], "materialId": mid,
         "unionId": c.get("unionId", ""), "chainType": c.get("chainType", 2)}
    base = "http://api.zhetaoke.com:%d/api/open_jing_union_open_promotion_byunionid_get.ashx" % port
    try:
        r = s.get(base, params=p, timeout=25)
    except Exception as e:
        return "REQ-ERR " + str(e)[:60], None
    txt = r.text
    # 解析
    try:
        j = r.json()
    except Exception:
        return "RAW(status=%d,len=%d): %s" % (r.status_code, len(txt), txt[:200]), None
    inner = (j.get("jd_union_open_promotion_byunionid_get_response") or {}).get("result")
    d = json.loads(inner) if isinstance(inner, str) else (inner or {})
    data = d.get("data") or {}
    short = data.get("shortURL") or (data.get("short_url"))
    comm = data.get("commissionShare") or (data.get("commissionInfo") or {}).get("commissionShare")
    if short:
        return "OK shortURL=%s comm=%s" % (str(short)[:40], comm), j
    return "FAIL status=%s content=%s" % (j.get("status"), str(j.get("content"))[:60]), j


for port in (20000, 10001):
    print("\n########## 端口 :%d ##########" % port)
    for label, mid in URLS.items():
        res, j = conv(port, mid)
        print("[%s] %s -> %s" % (label, mid[:50], res))
