# -*- coding: utf-8 -*-
"""抓京东联盟 20033（超级补贴/热卖清单榜）页面商品列表底层接口 + 响应体。
连已开的 20033 tab，Page.navigate 整页重载（不走 /json/new 以免截断 &union_page_id），
拦截 jd 联盟域的非 js 响应，存盘待分析。"""
import json
import os
import time
import urllib.request

import websocket

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
URL = "https://jingfen.jd.com/item?u_act_p=union-activity&union_page_id=20033"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jd20033_bodies")
os.makedirs(OUT, exist_ok=True)

tabs = json.loads(OPENER.open("http://127.0.0.1:9222/json", timeout=8).read())
tab = next((x for x in tabs if "union_page_id=20033" in x.get("url", "")), None)
if not tab:
    new = json.loads(OPENER.open("http://127.0.0.1:9222/json/new?" + URL, timeout=10).read())
    tab = new
    print("新开 tab:", new["id"])
else:
    print("复用已开 tab:", tab["id"], tab["url"])

ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=60)
_id = [0]


def send(m, p=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": m, "params": p or {}}))
    return _id[0]


send("Network.enable")
send("Page.enable")
send("Emulation.setUserAgentOverride", {"userAgent": UA})
send("Page.navigate", {"url": URL})

reqs, done = {}, {}
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
        reqs[p["requestId"]] = p["request"]["url"]
    elif meth == "Network.responseReceived":
        r = p["response"]
        if r.get("status") == 200 and p["requestId"] in reqs:
            u = r["url"]
            if ("jingfen" in u or "union" in u or "api.m.jd" in u) and ".js" not in u:
                done[p["requestId"]] = u

idx = 0
for rid, u in done.items():
    idx += 1
    i = send("Network.getResponseBody", {"requestId": rid})
    ws.settimeout(10)
    try:
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == i:
                b = m.get("result") or {}
                body = b.get("body", "")
                if b.get("base64Encoded"):
                    import base64
                    body = base64.b64decode(body).decode("utf-8", "ignore")
                fn = os.path.join(OUT, "resp%02d.json" % idx)
                with open(fn, "w", encoding="utf-8") as f:
                    f.write("URL: " + u + "\n\n" + body[:400000])
                print("  [%6d B] %s -> %s" % (len(body), u[:110], os.path.basename(fn)))
                break
            if m.get("id", 0) > i:
                break
    except Exception:
        pass
print("\n=== 抓到 %d 个候选响应 ===" % idx)
ws.close()
