# -*- coding: utf-8 -*-
"""deals.json 数据恢复第四次（2026-10-19 上午）+ 顺带用新模板重建 index.html。

事故链：磁盘 deals.json 又被清（36 条），监控读空静默重建，
persist 把 36 条整包写回磁盘和 KV（线上也从 1.1 万瘦成 36 条）。

恢复：git 快照 52b44c5（12518 条，截至 10-18 23:27）+ 磁盘今日 36 条按 id 合并
（磁盘优先）→ 落盘 + 用 build_site 新 TPL 重建 index.html（带双11福利清单）
→ 推 KV 两遍 → 等 30s 核对磁盘是否被监控顶掉。
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import cf_kv
from build_site import build_html

DEALS_PATH = os.path.join("site", "deals.json")
SNAPSHOT_COMMIT = "52b44c5"


def main():
    with open(DEALS_PATH, encoding="utf-8") as f:
        disk = json.load(f)
    out = subprocess.run(
        ["git", "show", f"{SNAPSHOT_COMMIT}:site/deals.json"],
        capture_output=True, timeout=60)
    snap = json.loads(out.stdout.decode("utf-8"))
    print(f"磁盘 {len(disk)} 条 | git 快照 {len(snap)} 条")

    disk_ids = {str(d.get("id")) for d in disk}
    merged = list(disk) + [d for d in snap if str(d.get("id")) not in disk_ids]
    merged.sort(key=lambda x: x.get("time", ""), reverse=True)
    print(f"合并后 {len(merged)} 条 | 最新: {merged[0].get('time')}")

    with open(DEALS_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)

    # 新模板重建 index.html（内嵌最新 500 条 + 双11福利清单 tab）
    with open(os.path.join("config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    html = build_html(merged, cfg, {})
    with open(os.path.join("site", "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"index.html 已按新模板重建（{len(html)//1024}KB）")

    for i in (1, 2):
        ok, msg = cf_kv.put_deals(merged)
        print(f"KV 推送第{i}遍：{'成功' if ok else '失败'} {msg}")
        if ok:
            time.sleep(3)

    time.sleep(30)
    with open(DEALS_PATH, encoding="utf-8") as f:
        now_n = len(json.load(f))
    print(f"30 秒后磁盘核对：{now_n} 条（{'稳定 ✓' if now_n >= len(merged) else '被监控顶掉了，需重跑 ✗'}）")


if __name__ == "__main__":
    main()
