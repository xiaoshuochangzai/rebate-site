# -*- coding: utf-8 -*-
"""从 unionSearchRecommend 请求里抠出完整 URL + 浏览器 Cookie 头，用 requests GET 复现，
确认能否做成纯后端自动源。"""
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
send("Page.navigate", {"url": URL})

full_url = None
cookie = None
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
    if meth == "Network.requestWillBeSent":
        u = p["request"]["url"]
        if "unionSearchRecommend" in u:
            full_url = u
            cookie = (p["request"].get("headers") or {}).get("Cookie")
    elif meth == "Network.responseReceived":
        u = p["response"]["url"]
        if "unionSearchRecommend" in u and p["response"].get("status") == 200 and not rid:
            rid = p["requestId"]
resp_body = None
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

print("=== 完整 URL (unionSearchRecommend) ===")
print((full_url or "无")[:1500])
print("\n=== Cookie 头长度 ===", len(cookie) if cookie else 0)
print((cookie or "")[:300], "...")

if full_url and cookie:
    s = requests.Session()
    s.trust_env = False
    try:
        r = s.get(full_url, headers={"User-Agent": UA, "Cookie": cookie,
                                     "Referer": "https://jingfen.jd.com/"}, timeout=20)
        print("\n复现 GET status:", r.status_code)
        jj = r.json()
        print("复现 code:", jj.get("code"), "| msg:", jj.get("message"),
              "| 商品数:", len(jj.get("result") or []))
    except Exception as e:
        print("\n复现异常:", repr(e)[:160])

if resp_body:
    j = json.loads(resp_body)
    items = j.get("result") or []
    print("\n=== 响应分析 ===")
    print("商品数:", len(items), "| 分页:", {k: j.get(k) for k in ("pageNo", "pageSize", "hasNext", "totalNum", "lastIndex")})
    if items:
        one = items[0]
        print("首条字段 keys:", list(one.keys()))
        print("skuTagList 样例:", json.dumps(one.get("skuTagList"), ensure_ascii=False)[:300])
        for k in one:
            if "comm" in k.lower() or "rate" in k.lower():
                print("  佣/率字段:", k, "=", str(one[k])[:90])
