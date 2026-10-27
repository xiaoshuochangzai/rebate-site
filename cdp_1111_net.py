# -*- coding: utf-8 -*-
"""CDP 抓 dataoke /xp/1111 页面（双11主会场）的真实数据接口 + 响应体。
重点找「猫超佣金膨胀」专区的接口与佣金字段。"""
import json
import os
import time
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dtk_1111_bodies")
os.makedirs(OUT, exist_ok=True)


def main():
    req = urllib.request.Request(
        "http://127.0.0.1:9222/json/new?about:blank", method="PUT")
    new = json.loads(OPENER.open(req, timeout=10).read().decode())
    ws_url = new["webSocketDebuggerUrl"]
    print("tab:", new["id"])

    import websocket
    ws = websocket.create_connection(ws_url, timeout=30)
    _id = [0]
    reqs = {}          # requestId -> url
    done = {}          # requestId -> (status, url)
    bodies = []        # 抓到的响应体

    def send(method, params=None):
        _id[0] += 1
        ws.send(json.dumps({"id": _id[0], "method": method, "params": params or {}}))
        return _id[0]

    send("Network.enable")
    send("Page.enable")
    send("Emulation.setUserAgentOverride", {"userAgent": UA})
    send("Page.navigate", {"url": "https://www.dataoke.com/xp/1111?v=2"})

    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            ws.settimeout(max(1, deadline - time.time()))
            m = json.loads(ws.recv())
        except Exception:
            break
        meth = m.get("method", "")
        p = m.get("params", {})
        if meth == "Network.requestWillBeSent":
            reqs[p["requestId"]] = p["request"]["url"]
        elif meth == "Network.responseReceived":
            r = p["response"]
            if r.get("status") == 200 and p["requestId"] in reqs:
                u = r["url"]
                if any(k in u for k in ("ffquan", "dtk-go", "api")) and ".js" not in u:
                    done[p["requestId"]] = (u, _id[0])

    # 逐个拉响应体（需在连接存活时）
    idx = 0
    for rid, (u, _) in done.items():
        idx += 1
        i = send("Network.getResponseBody", {"requestId": rid})
        ws.settimeout(10)
        try:
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == i:
                    b = (m.get("result") or {})
                    body = b.get("body", "")
                    if b.get("base64Encoded"):
                        import base64
                        body = base64.b64decode(body).decode("utf-8", "ignore")
                    fn = os.path.join(OUT, "resp%02d.json" % idx)
                    with open(fn, "w", encoding="utf-8") as f:
                        f.write("URL: " + u + "\n\n" + body[:300000])
                    bodies.append((u, fn, len(body)))
                    break
                if m.get("id", 0) > i:
                    break
        except Exception:
            pass

    print("\n=== 抓到 %d 个数据响应 ===" % len(bodies))
    for u, fn, n in bodies:
        print("  [%6d B] %s -> %s" % (n, u[:120], os.path.basename(fn)))

    # 找含「猫超/佣金膨胀」的响应
    for u, fn, n in bodies:
        try:
            t = open(fn, encoding="utf-8").read()
            if any(k in t for k in ("猫超", "佣金膨胀", "maochao", "catSuper", "膨胀")):
                print("\n*** 命中猫超关键词: %s" % fn)
        except Exception:
            pass

    try:
        OPENER.open("http://127.0.0.1:9222/json/close/" + new["id"], timeout=5)
    except Exception:
        pass


if __name__ == "__main__":
    main()
