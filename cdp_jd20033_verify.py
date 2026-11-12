# -*- coding: utf-8 -*-
"""抓 20033 unionSearchRecommend 的 POST 业务参数 + 京东联盟 cookie，并尝试用 requests 复现，
确认能否做成纯后端自动源（不依赖浏览器常开）。"""
import base64
import json
import os
import time
import urllib.request

import requests
import websocket

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
URL = "https://jingfen.jd.com/item?u_act_p=union-activity&union_page_id=20033"

tabs = json.loads(OPENER.open("http://127.0.0.1:9222/json", timeout=8).read())
tab = next((x for x in tabs if "union_page_id=20033" in x.get("url", "")), None)
ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=60)
_id = [0]


def send(m, p=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": m, "params": p or {}}))
    return _id[0]


send("Network.enable")
send("Page.enable")
cid = send("Network.getCookies", {"urls": ["https://api.m.jd.com/", "https://jingfen.jd.com/",
                                            "https://union.jd.com/"]})
send("Page.navigate", {"url": URL})

postdata = None
resp_body = None
cookies = None
rid = None
deadline = time.time() + 35
while time.time() < deadline:
    try:
        ws.settimeout(max(1, deadline - time.time()))
        m = json.loads(ws.recv())
    except Exception:
        break
    meth = m.get("method", "")
    p = m.get("params", {})
    if m.get("id") == cid:
        cookies = p.get("cookies") or []
        continue
    if meth == "Network.requestWillBeSent":
        u = p["request"]["url"]
        if "unionSearchRecommend" in u and not postdata:
            postdata = p["request"].get("postData")
    elif meth == "Network.responseReceived":
        u = p["response"]["url"]
        if "unionSearchRecommend" in u and p["response"].get("status") == 200 and not rid:
            rid = p["requestId"]
if rid:
    i = send("Network.getResponseBody", {"requestId": rid})
    ws.settimeout(10)
    try:
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == i:
                b = m.get("result") or {}
                body = b.get("body", "")
                if b.get("base64Encoded"):
                    body = base64.b64decode(body).decode("utf-8", "ignore")
                resp_body = body
                break
            if m.get("id", 0) > i:
                break
    except Exception:
        pass
ws.close()

print("=== POSTDATA (unionSearchRecommend 请求体) ===")
print((postdata or "无")[:2500])
print("\n=== COOKIE ===")
print("count:", len(cookies) if cookies else 0)
if cookies:
    ck = "; ".join("%s=%s" % (c["name"], c["value"]) for c in cookies)
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.post(
            "https://api.m.jd.com/api?functionId=unionSearchRecommend&appid=u_activity_h5&loginType=2&client=&clientVersion=",
            data=postdata,
            headers={"User-Agent": UA, "Cookie": ck, "Content-Type": "application/json",
                     "Referer": "https://jingfen.jd.com/", "Origin": "https://jingfen.jd.com/"},
            timeout=20)
        print("复现 status:", r.status_code)
        jj = r.json()
        print("复现 code:", jj.get("code"), "| msg:", jj.get("message"),
              "| 商品数:", len(jj.get("result") or []))
    except Exception as e:
        print("复现异常:", repr(e)[:120])

if resp_body:
    j = json.loads(resp_body)
    items = j.get("result") or []
    print("\n=== 响应分析 ===")
    print("TOP keys:", list(j.keys()))
    print("商品数:", len(items))
    if items:
        one = items[0]
        print("首条字段 keys:", list(one.keys()))
        tags = {}
        for it in items:
            for t in (it.get("skuTagList") or []):
                tags[t.get("name")] = tags.get(t.get("name"), 0) + 1
        print("标签分布:", tags)
        for k in one:
            if "comm" in k.lower() or "rate" in k.lower():
                print("  佣/率字段:", k, "=", str(one[k])[:90])
        print("分页:", {k: j.get(k) for k in ("pageNo", "pageSize", "hasNext", "totalNum", "lastIndex")})
