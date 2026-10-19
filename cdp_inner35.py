# -*- coding: utf-8 -*-
"""开 source_market_inner?id=35，提取标签与数据接口"""
import json
import time
import urllib.request

import websocket

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# 新开 tab
req = urllib.request.Request(
    "http://127.0.0.1:9222/json/new?https://www.haodanku.com/openapi/source_market_inner?id=35",
    method="PUT")
with OPENER.open(req, timeout=8) as r:
    t = json.loads(r.read().decode("utf-8"))
print("tab:", t["id"])
time.sleep(6)

with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
    tabs = json.loads(r.read().decode("utf-8"))
t = next(x for x in tabs if x.get("type") == "page" and "source_market_inner" in x.get("url", ""))
print("url:", t["url"][:110])
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=40)
js = (
    "(function(){"
    "var out={title:document.title,url:location.href.slice(0,140),text:document.body.innerText.slice(0,2200),xhr:[]};"
    "performance.getEntriesByType('resource').forEach(function(e){"
    "var n=e.name; if(n.match(/\\.(css|woff|ico|png|jpg|gif|js)(\\?|$)/)) return;"
    "out.xhr.push(n.slice(0,180));});"
    "return JSON.stringify(out);})()"
)
ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                    "params": {"expression": js, "returnByValue": True}}))
while True:
    m = json.loads(ws.recv())
    if m.get("id") == 1:
        val = m["result"]["result"]["value"]
        print(json.dumps(json.loads(val), ensure_ascii=False, indent=1)[:6000])
        break
ws.close()
