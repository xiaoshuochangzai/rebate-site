# -*- coding: utf-8 -*-
"""探针 v12：刷新页面后等久一点，抓全 dtkapi 接口并取响应体，找线报列表 API。"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

DTK = "dataoke.com"


def main():
    t = jd_bot.find_page(DTK)
    if not t:
        print("没找到大淘客标签页"); return
    ws = jd_bot.websocket.create_connection(t["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
    mid = [0]
    def call(method, params=None, timeout=30):
        mid[0] += 1
        ws.settimeout(timeout)
        ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == mid[0]:
                if "error" in m: raise RuntimeError(m["error"])
                return m.get("result", {})

    call("Network.enable")
    call("Page.navigate", {"url": "https://www.dataoke.com/xp/xb"})

    events = {}
    deadline = time.time() + 20
    ws.settimeout(1)
    while time.time() < deadline:
        try:
            m = json.loads(ws.recv())
        except Exception:
            continue
        if m.get("method") == "Network.requestWillBeSent":
            req = m["params"]["request"]
            events[m["params"]["requestId"]] = {"url": req["url"], "post": (req.get("postData") or "")[:800]}
        elif m.get("method") == "Network.loadingFinished":
            rid = m["params"]["requestId"]
            info = events.get(rid)
            if not info: continue
            u = info["url"]
            if "dtkapi.ffquan.cn" not in u: continue
            low = u.lower()
            if any(k in low for k in ["tip", "xb", "list", "news", "wire", "info"]):
                try:
                    body = call("Network.getResponseBody", {"requestId": rid}, timeout=10)
                    b = body.get("body", "")
                    if body.get("base64Encoded"): b = "(base64)"
                except Exception as e:
                    b = f"(取失败:{e})"
                info["body"] = b

    for info in events.values():
        if "body" in info:
            print("\n[URL]", info["url"][:200])
            if info["post"]: print("  POST:", info["post"][:500])
            print("  BODY:", info["body"][:700].replace("\n", " "))
    ws.close()


if __name__ == "__main__":
    main()
