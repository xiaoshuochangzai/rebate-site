# -*- coding: utf-8 -*-
"""探针 v7：覆盖检查 + 完整鼠标序列真实点击 + 抓全部请求。
把按钮滚到视口中央下方，避开顶部提示条。
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

DTK = "dataoke.com"

LOCATE_JS = r"""
(function(){
  // 选第一条线报的转链复制按钮
  const b = [...document.querySelectorAll('[class*="btn2"]')].find(x=>(x.innerText||'').includes('转链复制'));
  if(!b) return JSON.stringify({err:'NO_BTN'});
  b.scrollIntoView({block:'center'});
  const r = b.getBoundingClientRect();
  const cx = r.x + r.width/2, cy = r.y + r.height/2;
  const top = document.elementFromPoint(cx, cy);
  // 卡片文案（确认点的是哪条）
  let card = b; 
  for(let i=0;i<10 && card;i++){ if((card.className||'').includes('tip-grid-style-item')||(card.className||'').includes('tip-grid-style')) break; card = card.parentElement; }
  return JSON.stringify({
    cx, cy, w:r.width, h:r.height,
    topEl: top ? {tag: top.tagName, cls: String(top.className).slice(0,80), txt:(top.innerText||'').slice(0,60)} : null,
    cardTxt: card ? (card.innerText||'').slice(0,200) : null,
    viewport: {w: innerWidth, h: innerHeight}
  });
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

    info = json.loads(ev(LOCATE_JS))
    if info.get("err"):
        print(info); ws.close(); return
    print("定位:", json.dumps(info, ensure_ascii=False)[:500])
    if info.get("topEl") and "btn2" not in str(info["topEl"].get("cls","")):
        print("⚠️ 按钮被覆盖：", info["topEl"])

    call("Network.enable")

    cx, cy = info["cx"], info["cy"]
    # 完整鼠标序列
    call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": cx, "y": cy, "button": "none", "buttons": 0})
    time.sleep(0.3)
    call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": cx, "y": cy, "button": "left", "clickCount": 1, "buttons": 1})
    time.sleep(0.15)
    call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": cx, "y": cy, "button": "left", "clickCount": 1, "buttons": 0})
    print(">>> 已点击，监听 15 秒…")

    events = {}; bodies = []
    deadline = time.time() + 15
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
            info2 = events.get(prm["requestId"])
            if not info2: continue
            u = info2["url"]
            if u.startswith("data:") or "/static/" in u or u.endswith((".js",".css",".woff2",".png",".jpg",".svg",".ico")):
                continue
            try:
                body = call("Network.getResponseBody", {"requestId": prm["requestId"]}, timeout=10)
                b = body.get("body", "")
                if body.get("base64Encoded"): b = "(base64)"
            except Exception as e:
                b = f"(取失败:{e})"
            bodies.append({**info2, "body": b[:3000]})

    print("\n=== 请求 %d 个 ===" % len(bodies))
    for b in bodies:
        print("\n[%s] %s" % (b["method"], b["url"][:200]))
        if b["post"]: print("  POST:", b["post"][:800])
        print("  BODY:", (b["body"] or "").replace("\n", " ")[:1000])

    # 点击后页面状态：弹窗/剪贴板提示/按钮文字变化
    after = ev(r"""
(function(){
  const set = [];
  document.querySelectorAll('[class*="modal"],[class*="Modal"],[class*="dialog"],[class*="Toast"],[class*="toast"],[class*="ant-message"],[class*="ant-popover"],[class*="copy-tip"],[class*="result"]').forEach(el=>{
    const t=(el.innerText||'').trim();
    if(t && el.offsetParent!==null) set.push(String(el.className).slice(0,50)+' => '+t.slice(0,300));
  });
  return JSON.stringify(set);
})()""", timeout=15)
    print("\n=== 点击后弹层 ===")
    for s in json.loads(after or "[]"):
        print(" *", s.replace("\n", " | ")[:350])
    ws.close()


if __name__ == "__main__":
    main()
