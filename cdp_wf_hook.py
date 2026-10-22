# -*- coding: utf-8 -*-
"""hook window.open + 看按钮 DOM 属性，弄清「立即购买」跳哪。"""
import json, io, sys, time
import urllib.request
import websocket

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

tabs = json.loads(opener.open("http://127.0.0.1:9222/json", timeout=6).read())
target = None
for t in tabs:
    if t.get("type") == "page" and "kzurl01" in (t.get("url") or ""):
        target = t
        break
print("tab:", target["url"][:120])
ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=25, http_proxy_host=None)

_id = [0]
def ev(expr, wait_id=None):
    _id[0] += 1
    wid = _id[0]
    ws.send(json.dumps({"id": wid, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True,
                                   "awaitPromise": bool(wait_id)}}))
    end = time.time() + (20 if wait_id else 8)
    ws.settimeout(3)
    while time.time() < end:
        try:
            m = json.loads(ws.recv())
        except websocket.WebSocketTimeoutException:
            continue
        if m.get("id") == wid:
            r = m.get("result", {})
            return r.get("result", {}).get("value") if "result" in r else r
    return None

# 1) 按钮 DOM 外层结构 + data 属性
v = ev(r"""
(function(){
  const b=document.querySelector('.btn-order')||document.querySelector('.btn-block');
  if(!b) return 'no btn';
  let el=b, out=[];
  for(let i=0;i<5 && el;i++){ out.push(el.tagName+'.'+(el.className||'').toString().slice(0,60)+' attrs='+JSON.stringify(el.getAttributeNames?el.getAttributeNames():[])); el=el.parentElement; }
  return out.join(' || ');
})()
""")
print("按钮结构:", v)

# 2) hook window.open + 点击
ev(r"""
window.__opens=[];
const orig=window.open;
window.open=function(u,...a){ window.__opens.push(String(u)); try{return orig.call(window,u,...a);}catch(e){} };
const btns=document.querySelectorAll('.btn-order,.btn-block');
let c=0;
for(const b of btns){ if((b.textContent||'').includes('立即购买')){ b.click(); c++; break; } }
'clicked '+c
""")

# 3) 读结果（含 scheme 跳转尝试）
time.sleep(3)
v = ev(r"""
JSON.stringify({
  opens: (window.__opens||[]).slice(0,5),
  loc: location.href.slice(0,200)
})
""")
print("结果:", v)

# 4) 看有没有新 tab 开出
tabs2 = json.loads(opener.open("http://127.0.0.1:9222/json", timeout=6).read())
for t in tabs2:
    if t.get("type") == "page" and any(k in t.get("url", "") for k in ("taobao", "tmall", "tbopen")):
        print("新tab:", t["url"][:200])
