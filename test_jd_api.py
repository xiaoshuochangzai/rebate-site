# -*- coding: utf-8 -*-
"""京东联盟 API 调用测试：验证 appKey/appSecret + 找 unionId"""
import hashlib
import json
import sys
import time
import urllib.request

APP_KEY = "0c6b36c415816e272576a58271506e70"
APP_SECRET = "17b11c308acf4d1f8b3d4f6c22b514f4"
GATEWAY = "https://api.jd.com/routerjson"
UNION_ID = ""  # 待确认


def call_api(method, param_json):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    params = {
        "method": method,
        "app_key": APP_KEY,
        "timestamp": ts,
        "format": "json",
        "v": "1.0",
        "sign_method": "md5",
        "360buy_param_json": json.dumps(param_json, ensure_ascii=False, separators=(",", ":")),
    }
    sign_src = APP_SECRET + "".join(f"{k}{v}" for k, v in sorted(params.items())) + APP_SECRET
    params["sign"] = hashlib.md5(sign_src.encode("utf-8")).hexdigest().upper()
    data = "&".join(f"{k}={urllib.request.quote(str(v), safe='')}" for k, v in params.items())
    req = urllib.request.Request(GATEWAY, data=data.encode("utf-8"),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


if __name__ == "__main__":
    # 转链测试：好单库抓到的一条京东券链接
    material = "https://coupon.m.jd.com/coupons/show.action?key=c9m4c3s9o7a641d582632602f104dfa1&roleId=3159198800"
    pj = {"materialUrl": material, "siteId": 4101168346}
    if UNION_ID:
        pj["unionId"] = UNION_ID
    try:
        resp = call_api("jd.union.open.promotion.common.get", pj)
        print(json.dumps(resp, ensure_ascii=False, indent=2)[:2000])
    except Exception as e:
        print("ERROR:", e)
