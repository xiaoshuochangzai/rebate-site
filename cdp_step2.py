# -*- coding: utf-8 -*-
"""检查登录态"""
import json, time, urllib.request
import websocket
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
    tabs = json.loads(r.read().decode("utf-8"))
t = [x for x in tabs if x.get("type")=="page" and "source_market" in x.get("url","")][-1]
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=30)
ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":r"""
(function(){
  var b = document.body.innerText||'';
  return JSON.stringify({
    logged_in: b.indexOf('密码登录')<0 && b.indexOf('免费注册')<0,
    pages: (b.match(/共\s*\d+个单页/)||[''])[0],
    head: b.slice(0,150).replace(/\n+/g,' | ')
  });
})()""","returnByValue":True}}))
while True:
    m = json.loads(ws.recv())
    if m.get("id")==1:
        print(m["result"]["result"].get("value")); break
ws.close()
