# -*- coding: utf-8 -*-
"""只重建 site/index.html（读磁盘 deals.json + build_html 新模板），不抓取不转链。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from build_site import build_html

with open(os.path.join("site", "deals.json"), encoding="utf-8") as f:
    deals = json.load(f)
with open("config.json", encoding="utf-8") as f:
    cfg = json.load(f)
html = build_html(deals, cfg, {})
with open(os.path.join("site", "index.html"), "w", encoding="utf-8") as f:
    f.write(html)
print(f"index.html 重建完成：{len(deals)} 条内嵌前 {min(len(deals), 500)}，{len(html)//1024}KB")
