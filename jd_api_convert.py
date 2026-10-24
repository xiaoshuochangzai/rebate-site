#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jd_api_convert.py — 京东线报转链（好单库开放平台 API 版，2026-10-23）

替代精品库 API/浏览器转链（~9s/条串行，是新线报落后好单库几分钟的大头）。
两个接口（Boss 2026-10-23 在好单库后台配好 apikey 白名单，已实测 code:200）：
  1. v3 unify_jditems_link  官方文档收录：material_id(商品链接或ID) + coupon_url
                          → clickURL(推广链接) / shortURL(短链接)
  2. v2 wire_report_ratesurl  好单库实时线报页同款：type=2(京东) + content(商品链接)
                          + coupon(券链接) → data.data(下单链接)

授权状态（2026-10-23 12:45 实测）：
  - apikey 白名单：已生效（Boss 配好）
  - 淘宝授权：正常（createConference_code 通）
  - 京东官方授权：未开通 → unify 报「未开通京东官方账号」、
    ratesurl type=2 返回空 data。需 Boss 到
    https://publish.haodanku.com/Promotioncenter/auth?platform=2 开通后才能用。

纪律：没转上链的绝不上站（失败返回 ok=False，由调用方决定是否入 pending）。
"""
import json
import os
import time
import urllib.request
import urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))

API_UNIFY = "https://v3.api.haodanku.com/unify_jditems_link"
API_RATESURL = "https://v2.api.haodanku.com/wire_report_ratesurl"
APIKEY = "9AC3C71D776A"

TIMEOUT = 15
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _post(url, params):
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"User-Agent": _UA,
                                          "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def convert_unify(item_url, coupon_url=None):
    """官方京东转链。返回 (ok, link, msg)。link 取 shortURL，无则 clickURL。"""
    p = {"apikey": APIKEY, "material_id": item_url}
    if coupon_url:
        p["coupon_url"] = coupon_url
    try:
        r = _post(API_UNIFY, p)
    except Exception as e:
        return False, "", "unify 请求异常: %s" % str(e)[:80]
    if r.get("code") != 200:
        return False, "", "unify code=%s %s" % (r.get("code"), str(r.get("msg"))[:80])
    d = r.get("data") or {}
    link = d.get("shortURL") or d.get("shortUrl") or d.get("clickURL") or d.get("clickUrl") or ""
    if not link:
        return False, "", "unify 200 但无链接: %s" % json.dumps(d, ensure_ascii=False)[:120]
    return True, link, "ok"


def convert_ratesurl(item_url, coupon_url=None):
    """线报页同款转链（type=2 京东）。返回 (ok, link, msg)。"""
    p = {"apikey": APIKEY, "type": "2", "content": item_url,
         "request_head": "https://www.haodanku.com"}
    if coupon_url:
        p["coupon"] = coupon_url
    try:
        r = _post(API_RATESURL, p)
    except Exception as e:
        return False, "", "ratesurl 请求异常: %s" % str(e)[:80]
    if r.get("code") != 200:
        return False, "", "ratesurl code=%s %s" % (r.get("code"), str(r.get("msg"))[:80])
    d = r.get("data") or {}
    link = d.get("data") or d.get("url") or ""
    if not link:
        return False, "", "ratesurl 200 但空（京东授权未开通?）"
    return True, link, "ok"


def convert_one(item_url, coupon_url=None):
    """单条转链：优先官方 unify，失败/未授权降级 ratesurl。
    返回 (ok, link, via, msg)。via = 'unify' | 'ratesurl' | ''。"""
    ok, link, msg = convert_unify(item_url, coupon_url)
    if ok:
        return True, link, "unify", msg
    ok2, link2, msg2 = convert_ratesurl(item_url, coupon_url)
    if ok2:
        return True, link2, "ratesurl", msg2
    return False, "", "", "unify: %s | ratesurl: %s" % (msg, msg2)


if __name__ == "__main__":
    import sys
    item = sys.argv[1] if len(sys.argv) > 1 else "https://u.jd.com/5GYDsMP"
    coupon = sys.argv[2] if len(sys.argv) > 2 else None
    print(convert_one(item, coupon))
