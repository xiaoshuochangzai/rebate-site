# -*- coding: utf-8 -*-
"""探针 v8：bringToFront + 焦点/剪贴板侦听 + 真实点击。
验证假设：页面无焦点时转链复制流程静默中断。
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

DTK = "dataoke.com"

SPY_JS = r"""
(function(){
  window.__log = [];
  const L = (s)=>{ try{ window.__log.push(s);}catch(e){} };
  L('hasFocus_before='+document.hasFocus());
  if (navigator.clipboard && navigator.clipboard.writeText) {
    const ow = navigator.clipboard.writeText.bind(navigator.clipboard);
    navigator.clipboard.writeText = function(t){ L('clipboard.writeText len='+(t||'').length+' head='+String(t).slice(0,80)); return ow(t).then(()=>L('writeText OK')).catch(e=>L('writeText ERR:'+e.message)); };
  }
  const oe = document.execCommand.bind(document);
  document.execCommand = function(cmd){ L('execCommand:'+cmd); return oe.apply(document, arguments); };
  // 钩 fetch 抓 pwd-analysis 等
  const of = window.fetch;
  window.fetch = function(input, init){
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (/dtkapi|taobaoapi|convert|pwd/i.test(String(url))) L('fetch '+url.slice(0,120));
    return of.apply(this, arguments);
  };
  return 'SPY_ON';
})();
"""

RESULT_JS = r"""
JSON.stringify({
  hasFocus: document.hasFocus(),
  log: window.__log || []
});
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

    call("Network.enable")

    # 定位按钮
    loc = json.loads(ev(r"""
(function(){
  const b = [...document.querySelectorAll('[class*="btn2"]')].find(x=>(x.innerText||'').includes('转链复制'));
  if(!b) return '{}';
  b.scrollIntoView({block:'center'});
  const r = b.getBoundingClientRect();
  return JSON.stringify({x:r.x+r.width/2, y:r.y+r.height/2});
})()"""))
    if not loc:
        print("NO_BTN"); ws.close(); return

    # 装侦听
    print("侦听:", ev(SPY_JS))

    # 带到前台
    call("Page.bringToFront")
    time.sleep(1)
    print("bringToFront 后 hasFocus:", ev("document.hasFocus()"))

    # 真实点击
    cx, cy = loc["x"], loc["y"]
    call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": cx, "y": cy, "button": "none", "buttons": 0})
    time.sleep(0.3)
    call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": cx, "y": cy, "button": "left", "clickCount": 1, "buttons": 1})
    time.sleep(0.15)
    call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": cx, "y": cy, "button": "left", "clickCount": 1, "buttons": 0})
    print(">>> 已点击，观察 15 秒…")

    deadline = time.time() + 15
    seen = {}
    ws.settimeout(1)
    while time.time() < deadline:
        try:
            m = json.loads(ws.recv())
        except Exception:
            continue
        if m.get("method") == "Network.requestWillBeSent":
            u = m["params"]["request"]["url"]
            if "sendEvent" in u or u.endswith((".js",".css",".png",".gif",".woff2")):
                continue
            seen[u[:150]] = m["params"]["request"].get("postData", "")[:300]

    out = json.loads(ev(RESULT_JS))
    print("\n=== 页面日志 ===")
    for l in out.get("log", []):
        print(" *", l[:200])
    print("\n=== 网络请求 ===")
    for u, p in seen.items():
        print(" *", u)
        if p: print("   POST:", p)
    ws.close()


if __name__ == "__main__":
    main()
