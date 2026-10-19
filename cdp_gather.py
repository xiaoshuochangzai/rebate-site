# -*- coding: utf-8 -*-
"""探 gather_new 聚合页：标签列表 + 数据接口"""
import json
import time
import urllib.request

import websocket

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
    tabs = json.loads(r.read().decode("utf-8"))
t = next(x for x in tabs if x.get("type") == "page" and "gather_new" in x.get("url", ""))
print("url:", t["url"][:140])
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=40)
js = (
    "(function(){"
    "var out={title:document.title,url:location.href.slice(0,160),"
    "text:document.body.innerText.slice(0,1800),tabs:[],xhr:[]};"
    "document.querySelectorAll('[class*=tab],[class*=cate],[class*=nav] li,li').forEach(function(e){"
    "var tx=(e.innerText||'').trim();"
    "if(tx && tx.length<=8 && out.tabs.indexOf(tx)<0) out.tabs.push(tx);});"
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
