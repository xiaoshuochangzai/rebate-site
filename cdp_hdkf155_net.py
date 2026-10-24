# -*- coding: utf-8 -*-
"""渲染 hdkf155 聚合页，抓所有网络请求 → 定位红包/跳转相关资源与接口。"""
import json, io, sys, time
import urllib.request
import websocket

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
URL = "https://hdkf155.kzurl01.cn/?tmp=gather_new&code=pXVDTx&fq=web&spa_cate_id=433"

r = opener.open(urllib.request.Request(
    "http://127.0.0.1:9222/json/new?" + URL, method="PUT"), timeout=8).read()
tab = json.loads(r)
print("tab:", tab["url"][:90])
ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30, http_proxy_host=None)

_id = [0]
def cmd(method, params=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": method, "params": params or {}}))
    return _id[0]

cmd("Network.enable")
cmd("Network.setUserAgentOverride", {"userAgent":
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.40 Safari/604.1"})
cmd("Runtime.enable")
cmd("Page.enable")
cmd("Page.navigate", {"url": URL})

reqs, errs = [], []
ws.settimeout(2)
t0 = time.time()
while time.time() - t0 < 12:
    try:
        m = json.loads(ws.recv())
    except websocket.WebSocketTimeoutException:
        continue
    except Exception:
        break
    if m.get("method") == "Network.requestWillBeSent":
        reqs.append(m["params"]["request"]["url"])
    if m.get("method") == "Runtime.exceptionThrown":
        d = m["params"]["exceptionDetails"]
        errs.append((d.get("exception", {}).get("description") or d.get("text") or "")[:150])

print("== 请求 %d 条 ==" % len(reqs))
seen = set()
for u in reqs:
    k = u[:70]
    if k in seen:
        continue
    seen.add(k)
    print("  ", u[:130])
print("== 异常 %d 条 ==" % len(errs))
for e in errs[:5]:
    print("  ", e)
