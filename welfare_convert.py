# -*- coding: utf-8 -*-
"""双11福利清单批量转链：ratesurl v3（apikey 普通接口）。
itemid(加密串) → s.tb.cn 短链 + 淘口令。缓存 wf_conv_cache.json 支持断点续跑。
失败条保留原 couponurl 不阻塞。"""
import json, os, sys, time, io, urllib.request, urllib.parse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

API = "https://v3.api.haodanku.com/ratesurl"
APIKEY = "9AC3C71D776A"
PID = "mm_2130470034_3434000269_116316900171"
TB_NAME = "淘淘淘淘yh"
GAP = 0.8
CACHE = "wf_conv_cache.json"


def load_cache():
    try:
        return json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        return {}


def conv(itemid, title):
    d = {"apikey": APIKEY, "pid": PID, "tb_name": TB_NAME, "get_taoword": "1",
         "title": title, "itemid": itemid}
    form = urllib.parse.urlencode(d, encoding="utf-8").encode("ascii")
    req = urllib.request.Request(API, data=form, headers={
        "User-Agent": "Mozilla/5.0 Chrome/126.0",
        "Content-Type": "application/x-www-form-urlencoded"})
    j = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
    if str(j.get("code")) != "1":
        raise RuntimeError("code=%s %s" % (j.get("code"), str(j.get("msg"))[:60]))
    data = j.get("data") or {}
    link = (data.get("link") or "").strip() or (data.get("coupon_click_url") or "").strip()
    return {"link": link, "tpwd": (data.get("taoword") or "").strip()}


def main():
    w = json.load(open("site/welfare.json", encoding="utf-8"))
    cache = load_cache()
    # 全局按 itemid 去重（同商品跨标签共用一条转链结果）
    todo = {}
    for cat in w["cats"]:
        for it in cat["items"]:
            iid = it.get("itemid") or ""
            if iid:
                todo.setdefault(iid, it)
    print(f"总商品 {sum(len(c['items']) for c in w['cats'])} 条，唯一 itemid {len(todo)}，缓存已转 {len(cache)}")

    done = fail = 0
    for n, (iid, it) in enumerate(todo.items(), 1):
        if iid in cache and cache[iid].get("link"):
            continue
        title = it.get("t") or "商品"
        try:
            r = conv(iid, title)
            if r["link"]:
                cache[iid] = r
                done += 1
            else:
                fail += 1
                print(f"  [{n}] 空链 {title[:18]}")
        except Exception as e:
            fail += 1
            print(f"  [{n}] 失败 {title[:18]}: {e}")
            if "404" in str(e) or "429" in str(e):
                time.sleep(6)
        if n % 40 == 0:
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"进度 {n}/{len(todo)} 成功+{done} 失败+{fail}")
        time.sleep(GAP)

    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)

    # 回写 welfare.json
    hit = miss = 0
    for cat in w["cats"]:
        for it in cat["items"]:
            c = cache.get(it.get("itemid") or "")
            if c and c.get("link"):
                it["link"] = c["link"]
                if c.get("tpwd"):
                    it["tpwd"] = c["tpwd"]
                hit += 1
            else:
                miss += 1
    json.dump(w, open("site/welfare.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"完成：转链命中 {hit}，保留原券链 {miss}，welfare.json 已回写")


if __name__ == "__main__":
    main()
