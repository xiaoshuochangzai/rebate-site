# -*- coding: utf-8 -*-
"""CDP 实测好单库单页专区（source_market）：提取猫超好货/天猫超市入口与数据接口。"""
import json
import sys
import urllib.request

import websocket  # noqa: 监控 venv 运行

PROXY_NULL = urllib.request.ProxyHandler({})
OPENER = urllib.request.build_opener(PROXY_NULL)


def find_target():
    with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
        tabs = json.loads(r.read().decode("utf-8"))
    for t in tabs:
        if t.get("type") == "page" and "source_market" in t.get("url", ""):
            return t
    return None


def evaluate(ws_url, expr):
    ws = websocket.create_connection(ws_url, timeout=25)
    try:
        ws.send(json.dumps({
            "id": 1, "method": "Runtime.evaluate",
            "params": {"expression": expr, "returnByValue": True, "awaitPromise": False},
        }))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                res = msg.get("result", {}).get("result", {})
                return res.get("value")
    finally:
        ws.close()


JS = r"""
(function(){
  var out = {title: document.title, url: location.href, text_hits: [], links: [], xhr: []};
  // 1) 页面可见文本里找猫超/天猫超市
  var body = document.body.innerText || '';
  ['猫超好货','天猫超市','精品单页','万能单页'].forEach(function(kw){
    if (body.indexOf(kw) >= 0) out.text_hits.push(kw);
  });
  // 2) 所有链接（标题+href）
  document.querySelectorAll('a').forEach(function(a){
    var t = (a.innerText||'').trim();
    var h = a.href||'';
    if (t && h && h.indexOf('javascript') < 0) out.links.push(t.slice(0,40) + ' => ' + h.slice(0,110));
  });
  // 3) 页面已发的 XHR/fetch 资源
  performance.getEntriesByType('resource').forEach(function(e){
    var n = e.name;
    if (/api|json|ajax|source|market|page/i.test(n) && !/\.(png|jpg|gif|css|js|ico|woff)/.test(n)) {
      out.xhr.push(n.slice(0,140));
    }
  });
  // 4) Vue 数据源探测
  try {
    var app = document.querySelector('#app') || document.body;
    var v = app.__vue__ || (app.__vue_app__ && app.__vue_app__._instance && app.__vue_app__._instance.proxy);
    if (v && v.$data) out.vue_keys = Object.keys(v.$data).slice(0,20);
    if (v && v.$store && v.$store.state) out.store_keys = Object.keys(v.$store.state).slice(0,20);
  } catch(e) { out.vue_err = String(e).slice(0,60); }
  out.body_slice = body.slice(0, 1500);
  return JSON.stringify(out).slice(0, 6000);
})()
"""

if __name__ == "__main__":
    t = find_target()
    if not t:
        print("未找到 source_market 标签页")
        sys.exit(1)
    print("target:", t["url"])
    val = evaluate(t["webSocketDebuggerUrl"], JS)
    try:
        d = json.loads(val)
    except Exception:
        print("原始返回:", str(val)[:2000])
        sys.exit(0)
    print("标题:", d.get("title"))
    print("命中关键词:", d.get("text_hits"))
    print("vue_keys:", d.get("vue_keys"), "| store_keys:", d.get("store_keys"))
    print("--- 链接 ---")
    for l in d.get("links", [])[:25]:
        print(" ", l)
    print("--- XHR ---")
    for x in d.get("xhr", [])[:25]:
        print(" ", x)
    print("--- 正文切片 ---")
    print(d.get("body_slice", "")[:900])
