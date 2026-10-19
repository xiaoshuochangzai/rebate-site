# -*- coding: utf-8 -*-
"""摸清猫超接口供给：type 1-4 各页量与去重总量"""
import json
import urllib.request

import websocket

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with OPENER.open("http://127.0.0.1:9222/json", timeout=8) as r:
    tabs = json.loads(r.read().decode("utf-8"))
t = next(x for x in tabs if x.get("type") == "page" and "kzurl01" in x.get("url", ""))
ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=40)
_id = [0]
NAMES = {1: "低价包邮", 2: "猫超热销", 3: "即将开抢", 4: "一元购"}
seen = {}
for typ in (1, 2, 3, 4):
    page = 1
    while page <= 5:
        js = (
            "(function(){return fetch('https://api.haodanku.com/api/maochao_items?type=%d&p=%d&order=3&cat_id=0&code=nO1uOS')"
            ".then(function(r){return r.text()});})()" % (typ, page)
        )
        ws.send(json.dumps({"id": None, "method": "Runtime.evaluate",
                            "params": {"expression": js, "returnByValue": True, "awaitPromise": True}}))
        # id=None 不行，CDP 需要 id；用计数
        _id[0] += 1
        ws.send(json.dumps({"id": 1000 + _id[0], "method": "Runtime.evaluate",
                            "params": {"expression": js, "returnByValue": True, "awaitPromise": True}}))
        got = None
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == 1000 + _id[0]:
                got = m["result"]["result"].get("value", "")
                break
        try:
            d = json.loads(got)
        except Exception:
            print(f"type{typ} p{page}: 解析失败", str(got)[:80])
            break
        data = (d.get("data") or {})
        arr = data.get("data") or []
        n_new = 0
        for it in arr:
            iid = str(it.get("itemid"))
            if iid not in seen:
                seen[iid] = NAMES[typ]
                n_new += 1
        print(f"type{typ}({NAMES[typ]}) p{page}: {len(arr)} 条(新{n_new}) page_all={data.get('page_all')}")
        if not arr or page >= int(data.get("page_all") or 1):
            break
        page += 1
print("四类去重总量:", len(seen))
from collections import Counter
print(Counter(seen.values()))
ws.close()
