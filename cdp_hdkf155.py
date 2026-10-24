# -*- coding: utf-8 -*-
"""真渲染 hdkf155 聚合页，抓剪贴板写入/跳转/红包弹窗。"""
import json, io, sys, time
import urllib.request
import websocket

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
URL = "https://hdkf155.kzurl01.cn/?tmp=gather_new&code=pXVDTx&fq=web&spa_cate_id=433"

# 新建 tab
_newreq = urllib.request.Request("http://127.0.0.1:9222/json/new?" + URL, method="PUT")
r = opener.open(_newreq, timeout=8).read()
tab = json.loads(r)
print("tab:", tab["url"][:90])
ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30, http_proxy_host=None)

_id = [0]
def cmd(method, params=None):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": method, "params": params or {}}))
    return _id[0]

# 手机环境：接管 UA + 尺寸（模拟微信内置浏览器）
cmd("Network.enable")
cmd("Network.setUserAgentOverride", {"userAgent":
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.40 Safari/604.1"})
cmd("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844,
                                            "deviceScaleFactor": 2, "mobile": True})
# 提前注入剪贴板 hook（页面脚本执行前）
HOOK = """
(function(){
  try{
    Object.defineProperty(navigator,'clipboard',{value:{writeText:function(t){ window.__cap=String(t); return Promise.resolve(); }}, configurable:true});
  }catch(e){}
  try{
    var _o = document.execCommand;
    document.execCommand = function(c){
      if(String(c).toLowerCase()==='copy'){
        var a=document.activeElement;
        if(a && (a.tagName==='TEXTAREA'||a.tagName==='INPUT')) window.__cap = a.value;
      }
      return _o.apply(document, arguments);
    };
  }catch(e){}
  try{
    window.__navs = [];
    var _op = window.open; window.open = function(u){ window.__navs.push(String(u)); return null; };
  }catch(e){}
})();
"""
cmd("Page.addScriptToEvaluateOnNewDocument", {"source": HOOK})
cmd("Page.navigate", {"url": URL})
time.sleep(9)

def ev(expr):
    _id[0] += 1
    wid = _id[0]
    ws.send(json.dumps({"id": wid, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True}}))
    end = time.time() + 8
    ws.settimeout(2)
    while time.time() < end:
        try:
            m = json.loads(ws.recv())
        except websocket.WebSocketTimeoutException:
            continue
        if m.get("id") == wid:
            return m.get("result", {}).get("result", {}).get("value")
    return None

state = ev(r"""JSON.stringify({
 url: location.href,
 cap: (window.__cap||''),
 navs: (window.__navs||[]),
 imgs: Array.from(document.images).map(i=>i.src).filter(s=>/red|ticket|hongbao|hb/i.test(s)).slice(0,6),
 popup: (function(){
   const all = Array.from(document.querySelectorAll('div,section,a'));
   for (const e of all){
     const t = (e.innerText||'').trim();
     if (t && t.length < 90 && /超级红包|開|抢红包/.test(t)) return t.replace(/\n+/g,' | ');
   }
   return '';
 })()
})""")
print(state)
