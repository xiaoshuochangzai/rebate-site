# -*- coding: utf-8 -*-
"""id=35 详情页点预览，抓落地页 URL 与标签"""
import json
import time
import urllib.request

import websocket

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
    tabs = json.loads(r.read().decode("utf-8"))
t = next(x for x in tabs if x.get("type") == "page" and "source_market_inner" in x.get("url", ""))

# 先开 Network 抓预览跳转
_id = [0]
def send(method, params=None):
    _id[0] += 1
    ws_id = _id[0]
    ws.send(json.dumps({"id": ws_id, "method": method, "params": params or {}}))
    return ws_id

ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=60)
send("Network.enable", {})
w = send("Runtime.evaluate", {"expression": (
    "(function(){var bs=document.querySelectorAll('button,a');"
    "for(var i=0;i<bs.length;i++){if((bs[i].innerText||'').trim()==='预览'){bs[i].click();return 'clicked';}}"
    "return 'nf';})()"), "returnByValue": True})
time.sleep(8)
# 收集：新 tab 事件 + 当前 URL
new_urls = []
end = time.time() + 5
try:
    while time.time() < end:
        ws.settimeout(max(1, end - time.time()))
        m = json.loads(ws.recv())
        if m.get("method") == "Network.requestWillBeSent":
            u = m["params"]["request"]["url"]
            if "kzurl" in u or "tmp=" in u or "s.hd00" in u or "superpage" in u:
                new_urls.append(u[:160])
except Exception:
    pass
print("reply:", m.get("result", {}).get("result", {}).get("value") if m.get("id") == w else "?")
print("捕获URL:")
for u in new_urls:
    print(" ", u)
ws.close()
# 看是否新开了 tab
with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
    tabs = json.loads(r.read().decode("utf-8"))
for x in tabs:
    if x.get("type") == "page" and ("kzurl" in x.get("url", "") or "hd00" in x.get("url", "")):
        print("新tab:", x["url"][:150])
