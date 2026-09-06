# -*- coding: utf-8 -*-
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import incremental

deals = incremental.load_json("site/deals.json", [])
print(f"载入 {len(deals)} 条准备部署")
ok = incremental.deploy(deals, "ui: 双击复制 + 补转最早两条伊利/舒客")
print("部署+推送：", "成功" if ok else "失败(稍后重试)")
