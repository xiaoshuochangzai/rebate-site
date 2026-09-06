# -*- coding: utf-8 -*-
"""探测万能转链对「整段文案含券长链」的处理：捕获全部 ConvertSuperLink 响应，
并自动点掉【保留失败链接转链】弹窗，把前后响应都落盘供分析。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_convert_browser as jc

MATERIAL = """好想你 阿胶固元糕 180g*3盒
拍下55.8元；Plus【50.81元】
送黑芝麻软糕135g；留意赠品
领 https://coupon.m.jd.com/coupons/show.action?key=c7m4c3s2o9a34c9f9420f5fa520f377e&roleId=3162250004
https://u.jd.com/xOzNaU3"""

JS = r"""
(async () => {
  const MATERIAL = __TEXT__;
  window.__resp = [];
  const of = window.fetch;
  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    let body = '';
    try { if (init && init.body) body = String(init.body).slice(0, 4000); } catch(e) {}
    const p = of.apply(this, arguments);
    p.then(r => { try { r.clone().text().then(t => {
      window.__resp.push({u:String(url), s:r.status, req:body, b:t.slice(0,30000)});
    }); } catch(e) {} }).catch(()=>{});
    return p;
  };
  const XO = XMLHttpRequest.prototype.open;
  const XS = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(m, url){ this.__cap={u:String(url),req:'',resp:''}; return XO.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function(b){
    if(this.__cap){ this.__cap.req=(b||'').slice(0,4000);
      const orig=this.onreadystatechange;
      this.onreadystatechange=function(){ if(this.readyState===4){ this.__cap.resp=(this.responseText||'').slice(0,30000); } if(orig) orig.apply(this, arguments); };
      window.__resp.push(this.__cap);
    }
    return XS.apply(this, arguments);
  };

  for (let i=0;i<20;i++) {
    const ta = document.querySelectorAll('textarea')[0];
    if (ta && ta.offsetParent !== null) break;
    await new Promise(r => setTimeout(r, 300));
  }
  const tas = document.querySelectorAll('textarea');
  const ta = tas[0];
  if (!ta) return JSON.stringify({err:'NO_TEXTAREA'});

  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(ta, MATERIAL);
  ta.dispatchEvent(new Event('input', {bubbles:true}));
  ta.dispatchEvent(new Event('change', {bubbles:true}));
  await new Promise(r => setTimeout(r, 600));
  ta.focus();

  let clicked = false;
  for (let w=0; w<12 && !clicked; w++) {
    for (const b of document.querySelectorAll('button')) {
      if ((b.innerText||'').includes('获取推广链接') && !b.disabled) {
        b.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
        b.click();
        clicked = true;
        break;
      }
    }
    if (!clicked) {
      setter.call(ta, MATERIAL);
      ta.dispatchEvent(new Event('input', {bubbles:true}));
      await new Promise(r => setTimeout(r, 300));
    }
  }
  if (!clicked) return JSON.stringify({err:'NO_BUTTON'});

  // 弹窗监测：出现【保留失败链接转链】就点掉，然后等下一发 ConvertSuperLink 响应
  let dialogClicked = false;
  for (let i=0;i<40;i++) {
    for (const b of document.querySelectorAll('button')) {
      const t = (b.innerText||'').replace(/\s/g,'');
      if ((t.includes('保留失败') || t.includes('保留失效')) && b.offsetParent !== null) {
        b.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
        b.click();
        dialogClicked = true;
        break;
      }
    }
    const n = window.__resp.filter(x => x.u && x.u.includes('ConvertSuperLink') && (x.resp || x.b)).length;
    if (dialogClicked && n >= 2) break;
    if (!dialogClicked && n >= 1 && i > 16) break;
    await new Promise(r => setTimeout(r, 500));
  }
  const all = window.__resp.filter(x => x.u && x.u.includes('ConvertSuperLink'));
  return JSON.stringify({dialogClicked, count: all.length, resp: all});
})();
"""

js = JS.replace("__TEXT__", json.dumps(MATERIAL, ensure_ascii=False))
cdp = jc._get_cdp()
val = cdp.evaluate(js, timeout=120)
data = json.loads(val)
print("dialogClicked:", data.get("dialogClicked"), "| 捕获响应数:", data.get("count"))
with open("probe_resp.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=1)
for i, r in enumerate(data.get("resp", [])):
    body = r.get("resp") or r.get("b") or ""
    print(f"--- 响应{i+1} len={len(body)} ---")
    print(body[:600])
    print()
