# -*- coding: utf-8 -*-
"""拼多多种子：把 get_pdd_itemlist 当前页商品转链后种进站（2026-10-18）。

背景：poll_pdd 首跑误建基线（照搬淘宝必推榜防炸群逻辑），现页 10 条全跳过，
而监控内存已缓存 seen，改代码也救不回这 10 条——只能手动转链种入。
监控每轮从磁盘重载 deals.json，pdd_ id 进 have_ids 后不会重复转链，无冲突。
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
GAP_SEC = 2.5  # 条间间隔（好单库 2000/分钟，2.5s 已非常保守）


def main():
    with open(DEALS_PATH, encoding="utf-8") as f:
        deals = json.load(f)
    have = {str(d.get("id")) for d in deals}
    items = pdd_hdk.fetch_items()
    print(f"商品页 {len(items)} 条；现有库 {len(deals)} 条")
    added, failed = 0, 0
    for it in items:  # 列表顺序=热度序，反插让第一名排最顶
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
            print(f"  {gid} 转链失败（空链），不入站")
            failed += 1
            time.sleep(GAP_SEC)
            continue
        deal = pdd_hdk.to_deal(it, link)
        deal["_addedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        deals.insert(0, deal)
        have.add(did)
        added += 1
        print(f"  ✓ pdd_{gid} | {str(it.get('goodsname') or '')[:24]} | {link}")
        time.sleep(GAP_SEC)
    if not added:
        print("没有新增，不落盘不推 KV")
        return
    with open(DEALS_PATH, "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=1)
    print(f"已落盘：新增 {added} 条，失败 {failed} 条，全库 {len(deals)} 条")
    # 推 KV 两遍（第二遍防与监控 persist 撞车的极端时序）
    for i in (1, 2):
        ok, msg = cf_kv.put_deals(deals)
        print(f"KV 推送第{i}遍：{'成功' if ok else '失败'} {msg}")
        if ok and i == 1:
            time.sleep(3)


if __name__ == "__main__":
    main()
