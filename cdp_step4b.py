# -*- coding: utf-8 -*-
"""开弹窗→劫持剪贴板→点复制链接"""
import json, time, urllib.request
import websocket
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
    tabs = json.loads(r.read().decode("utf-8"))
t = [x for x in tabs if x.get("type")=="page" and "source_market" in x.get("url","")][-1]
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=40)

def ev(js):
    ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":js,"returnByValue":True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id")==1: return m["result"]["result"].get("value")

ev("""
(function(){
  window.__cap='';
  try { navigator.clipboard.writeText = function(t){ window.__cap = String(t); return Promise.resolve(); }; } catch(e){}
  var orig = document.execCommand;
  document.execCommand = function(cmd){ if(cmd==='copy'){ var s=window.getSelection?String(window.getSelection()):''; if(s) window.__cap=s; } return orig.apply(document, arguments); };
  return 'hooked';
})()
""")

def flow(kw):
    ev("(function(){window.__cap='';return 1})()")
    open_r = ev(r"""
(function(){
  var cards = document.querySelectorAll('[class*=card]');
  for (var i=0;i<cards.length;i++){
    var c=cards[i];
    if ((c.innerText||'').indexOf('%s')>=0){
      var bs=c.querySelectorAll('button');
      for (var j=0;j<bs.length;j++){
        if ((bs[j].innerText||'').trim()==='免费推广'){ bs[j].click(); return 'opened'; }
      }
    }
  }
  return 'card not found';
})()""" % kw)
    time.sleep(3)
    copy_r = ev(r"""
(function(){
  var all = document.querySelectorAll('button, a, span, div');
  for (var i=all.length-1;i>=0;i--){
    var e=all[i];
    if ((e.innerText||'').trim()==='复制链接' && e.offsetParent!==null){ e.click(); return 'copy clicked'; }
  }
  return 'copy btn not found';
})()""")
    time.sleep(4)
    cap = ev("window.__cap")
    return open_r, copy_r, (cap or '')[:300]

print("== 猫超好货 ==")
print(flow("猫超好货"))
time.sleep(1)
print("== 天猫超市 ==")
print(flow("天猫超市"))
ws.close()
