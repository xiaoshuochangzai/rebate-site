# -*- coding: utf-8 -*-
"""解码 kzurl01 落地页混淆 JS 里的字符串，找接口/跳转链接痕迹。"""
import re, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

for f in [r"E:/Jingdong/rebate-site/fresh_page.html", r"E:/Jingdong/rebate-site/gather_page.html"]:
    h = open(f, encoding="utf-8", errors="replace").read()
    dec = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), h)
    hits = set()
    pats = [
        r"[a-zA-Z0-9_./:-]{0,40}api[a-zA-Z0-9_./:-]{0,40}",
        r"s\.hd00[^\s'\"\\\\]{0,40}",
        r"haodanku[^\s'\"\\\\]{0,50}",
        r"kzurl[^\s'\"\\\\]{0,50}",
        r"taobao[^\s'\"\\\\]{0,50}",
        r"tbopen[^\s'\"\\\\]{0,50}",
        r"s\.click[^\s'\"\\\\]{0,50}",
        r"activity_[a-z]{2,20}",
        r"itemid[^\s'\"\\\\]{0,30}",
        r"couponurl[^\s'\"\\\\]{0,30}",
        r"jump[^\s'\"\\\\]{0,40}",
        r"fq=[a-z]{2,10}",
    ]
    for pat in pats:
        for m in re.findall(pat, dec, re.I):
            if len(m) > 4:
                hits.add(m[:90])
    print("==", f)
    for x in sorted(hits):
        print("  ", x)
