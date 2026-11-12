# -*- coding: utf-8 -*-
"""重开 20033 tab（避开 /json/new 截断），加载后提取页面 HTML 里的 jingfen 推广链接，
验证路径3（CDP 抓取时直接提取商品京粉链接用于转链）。"""
import json
import time
import urllib.request

import websocket

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
URL = "https://jingfen.jd.com/item?u_act_p=union-activity&union_page_id=20033"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

new = json.loads(OPENER.open("http://127.0.0.1:9222/json/new?about:blank", timeout=10).read())
ws = websocket.create_connection(new["webSocketDebuggerUrl"], timeout=60)
_id = [0]


def send(m, p=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": m, "params": p or {}}))
    return _id[0]


send("Page.enable")
send("Runtime.enable")
send("Emulation.setUserAgentOverride", {"userAgent": UA})
send("Page.navigate", {"url": URL})
time.sleep(8)

expr = (r"(function(){var s=document.documentElement.outerHTML;"
        r"var re=/https?:\/\/[^\"'\s]*jingfen\.jd\.com\/detail\/[^\"'\s]*/g;"
        r"var m=s.match(re)||[];return JSON.stringify({href:location.href,title:document.title,"
        r"links:m.slice(0,30)});})()")
i = send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
deadline = time.time() + 10
while time.time() < deadline:
    try:
        ws.settimeout(max(1, deadline - time.time()))
        m = json.loads(ws.recv())
    except Exception:
        break
    if m.get("id") == i:
        val = m.get("result", {}).get("result", {}).get("value") or "NO"
        try:
            d = json.loads(val)
            print("页面 href:", d.get("href"))
            print("页面 title:", d.get("title"))
            print("jingfen 链接数:", len(d.get("links", [])))
            for u in d.get("links", [])[:10]:
                print("  ", u[:120])
        except Exception:
            print("原始:", val[:500])
        break
ws.close()
