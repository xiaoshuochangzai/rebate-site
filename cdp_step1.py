# -*- coding: utf-8 -*-
"""验证好单库登录态并刷新单页专区"""
import json, time, urllib.request
import websocket
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def tabs():
    with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))
def ev(ws, js, ap=False):
    ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":js,"returnByValue":True,"awaitPromise":ap}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id")==1: return m["result"]["result"].get("value")

ts = tabs()
login_tab = [t for t in ts if t.get("type")=="page" and "publish.haodanku.com/Login" in t.get("url","")]
sm_tab = [t for t in ts if t.get("type")=="page" and "source_market" in t.get("url","")]
print("登录页tab:", len(login_tab), "| 单页专区tab:", len(sm_tab))
t = (login_tab or sm_tab)[0]
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=30)
# 跳到单页专区（若还在登录页，returnurl 会自动带；直接导航最稳）
ev(ws, "location.href='https://www.haodanku.com/Openindex/source_market'")
time.sleep(4)
ws.close()
ts = tabs()
t = next(t for t in ts if t.get("type")=="page" and "source_market" in t.get("url",""))
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=30)
r = ev(ws, r"""
(function(){
  var b = document.body.innerText||'';
  return JSON.stringify({
    logged_in: b.indexOf('密码登录')<0 && b.indexOf('免费注册')<0,
    has_28: b.indexOf('共28个单页')>=0 || b.indexOf('个单页')>=0,
    head: b.slice(0,200)
  });
})()
""")
print(r)
ws.close()
