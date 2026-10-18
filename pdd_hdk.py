# -*- coding: utf-8 -*-
"""好单库拼多多商品模块（2026-10-18 接入）。

数据源：get_pdd_itemlist（有券商品列表，免登录、apikey 直调，实测 10 条/页字段齐全）
转链：v3.api.haodanku.com/unify_pdditems_link（拼多多商品转链·官方高佣账号版）
  —— POST form-data，必填 apikey + itemid(=goods_sign)，实测 2026-10-18 直调即通
  （code 200，返回 short_url https://p.pinduoduo.com/xxx）。
  走好单库官方高佣通道，**不需要也没用 Boss 的多多进宝 pid**（旧 v2 get_pdditems_link
  才是「未在白名单内」，官方文档包明确推荐 v3，接口文档 id=186）。
  佣金经好单库绑定的多多进宝账号结算，订单走「拼多多订单拉取」接口。
  失败仍保留 WhitelistError 兜底（监控冷却 1h 自愈），但正常情况下用不到。

红线：没转上链的绝不上站（与京东/淘宝同规矩）。
"""
import json
import os
import re
import time
import urllib.request
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APIKEY = "9AC3C71D776A"          # 好单库开放平台（Boss 提供，应用 0 级：10万/天、2000/分钟）

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
    """v3 转推广链（官方高佣账号版）。成功返回 short_url（无则退 url）；
    权限类报错抛 WhitelistError；其它失败返回 ''。"""
    url = "https://v3.api.haodanku.com/unify_pdditems_link"
    form = urllib.parse.urlencode({"apikey": APIKEY, "itemid": goods_sign}).encode("utf-8")
    req = urllib.request.Request(url, data=form, headers=HEADERS, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception:
        return ""
    msg = str(d.get("msg") or "")
    if d.get("code") != 200:
        if "白名单" in msg or "权限" in msg:
            raise WhitelistError(msg[:80])
        return ""
    data = d.get("data") or {}
    if not isinstance(data, dict):
        return ""
    return (data.get("short_url") or data.get("url") or "").strip()


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
