# -*- coding: utf-8 -*-
import json, time, urllib.request
import websocket
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
    tabs = json.loads(r.read().decode("utf-8"))
t = [x for x in tabs if x.get("type")=="page" and "source_market" in x.get("url","")][-1]
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=60)
_id = [0]
def send(method, params=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": method, "params": params or {}}))
    return _id[0]

send("Network.enable", {})
# 重挂剪贴板钩子
send("Runtime.evaluate", {"expression": """
(function(){ window.__cap='';
  try { navigator.clipboard.writeText = function(t){ window.__cap=String(t); return Promise.resolve(); }; } catch(e){}
  var o=document.execCommand; document.execCommand=function(c){ if(c==='copy'){var s=window.getSelection?String(window.getSelection()):''; if(s) window.__cap=s;} return o.apply(document,arguments); };
  return 1})()""", "returnByValue": True})
# 开弹窗
send("Runtime.evaluate", {"expression": r"""
(function(){
  var cards=document.querySelectorAll('[class*=card]');
  for (var i=0;i<cards.length;i++){
    if ((cards[i].innerText||'').indexOf('猫超好货')>=0){
      var bs=cards[i].querySelectorAll('button');
      for (var j=0;j<bs.length;j++){ if((bs[j].innerText||'').trim()==='免费推广'){ bs[j].click(); return 'opened'; } }
    }
  } return 'nf';
})()""", "returnByValue": True})
time.sleep(3)
# 点复制链接
send("Runtime.evaluate", {"expression": r"""
(function(){
  var all=document.querySelectorAll('button,a,span,div');
  for (var i=all.length-1;i>=0;i--){ if((all[i].innerText||'').trim()==='复制链接'){ all[i].click(); return 'clicked'; } }
  return 'nf';
})()""", "returnByValue": True})
time.sleep(6)
# 收割：剪贴板 + 弹窗 HTML 里的 http 链接 + 全部 XHR
send("Runtime.evaluate", {"expression": r"""
(function(){
  var out={cap:(window.__cap||'').slice(0,400), urls:[], xhr:[]};
  var dlg=document.querySelector('.el-dialog');
  if (dlg){
    var m=dlg.innerHTML.match(/https?:\/\/[^\"'<>\s]+/g)||[];
    out.urls=m.slice(0,20);
  }
  performance.getEntriesByType('resource').slice(-40).forEach(function(e){
    if (/\.js|\.css|\.png|\.jpg|\.gif|\.woff/.test(e.name)) return;
    out.xhr.push(e.name.slice(0,160));
  });
  return JSON.stringify(out);
})()""", "returnByValue": True})
time.sleep(2)
end = time.time() + 8
result = None
reqs = []
while time.time() < end:
    try:
        ws.settimeout(max(1, end-time.time()))
        m = json.loads(ws.recv())
    except Exception:
        break
    if m.get("id") and m["id"] >= 3 and m.get("result", {}).get("result", {}).get("value"):
        result = m["result"]["result"]["value"]
    elif m.get("method") == "Network.requestWillBeSent":
        u = m["params"]["request"]["url"]
        if "/openapi/" in u or "superpage" in u or "short" in u or "promo" in u or "create" in u:
            reqs.append((u[:150], (m["params"]["request"].get("postData") or "")[:150]))
ws.close()
print("== 剪贴板/弹窗URL/XHR ==")
print(result)
print("== 捕获请求 ==")
for u, pd in reqs[-12:]:
    print(" ", u, "|", pd)
