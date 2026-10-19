# -*- coding: utf-8 -*-
"""点击猫超好货/天猫超市的免费推广，抓弹窗"""
import json, time, urllib.request
import websocket
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
    tabs = json.loads(r.read().decode("utf-8"))
t = [x for x in tabs if x.get("type")=="page" and "source_market" in x.get("url","")][-1]
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=40)

def ev(js, ap=False):
    ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":js,"returnByValue":True,"awaitPromise":ap}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id")==1: return m["result"]["result"].get("value")

def click_free_promo(kw):
    return ev(r"""
(function(){
  var cards = document.querySelectorAll('[class*=card]');
  for (var i=0;i<cards.length;i++){
    var c=cards[i];
    if ((c.innerText||'').indexOf('%s')>=0){
      var bs=c.querySelectorAll('button');
      for (var j=0;j<bs.length;j++){
        if ((bs[j].innerText||'').trim()==='免费推广'){ bs[j].click(); return 'clicked'; }
      }
    }
  }
  return 'not found';
})()""" % kw)

def dump_dialog():
    time.sleep(3)
    return ev(r"""
(function(){
  var dlg = document.querySelector('.el-dialog__wrapper:not([style*="display: none"]) .el-dialog, .el-dialog:not([style*="display: none"])');
  var out = {dlg: dlg ? dlg.innerText.slice(0,800) : '', url: location.href, new_tabs: []};
  // 弹窗里的链接与图片（二维码）
  if (dlg) {
    dlg.querySelectorAll('a,img,input,iframe').forEach(function(e){
      if (e.tagName==='A' && e.href) out.new_tabs.push('A: '+e.href.slice(0,150));
      if (e.tagName==='IMG' && e.src) out.new_tabs.push('IMG: '+e.src.slice(0,150));
      if (e.tagName==='IFRAME' && e.src) out.new_tabs.push('IFRAME: '+e.src.slice(0,150));
      if (e.tagName==='INPUT') out.new_tabs.push('INPUT: '+(e.value||'').slice(0,150));
    });
  }
  return JSON.stringify(out);
})()""")

print("== 猫超好货 ==")
print("click:", click_free_promo("猫超好货"))
print(json.dumps(json.loads(dump_dialog()), ensure_ascii=False, indent=1)[:1800])
# 关掉弹窗（Esc 或关闭按钮），再点天猫超市
ev("(function(){document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',keyCode:27,bubbles:true}));var b=document.querySelector('.el-dialog__headerbtn');if(b)b.click();return 1})()")
time.sleep(2)
print("== 天猫超市 ==")
print("click:", click_free_promo("天猫超市"))
print(json.dumps(json.loads(dump_dialog()), ensure_ascii=False, indent=1)[:1800])
ws.close()
