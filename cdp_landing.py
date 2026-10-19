# -*- coding: utf-8 -*-
"""抓猫超落地页：标题/文本/全部XHR"""
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
    "var out={title:document.title,url:location.href.slice(0,120),"
    "text:document.body.innerText.slice(0,1500),xhr:[]};"
    "performance.getEntriesByType('resource').forEach(function(e){"
    "var n=e.name; if(n.match(/\\.(css|woff|ico|png|jpg|gif)(\\?|$)/)) return;"
    "out.xhr.push(n.slice(0,170));});"
    "return JSON.stringify(out);})()"
)
ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                    "params": {"expression": js, "returnByValue": True}}))
while True:
    m = json.loads(ws.recv())
    if m.get("id") == 1:
        val = m["result"]["result"]["value"]
        print(json.dumps(json.loads(val), ensure_ascii=False, indent=1)[:4500])
        break
ws.close()
