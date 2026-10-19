# -*- coding: utf-8 -*-
import json, time, urllib.request
import websocket
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def target():
    with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
        tabs = json.loads(r.read().decode("utf-8"))
    return next(t for t in tabs if t.get("type")=="page" and "source_market" in t.get("url",""))
def ev(ws, js):
    ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":js,"returnByValue":True,"awaitPromise":True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id")==1: return m["result"]["result"].get("value")

t = target()
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=30)
# 找猫超好货卡片里的按钮
r1 = ev(ws, r"""
(function(){
  var cards = document.querySelectorAll('.c-card, [class*=card]');
  var out = [];
  cards.forEach(function(c){
    var t=(c.innerText||'');
    if (t.indexOf('猫超好货')>=0 || t.indexOf('天猫超市')>=0) {
      var btns=[];
      c.querySelectorAll('a,button,span,div').forEach(function(b){
        var bt=(b.innerText||'').trim();
        if (bt && bt.length<12 && /下载|推广|预览|使用|克隆|查看/i.test(bt)) btns.push({t:bt, tag:b.tagName, cls:(b.className||'').toString().slice(0,40), onclick:(b.getAttribute('onclick')||'').slice(0,60)});
      });
      out.push({title: t.split('\n')[0], btns: btns});
    }
  });
  return JSON.stringify(out);
})()
""")
print("卡片按钮：", r1)
ws.close()
