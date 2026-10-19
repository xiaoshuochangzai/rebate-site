# -*- coding: utf-8 -*-
"""劫持剪贴板，点复制链接抓推广页 URL（两个单页）"""
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

# 劫持剪贴板与 execCommand
ev("""
(function(){
  window.__cap='';
  try { navigator.clipboard.writeText = function(t){ window.__cap = String(t); return Promise.resolve(); }; } catch(e){}
  var orig = document.execCommand;
  document.execCommand = function(cmd, ui, val){ if(cmd==='copy'){ var s=window.getSelection?String(window.getSelection()):''; if(s) window.__cap=s; } return orig.apply(document, arguments); };
  return 'hooked';
})()
""")

def get_link(kw):
    ev("(function(){window.__cap='';return 1})()")
    r = ev(r"""
(function(){
  var cards = document.querySelectorAll('[class*=card]');
  for (var i=0;i<cards.length;i++){
    var c=cards[i];
    if ((c.innerText||'').indexOf('%s')>=0){
      var bs=c.querySelectorAll('button');
      for (var j=0;j<bs.length;j++){
        if ((bs[j].innerText||'').trim()==='复制链接'){ bs[j].click(); return 'clicked'; }
      }
    }
  }
  return 'not found';
})()""" % kw)
    time.sleep(4)
    cap = ev("window.__cap")
    return r, cap

print("== 猫超好货 ==")
print(get_link("猫超好货"))
print("== 天猫超市 ==")
print(get_link("天猫超市"))
ws.close()
