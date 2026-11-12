# -*- coding: utf-8 -*-
"""在 20033 已开 tab 里，从页面 HTML 提取所有 jingfen.jd.com/detail 京粉推广链接，
看商品卡片是否自带京粉链接（可用于折京客转链）。"""
import json
import time
import urllib.request

import websocket

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
tabs = json.loads(OPENER.open("http://127.0.0.1:9222/json", timeout=8).read())
tab = next((x for x in tabs if "union_page_id=20033" in x.get("url", "")), None)
ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=60)
_id = [0]


def send(m, p=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": m, "params": p or {}}))
    return _id[0]


send("Runtime.enable")
expr = (r"(function(){var s=document.documentElement.outerHTML;"
        r"var re=/https?:\/\/[^\"'\s]*jingfen\.jd\.com\/detail\/[^\"'\s]*/g;"
        r"var m=s.match(re)||[];return JSON.stringify(m.slice(0,30));})()")
i = send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
deadline = time.time() + 10
while time.time() < deadline:
    try:
        ws.settimeout(max(1, deadline - time.time()))
        m = json.loads(ws.recv())
    except Exception:
        break
    if m.get("id") == i:
        val = (m.get("result", {}).get("result", {}).get("value") or "NO")[:2000]
        print("页面HTML中的 jingfen 链接:")
        print(val)
        break
ws.close()
