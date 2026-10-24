# -*- coding: utf-8 -*-
"""实测：淘宝红包链在微信 UA 下的真实行为（对比旧写死链 vs 新生成链）"""
import json
import os
import urllib.parse
import urllib.request

os.chdir(os.path.dirname(os.path.abspath(__file__)))
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
WUA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
       "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.42(0x18002a2b) NetType/WIFI Language/zh_CN")
IUA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
       "(KHTML, like Gecko) Mobile/15E148 Safari/604.1")


def head(url, ua, label):
    print("-" * 66)
    print("URL:", url)
    print("UA :", label)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua})
        op = OPENER.open(req, timeout=25)
        body = op.read(4000).decode("utf-8", "replace")
        print("  状态:", op.status)
        for k in ("Location", "Content-Type", "Content-Length", "Refresh"):
            v = op.getheader(k)
            if v:
                print("  %s: %s" % (k, v[:160]))
        low = body.lower()
        print("  body 前 200 字:", " ".join(body[:200].split())[:200])
        for kw in ("login", "登录", "taobao://", "tbopen://", "uland", "download", "appstore"):
            if kw in low:
                print("  !! 命中关键词:", kw)
    except Exception as e:
        print("  ERR", e)


def gen():
    p = {"apikey": "9AC3C71D776A", "pid": "mm_2130470034_3434000269_116316900171",
         "tb_name": "淘淘淘淘yh", "activity_id": "20150318020007201",
         "title": "2026年双11超级红包", "get_taoword": 1, "domain": "shengqian.cyou"}
    b = urllib.parse.urlencode(p).encode()
    r = urllib.request.Request("https://v2.api.haodanku.com/createConference_code", data=b,
                               headers={"User-Agent": "Mozilla/5.0",
                                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    return json.loads(OPENER.open(r, timeout=30).read().decode())["data"]


d = gen()
print("新生成：")
print("  tao_code:", d.get("tao_code"))
print("  link    :", d.get("link"))
print("  url     :", (d.get("url") or "")[:150], "...")
print()

old = "https://m.tb.cn/h.jXgUEoC"
head(old, WUA, "微信UA")
head(d["link"], WUA, "微信UA")
head(d["link"], IUA, "SafariUA(非微信)")
head(d["url"], WUA, "微信UA")
