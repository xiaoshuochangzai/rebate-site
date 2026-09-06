# -*- coding: utf-8 -*-
"""大淘客线报「转链复制」探针：
1) 注入 fetch/XHR 钩子抓响应体
2) 定位第一个「转链复制」按钮，滚动到可视区
3) CDP 真实鼠标点击（React 合成事件才触发）
4) 收集：pwd-analysis 响应体 / 后续转链 API / 页面弹层与剪贴板内容
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

DTK = "dataoke.com"

HOOK_JS = r"""
window.__resp = [];
window.__dtkBtn = null;
(function(){
  const of = window.fetch;
  window.fetch = function(input, init){
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const p = of.apply(this, arguments);
    p.then(r => { try { r.clone().text().then(t => {
      window.__resp.push({u:String(url), s:r.status, b:t.slice(0,4000)});
    }); } catch(e){} }).catch(()=>{});
    return p;
  };
  const XO = XMLHttpRequest.prototype.open;
  const XS = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(m, url){ this.__cap={u:String(url),resp:''}; return XO.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function(b){
    if(this.__cap){ const orig=this.onreadystatechange;
      this.onreadystatechange=function(){ if(this.readyState===4){ this.__cap.resp=(this.responseText||'').slice(0,4000); } if(orig) orig.apply(this, arguments); };
      window.__resp.push(this.__cap); }
    return XS.apply(this, arguments);
  };
})();
(function(){
  const btns = document.querySelectorAll('[class*="btn2"]');
  for (const b of btns) {
    if ((b.innerText||'').includes('转链复制')) {
      b.scrollIntoView({block:'center'});
      window.__dtkBtn = {txt: b.innerText.trim(), cls: b.className};
      break;
    }
  }
})();
JSON.stringify(window.__dtkBtn);
"""

RECT_JS = r"""
(function(){
  for (const b of document.querySelectorAll('[class*="btn2"]')) {
    if ((b.innerText||'').includes('转链复制')) {
      const r = b.getBoundingClientRect();
      return JSON.stringify({x:r.x+r.width/2, y:r.y+r.height/2, w:r.width, h:r.height});
    }
  }
  return null;
})();
"""

READ_JS = r"""
(function(){
  // 收集点击后出现的浮层/提示
  const pops = [];
  document.querySelectorAll('[class*="toast"],[class*="Toast"],[class*="message"],[class*="Message"],[class*="popover"],[class*="Popover"],[class*="dialog"],[class*="Dialog"],[class*="modal"],[class*="Modal"],[class*="copy"],[class*="Copy"],[class*="tip"],[class*="Tip"]').forEach(el=>{
    const t = (el.innerText||'').trim();
    if (t && el.offsetParent !== null) pops.push(t.slice(0,800));
  });
  return JSON.stringify({
    respCount: window.__resp.length,
    resps: window.__resp.map(x=>({u:(x.u||'').slice(0,150), s:x.s||'', body:(x.resp||x.b||'').slice(0,2000)})),
    pops: pops.slice(0,10)
  });
})();
"""


def main():
    t = jd_bot.find_page(DTK)
    if not t:
        print("没找到大淘客标签页")
        return
    cdp = jd_bot.CDP(t["webSocketDebuggerUrl"])
    print("页面:", t.get("url"))

    # 1. 注入钩子 + 滚动按钮到可视区
    info = cdp.evaluate(HOOK_JS, timeout=30)
    print("按钮信息:", info)
    if not info or "转链复制" not in str(info):
        print("未找到转链复制按钮")
        cdp.close(); return

    # 2. 取按钮中心坐标
    rect = cdp.evaluate(RECT_JS, timeout=15)
    print("按钮坐标:", rect)
    r = json.loads(rect)
    x, y = r["x"], r["y"]

    # 3. 真实鼠标点击
    for etype in ["mousePressed", "mouseReleased"]:
        cdp.send("Input.dispatchMouseEvent", {
            "type": etype, "x": x, "y": y,
            "button": "left", "clickCount": 1,
            "buttons": 1 if etype == "mousePressed" else 0,
        })
    print("已真实点击")

    # 4. 等 8 秒收响应
    time.sleep(8)
    out = cdp.evaluate(READ_JS, timeout=30)
    try:
        d = json.loads(out)
    except Exception:
        print("原始:", str(out)[:800]); cdp.close(); return

    print("\n=== 捕获响应 %d 条 ===" % d["respCount"])
    for r2 in d["resps"]:
        print("\n[%s] %s" % (r2["s"], r2["u"]))
        print("  body:", (r2["body"] or "").replace("\n", " ")[:600])
    print("\n=== 页面浮层/提示 ===")
    for p in d["pops"]:
        print(" *", p.replace("\n", " | ")[:400])

    # 5. 顺带读剪贴板（可能被拒）
    try:
        cb = cdp.evaluate("navigator.clipboard.readText().then(t=>t.slice(0,1500)).catch(e=>'DENY:'+e.message)", timeout=15)
        print("\n=== 剪贴板 ===\n", cb)
    except Exception as e:
        print("\n剪贴板读取失败:", e)
    cdp.close()


if __name__ == "__main__":
    main()
