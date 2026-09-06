# -*- coding: utf-8 -*-
"""补转所有未转上链的线报（8 秒间隔），完成自动部署。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["JD_CONV_DELAY"] = "8"
import incremental
import jd_convert_browser as jc

deals = incremental.load_json("site/deals.json", [])
pending = [d for d in deals if not any(it.get("converted") for it in d.get("list", []))]
print(f"共 {len(deals)} 条，未转上链 {len(pending)} 条: {[d['id'] for d in pending]}", flush=True)
if pending:
    out, stats = jc.convert_all_browser(pending)
    print("补转结果:", stats, flush=True)
    incremental.save_json("site/deals.json", deals)
    ok = incremental.deploy(deals, "fix: 补转未转线报")
    print("部署:", "成功" if ok else "失败", flush=True)
else:
    print("无需补转", flush=True)
