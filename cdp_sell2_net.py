# -*- coding: utf-8 -*-
"""CDP 抓 top_sell2（2小时热销榜）页面的真实数据接口。"""
import json
import time
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def cdp(ws_url, msg):
    import websocket  # websocket-client
    ws = websocket.create_connection(ws_url, timeout=15)
    ws.send(json.dumps(msg))
    return ws


def main():
    tabs = json.loads(OPENER.open("http://127.0.0.1:9222/json", timeout=10).read().decode())
    page = next((t for t in tabs if t.get("type") == "page"), None)
    if not page:
        print("无可用页面"); return
    # 新开标签（新版 Chrome 的 /json/new 要求 PUT）
    req = urllib.request.Request(
        "http://127.0.0.1:9222/json/new?https://www.dataoke.com/top_sell2?v=2",
        method="PUT")
    new = json.loads(OPENER.open(req, timeout=10).read().decode())
    ws_url = new["webSocketDebuggerUrl"]
    print("tab:", new["id"], new["url"])

    import websocket
    ws = websocket.create_connection(ws_url, timeout=30)
    reqs = {}

    def send(id_, method, params=None):
        ws.send(json.dumps({"id": id_, "method": method, "params": params or {}}))

    send(1, "Network.enable")
    send(2, "Page.enable")
    send(3, "Runtime.enable")
    send(4, "Emulation.setUserAgentOverride", {"userAgent": UA})
    send(5, "Page.navigate", {"url": "https://www.dataoke.com/top_sell2?v=2"})

    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            ws.settimeout(max(1, deadline - time.time()))
            m = json.loads(ws.recv())
        except Exception:
            break
        meth = m.get("method", "")
        p = m.get("params", {})
        if meth == "Network.requestWillBeSent":
            u = p["request"]["url"]
            if any(k in u for k in ("ffquan", "dataoke", "api")):
                reqs[p["request"]["url"]] = p["request"].get("method")
        elif meth == "Network.responseReceived":
            u = p["response"]["url"]
            if u in reqs and p["response"]["status"] == 200:
                reqs[u] = reqs[u] + " => 200"

    print("\n=== 数据类请求（%d 条）===" % len(reqs))
    for u, meth in sorted(reqs.items()):
        if "=> 200" in meth or ".js" not in u:
            print("  [%s] %s" % (meth.replace(" => 200", ""), u[:160]))

    try:
        OPENER.open("http://127.0.0.1:9222/json/close/" + new["id"], timeout=5)
    except Exception:
        pass


if __name__ == "__main__":
    main()
