# -*- coding: utf-8 -*-
"""好单库拼多多商品模块（2026-10-18 接入）。

数据源：get_pdd_itemlist（有券商品列表，免登录、apikey 直调，实测 10 条/页字段齐全）
转链：get_pdditems_link（apikey + pid + goods_sign → 推广短链）
  —— 转链需应用白名单（openapi/api_apply 申请）。未过审时本模块抛 WhitelistError，
  监控侧自动进 1 小时冷却（冷却期不抓不转），过审后下一轮自愈，无需重启监控。

红线：没转上链的绝不上站（与京东/淘宝同规矩）。
"""
import json
import os
import re
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APIKEY = "9AC3C71D776A"          # 好单库开放平台（Boss 提供，应用 0 级：10万/天、2000/分钟）
PID = "37475613_267806823"       # 多多进宝推广位（Boss 提供）

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Referer": "https://www.haodanku.com/",
}
HTTP_URL_RE = re.compile(r"https?://[^\s\"'<>\\，。；、）】]+", re.I)


class WhitelistError(Exception):
    """转链接口返回「未在白名单内」——应用还没过审。"""


def _get(url, timeout=12):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_items(page=1):
    """有券商品列表，一页 10 条。返回 list[dict]，失败返回 []。"""
    url = (f"https://v2.api.haodanku.com/get_pdd_itemlist"
           f"?apikey={APIKEY}&is_coupon=1&min_id={page}")
    try:
        d = _get(url)
        arr = d.get("data")
        if d.get("code") == 200 and isinstance(arr, list):
            return arr
    except Exception:
        pass
    return []


def convert_item(goods_sign):
    """转推广链。成功返回短链字符串；未过审抛 WhitelistError；其它失败返回 ''。"""
    url = (f"https://v2.api.haodanku.com/get_pdditems_link"
           f"?apikey={APIKEY}&pid={PID}&goods_sign={goods_sign}")
    try:
        d = _get(url)
    except Exception:
        return ""
    msg = str(d.get("msg") or "")
    if d.get("code") not in (200, 0) or msg and ("白名单" in msg):
        raise WhitelistError(msg[:80])
    # 返回结构过审后才能确认：防御式取响应里第一个 http 链接（递归找）
    found = []

    def dig(o):
        if len(found) >= 1:
            return
        if isinstance(o, str):
            m = HTTP_URL_RE.search(o)
            if m:
                found.append(m.group(0))
        elif isinstance(o, dict):
            for v in o.values():
                dig(v)
        elif isinstance(o, list):
            for v in o:
                dig(v)

    dig(d)
    return found[0] if found else ""


def to_deal(it, link):
    """转成站上 deal（platform='4'，复用京东上图下文卡片渲染）。"""
    name = str(it.get("goodsname") or "").strip()
    endp = str(it.get("itemendprice") or "").strip()
    orig = str(it.get("itemprice") or "").strip()
    coupon = str(it.get("couponmoney") or "").strip()
    pic = it.get("itempic") or ""
    lines = [name]
    if endp:
        seg = f"券后价{endp}元"
        if coupon and coupon not in ("0", "0.0"):
            seg += f"（领{coupon}元券"
            if orig:
                seg += f"，原价{orig}元"
            seg += "）"
        lines.append(seg)
    if link:
        lines.append(link)
    body = "\n".join(x for x in lines if x)
    return {
        "id": "pdd_" + str(it.get("goods_id") or it.get("goods_sign") or ""),
        "platform": "4",
        "platform_name": "拼多多",
        "cate": "",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "images": [pic] if pic else [],
        "price": orig,            # 原价（卡片划线价）
        "_couponAfterPrice": endp,  # 券后价（卡片到手价）
        "list": [{"content": body, "item_id": link, "coupon_url": "", "url": link}],
        "_originalContext": body,
        "_pdd": True,             # 标记：拼多多来源
    }


if __name__ == "__main__":
    # 自检：拉一页 → 转链第一条（不碰线上数据）
    items = fetch_items()
    print("商品页:", len(items), "条")
    if items:
        it = items[0]
        print("样本:", it.get("goodsname", "")[:30], "| 券后", it.get("itemendprice"))
        try:
            t0 = time.time()
            link = convert_item(it["goods_sign"])
            print("转链 %.1fs" % (time.time() - t0), "ok" if link else "空")
            if link:
                print("短链:", link)
                print(to_deal(it, link)["_originalContext"])
        except WhitelistError as e:
            print("转链未过审（白名单）：", e)
