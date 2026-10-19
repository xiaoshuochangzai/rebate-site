# -*- coding: utf-8 -*-
"""定位 source_market 页面上 猫超好货/天猫超市 的上下文与入口"""
import json, urllib.request
import websocket
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
    tabs = json.loads(r.read().decode("utf-8"))
t = next(t for t in tabs if t.get("type")=="page" and "source_market" in t.get("url",""))
JS = r"""
(function(){
  var out = {ctx: [], els: [], xhr: []};
  var body = document.body.innerText || '';
  ['猫超好货','天猫超市'].forEach(function(kw){
    var i = body.indexOf(kw);
    while (i >= 0 && out.ctx.length < 4) {
      out.ctx.push('[' + kw + '] ...' + body.slice(Math.max(0,i-120), i+180).replace(/\n+/g,' | ') + '...');
      i = body.indexOf(kw, i+1);
    }
  });
  // 找包含关键词的元素及其可点击性/属性
  var all = document.querySelectorAll('a,div,span,li,button,img');
  for (var k = 0; k < all.length && out.els.length < 10; k++) {
    var e = all[k];
    var txt = (e.innerText || e.title || e.alt || '').trim();
    if (txt.indexOf('猫超') >= 0 || txt.indexOf('天猫超市') >= 0) {
      var a = e.closest('a');
      out.els.push({
        tag: e.tagName, cls: (e.className||'').toString().slice(0,50),
        txt: txt.slice(0,40),
        href: (a && a.href) || e.getAttribute('href') || (e.getAttribute('onclick')||'').slice(0,80) || ''
      });
    }
  }
  performance.getEntriesByType('resource').forEach(function(e){
    var n = e.name;
    if (/api|json|ajax|source|market|single/i.test(n) && !/\.(png|jpg|gif|css|js|ico|woff)/.test(n)) out.xhr.push(n.slice(0,150));
  });
  return JSON.stringify(out);
})()
"""
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=25)
ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":JS,"returnByValue":True}}))
while True:
    msg = json.loads(ws.recv())
    if msg.get("id")==1:
        val = msg["result"]["result"].get("value")
        break
ws.close()
d = json.loads(val)
print("== 关键词上下文 ==")
for c in d["ctx"]: print(" ", c[:300]); print()
print("== 命中元素 ==")
for e in d["els"]: print(" ", json.dumps(e, ensure_ascii=False)[:200])
print("== XHR/资源 ==")
for x in d["xhr"][:20]: print(" ", x)
