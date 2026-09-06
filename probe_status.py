# -*- coding: utf-8 -*-
"""抓 ConvertSuperLink 的 HTTP 状态码 + 失败原因。"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

JS = r"""
(async () => {
  window.__resp = [];
  const XO = XMLHttpRequest.prototype.open;
  const XS = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(m, url){ this.__cap={u:String(url),resp:'',status:0,st:''}; return XO.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function(b){
    if(this.__cap){ this.__cap.body=(b||'').slice(0,800);
      const orig=this.onreadystatechange;
      this.onreadystatechange=function(){ if(this.readyState===4){ this.__cap.resp=(this.responseText||'').slice(0,1000); this.__cap.status=this.status; this.__cap.st=this.statusText; } if(orig) orig.apply(this, arguments); };
      window.__resp.push(this.__cap); }
    return XS.apply(this, arguments);
  };
  const of = window.fetch;
  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const p = of.apply(this, arguments);
    p.then(r => { try { r.clone().text().then(t => {
      window.__resp.push({u:String(url), status:r.status, st:r.statusText, resp:t.slice(0,1000)});
    }).catch(e => window.__resp.push({u:String(url), status:-2, st:'bodyread:'+e})); } catch(e) {} })
    .catch(e => window.__resp.push({u:String(url), status:-1, st:'fetchfail:'+e}));
    return p;
  };

  const ta = document.querySelectorAll('textarea')[0];
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(ta, "测试商品 京东自营\nhttps://item.jd.com/100012043978.html");
  ta.dispatchEvent(new Event('input', {bubbles:true}));
  await new Promise(r => setTimeout(r, 800));
  for (const b of document.querySelectorAll('button')) {
    if ((b.innerText||'').includes('获取推广链接') && !b.disabled) {
      b.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
      b.click();
      break;
    }
  }
  await new Promise(r => setTimeout(r, 10000));
  const conv = window.__resp.filter(x => (x.u||'').includes('ConvertSuperLink'));
  return JSON.stringify(conv.map(x => ({status:x.status||x.s, st:x.st||'', u:(x.u||'').slice(0,100), resp:(x.resp||'').slice(0,400), body:(x.body||'').slice(0,300)})));
})();
"""

cdp, t = jd_bot.connect_browser()
val = cdp.evaluate(JS, timeout=90)
rows = json.loads(val)
print("ConvertSuperLink 捕获:", len(rows))
for r in rows:
    print("== status:", r.get("status"), r.get("st"))
    print("   resp:", (r.get("resp") or "")[:250])
    print("   body:", (r.get("body") or "")[:200])
cdp.close()
