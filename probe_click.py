# -*- coding: utf-8 -*-
"""深挖：点击转链后，抓全部网络响应 + 页面弹窗/提示状态。"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

JS = r"""
(async () => {
  window.__resp = [];
  const of = window.fetch;
  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const p = of.apply(this, arguments);
    p.then(r => { try { r.clone().text().then(t => {
      window.__resp.push({u:String(url), s:r.status, b:t.slice(0,1500)});
    }); } catch(e) {} }).catch(()=>{});
    return p;
  };
  const XO = XMLHttpRequest.prototype.open;
  const XS = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(m, url){ this.__cap={u:String(url),resp:''}; return XO.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function(b){
    if(this.__cap){ const orig=this.onreadystatechange;
      this.onreadystatechange=function(){ if(this.readyState===4){ this.__cap.resp=(this.responseText||'').slice(0,1500); } if(orig) orig.apply(this, arguments); };
      window.__resp.push(this.__cap); }
    return XS.apply(this, arguments);
  };

  const ta = document.querySelectorAll('textarea')[0];
  if (!ta) return JSON.stringify({err:'NO_TEXTAREA'});
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(ta, "测试商品 京东自营\nhttps://item.jd.com/100012043978.html");
  ta.dispatchEvent(new Event('input', {bubbles:true}));
  await new Promise(r => setTimeout(r, 800));

  let clicked = false;
  for (const b of document.querySelectorAll('button')) {
    if ((b.innerText||'').includes('获取推广链接') && !b.disabled) {
      b.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
      b.click();
      clicked = true; break;
    }
  }
  await new Promise(r => setTimeout(r, 8000));

  // 收集可见弹窗/提示
  const modals = [];
  document.querySelectorAll('[class*="modal"],[class*="Modal"],[class*="dialog"],[class*="Dialog"],[class*="message"],[class*="Message"],[class*="toast"],[class*="Toast"]').forEach(el => {
    if (el.offsetParent !== null && (el.innerText||'').trim()) modals.push(el.innerText.trim().slice(0,200));
  });
  return JSON.stringify({
    clicked, taLen: (ta.value||'').length,
    respCount: window.__resp.length,
    resps: window.__resp.map(x => ({u: (x.u||'').slice(0,120), s: x.s||'', body: (x.resp||x.b||'').slice(0,300)})),
    modals: modals.slice(0,8),
    bodyHead: (document.body.innerText||'').slice(0,300)
  });
})();
"""

cdp, t = jd_bot.connect_browser()
val = cdp.evaluate(JS, timeout=90)
try:
    d = json.loads(val)
except Exception:
    print("原始返回:", str(val)[:500]); sys.exit(0)
print("clicked:", d.get("clicked"), "| taLen:", d.get("taLen"), "| 网络响应数:", d.get("respCount"))
print("--- 弹窗/提示 ---")
for m in d.get("modals", []):
    print(" *", m.replace("\n", " | ")[:180])
print("--- 网络响应 ---")
for r in d.get("resps", [])[:15]:
    print(" *", r.get("s"), r.get("u"), "|", (r.get("body") or "")[:120].replace("\n"," "))
cdp.close()
