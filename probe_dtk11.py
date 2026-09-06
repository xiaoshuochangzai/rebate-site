# -*- coding: utf-8 -*-
"""探针 v11：刷新大淘客线报页，抓线报列表 API（确定数据源与字段）。"""
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
    print("已刷新页面，监听 12 秒…")

    events = {}; hits = []
    deadline = time.time() + 12
    ws.settimeout(1)
    while time.time() < deadline:
        try:
            m = json.loads(ws.recv())
        except Exception:
            continue
        if m.get("method") == "Network.requestWillBeSent":
            req = m["params"]["request"]
            u = req["url"]
            events[m["params"]["requestId"]] = u
            if "ffquan.cn" in u and "sendEvent" not in u and not u.endswith((".js",".css",".png",".jpg",".gif",".woff2",".svg",".ico")):
                hits.append({"url": u, "post": (req.get("postData") or "")[:500]})

    # 对命中的接口取响应体（看哪个是线报列表）
    for h in hits[:12]:
        print("\n[URL]", h["url"][:180])
        if h["post"]: print("  POST:", h["post"][:300])
    ws.close()

    # 再开一次连接取响应体太麻烦——直接把候选 URL 打出来人工判断
    print("\n候选接口共", len(hits), "个")


if __name__ == "__main__":
    main()
