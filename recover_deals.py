# -*- coding: utf-8 -*-
"""deals.json 数据恢复（2026-10-18 第三次删除事故）。

事故链：昨天 23:30 关机时磁盘有 13142 条（git 3fc1c94 有全量快照）；
今天白天监控没跑，deals.json 又被清理工具扫走；监控 16:26 启动读到空文件，
只从今天重建出 36 条；16:37 persist 时还把种地脚本刚写的 10 条拼多多顶掉。

恢复：git 快照 13142 + 磁盘今日 40 按 id 合并（今日版优先）+ 拼多多种子 + 推 KV。
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import pdd_hdk
import cf_kv

DEALS_PATH = os.path.join("site", "deals.json")
SNAPSHOT_COMMIT = "3fc1c94"  # 昨天 23:29 最后一份全量快照
GAP_SEC = 2.5


def load_snapshot():
    out = subprocess.run(
        ["git", "show", f"{SNAPSHOT_COMMIT}:site/deals.json"],
        capture_output=True, timeout=60)
    return json.loads(out.stdout.decode("utf-8"))


def main():
    with open(DEALS_PATH, encoding="utf-8") as f:
        disk = json.load(f)
    snap = load_snapshot()
    print(f"磁盘 {len(disk)} 条 | git 快照 {len(snap)} 条")

    # 合并：今日磁盘条目优先（含今天的转链成品），快照里其余的按原顺序补回
    disk_ids = {str(d.get("id")) for d in disk}
    merged = list(disk) + [d for d in snap if str(d.get("id")) not in disk_ids]
    print(f"合并后 {len(merged)} 条")

    # 拼多多种子（当前页商品全部转链上站）
    items = pdd_hdk.fetch_items()
    have = {str(d.get("id")) for d in merged}
    added = 0
    for it in items:
        gid = str(it.get("goods_id") or "")
        did = "pdd_" + gid
        if not gid or did in have:
            continue
        try:
            link = pdd_hdk.convert_item(it.get("goods_sign") or "")
        except pdd_hdk.WhitelistError as e:
            print(f"  pdd {gid} 权限报错：{e}")
            continue
        if not link:
            print(f"  pdd {gid} 转链空链，跳过")
            time.sleep(GAP_SEC)
            continue
        deal = pdd_hdk.to_deal(it, link)
        deal["_addedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        merged.insert(0, deal)
        have.add(did)
        added += 1
        print(f"  ✓ pdd_{gid} | {str(it.get('goodsname') or '')[:22]} | {link}")
        time.sleep(GAP_SEC)
    print(f"拼多多新增 {added} 条，总计 {len(merged)} 条")

    with open(DEALS_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)

    # 推 KV：两遍，第二遍防竞态；随后等监控过一轮再核对磁盘
    for i in (1, 2):
        ok, msg = cf_kv.put_deals(merged)
        print(f"KV 推送第{i}遍：{'成功' if ok else '失败'} {msg}")
        if ok:
            time.sleep(3)

    time.sleep(20)  # 等监控走完一轮（15s 间隔），看它有没有把合并结果顶掉
    with open(DEALS_PATH, encoding="utf-8") as f:
        now_n = len(json.load(f))
    print(f"20 秒后磁盘核对：{now_n} 条（{'稳定 ✓' if now_n >= len(merged) else '被监控顶掉了，需重跑 ✗'}）")


if __name__ == "__main__":
    main()
