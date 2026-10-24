# -*- coding: utf-8 -*-
"""解码 hdkf155 落地页混淆数组，挖红包/跳转相关明文。"""
import re, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

for f in [r"E:/Jingdong/rebate-site/g2.html", r"E:/Jingdong/rebate-site/gather_page.html"]:
    h = open(f, encoding="utf-8", errors="replace").read()
    dec = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), h)
    print("=====", f)
    # 找 URL / 协议 / 接口关键词
    for pat in [r"https?://[^\s'\"\\\\\)\]]{5,120}", r"tbopen[^\s'\"]{0,60}",
                 r"[a-z0-9_./-]*api[^\s'\"]{0,40}", r"红包", r"口令",
                 r"copy[A-Za-z]*", r"paste[A-Za-z]*", r"Universal[A-Za-z]*",
                 r"launch[A-Za-z]*", r"wechat|wx[A-Za-z]*"]:
        hits = set(m[:110] for m in re.findall(pat, dec, re.I))
        if hits:
            print(" ", pat, "->", list(hits)[:8])
