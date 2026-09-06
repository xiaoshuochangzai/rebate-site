# -*- coding: utf-8 -*-
"""大淘客探针 v2：CDP Network 域监听（比页面钩子可靠）。
流程：连 ws → Network.enable → 真实点击「转链复制」→ 收 12s 请求事件 →
对 dtkapi.ffquan.cn 的请求取响应体。
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

DTK = "dataoke.com"
WATCH = ("dtkapi.ffquan.cn", "pwd-analysis", "convert", "taobao")


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
    print("页面:", t.get("url"))

    # 定位第一个「转链复制」按钮坐标（滚动到可视区）
    rect = call("Runtime.evaluate", {"expression": r"""
(function(){
  for (const b of document.querySelectorAll('[class*="btn2"]')) {
    if ((b.innerText||'').includes('转链复制')) {
      b.scrollIntoView({block:'center'});
      const r = b.getBoundingClientRect();
      return JSON.stringify({x:r.x+r.width/2, y:r.y+r.height/2});
    }
  }
  return null;
})()""", "returnByValue": True}, timeout=15)
    rv = rect["result"]["value"]
    print("按钮坐标:", rv)
    if not rv:
        ws.close(); return
    p = json.loads(rv)

    # 真实点击
    for etype, buttons in [("mousePressed", 1), ("mouseReleased", 0)]:
        call("Input.dispatchMouseEvent", {"type": etype, "x": p["x"], "y": p["y"],
                                          "button": "left", "clickCount": 1, "buttons": buttons})
    print("已真实点击，监听 12 秒…")

    events = {}   # requestId -> {url, method, postData}
    bodies = []
    deadline = time.time() + 12
    ws.settimeout(1)
    while time.time() < deadline:
        try:
            m = json.loads(ws.recv())
        except Exception:
            continue
        meth = m.get("method", "")
        prm = m.get("params", {})
        if meth == "Network.requestWillBeSent":
            req = prm["request"]
            rid = prm["requestId"]
            events[rid] = {"url": req["url"], "method": req["method"], "post": req.get("postData", "")}
        elif meth == "Network.loadingFinished":
            rid = prm["requestId"]
            info = events.get(rid)
            if not info: continue
            if any(w in info["url"] for w in WATCH) or "ffquan.cn" in info["url"]:
                try:
                    body = call("Network.getResponseBody", {"requestId": rid}, timeout=10)
                    b = body.get("body", "")
                    if body.get("base64Encoded"): b = "(base64)"
                except Exception as e:
                    b = f"(取响应体失败: {e})"
                bodies.append({**info, "body": b[:2500]})

    print("\n=== 捕获到 %d 个请求，ffquan 相关 %d 个 ===" % (len(events), len(bodies)))
    for b in bodies:
        print("\n[%s] %s" % (b["method"], b["url"][:180]))
        if b["post"]:
            print("  POST:", b["post"][:600])
        print("  BODY:", (b["body"] or "").replace("\n", " ")[:1200])

    # 同时看看点击后页面有没有变化（弹层）
    pop = call("Runtime.evaluate", {"expression": r"""
(function(){
  const set = new Set();
  document.querySelectorAll('[class*="toast"],[class*="Toast"],[class*="message"],[class*="Modal"],[class*="dialog"],[class*="copy"]').forEach(el=>{
    const t=(el.innerText||'').trim();
    if(t && el.offsetParent!==null) set.add(t.slice(0,500));
  });
  return JSON.stringify([...set]);
})()""", "returnByValue": True}, timeout=15)
    print("\n=== 点击后弹层 ===")
    for s in json.loads(pop["result"]["value"] or "[]"):
        print(" *", s.replace("\n", " | ")[:300])
    ws.close()


if __name__ == "__main__":
    main()
