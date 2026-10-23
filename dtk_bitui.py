# -*- coding: utf-8 -*-
"""大淘客【必推榜】新品监听 + 转链（Boss 2026-09-16 明令：淘宝只推必推榜新品）。

2026-10-13 扩展：Boss 明令淘宝新增热销榜（top_sell）+ 热推榜（top_tui），
三榜一起监听，跨榜去重（同商品三榜共用 dataoke 商品 id，进过一榜就不再推）。

数据源（全部纯 API，不开页面、不点按钮，永不冻结）：
- 必推榜：GET .../dtk-go-xp-bff/v1/top-ranking-list?list_type=mustRecommendList&...（66 条）
- 热销榜：GET .../dtk-go-xp-bff/v1/top-sell?platform=1&is_set=0&...（实测 200 条/页）
- 热推榜：GET .../dtk-go-xp-bff/v1/top-hot?platform=1&is_set=0&...（实测 100 条/页）
  三榜字段完全同名：id/goodsid/d_title/title/price/original_price/coupon_amount/
  coupon_id/main_pic/add_time —— fetch/convert/build 全链路复用
  （注：top-sell/top-hot 的 data 可能直接是 list 而非 {list:[...]}，已做兼容）
- 转链：GET https://dtkapi.ffquan.cn/taobaoapi/get-privilege?p=<base64url>&referer=...&new_refer=tkzy&jaw_uid=<登录cookie>
  即页面【转链并复制】按钮背后的同一个接口，实测 0.5s/条，返回
  Tpwd（￥xxxx￥）/ TpwdNew / ShortLink / Link / ItemLink
  鉴权 jaw_uid 复用 dtk_convert._get_jaw()（浏览器 cookie，缓存 1 小时，过期自动重捞）

纪律：
- 只推「新进榜」的商品：id 与 seen_bitui.json 比对（三榜共享，跨榜去重）；
  首次运行建基线全跳过（防一次性轰炸）
- 转不上链（无 tpwd）绝不上推送队列，下轮重试
"""
import base64
import json
import time
import urllib.parse

import requests

import dtk_convert

_BFF = "https://dtkapi.ffquan.cn/dtk-go-xp-bff/v1"
PRIV_URL = "https://dtkapi.ffquan.cn/taobaoapi/get-privilege"

# 三榜配置：kind -> (榜单URL, referer, 分类名, deal id 前缀)；RANK_ORDER 为轮询顺序
RANKS = {
    "bitui": (
        _BFF + "/top-ranking-list?list_type=mustRecommendList&cid=0&is_forbid=0"
               "&only_brand=1&peer_promotion=0&start_price&end_price&start_commission"
               "&auto_choose=0&is_show_condition=1&platform=1",
        "https://www.dataoke.com/top_bitui",
        "大淘客必推榜",
        "bt_",
    ),
    "sell": (
        _BFF + "/top-sell?platform=1&is_set=0&cid=0&page=1&size=120&is_brand=0",
        "https://www.dataoke.com/top_sell",
        "大淘客热销榜",
        "ts_",
    ),
    "tui": (
        _BFF + "/top-hot?platform=1&is_set=0&cid=0&page=1&size=100&is_brand=1",
        "https://www.dataoke.com/top_tui",
        "大淘客热推榜",
        "tt_",
    ),
    # 2小时热销榜（top_sell2 页面）：2026-10-23 接入，Boss 明令双11期间**只推外部群**、
    # 不进主群。同一个 top-sell 接口，type=2h_new（CDP 实扒页面请求）。
    # 注意：不加入 RANK_ORDER（三榜照旧走主群链路），由 incremental.poll_sell2 单独处理。
    "sell2": (
        _BFF + "/top-sell?type=2h_new&cid=0&only_brand=0&list_hidden=0&is_forbid=0"
               "&rank_rise=0&newly_listed=0&peer_promotion=0&page=1&size=120&platform=1",
        "https://www.dataoke.com/top_sell2?v=2",
        "大淘客2小时热销榜",
        "s2_",
    ),
}
RANK_ORDER = ("bitui", "sell", "tui")
# 双11 时间窗：外部群淘宝线报换成 2小时热销榜（Boss 2026-10-23 明令），含当天；
# 过期后自动恢复原样（主群淘宝照旧同步外部群、2h 榜停推），无需人工干预
SELL2_UNTIL = "2026-11-13"


def sell2_active():
    """双11 时间窗开关：当前日期 <= SELL2_UNTIL 视为活动期。"""
    try:
        return time.strftime("%Y-%m-%d") <= SELL2_UNTIL
    except Exception:
        return False
# 账号相关常量（从页面请求里抓到的，绑定到当前登录的大淘客账号）
SITE_ID = 1954293
PID = "mm_2130470034_3434000269_116316900171"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def fetch_rank(kind="bitui"):
    """拉指定榜单（bitui/sell/tui）。返回 list[dict]（精简字段）；异常返回 []。"""
    url, referer, _, _ = RANKS[kind]
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Referer": referer}, timeout=20)
        j = r.json()
        d = j.get("data")
        if isinstance(d, dict):
            lst = d.get("list") or []
        elif isinstance(d, list):
            lst = d
        else:
            lst = []
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
            "_kind": kind,  # 供 convert/to_deal 取对应 referer/分类名/前缀
        })
    return out


def convert_item(it):
    """转链一条榜单商品。返回 dict{tpwd, short, link, item_link}；失败返回 None。
    2026-10-13 起：优先品带超红通路（parse-tb-multiple-new supered=1，口令带超级红包会场），
    异常/没转出自动退回 get-privilege 老通路。"""
    if not it.get("goodsid"):
        return None
    # 品带超红通路：商品链接进 → 带超级红包的口令出（红包订单分成90%）
    try:
        x = dtk_convert.direct_convert_super(
            "https://item.taobao.com/item.htm?id=%s" % it["goodsid"])
        if x and x.get("_super_tpwd"):
            return {
                "tpwd": x["_super_tpwd"],
                "tpwd_new": "",
                "short": x.get("_super_url") or "",
                "link": "",
                "item_link": "",
                "_supered": True,  # 标记：这条口令带了超红
            }
    except Exception:
        pass
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
    referer = RANKS[it.get("_kind") or "bitui"][1]
    url = "%s?p=%s&referer=%s&new_refer=tkzy&jaw_uid=%s" % (
        PRIV_URL, p, urllib.parse.quote(referer, safe=""), urllib.parse.quote(jaw))
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
    # Boss 2026-10-12 明令：取消 s.click 短链（PID 明文易被扒），只留淘口令
    return "\n".join([x for x in lines if str(x).strip()]).strip()


def to_deal(it, conv):
    """转成与淘宝线报同构的 deal（只用于推送，不进站）。"""
    body = build_text(it, conv)
    kind = it.get("_kind") or "bitui"
    _, _, cate, prefix = RANKS[kind]
    return {
        "id": prefix + str(it.get("id") or ""),
        "platform": "1",
        "platform_name": "淘宝",
        "cate": cate,
        "time": it.get("add_time") or time.strftime("%Y-%m-%d %H:%M:%S"),
        "images": [it["main_pic"]] if it.get("main_pic") else [],
        "price": it.get("price") or "",
        "list": [{"content": body, "item_id": "", "coupon_url": ""}],
        "_originalContext": body,
        "_bitui": True,  # 标记：淘宝只推三榜新品（keyword_push 认这个标记）
    }


if __name__ == "__main__":
    # 自检：三榜各拉一轮 → 转链第一条 → 打印成品文案（不推送、不入库）
    for kind in RANK_ORDER:
        items = fetch_rank(kind)
        print("%s %d 条" % (RANKS[kind][2], len(items)))
        if items:
            it = items[0]
            print("样本:", it["d_title"], "| 券后", it["price"])
            t0 = time.time()
            conv = convert_item(it)
            print("转链耗时 %.1fs" % (time.time() - t0), "ok" if conv else "FAIL")
            if conv:
                print("--- 成品文案 ---")
                print(build_text(it, conv))
        print()
