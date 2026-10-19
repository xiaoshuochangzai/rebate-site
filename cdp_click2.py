# -*- coding: utf-8 -*-
import json, time, urllib.request
import websocket
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def target():
    with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
        tabs = json.loads(r.read().decode("utf-8"))
    return next(t for t in tabs if t.get("type")=="page" and "source_market" in t.get("url",""))
def ev(ws, js, wait_promise=False):
    ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":js,"returnByValue":True,"awaitPromise":wait_promise}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id")==1: return m["result"]["result"].get("value")

t = target()
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=30)
r = ev(ws, r"""
(function(){
  var cards = document.querySelectorAll('[class*=card]');
  for (var i=0;i<cards.length;i++){
    var c=cards[i];
    if ((c.innerText||'').indexOf('猫超好货')>=0){
      var bs=c.querySelectorAll('button');
      for (var j=0;j<bs.length;j++){
        if ((bs[j].innerText||'').trim()==='免费推广'){ bs[j].click(); return 'clicked'; }
      }
    }
  }
  return 'not found';
})()
""")
print("click:", r)
time.sleep(3)
r2 = ev(ws, r"""
(function(){
  var out = {url: location.href, modal: '', body_head: ''};
  var dlg = document.querySelector('.el-dialog, .el-message-box, [class*=dialog], [class*=modal]');
  if (dlg) out.modal = dlg.innerText.slice(0,500);
  out.body_head = document.body.innerText.slice(0,400);
  return JSON.stringify(out);
})()
""")
print(json.dumps(json.loads(r2), ensure_ascii=False, indent=1)[:1200])
ws.close()
