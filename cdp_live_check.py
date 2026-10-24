# -*- coding: utf-8 -*-
"""用 9222 Chrome 打开 shengqian.cyou，抓页面运行时 JS 异常。"""
import json, io, sys, time
import urllib.request
import websocket

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

tabs = json.loads(opener.open("http://127.0.0.1:9222/json", timeout=6).read())
target = None
for t in tabs:
    if t.get("type") == "page" and "shengqian.cyou" in (t.get("url") or ""):
        target = t
        break
if not target:
    r = opener.open("http://127.0.0.1:9222/json/new?https://shengqian.cyou/", timeout=8)
    target = json.loads(r.read())
    time.sleep(5)
print("tab:", target["url"][:80])
ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=25, http_proxy_host=None)

_id = [0]
def cmd(method, params=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": method, "params": params or {}}))
    return _id[0]

cmd("Runtime.enable")
cmd("Page.enable")
cmd("Page.reload")

errs = []
ws.settimeout(2)
t0 = time.time()
while time.time() - t0 < 10:
    try:
        m = json.loads(ws.recv())
    except websocket.WebSocketTimeoutException:
        continue
    except Exception:
        break
    if m.get("method") == "Runtime.exceptionThrown":
        d = m["params"]["exceptionDetails"]
        txt = d.get("exception", {}).get("description") or d.get("text") or ""
        errs.append(txt[:300])
    if m.get("method") == "Runtime.consoleAPICalled":
        if m["params"].get("type") == "error":
            args = m["params"].get("args", [])
            errs.append("console.error: " + " ".join(str(a.get("value", a.get("description", "")))[:200] for a in args))

# 页面最终状态
_id[0] += 1
wid = _id[0]
ws.send(json.dumps({"id": wid, "method": "Runtime.evaluate", "params": {
    "expression": "JSON.stringify({cards: document.querySelectorAll('.report-item,.wf-row').length,"
                  " wfrows: document.querySelectorAll('.wf-row').length,"
                  " filter: (typeof filter!=='undefined')?filter:'?',"
                  " err: document.getElementById('list') ? document.getElementById('list').innerHTML.slice(0,120) : 'no #list'})",
    "returnByValue": True}}))
state = None
end = time.time() + 6
ws.settimeout(2)
while time.time() < end:
    try:
        m = json.loads(ws.recv())
    except websocket.WebSocketTimeoutException:
        continue
    if m.get("id") == wid:
        state = m.get("result", {}).get("result", {}).get("value")
        break

print("== 运行时异常 %d 条 ==" % len(errs))
for e in errs[:6]:
    print("  ", e.replace("\n", " | ")[:260])
print("== 页面状态 ==")
print("  ", state)
