# -*- coding: utf-8 -*-
"""大淘客探针 v10：恢复剪贴板权限 + 真实点击「转链复制」+ 抓转链 API 与剪贴板结果。
背景：Boss 曾误拒剪贴板权限，此后点击只复制原文、不调转链 API（疑似权限守卫）。
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

DTK = "dataoke.com"

SPY_JS = r"""
(function(){
  window.__log = [];
  const L = (s)=>{ try{ window.__log.push(String(s)); }catch(e){} };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    const ow = navigator.clipboard.writeText.bind(navigator.clipboard);
    navigator.clipboard.writeText = function(t){
      L('writeText len='+(t||'').length+' >>> '+String(t).slice(0,300));
      return ow(t).then(()=>L('writeText OK')).catch(e=>L('writeText ERR:'+e.message));
    };
  }
  const oe = document.execCommand.bind(document);
  document.execCommand = function(cmd){ L('execCommand:'+cmd); return oe.apply(document, arguments); };
  return 'SPY_ON';
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
                if "error" in m: raise RuntimeError(f"CDP {method}: {m['error']}")
                return m.get("result", {})

    def ev(expression, timeout=20):
        return call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True}, timeout)["result"]["value"]

    call("Network.enable")

    # 1. 查当前剪贴板权限状态
    perm = ev(r"""
(async()=>{
  function q(n){ return navigator.permissions.query({name:n}).then(s=>s.state).catch(e=>'ERR:'+e.message); }
  return JSON.stringify({
    read: await q('clipboard-read'),
    write: await q('clipboard-write'),
    hasFocus: document.hasFocus()
  });
})()""")
    print("当前权限:", perm)

    # 2. CDP 直接授权（不需要 Boss 点弹窗）
    try:
        call("Browser.grantPermissions", {
            "permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"],
            "origin": "https://www.dataoke.com",
        })
        print(">>> 已通过 CDP 授权剪贴板读写")
    except Exception as e:
        print("页面级授权失败，改用浏览器级:", str(e)[:100])
        ver = jd_bot.is_running()
        bws = jd_bot.websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
        bmid = [1000]
        def bcall(method, params=None):
            bmid[0] += 1
            bws.settimeout(30)
            bws.send(json.dumps({"id": bmid[0], "method": method, "params": params or {}}))
            while True:
                m = json.loads(bws.recv())
                if m.get("id") == bmid[0]:
                    if "error" in m: raise RuntimeError(m["error"])
                    return m.get("result", {})
        bcall("Browser.grantPermissions", {
            "permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"],
            "origin": "https://www.dataoke.com",
        })
        bws.close()
        print(">>> 浏览器级授权完成")

    perm2 = ev(r"""
(async()=>{
  function q(n){ return navigator.permissions.query({name:n}).then(s=>s.state).catch(e=>'ERR:'+e.message); }
  return JSON.stringify({read: await q('clipboard-read'), write: await q('clipboard-write')});
})()""")
    print("授权后权限:", perm2)

    # 3. 装剪贴板侦听 + 定位按钮
    print("侦听:", ev(SPY_JS))
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

    # 4. 带到前台 + 真实点击
    call("Page.bringToFront")
    time.sleep(0.8)
    cx, cy = loc["x"], loc["y"]
    call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": cx, "y": cy, "button": "none", "buttons": 0})
    time.sleep(0.3)
    call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": cx, "y": cy, "button": "left", "clickCount": 1, "buttons": 1})
    time.sleep(0.15)
    call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": cx, "y": cy, "button": "left", "clickCount": 1, "buttons": 0})
    print(">>> 已点击，观察 18 秒…")

    # 5. 收网络请求
    events = {}; bodies = []
    deadline = time.time() + 18
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
            u = info["url"]
            if "sendEvent" in u or u.endswith((".js",".css",".png",".jpg",".gif",".woff2",".svg",".ico")):
                continue
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
        if b["post"]: print("  POST:", b["post"][:600])
        print("  BODY:", (b["body"] or "").replace("\n", " ")[:1200])

    # 6. 页面日志 + 读剪贴板
    log = ev("JSON.stringify(window.__log||[])")
    print("\n=== 页面剪贴板日志 ===")
    for l in json.loads(log or "[]"):
        print(" *", l[:400])
    cb = ev("navigator.clipboard.readText().then(t=>'LEN:'+t.length+' >>> '+t.slice(0,500)).catch(e=>'DENY:'+e.message)")
    print("\n=== 剪贴板当前内容 ===\n", cb)
    ws.close()


if __name__ == "__main__":
    main()
