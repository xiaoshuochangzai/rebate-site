# -*- coding: utf-8 -*-
"""京东低价好物（折京客 API）—— Boss 2026-11-12 拍板执行。

口径：佣金比例>=10% + 券后价 3~60 元 + 月销量>=1000（api_all 三参数直接筛，本地再校验）；
      同款不同链接只留一条（标题前10字分组留最低价）。
数据源：①全站领券商品库 api_all；②20032 页面「自营热卖榜」= 折京客 eliteId=41 频道。
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


def fetch_api_all(log=_log):
    """数据源①：全站领券商品库，分页拉三条件全量；失败返回空 dict。"""
    c = _conf()
    s = _session()
    out = {}
    for page in range(1, MAX_PAGES + 1):
        p = {"appkey": c["appkey"], "page": page, "page_size": PAGE_SIZE,
             "sort": "sale_num_desc", "price": "0.0-60",
             "commission_rate_start": 10, "sale_num_start": 1000}
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
    log("源站三条件全量 %d 条（%d 页）" % (len(out), page))
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


def fetch_all(log=_log):
    """合并两个数据源；任一源失败 → 返回空 dict（整轮跳过，防镜像误删）。"""
    a = fetch_api_all(log)
    if not a:
        return {}
    b = fetch_channel(log)
    if b is None:
        return {}
    a.update(b)
    return a


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
    low = sorted([x for x in items if price(x) < SPLIT_PRICE], key=sales, reverse=True)
    high = sorted([x for x in items if price(x) >= SPLIT_PRICE], key=sales, reverse=True)
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
        rate = float(it.get("tkrate3") or 0)
        sales = float(it.get("volume") or 0)
    except Exception:
        return False
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


def run_once(log=_log, limit=None, dry=False):
    raw = fetch_all(log)
    if not raw:
        log("源站返回空/失败，本轮跳过（不清空，防误删）")
        return -1
    target = {g: it for g, it in raw.items() if qualifies(it)}
    if not target:
        log("本轮无命中商品，跳过（不清空，防误删）")
        return -1
    # Boss 2026-11-12 明令：同商品不同链接只留一条 —— 按标题前10字分组，
    # 每组只保留券后价最低的那条（先过滤 <3 元，保证留下的是合格商品）
    best = {}
    for gid, it in target.items():
        k = _variant_key(it.get("title") or it.get("tao_title")) or ("id:" + gid)
        try:
            p = float(it.get("quanhou_jiage") or 0)
        except Exception:
            p = 0.0
        cur = best.get(k)
        if cur is None or p < cur[2]:
            best[k] = (gid, it, p)
    n_dup = len(target) - len(best)
    target = {gid: it for gid, it, _p in best.values()}
    log("同款归一：合并 %d 条变体，剩 %d 条" % (n_dup, len(target)))
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
    run_once(limit=lim, dry="--dry" in sys.argv)
