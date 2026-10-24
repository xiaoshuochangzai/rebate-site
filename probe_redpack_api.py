# -*- coding: utf-8 -*-
"""实证：好单库红包转链接口 createConference_code 能否用我们自己的 apikey 调通
对照 hdkf155 聚合页 bundle(gather_new.min.js) 里 function be() 的真实调用：
    wi("https://v2.api.haodanku.com/createConference_code", Ae(h))
    -> ns({platformType:"tb", link:"", token:g.tao_code||"", copySuccessMsg:"复制口令成功,请打开淘宝领取"})
Ae 构造的参数：activity_id / title / itemid / activity_url / activityid /
               domain / shopurl / shopid / cat_id / get_taoword=1 (+apikey,pid,tb_name)
"""
import json
import os
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)

APIKEY = "9AC3C71D776A"
PID = "mm_2130470034_3434000269_116316900171"
TB_NAME = "淘淘淘淘yh"
ACT_ID = "20150318020007201"
ACT_NAME = "2026年双11超级红包"

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.40(0x18002832) NetType/WIFI Language/zh_CN")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def build_params(title, itemid="", activity_url="", cat_id="", shopurl="", shopid="", activityid=""):
    return {
        "apikey": APIKEY,
        "pid": PID,
        "tb_name": TB_NAME,
        "activity_id": ACT_ID,
        "title": title,
        "itemid": itemid,
        "activity_url": activity_url,
        "activityid": activityid,
        "domain": "shengqian.cyou",
        "shopurl": shopurl,
        "shopid": shopid,
        "cat_id": cat_id,
        "get_taoword": 1,
    }


def call(url, params, method="POST"):
    body = urllib.parse.urlencode(params).encode("utf-8")
    if method == "POST":
        req = urllib.request.Request(
            url, data=body,
            headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    else:
        req = urllib.request.Request(url + "?" + body.decode("utf-8"), headers={"User-Agent": UA})
    try:
        raw = OPENER.open(req, timeout=30).read().decode("utf-8", "replace")
        return raw
    except Exception as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return "ERR %s | %s" % (e, detail)


def main():
    v2 = "https://v2.api.haodanku.com/createConference_code"
    v3 = "https://v3.api.haodanku.com/createConference_code"

    cases = [
        ("v2 POST 中文title(对齐bundle)", v2, build_params(ACT_NAME), "POST"),
        ("v2 GET  中文title", v2, build_params(ACT_NAME), "GET"),
        ("v2 POST 英文title", v2, build_params("Double11SuperRedPacket"), "POST"),
        ("v3 POST 中文title", v3, build_params(ACT_NAME), "POST"),
        ("v3 GET  中文title", v3, build_params(ACT_NAME), "GET"),
    ]
    for name, url, p, m in cases:
        print("=" * 72)
        print("CASE:", name)
        print(call(url, p, m)[:600])
    print("=" * 72)

    # 对照：v3 ratesurl（我们已在用的商品转链），看它对红包 activity_id 是否有反应
    ru = "https://v3.api.haodanku.com/ratesurl"
    print("CASE: v3 ratesurl 传 activity_id（试探红包转链可行性）")
    print(call(ru, build_params(ACT_NAME), "POST")[:600])


if __name__ == "__main__":
    main()
