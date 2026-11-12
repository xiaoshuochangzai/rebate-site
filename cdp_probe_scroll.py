# -*- coding: utf-8 -*-
"""实验2：reload 后耐心滚动，观察 scrollHeight 是否增长 + 各页 pageNo 是否被触发。"""
import json
import time
import urllib.parse
import urllib.request
import websocket

OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
tabs = json.loads(OP.open("http://127.0.0.1:9222/json/list", timeout=5).read())
tab = next((t for t in tabs if "union_page_id=20033" in t.get("url", "")), None)
ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=60)
_id = [0]


def send(m, p=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": m, "params": p or {}}))
    return _id[0]


def recv(i, timeout=20):
    ws.settimeout(timeout)
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == i:
            return m.get("result", {})
        if m.get("id", 0) > i:
            return {}


def page_no_of(url):
    try:
        for k, v in urllib.parse.parse_qsl(urllib.parse.urlparse(url).query):
            if k == "body":
                return json.loads(urllib.parse.unquote(v)).get("page", {}).get("pageNo")
    except Exception:
        pass
    return None


send("Network.enable")
send("Page.enable")
send("Page.navigate", {"url": "https://jingfen.jd.com/item?u_act_p=union-activity&union_page_id=20033"})
time.sleep(6)
seen, reqs = set(), {}
pns = []
for r in range(14):
    send("Runtime.evaluate", {"expression":
         "window.scrollTo(0,document.documentElement.scrollHeight);", "returnByValue": True})
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            ws.settimeout(max(0.3, deadline - time.time()))
            m = json.loads(ws.recv())
        except Exception:
            break
        p = m.get("params", {})
        meth = m.get("method", "")
        if meth == "Network.responseReceived":
            rr = p.get("response", {})
            u = rr.get("url", "")
            if "unionSearchRecommend" in u and rr.get("status") == 200:
                reqs[p["requestId"]] = u
        elif meth == "Network.loadingFinished":
            rid = p.get("requestId")
            if rid in reqs and rid not in seen:
                i2 = send("Network.getResponseBody", {"requestId": rid})
                rb = recv(i2, 12)
                b = (rb.get("result") or {})
                body = b.get("body", "")
                if b.get("base64Encoded"):
                    import base64
                    body = base64.b64decode(body).decode("utf-8", "ignore")
                seen.add(rid)
                pn = page_no_of(reqs[rid])
                pns.append(pn)
                print("step %d: pageNo=%s" % (r, pn))
    # 报告当前 scrollHeight
    i3 = send("Runtime.evaluate", {"expression": "JSON.stringify({sh:document.documentElement.scrollHeight,sy:window.scrollY})", "returnByValue": True})
    info = recv(i3).get("result", {}).get("value")
    print("  after step %d: %s" % (r, info))
print("PAGE NOS CAPTURED:", sorted([x for x in pns if x is not None]))
ws.close()
