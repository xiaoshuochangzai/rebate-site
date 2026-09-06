# -*- coding: utf-8 -*-
"""用精品库转链引擎补转 pending.json 里的线报，转上链的入库上线。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import incremental
import jp_convert

deals = incremental.load_json("site/deals.json", [])
pending = incremental.load_json("pending.json", [])
print(f"线上 {len(deals)} 条 | 待转队列 {len(pending)} 条", flush=True)
if not pending:
    sys.exit(0)

out, stats = jp_convert.convert_all_browser(pending)
print("补转结果:", stats, flush=True)

ok_ids = {str(d["id"]) for d in pending
          if d.get("_originalContext") or any(it.get("converted") for it in d.get("list", []))}
still = [d for d in pending if str(d["id"]) not in ok_ids]
for d in pending:
    if str(d["id"]) in ok_ids and not any(str(x.get("id")) == str(d["id"]) for x in deals):
        deals.insert(0, d)

incremental.save_json("site/deals.json", deals)
incremental.save_json("pending.json", still)
print(f"上线 {len(ok_ids)} 条 | 仍未转 {len(still)} 条", flush=True)
ok = incremental.deploy(deals, "fix: 精品库转链补齐待转队列")
print("部署:", "成功" if ok else "失败", flush=True)
