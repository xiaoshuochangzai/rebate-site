# -*- coding: utf-8 -*-
"""连 9222 Chrome 的 kzurl01 activity_fresh 标签页，dump 渲染后的商品跳转链接。"""
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
if not target:
    print("没有 kzurl01 标签页")
    sys.exit(1)
print("tab:", target["url"][:120])
ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=25, http_proxy_host=None)

JS = r"""
(function(){
  const out = {links: [], btns: []};
  document.querySelectorAll('a[href]').forEach(a=>{
    const h = a.getAttribute('href') || '';
    if (/taobao|tbopen|s\.click|hd00|uland/i.test(h)) {
      out.links.push(h.slice(0,250));
    }
  });
  // 按钮不一定是 <a>，把带「抢购/购买/下单」文案的可点元素也列出来
  document.querySelectorAll('div,button,span,p').forEach(el=>{
    const t=(el.textContent||'').trim();
    if(t.length<=6 && /抢购|购买|下单|去逛/.test(t)){
      let a=el.closest('a');
      out.btns.push({t:t, href: a?a.getAttribute('href'):'(非a标签)', tag: el.tagName, cls: (el.className||'').toString().slice(0,40)});
    }
  });
  out.btns = out.btns.slice(0,12);
  return JSON.stringify(out);
})()
"""

def ev(expr):
    msg = json.dumps({"id": 7, "method": "Runtime.evaluate",
                      "params": {"expression": expr, "returnByValue": True}})
    ws.send(msg)
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == 7:
            return m

r = ev(JS)
val = r.get("result", {}).get("result", {}).get("value")
if not val:
    print("eval 失败:", json.dumps(r, ensure_ascii=False)[:400])
    sys.exit(1)
d = json.loads(val)
print("== taobao/hd00 直链 %d 条 ==" % len(d["links"]))
seen = set()
for h in d["links"]:
    key = h[:60]
    if key in seen:
        continue
    seen.add(key)
    print("  ", h)
print("== 按钮 ==")
for b in d["btns"]:
    print("  ", b)
