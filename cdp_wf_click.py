# -*- coding: utf-8 -*-
"""点击 activity_fresh 页的「立即购买」，抓跳转请求（Network 抓包）。"""
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
def cmd(method, params=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": method, "params": params or {}}))
    return _id[0]

cmd("Network.enable")
cmd("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})

# 点击第一个「立即购买」
JS = r"""
(function(){
  const btns = document.querySelectorAll('.btn-block, .btn-order');
  for (const b of btns) {
    if ((b.textContent||'').includes('立即购买')) { b.click(); return 'clicked: '+b.className; }
  }
  return 'no btn';
})()
"""
cmd("Runtime.evaluate", {"expression": JS, "returnByValue": True})

ws.settimeout(3)
hits = []
t0 = time.time()
while time.time() - t0 < 12:
    try:
        m = json.loads(ws.recv())
    except websocket.WebSocketTimeoutException:
        continue
    except Exception:
        break
    if m.get("method") == "Network.requestWillBeSent":
        u = m["params"]["request"]["url"]
        if any(k in u for k in ("taobao", "tbopen", "s.click", "hd00", "uland", "tmall")):
            hits.append(u[:220])
    if m.get("method") == "Page.frameStartedLoading":
        pass

# 跳转后 tab 的最终 URL
try:
    tabs2 = json.loads(opener.open("http://127.0.0.1:9222/json", timeout=6).read())
    for t in tabs2:
        if t.get("id") == target.get("id"):
            print("点击后 tab URL:", t["url"][:220])
except Exception:
    pass
print("== 抓到的 taobao 系请求 ==")
seen = set()
for u in hits:
    k = u[:80]
    if k in seen:
        continue
    seen.add(k)
    print("  ", u)
