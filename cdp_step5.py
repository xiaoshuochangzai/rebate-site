# -*- coding: utf-8 -*-
"""Network 抓包版：开弹窗→点复制链接→捕获创建接口与返回"""
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
def wait_reply(want):
    hits = []
    end = time.time() + 25
    while time.time() < end:
        try:
            ws.settimeout(max(1, end - time.time()))
            m = json.loads(ws.recv())
        except Exception:
            break
        if m.get("id") == want:
            hits.append(("reply", m.get("result", {}).get("result", {}).get("value")))
            if len(hits) >= 1 and want != -1:
                pass
        elif m.get("method") == "Network.requestWillBeSent":
            u = m["params"]["request"]["url"]
            if any(k in u for k in ("sourcecode", "promo", "superpage", "short", "create")):
                pd = m["params"]["request"].get("postData", "")
                hits.append(("req", u, pd[:200]))
        elif m.get("method") == "Network.responseReceived":
            u = m["params"]["response"]["url"]
            if any(k in u for k in ("sourcecode", "promo", "superpage", "short", "create")):
                hits.append(("resp", u, m["params"]["response"]["status"]))
    return hits

send("Network.enable", {})
time.sleep(0.5)
# 开弹窗（猫超好货）
w = send("Runtime.evaluate", {"expression": r"""
(function(){
  var cards = document.querySelectorAll('[class*=card]');
  for (var i=0;i<cards.length;i++){
    if ((cards[i].innerText||'').indexOf('猫超好货')>=0){
      var bs=cards[i].querySelectorAll('button');
      for (var j=0;j<bs.length;j++){ if((bs[j].innerText||'').trim()==='免费推广'){ bs[j].click(); return 'opened'; } }
    }
  }
  return 'nf';
})()""", "returnByValue": True})
time.sleep(3)
# 点复制链接（visibility 判断放宽）
w2 = send("Runtime.evaluate", {"expression": r"""
(function(){
  var all = document.querySelectorAll('button, a, span, div');
  for (var i=all.length-1;i>=0;i--){
    var e=all[i];
    if ((e.innerText||'').trim()==='复制链接'){ e.click(); return 'copy clicked'; }
  }
  return 'nf';
})()""", "returnByValue": True})
time.sleep(6)
hits = wait_reply(-1)
ws.close()
for h in hits:
    print(json.dumps(h, ensure_ascii=False)[:300])
