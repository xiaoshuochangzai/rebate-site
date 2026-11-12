# -*- coding: utf-8 -*-
"""临时验证：从 20033 页面上下文用同步 XHR 直调 unionSearchRecommend。"""
import json
import urllib.parse
import urllib.request
import websocket

OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main():
    tabs = json.loads(OP.open("http://127.0.0.1:9222/json/list", timeout=5).read())
    tab = next((t for t in tabs if "union_page_id=20033" in t.get("url", "")), None)
    if not tab:
        print("NO 20033 TAB")
        return
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=60)
    _id = [0]

    def send(m, p=None):
        _id[0] += 1
        ws.send(json.dumps({"id": _id[0], "method": m, "params": p or {}}))
        return _id[0]

    def recv(i):
        ws.settimeout(40)
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == i:
                return m
            if m.get("id", 0) > i:
                return {}

    send("Runtime.enable")
    body = {
        "funName": "getSkuByMaterialId",
        "page": {"pageNo": 1, "pageSize": 20},
        "param": {
            "materialId": 40, "sortName": None, "sortType": "", "keyword": "",
            "category1": None, "requestScene": 1, "source": 20200,
            "clientPageId": "union_activity_20033", "packageName": "", "baseType": "",
        },
    }
    enc = urllib.parse.quote(json.dumps(body, ensure_ascii=False))
    url = ("https://api.m.jd.com/api?functionId=unionSearchRecommend"
           "&appid=u_activity_h5&loginType=2&client=&clientVersion=&body=" + enc)
    expr = (
        "(function(){"
        "var x=new XMLHttpRequest();"
        "x.open('GET'," + json.dumps(url) + ",false);"
        "x.withCredentials=true;"
        "x.send();"
        "var t=x.responseText;"
        "try{var j=JSON.parse(t);var lst=j.result&&j.result.data&&j.result.data.goodsSynopsisList;"
        "return JSON.stringify({status:x.status,len:t.length,n:lst?lst.length:0,sku:lst&&lst[0]?lst[0].skuId:null});}"
        "catch(e){return JSON.stringify({status:x.status,err:String(e),head:t.slice(0,120)});}"
        "})()"
    )
    i = send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    m = recv(i)
    print("RESULT:", json.dumps(m.get("result", {}), ensure_ascii=False)[:800])
    ws.close()


if __name__ == "__main__":
    main()
