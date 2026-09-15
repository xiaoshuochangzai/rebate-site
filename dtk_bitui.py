# -*- coding: utf-8 -*-
"""大淘客【必推榜】新品监听 + 转链（Boss 2026-09-16 明令：淘宝只推必推榜新品）。

数据源（全部纯 API，不开页面、不点按钮，永不冻结）：
- 榜单：GET https://dtkapi.ffquan.cn/dtk-go-xp-bff/v1/top-ranking-list?list_type=mustRecommendList&...
  实测裸调即可用（无需 cookie），当前返回 66 条；关键字段 id/goodsid/d_title/price/
  original_price/coupon_amount/coupon_id/main_pic/add_time
- 转链：GET https://dtkapi.ffquan.cn/taobaoapi/get-privilege?p=<base64url>&referer=...&new_refer=tkzy&jaw_uid=<登录cookie>
  即页面【转链并复制】按钮背后的同一个接口，实测 0.5s/条，返回
  Tpwd（￥xxxx￥）/ TpwdNew / ShortLink / Link / ItemLink
  鉴权 jaw_uid 复用 dtk_convert._get_jaw()（浏览器 cookie，缓存 1 小时，过期自动重捞）

纪律：
- 只推「新进榜」的商品：id 与 seen_bitui.json 比对；首次运行建基线全跳过（防 66 条轰炸）
- 转不上链（无 tpwd）绝不上推送队列，下轮重试
"""
import base64
import json
import time
import urllib.parse

import requests

import dtk_convert

RANK_URL = ("https://dtkapi.ffquan.cn/dtk-go-xp-bff/v1/top-ranking-list"
            "?list_type=mustRecommendList&cid=0&is_forbid=0&only_brand=1&peer_promotion=0"
            "&start_price&end_price&start_commission&auto_choose=0&is_show_condition=1&platform=1")
PRIV_URL = "https://dtkapi.ffquan.cn/taobaoapi/get-privilege"
REFERER = "https%3A%2F%2Fwww.dataoke.com%2Ftop_bitui%3Fis_brand%3D0"
# 账号相关常量（从页面请求里抓到的，绑定到当前登录的大淘客账号）
SITE_ID = 1954293
PID = "mm_2130470034_3434000269_116316900171"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def fetch_rank():
    """拉必推榜。返回 list[dict]（精简字段）；异常返回 []。"""
    try:
        r = requests.get(RANK_URL, headers={"User-Agent": UA,
                                            "Referer": "https://www.dataoke.com/top_bitui"},
                         timeout=20)
        j = r.json()
        lst = ((j.get("data") or {}).get("list")) or []
    except Exception:
        return []
    out = []
    for it in lst:
        if not isinstance(it, dict):
            continue
        out.append({
            "id": str(it.get("id") or ""),
            "goodsid": it.get("goodsid") or it.get("goodsId") or "",
            "d_title": (it.get("d_title") or it.get("title") or "").strip(),
            "title": (it.get("title") or "").strip(),
            "price": it.get("price") or "",
            "original_price": it.get("original_price") or "",
            "coupon_amount": it.get("coupon_amount") or "",
            "coupon_id": it.get("coupon_id") or "",
            "main_pic": it.get("main_pic") or "",
            "shop_name": it.get("shop_name") or "",
            "add_time": it.get("add_time") or "",
        })
    return out


def convert_item(it):
    """转链一条榜单商品。返回 dict{tpwd, short, link, item_link}；失败返回 None。"""
    if not it.get("goodsid"):
        return None
    payload = {
        "site_id": SITE_ID,
        "pid": PID,
        "need_tpwd": 1,
        "time": int(time.time() * 1000),
        "need_short_link": 1,
        "is_auto_quan": 0,
        "need_item_link": 0,
        "gid": str(it.get("id") or ""),
        "goodsid": it["goodsid"],
        "goodsId": it["goodsid"],
        "d_title": it.get("d_title") or "",
        "quan_id": it.get("coupon_id") or "",
        "ids": str(it.get("id") or ""),
        "main_pic": it.get("main_pic") or "",
    }
    p = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode()
    p = p.replace("+", "-").replace("/", "_").rstrip("=")
    jaw = dtk_convert._get_jaw()
    url = "%s?p=%s&referer=%s&new_refer=tkzy&jaw_uid=%s" % (
        PRIV_URL, p, urllib.parse.quote(REFERER), urllib.parse.quote(jaw))
    try:
        r = requests.get(url, headers={"User-Agent": UA,
                                       "Referer": "https://www.dataoke.com/top_bitui"},
                         timeout=25)
        j = r.json()
    except Exception:
        return None
    code = str(j.get("code"))
    if code == "1000":  # 登录态过期：重捞 cookie 再试一次
        dtk_convert._refresh_jaw()
        return convert_item(it)
    if code != "1":
        return None
    d = j.get("data") or {}
    tpwd = (d.get("Tpwd") or "").strip()
    if not tpwd:
        return None
    return {
        "tpwd": tpwd,
        "tpwd_new": (d.get("TpwdNew") or "").strip(),
        "short": (d.get("ShortLink") or "").strip(),
        "link": (d.get("Link") or "").strip(),
        "item_link": (d.get("ItemLink") or "").strip(),
    }


def build_text(it, conv):
    """拼推送文案：标题 + 价格 + 淘口令 + 短链（学大淘客成品文案，不额外加装饰）。"""
    lines = [it.get("d_title") or it.get("title") or ""]
    price, orig, quan = it.get("price"), it.get("original_price"), it.get("coupon_amount")
    seg = ""
    if price:
        seg = "券后%s元" % price
    if quan:
        seg += "（券%s元" % quan
        if orig:
            seg += "，原价%s元" % orig
        seg += "）"
    elif orig:
        seg += "（原价%s元）" % orig
    if seg:
        lines.append(seg)
    lines.append(conv.get("tpwd") or "")
    if conv.get("short"):
        lines.append(conv["short"])
    return "\n".join([x for x in lines if str(x).strip()]).strip()


def to_deal(it, conv):
    """转成与淘宝线报同构的 deal（只用于推送，不进站）。"""
    body = build_text(it, conv)
    return {
        "id": "bt_" + str(it.get("id") or ""),
        "platform": "1",
        "platform_name": "淘宝",
        "cate": "大淘客必推榜",
        "time": it.get("add_time") or time.strftime("%Y-%m-%d %H:%M:%S"),
        "images": [it["main_pic"]] if it.get("main_pic") else [],
        "price": it.get("price") or "",
        "list": [{"content": body, "item_id": "", "coupon_url": ""}],
        "_originalContext": body,
        "_bitui": True,  # 标记：淘宝只推必推榜新品（keyword_push 认这个标记）
    }


if __name__ == "__main__":
    # 自检：拉榜单 → 转链第一条 → 打印成品文案（不推送、不入库）
    items = fetch_rank()
    print("必推榜 %d 条" % len(items))
    if items:
        it = items[0]
        print("样本:", it["d_title"], "| 券后", it["price"])
        t0 = time.time()
        conv = convert_item(it)
        print("转链耗时 %.1fs" % (time.time() - t0), "ok" if conv else "FAIL")
        if conv:
            print("--- 成品文案 ---")
            print(build_text(it, conv))
