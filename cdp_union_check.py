# -*- coding: utf-8 -*-
"""只读：CDP 连 9222 的 union.jd.com tab，读当前登录账号的真实 unionId 与 unionName，
与 ztk_config.json 的 unionId 对证。不点击、不改任何状态。"""
import json, time, urllib.request as _ur
import websocket
PORT=9222
OP=_ur.build_opener(_ur.ProxyHandler({}))

def main():
    tabs=json.loads(OP.open("http://127.0.0.1:%d/json/list"%PORT,timeout=5).read())
    tab=next((t for t in tabs if "union.jd.com" in (t.get("url") or "")),None)
    if not tab:
        print("无 union.jd.com 标签"); return
    ws=websocket.create_connection(tab["webSocketDebuggerUrl"],timeout=30,suppress_origin=True)
    _id=[0]
    def send(m,p=None):
        _id[0]+=1; ws.send(json.dumps({"id":_id[0],"method":m,"params":p or {}})); return _id[0]
    def recv(i,to=15):
        ws.settimeout(to)
        while True:
            mm=json.loads(ws.recv())
            if mm.get("id")==i: return mm
    # 页面上下文里直接调联盟用户信息接口（同源带 cookie）
    js="""(function(){
      return fetch('https://union.jd.com/api/getUserInfo',{credentials:'include'})
        .then(function(r){return r.text();})
        .then(function(t){return t.slice(0,800);})
        .catch(function(e){return 'ERR '+e.message;});
    })()"""
    i=send("Runtime.evaluate",{"expression":js,"awaitPromise":True,"returnByValue":True})
    print("getUserInfo:",(recv(i).get("result",{}).get("result",{}) or {}).get("value",""))
    # 备用：页面内常见用户信息 DOM / 全局变量
    js2="""(function(){
      var t=(document.body&&document.body.innerText||'').slice(0,600);
      return JSON.stringify({url:location.href.slice(0,120),text:t});
    })()"""
    i=send("Runtime.evaluate",{"expression":js2,"returnByValue":True})
    r=(recv(i).get("result",{}).get("result",{}) or {}).get("value","")
    try:
        d=json.loads(r); print("URL:",d.get("url")); print("页面文本:",d.get("text","")[:500])
    except Exception:
        print(r[:600])
    ws.close()

if __name__=="__main__": main()
