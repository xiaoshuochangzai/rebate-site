# -*- coding: utf-8 -*-
"""京东低价好物（折京客 API）—— Boss 2026-11-12 拍板执行。

口径：券后价 3~60 元 + 佣金比例>=10% + 月销量>=1000（qualifies 统一把关，本地再校验）；
      同款不同链接只留一条（标题前10字分组留最低价）。
数据源（三个官方榜单，全站裸库已去掉）：自营热卖榜(eliteId=41)、超高佣金(commission_rate_start=50)、超高销量(sale_num_start=10000)。
展示排序：每 2 条 <20 元 穿插 2 条 >=20 元，组内按销量降序，剩余组降序补齐。
每 3 小时一轮（对齐北京时间 8/11/14/17/20/23 点整，Boss 2026-11-12 明令）：
  1. 分页拉全量（price=0.0-60 & commission_rate_start=10 & sale_num_start=1000）
  2. 镜像：以本轮源站命中 tao_id 集合为准，本地只保留集合内条目 —— 源站消失本站跟着下架，
     不做 7 天清空。源站拉空/失败本轮跳过不清空（防一次抖动误删全站）。
  3. 仅新出现的商品调折京客官方京东转链 API（item_url → u.jd.com 短链），
     转不上链的绝不上站（红线），失败下轮重试；已有链接走缓存复用。
  4. 落盘 site/lowprice_jd.json + KV key "lowprice_jd"（前端 /api/lowprice_jd 实时读）。

凭证在 ztk_config.json（.gitignore，绝不提交）；appkey 可用环境变量 ZTK_APPKEY 覆盖。
自检：python lowprice_jd_auto.py --once --limit 3 --dry （只转 3 条，不落盘不写 KV）
全量：python lowprice_jd_auto.py --once
"""
import json
import os
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(BASE_DIR, "ztk_config.json")
OUT = os.path.join(BASE_DIR, "site", "lowprice_jd.json")
CACHE = os.path.join(BASE_DIR, "lp_jd_conv_cache.json")
API_BASE = "http://api.zhetaoke.com:20000/api/"
API_ALL = API_BASE + "api_all.ashx"
API_CONV = API_BASE + "open_jing_union_open_promotion_byunionid_get.ashx"
API_JINGFEN = API_BASE + "open_jing_union_open_goods_jingfen_query.ashx"
CHANNEL_ID = 41        # 20032 页面「自营热卖榜」对应折京客京粉精选频道 eliteId=41
SPLIT_PRICE = 20.0     # Boss 2026-11-12：低价组 <20 元 / 高价组 >=20 元
MAX_PRICE = 60.0
MIN_PRICE = 3.0         # Boss 2026-11-12 明令：券后价 >=3 元（0.01/1元 那种凑单例剔除）
MIN_RATE = 10.0
MIN_SALES = 1000
PAGE_SIZE = 50
MAX_PAGES = 60
LOOP_SEC = 3 * 3600   # Boss 2026-11-12 明令：每 3 小时全量覆盖一次（原 10 分钟；epoch 对齐→北京 8/11/14/17/20/23 点整）
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"

# ---- 京东联盟 20033（超级补贴/热卖清单）活动：券商品先行（Boss 2026-11-12 拍板）----
# 转链死结（数字id/裸链/好单库代理/官方API权限）全部被「单品自带 coupon.m.jd.com 券链接
# → 折京客零成本转 u.jd.com」绕过。数据源 = 20033 活动页底层 unionSearchRecommend 接口，
# 经 9222 专用浏览器拦截页面自身请求抓取（注入直调会被京东 403 反爬拦截）。
JD20033_URL = "https://jingfen.jd.com/item?u_act_p=union-activity&union_page_id=20033"
CDP_PORT = 9222
IMG_BASE = "https://img14.360buyimg.com/"   # 20033 的 imageUrl 是相对 jfs 路径，需补域名
MAX_20033_SCROLL = 20                        # 活动约 17 页（326 商品），多留余量


def _log(msg):
    print("[%s] 京东低价好物：%s" % (time.strftime("%H:%M:%S"), msg))


def _conf():
    c = json.load(open(CONF, encoding="utf-8"))
    c["appkey"] = os.environ.get("ZTK_APPKEY") or c["appkey"]
    return c


def _session():
    import requests
    s = requests.Session()
    s.trust_env = False  # 本机代理残留会让直连超时（Boss 环境坑）
    s.headers["User-Agent"] = UA
    return s


def _load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def fetch_api_all(extra, label, log=_log):
    """数据源①②：api_all 全站库 + 参数组合（官方榜单即不同参数：超高佣金/超高销量）。
    失败返回空 dict。"""
    c = _conf()
    s = _session()
    out = {}
    base = {"appkey": c["appkey"], "page": 0, "page_size": PAGE_SIZE,
            "sort": "sale_num_desc", "price": "3.0-60"}
    base.update(extra)
    for page in range(1, MAX_PAGES + 1):
        p = dict(base); p["page"] = page
        try:
            r = s.get(API_ALL, params=p, timeout=25)
            j = r.json()
        except Exception as e:
            log("第%d页请求异常：%s" % (page, str(e)[:60]))
            return {}
        if str(j.get("status")) != "200":
            # 翻到底的正常信号：status=301 / content='无符合条件的数据'
            if str(j.get("status")) == "301" or "无符合条件" in str(j.get("content")):
                break
            log("第%d页返回异常：%s" % (page, str(j)[:80]))
            return {}
        lst = j.get("content") or []
        for it in lst:
            gid = str(it.get("tao_id") or "")
            if gid and gid not in out:
                out[gid] = it
        if len(lst) < PAGE_SIZE:
            break
        time.sleep(0.2)
    log("%s：%d 条（%d 页）" % (label, len(out), page))
    return out


def fetch_channel(log=_log):
    """数据源②：20032 页面「自营热卖榜」= 折京客京粉精选频道 eliteId=41。
    映射成与 api_all 同形字段；失败/返回 0 条返回 None（整轮跳过，防镜像误删）。"""
    c = _conf()
    s = _session()
    out = {}
    for page in range(1, 40):
        p = {"appkey": c["appkey"], "unionId": c.get("unionId", ""),
             "eliteId": CHANNEL_ID, "pageIndex": page, "pageSize": 20}
        try:
            j = s.get(API_JINGFEN, params=p, timeout=25).json()
            inner = (j.get("jd_union_open_goods_jingfen_query_response") or {}).get("result")
            x = json.loads(inner) if isinstance(inner, str) else (inner or {})
            rows = x.get("data") or []
        except Exception as e:
            log("频道第%d页异常：%s" % (page, str(e)[:60]))
            return None
        if str(x.get("code")) not in ("200", "0"):
            log("频道第%d页返回异常：%s" % (page, str(x)[:80]))
            return None
        for g in rows:
            gid = str(g.get("itemId") or g.get("skuId") or "")
            if not gid:
                continue
            pi = g.get("priceInfo") or {}
            ci = g.get("commissionInfo") or {}
            img = ((g.get("imageInfo") or {}).get("imageList") or [{}])[0].get("url") or ""
            cl = (g.get("couponInfo") or {}).get("couponList") or []
            cp = cl[0] if cl else {}
            mu = str(g.get("materialUrl") or "")
            if mu and not mu.startswith("http"):
                mu = "https://" + mu.lstrip("/")
            end = ""
            try:
                et = cp.get("endTime") or cp.get("useEndTime")
                if et:
                    end = time.strftime("%Y-%m-%d", time.localtime(float(et) / 1000))
            except Exception:
                pass
            out["ch_" + gid] = {
                "tao_id": "ch_" + gid,
                "title": g.get("skuName") or "",
                "quanhou_jiage": pi.get("lowestCouponPrice") or pi.get("price") or 0,
                "tkrate3": ci.get("commissionShare") or 0,
                "volume": g.get("inOrderCount30Days") or g.get("inOrderCount30DaysSku") or 0,
                "item_url": mu,
                "coupon_info_money": cp.get("discount") or cp.get("quota") or 0,
                "coupon_end_time": end,
                "pict_url": img,
                "size": pi.get("price") or 0,
            }
        if len(rows) < 20:
            break
        time.sleep(0.2)
    if not out:
        log("频道返回 0 条，视为异常（本轮跳过不清空）")
        return None
    log("20032 自营热卖榜频道 %d 条（%d 页）" % (len(out), page))
    return out


def parse_20033_response(j):
    """从 unionSearchRecommend 响应 JSON 抽出 goodsSynopsisList（兼容多层嵌套）。"""
    if not isinstance(j, dict):
        return []
    lst = (j.get("result") or {}).get("goodsSynopsisList")
    if lst:
        return lst
    def _find(o, key="goodsSynopsisList"):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == key and isinstance(v, list):
                    return v
                r = _find(v, key)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = _find(v, key)
                if r:
                    return r
        return None
    return _find(j) or []


def _norm_coupon(url):
    url = (url or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    return url


def _best_coupon(it):
    """抽最佳可转链券：优先 unionCouponList（与 purchasePrice 严格一致），
    否则在 otherCouponList 中选折扣最大且合理（discount>=1 且 < 门槛价）的券做最佳估计。
    返回 (couponUrl, discount, price_after, end_time) 或 None（破价品/无可用券）。"""
    ppi = it.get("purchasePriceInfo") or {}
    uc = (ppi.get("unionCouponList") or []) if isinstance(ppi, dict) else []
    oc = it.get("otherCouponList") or []
    threshold = float(ppi.get("thresholdPrice") or it.get("wlPrice") or 0)
    promo = float(ppi.get("promotionBenefit") or 0)
    purchase_price = ppi.get("purchasePrice")
    if uc:
        c0 = uc[0]
        url = _norm_coupon(c0.get("couponUrl"))
        disc = float(ppi.get("couponBenefit") or 0)
        price = float(purchase_price) if purchase_price is not None else (threshold - disc)
        end = str(c0.get("endTime") or "").strip()
        return (url, disc, price, end)
    # 无 union 券 → 在 other 券里挑最大且合理的（破价/无券则 None）
    best = None
    for c in oc:
        try:
            d = float(c.get("discount") or 0)
        except Exception:
            d = 0
        if d < 1 or (threshold and d >= threshold):
            continue
        end = str(c.get("endTime") or c.get("useEndTime") or "").strip()
        cand = (_norm_coupon(c.get("couponUrl")), d, max(0.0, threshold - d - promo), end)
        if best is None or d > best[1]:
            best = cand
    return best


def build_20033_items(raw_list, log=_log):
    """把 unionSearchRecommend 原始商品映射成与 api_all 同形 dict。
    破价品（无可用券）跳过；tao_id 用 jd2_ 前缀避免与 api_all 的 tao_id 碰撞。"""
    out, n_skip = {}, 0
    for it in (raw_list or []):
        sku = str(it.get("skuId") or "").strip()
        if not sku:
            continue
        coupon = _best_coupon(it)
        if not coupon or not coupon[0]:
            n_skip += 1
            continue
        url, disc, price, end = coupon
        img = str(it.get("imageUrl") or "").strip()
        if img and not img.startswith("http"):
            img = IMG_BASE + img
        gid = "jd2_" + sku
        out[gid] = {
            "tao_id": gid,
            "title": str(it.get("skuName") or "").strip(),
            "quanhou_jiage": price,
            "tkrate3": 0,            # 20033 联盟佣金比例未知，展示 0 不误导；实际佣金由转链后链接携带
            "volume": it.get("inOrderCount30Days") or 0,
            "item_url": url,         # 券链接（完整 URL，折京客不拦）
            "coupon_info_money": disc,
            "coupon_end_time": end,
            "pict_url": img,
            "size": float((it.get("purchasePriceInfo") or {}).get("thresholdPrice") or it.get("wlPrice") or 0),
            "_src": "20033",
        }
    log("20033 建项：可用券商品 %d 条，破价/无券跳过 %d 条" % (len(out), n_skip))
    return out


def load_offline_20033(log=_log):
    """离线种子：读 jd20033_bodies/ 下已抓回的 unionSearchRecommend 响应体，
    抽出可用商品。实时通道（登录态有效时）能拿更多/更新，但离线种子保证
    即使 9222 浏览器没登录 jingfen 会话、被登录墙拦截，20033 精选也永远有货。"""
    import glob as _gl
    raws = []
    d = os.path.join(BASE_DIR, "jd20033_bodies")
    for fn in sorted(_gl.glob(os.path.join(d, "resp*.json"))):
        try:
            txt = open(fn, encoding="utf-8").read().split("\n\n", 1)
            j = json.loads(txt[1] if len(txt) > 1 else txt[0])
            raws.extend(parse_20033_response(j))
        except Exception:
            pass
    log("20033 离线种子：%d 条（jd20033_bodies）" % len(raws))
    return raws


def fetch_20033_cdp(log=_log):
    """连 9222 浏览器里的 20033 活动页 tab，Network 拦截其自身 unionSearchRecommend
    分页请求（滚动到底触发），抓取商品。

    关键前置：jingfen.jd.com 活动页要求移动端 JD 登录态，专用 .jd-bot-profile
    只有 union.jd.com 会话 → 未登录时页面重定向到 plogin.m.jd.com 登录墙，
    此时直接跳过（返回 []），由离线种子兜底，绝不卡主流程。
    已登录时：真实滚轮触发 Taro scroll-view 的 onScrollToLower（加载守卫需
    每次等待释放，故每轮滚完等 2.5s），逐步翻完所有页。
    无浏览器/无 tab/异常 → 优雅返回 []，由全站库兜底。"""
    try:
        import websocket
        import urllib.request as _ur
        OP = _ur.build_opener(_ur.ProxyHandler({}))
        try:
            tabs = json.loads(OP.open("http://127.0.0.1:%d/json/list" % CDP_PORT, timeout=5).read())
        except Exception as e:
            log("20033：9222 浏览器未响应（%s），跳过，仅离线种子兜底" % str(e)[:40])
            return []
        tab = next((t for t in tabs if "union_page_id=20033" in (t.get("url") or "")), None)
        if not tab:
            jt = next((t for t in tabs if t.get("type") == "page" and "jd.com" in (t.get("url") or "")), None)
            if not jt:
                log("20033：无可用 jd 标签，跳过")
                return []
            tab = jt
        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=60)
        _id = [0]
        def send(m, p=None):
            _id[0] += 1
            ws.send(json.dumps({"id": _id[0], "method": m, "params": p or {}}))
            return _id[0]
        def recv(i, timeout=30):
            ws.settimeout(timeout)
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == i:
                    return m
                if m.get("id", 0) > i:
                    return {}
        send("Network.enable"); send("Page.enable"); send("Input.enable")
        # 重载到 20033 页
        send("Page.navigate", {"url": JD20033_URL})
        time.sleep(5)
        # 登录墙检测：未登录会 302 到 plogin.m.jd.com
        chk = send("Runtime.evaluate", {"expression": "location.href", "returnByValue": True})
        hr = recv(chk, 10)
        cur_url = (hr.get("result", {}).get("result", {}) or {}).get("value", "") or ""
        if "plogin.m.jd.com" in cur_url or "login" in cur_url:
            log("20033：检测到登录墙（jingfen 会话缺失），跳过实时抓取，回退离线种子")
            ws.close()
            return []
        reqs, bodies, no_new = {}, {}, 0
        # 先来一脚滚轮触发首屏加载
        send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 700, "y": 450,
                                          "deltaX": 0, "deltaY": 2000, "modifiers": 0})
        time.sleep(2)
        for _ in range(MAX_20033_SCROLL):
            send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 700, "y": 450,
                                              "deltaX": 0, "deltaY": 4000, "modifiers": 0})
            deadline = time.time() + 2.5   # 等加载守卫释放，避免 onScrollToLower 被吞
            got = 0
            while time.time() < deadline:
                try:
                    ws.settimeout(max(0.3, deadline - time.time()))
                    m = json.loads(ws.recv())
                except Exception:
                    break
                meth = m.get("method", ""); p = m.get("params", {})
                if meth == "Network.responseReceived":
                    r = p.get("response", {}); u = r.get("url", "")
                    if "unionSearchRecommend" in u and r.get("status") == 200:
                        reqs[p["requestId"]] = u
                elif meth == "Network.loadingFinished":
                    rid = p.get("requestId")
                    if rid in reqs and rid not in bodies:
                        i2 = send("Network.getResponseBody", {"requestId": rid})
                        rb = recv(i2, 12)
                        b = (rb.get("result") or {})
                        body = b.get("body", "")
                        if b.get("base64Encoded"):
                            import base64
                            body = base64.b64decode(body).decode("utf-8", "ignore")
                        bodies[rid] = body
                        try:
                            got += len(parse_20033_response(json.loads(body)))
                        except Exception:
                            pass
            no_new = 0 if got else no_new + 1
            if no_new >= 4:
                break
        all_items = []
        for rid, body in bodies.items():
            try:
                all_items.extend(parse_20033_response(json.loads(body)))
            except Exception:
                pass
        ws.close()
        log("20033 CDP 实时抓取：%d 个分页响应 / %d 商品（去重前）" % (len(bodies), len(all_items)))
        return all_items
    except Exception as e:
        log("20033 CDP 异常（跳过，仅离线种子兜底）：%s" % str(e)[:80])
        return []


def fetch_all(log=_log):
    """Boss 2026-11-12 15:14 明令：撤三榜单组合，只用全站领券商品库。
    三条件一次筛：券后 3~60 元 + 佣金≥10% + 月销量≥1000（参数直接下推）。"""
    return fetch_api_all({"price": "3.0-60", "commission_rate_start": 10,
                          "sale_num_start": 1000}, "全站领券商品库", log)


def interleave(items, log=_log):
    """Boss 2026-11-12：每 2 条 <20 元 穿插 2 条 >=20 元；
    两组内部各自按销量降序，某组取完后剩余另一组按销量降序依次补齐（反之亦然）。"""
    def sales(x):
        try:
            return float(x.get("sales30") or 0)
        except Exception:
            return 0.0
    def price(x):
        try:
            return float(x.get("price") or 0)
        except Exception:
            return 0.0
    # 组内 20033（活动精选）优先排前，再按销量降序 —— 落实「20033主+全站库兜底」
    def _key(x):
        return (0 if x.get("_src") == "20033" else 1, -sales(x))
    low = sorted([x for x in items if price(x) < SPLIT_PRICE], key=_key)
    high = sorted([x for x in items if price(x) >= SPLIT_PRICE], key=_key)
    out, i, j = [], 0, 0
    while i < len(low) or j < len(high):
        for _ in range(2):
            if i < len(low):
                out.append(low[i]); i += 1
        for _ in range(2):
            if j < len(high):
                out.append(high[j]); j += 1
    log("穿插排序：低价组(<20) %d 条 / 高价组(>=20) %d 条" % (len(low), len(high)))
    return out


def _variant_key(t):
    """同款归一键：去掉空白/标点后取标题前 10 字（与轮动池 _variant_key 同口径）。"""
    import re
    s = re.sub(r"[\s【】\[\]（）()!！,，。.:：;；\"'“”‘’\-—_/|｜＋+]", "", str(t or ""))
    return s[:10]


def qualifies(it):
    try:
        price = float(it.get("quanhou_jiage") or 0)
    except Exception:
        return False
    # 20033 券商品：Boss 明令只卡价 3~60 + 券未过期，不卡佣金/销量（活动精选本就优质）
    if it.get("_src") == "20033":
        if not (MIN_PRICE <= price <= MAX_PRICE):
            return False
    else:
        rate = float(it.get("tkrate3") or 0)
        sales = float(it.get("volume") or 0)
        if not (MIN_PRICE <= price <= MAX_PRICE and rate >= MIN_RATE and sales >= MIN_SALES):
            return False
    # 券已过期的不上站（dadongke 旧券教训）
    end = str(it.get("coupon_end_time") or "").strip()
    if end:
        try:
            t = time.mktime(time.strptime(end[:10].replace("/", "-"), "%Y-%m-%d"))
            if t < time.time() - 86400:
                return False
        except Exception:
            pass
    return True


def convert_one(it, log=_log):
    """调折京客官方京东转链，返回 u.jd.com 短链；失败/非短链返回 ''。"""
    c = _conf()
    mid = str(it.get("item_url") or it.get("tao_id") or "").strip()
    if not mid:
        return ""
    p = {"appkey": c["appkey"], "materialId": mid,
         "unionId": c.get("unionId", ""), "chainType": c.get("chainType", 2)}
    try:
        j = _session().get(API_CONV, params=p, timeout=25).json()
        inner = (j.get("jd_union_open_promotion_byunionid_get_response") or {}).get("result")
        d = json.loads(inner) if isinstance(inner, str) else (inner or {})
        u = str((d.get("data") or {}).get("shortURL") or "").strip()
    except Exception as e:
        log("转链异常 %s：%s" % (str(it.get("tao_id"))[:12], str(e)[:60]))
        return ""
    # 红线：必须是绑定我们联盟的 u.jd.com 短链
    if not u or "u.jd.com" not in u:
        return ""
    return u


def to_item(it, link):
    """映射成 lpCard 同形字段（t/price到手/quan券额/oprice原价/pic/link）。"""
    def n(v):
        try:
            f = float(v or 0)
            return ("%.2f" % f).rstrip("0").rstrip(".")
        except Exception:
            return "0"
    return {
        "id": str(it.get("tao_id") or ""),
        "t": str(it.get("title") or it.get("tao_title") or "").strip(),
        "price": n(it.get("quanhou_jiage")),     # 到手价（券后）
        "quan": n(it.get("coupon_info_money")),  # 券额
        "oprice": n(it.get("size") or it.get("quanhou_jiage")),  # 折扣价/原价
        "pic": str(it.get("pict_url") or ""),
        "link": link,
        "sales30": it.get("volume") or 0,        # 月销量
        "rate": it.get("tkrate3") or 0,          # 佣金比例
        "_p": "jd",
    }


def run_once(log=_log, limit=None, dry=False, src20033=None):
    raw = fetch_all(log)
    if not raw:
        log("源站返回空/失败，本轮跳过（不清空，防误删）")
        return -1
    # 20033 券商品（活动精选，主推）。
    # 实时通道（浏览器已登录 jingfen 会话）拿全量最新；离线种子（jd20033_bodies）
    # 保证即使登录墙拦截/无浏览器也永远有货。两者按 skuId 合并，实时覆盖离线。
    if src20033 is None:
        live = fetch_20033_cdp(log)
        offline = load_offline_20033(log)
        src20033 = offline + (live or [])
    raw20033 = build_20033_items(src20033, log) if src20033 else {}
    # 合并：jd2_ 主键不撞全站库 tao_id；写入时 20033 覆盖同名键（同款去重再裁决）
    merged = dict(raw)
    merged.update(raw20033)
    target = {g: it for g, it in merged.items() if qualifies(it)}
    if not target:
        log("本轮无命中商品，跳过（不清空，防误删）")
        return -1
    # Boss 2026-11-12 明令：同商品不同链接只留一条 —— 按标题前10字分组，
    # 每组只保留券后价最低的那条；价格相同则 20033（活动精选）优先。
    best = {}
    for gid, it in target.items():
        k = _variant_key(it.get("title") or it.get("tao_title")) or ("id:" + gid)
        try:
            p = float(it.get("quanhou_jiage") or 0)
        except Exception:
            p = 0.0
        cur = best.get(k)
        if cur is None or p < cur[2] - 1e-9 or (abs(p - cur[2]) < 1e-9 and it.get("_src") == "20033"):
            best[k] = (gid, it, p)
    n_dup = len(target) - len(best)
    target = {gid: it for gid, it, _p in best.values()}
    log("同款归一：合并 %d 条变体（含 20033 %d 条），剩 %d 条" % (n_dup, len(raw20033), len(target)))
    cache = _load(CACHE, {})
    old_items = {str(x.get("id")): x for x in (_load(OUT, {}).get("items") or [])}
    ordered = sorted(target.items(), key=lambda kv: float(kv[1].get("volume") or 0), reverse=True)
    if limit:
        ordered = ordered[:limit]
    out_items, n_new, n_fail = [], 0, 0
    for gid, it in ordered:
        link = cache.get(gid) or (old_items.get(gid) or {}).get("link") or ""
        if not link:
            link = convert_one(it, log)
            if link:
                cache[gid] = link
                n_new += 1
            else:
                n_fail += 1
                if (old_items.get(gid) or {}).get("link"):
                    out_items.append(old_items[gid])  # 转链失败但本地有旧卡：保留防闪烁
                continue
            time.sleep(0.25)  # 礼貌间隔，别把免费接口刷爆
        out_items.append(to_item(it, link))
    if dry:
        log("自检：命中 %d 条，试转 %d 条 → 成功 %d / 失败 %d（未落盘未写KV）"
            % (len(target), len(ordered), n_new, n_fail))
        for x in out_items[:3]:
            log("  样例：%s | 到手%s | 佣%s%% | 月销%s | %s"
                % (x["t"][:20], x["price"], x["rate"], x["sales30"], x["link"]))
        return 0
    if limit:
        log("限量模式不落盘（防止冲掉全量数据）")
        return 0
    out_items = interleave(out_items, log)
    obj = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "total": len(out_items), "items": out_items}
    _save(OUT, obj)
    for g in list(cache):
        if g not in target:
            cache.pop(g, None)
    _save(CACHE, cache)
    try:
        import cf_kv
        ok, msg = cf_kv.put_value("lowprice_jd", obj)
        log("落盘+KV %s（%d 条，新转 %d / 失败 %d）%s"
            % ("OK" if ok else "FAIL", len(out_items), n_new, n_fail, "" if ok else str(msg)[:60]))
    except Exception as e:
        log("KV 写入异常：%s" % str(e)[:80])
    return len(out_items)


def start_thread(log=_log):
    """启动时先跑一次（保证重启后数据新鲜），之后对齐到每 3 小时边界整点全量覆盖。"""
    def loop():
        while True:
            try:
                run_once(log=log)
            except Exception as e:
                log("本轮异常：%s" % str(e)[:120])
            now = time.time()
            nxt = (int(now) // LOOP_SEC + 1) * LOOP_SEC
            time.sleep(max(60, nxt - now))
    threading.Thread(target=loop, daemon=True, name="lowprice-jd").start()
    log("镜像同步线程已启动（每 3 小时整点全量覆盖，源站消失即下架）")


if __name__ == "__main__":
    lim = None
    if "--limit" in sys.argv:
        try:
            lim = int(sys.argv[sys.argv.index("--limit") + 1])
        except Exception:
            lim = 3
    src20033 = None
    if "--offline20033" in sys.argv:
        import glob as _gl
        bodies_dir = os.path.join(BASE_DIR, "jd20033_bodies")
        raws = []
        for fn in sorted(_gl.glob(os.path.join(bodies_dir, "resp*.json"))):
            try:
                txt = open(fn, encoding="utf-8").read().split("\n\n", 1)
                j = json.loads(txt[1] if len(txt) > 1 else txt[0])
                raws.extend(parse_20033_response(j))
            except Exception:
                pass
        src20033 = raws
        print("[离线] 载入 20033 抓取体 %d 条（来自 jd20033_bodies）" % len(raws))
    run_once(limit=lim, dry="--dry" in sys.argv, src20033=src20033)
