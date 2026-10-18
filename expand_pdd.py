# -*- coding: utf-8 -*-
"""拼多多扩容：商品列表 15 页 + 实时热榜三榜，全部转链上站（2026-10-18）。

Boss 问「就那么点线报吗」——10 条只是列表第 1 页。本脚本一次性把供给源
（约 180 条去重后）全部 v3 转链种进站；之后监控 poll_pdd 每轮盯前 3 页 + 三榜增量。
红线照守：转链失败的条目不入站。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import pdd_hdk
import cf_kv

DEALS_PATH = os.path.join("site", "deals.json")
PAGES = 15
GAP_SEC = 1.5  # 好单库 2000/分钟额度，1.5s 间隔已足够保守


def main():
    with open(DEALS_PATH, encoding="utf-8") as f:
        deals = json.load(f)
    have = {str(d.get("id")) for d in deals}
    print(f"现有库 {len(deals)} 条（拼多多 {sum(1 for d in deals if str(d.get('id','')).startswith('pdd_'))} 条）")

    items = pdd_hdk.collect_supply(pages=PAGES)
    print(f"供给源（{PAGES} 页列表 + 热榜三榜）去重后 {len(items)} 条")

    added = failed = 0
    for it in items:
        gid = str(it.get("goods_id") or "")
        did = "pdd_" + gid
        if not gid or did in have:
            continue
        try:
            link = pdd_hdk.convert_item(it.get("goods_sign") or "")
        except pdd_hdk.WhitelistError as e:
            print(f"  {gid} 权限报错：{e}")
            failed += 1
            continue
        if not link:
            print(f"  {gid} 转链空链，不入站")
            failed += 1
            time.sleep(GAP_SEC)
            continue
        deal = pdd_hdk.to_deal(it, link)
        deal["_addedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        deals.insert(0, deal)
        have.add(did)
        added += 1
        if added % 20 == 0:
            print(f"  … 已转 {added} 条")
        time.sleep(GAP_SEC)
    if not added:
        print("没有新增")
        return
    with open(DEALS_PATH, "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=1)
    pdd_n = sum(1 for d in deals if str(d.get("id", "")).startswith("pdd_"))
    print(f"落盘：新增 {added} 失败 {failed}，全库 {len(deals)} 条（拼多多 {pdd_n}）")
    for i in (1, 2):
        ok, msg = cf_kv.put_deals(deals)
        print(f"KV 推送第{i}遍：{'成功' if ok else '失败'} {msg}")
        if ok:
            time.sleep(3)
    # 等监控过一轮，核对磁盘没被顶掉
    time.sleep(25)
    with open(DEALS_PATH, encoding="utf-8") as f:
        now_n = len(json.load(f))
    now_pdd = sum(1 for d in json.load(open(DEALS_PATH, encoding="utf-8"))
                  if str(d.get("id", "")).startswith("pdd_"))
    print(f"25 秒后核对：磁盘 {now_n} 条 / 拼多多 {now_pdd} 条（{'稳定 ✓' if now_pdd >= pdd_n else '被顶掉需重跑 ✗'}）")


if __name__ == "__main__":
    main()
