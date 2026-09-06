# -*- coding: utf-8 -*-
"""探针 v5：读 __reactEventHandlers$ 拿 onClick，直接调用（配 Network 监听抓响应）。
单条测试原则：只点第一条线报。
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

DTK = "dataoke.com"

READ_JS = r"""
(function(){
  const b = [...document.querySelectorAll('[class*="btn2"]')].find(x=>(x.innerText||'').includes('转链复制'));
  if(!b) return JSON.stringify({err:'NO_BTN'});
  let h = null;
  for (const k of Object.keys(b)) {
    if (k.startsWith('__reactEventHandlers$')) h = b[k];
  }
  if(!h) return JSON.stringify({err:'NO_HANDLERS'});
  return JSON.stringify({
    keys: Object.keys(h),
    onClickSrc: h.onClick ? h.onClick.toString().slice(0,2000) : null
  });
})();
"""

CLICK_JS = r"""
(function(){
  const b = [...document.querySelectorAll('[class*="btn2"]')].find(x=>(x.innerText||'').includes('转链复制'));
  if(!b) return 'NO_BTN';
  let h = null;
  for (const k of Object.keys(b)) {
    if (k.startsWith('__reactEventHandlers$')) h = b[k];
  }
  if(!h || !h.onClick) return 'NO_ONCLICK';
  try {
    h.onClick({
      preventDefault(){}, stopPropagation(){}, persist(){},
      nativeEvent:{}, target:b, currentTarget:b, type:'click'
    });
    return 'CALLED';
  } catch(e) { return 'ERR:' + e.message; }
})();
"""


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

    def ev(expression, timeout=20):
        return call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True}, timeout)["result"]["value"]

    print("onClick 定义:", ev(READ_JS)[:1800])

    call("Network.enable")
    print("\n>>> 直接调用 onClick …")
    res = ev(CLICK_JS)
    print("调用结果:", res)

    # 收 12s 请求
    events = {}; bodies = []
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
            events[prm["requestId"]] = {"url": req["url"], "method": req["method"], "post": req.get("postData", "")}
        elif meth == "Network.loadingFinished":
            info = events.get(prm["requestId"])
            if not info: continue
            if "ffquan.cn" in info["url"] and "sendEvent" not in info["url"]:
                try:
                    body = call("Network.getResponseBody", {"requestId": prm["requestId"]}, timeout=10)
                    b = body.get("body", "")
                    if body.get("base64Encoded"): b = "(base64)"
                except Exception as e:
                    b = f"(取失败:{e})"
                bodies.append({**info, "body": b[:3000]})

    print("\n=== 业务请求 %d 个 ===" % len(bodies))
    for b in bodies:
        print("\n[%s] %s" % (b["method"], b["url"][:200]))
        if b["post"]: print("  POST:", b["post"][:800])
        print("  BODY:", (b["body"] or "").replace("\n", " ")[:1500])
    ws.close()


if __name__ == "__main__":
    main()
