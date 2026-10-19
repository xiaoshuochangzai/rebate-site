# -*- coding: utf-8 -*-
"""在猫超落地页内部 fetch 商品接口（页面同源上下文）+ 裸调对照"""
import json
import urllib.request

import websocket

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
    tabs = json.loads(r.read().decode("utf-8"))
t = next(x for x in tabs if x.get("type") == "page" and "kzurl01" in x.get("url", ""))
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=40)
js = (
    "(function(){"
    "return fetch('https://api.haodanku.com/api/maochao_items?type=1&p=1&order=3&cat_id=0&code=nO1uOS')"
    ".then(function(r){return r.text()})"
    ".then(function(t){return t.slice(0,1600);});})"
    "()"
)
ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                    "params": {"expression": js, "returnByValue": True, "awaitPromise": True}}))
while True:
    m = json.loads(ws.recv())
    if m.get("id") == 1:
        print(m["result"]["result"].get("value", "")[:1600])
        break
ws.close()
