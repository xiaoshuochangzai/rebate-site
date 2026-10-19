# -*- coding: utf-8 -*-
"""看落地页 立即下单 按钮的实际跳转链接（是否已绑 pid）"""
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
    "var out=[];"
    "document.querySelectorAll('a,button,div,span').forEach(function(e){"
    "var tx=(e.innerText||'').trim();"
    "if(tx.indexOf('立即下单')>=0||tx.indexOf('马上抢')>=0||tx.indexOf('去购买')>=0){"
    "var a=e.tagName==='A'?e:(e.querySelector('a')||e.closest('a'));"
    "out.push({txt:tx.slice(0,12),href:a?a.href.slice(0,150):(e.getAttribute('data-href')||e.getAttribute('href')||'').slice(0,150)});}});"
    "return JSON.stringify(out.slice(0,8));})()"
)
ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                    "params": {"expression": js, "returnByValue": True}}))
while True:
    m = json.loads(ws.recv())
    if m.get("id") == 1:
        print(m["result"]["result"]["value"])
        break
ws.close()
