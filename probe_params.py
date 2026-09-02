# -*- coding: utf-8 -*-
"""京东联盟转链 API 参数探测：找出当前应用可用的参数组合"""
import hashlib
import json
import time
import urllib.parse
import urllib.request

APP_KEY = "0c6b36c415816e272576a58271506e70"
APP_SECRET = "17b11c308acf4d1f8b3d4f6c22b514f4"
GATEWAY = "https://api.jd.com/routerjson"
MATERIAL = ("https://coupon.m.jd.com/coupons/show.action"
            "?key=c9m4c3s9o7a641d582632602f104dfa1&roleId=3159198800")


def call_api(method, pj):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    params = {
        "method": method,
        "app_key": APP_KEY,
        "timestamp": ts,
        "format": "json",
        "v": "1.0",
        "sign_method": "md5",
        "360buy_param_json": json.dumps(pj, ensure_ascii=False, separators=(",", ":")),
    }
    sign_src = APP_SECRET + "".join(f"{k}{v}" for k, v in sorted(params.items())) + APP_SECRET
    params["sign"] = hashlib.md5(sign_src.encode("utf-8")).hexdigest().upper()
    data = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items())
    req = urllib.request.Request(GATEWAY, data=data.encode("utf-8"),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def brief(resp):
    key = [k for k in resp if k.endswith("_responce")]
    if not key:
        return json.dumps(resp, ensure_ascii=False)[:160]
    body = resp[key[0]]
    gr = body.get("getResult", "")
    if len(gr) > 300:
        gr = gr[:300] + "..."
    return f"code={body.get('code')} result={gr}"


COMBOS = [
    ("仅 materialUrl", {"materialUrl": MATERIAL}),
    ("materialUrl + siteId", {"materialUrl": MATERIAL, "siteId": 4101168346}),
    ("materialUrl + unionId(空)", {"materialUrl": MATERIAL, "unionId": 0}),
]

if __name__ == "__main__":
    for name, pj in COMBOS:
        try:
            print(f"[{name}] -> {brief(call_api('jd.union.open.promotion.common.get', pj))}")
        except Exception as e:
            print(f"[{name}] ERROR: {e}")
