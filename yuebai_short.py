# -*- coding: utf-8 -*-
"""u.jd.com 佣金链 → 悦拜短链(yue.fit) 防爬保护层（Boss 2026-09-11 明令）。

目的：站上展示的京东文案里不出现裸 u.jd.com 返利链，防机器人扒站偷链。
实现：把展示文本里的 u.jd.com 链接替换为悦拜短链（302 原样还原，实测不掺参数、不掉佣金）；
     结果存 _siteContext 供前端渲染。企微推送仍用 _originalContext 原文（u.jd.com 是
     企微白名单熟链，yue.fit 未知域不冒险）。

纪律：
- 悦拜接口幂等（同链永远同短链），本地再缓存一份省调用（yuebai_cache.json）
- 单条失败自动回退原文，绝不阻塞入库（红线仍是「没转上链绝不上站」，本层是锦上添花）
- 每条新链间隔 0.3s 温和调用，不触发对方限频（实测 15 连发无限制，仍留余量）
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "yuebai_cache.json")
API = "https://app.yuebuy.cn/api/domain/getShortUrl"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
PATTERN = re.compile(r"https?://u\.jd\.com/[A-Za-z0-9]+")
CALL_GAP = 0.3      # 同一轮新链之间的调用间隔（秒）
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 绕本机代理

_cache = None


def _load_cache():
    global _cache
    if _cache is None:
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                _cache = json.load(f) or {}
        except Exception:
            _cache = {}
    return _cache


def _save_cache():
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache or {}, f, ensure_ascii=False)
    except Exception:
        pass


def get_short(url, log=print):
    """单条 u.jd.com → 悦拜短链；失败返回 None（调用方回退原文）。"""
    cache = _load_cache()
    if url in cache:
        return cache[url]
    d = urllib.parse.urlencode({"url": url}).encode()
    req = urllib.request.Request(API, data=d, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": UA,
        "Referer": "http://yuebai.me/",
        "Origin": "http://yuebai.me"})
    try:
        with OPENER.open(req, timeout=10) as r:
            j = json.loads(r.read().decode("utf-8", "ignore"))
        if j.get("code") == 1:
            nu = ((j.get("data") or {}).get("new_url") or "").strip()
            if nu:
                cache[url] = nu
                _save_cache()
                return nu
        log("yuebai 短链拒绝 %s: %s" % (url[:44], str(j.get("message"))[:40]))
    except Exception as e:
        log("yuebai 短链异常 %s: %s" % (url[:44], repr(e)[:60]))
    return None


def protect(text, log=print):
    """把文本里的 u.jd.com 链接替换成悦拜短链。
    返回 (新文本, 成功替换数)；全部失败则原文返回（替换数 0）。"""
    if not text:
        return text, 0
    links = []
    seen = set()
    for u in PATTERN.findall(text):
        if u not in seen:
            seen.add(u)
            links.append(u)
    if not links:
        return text, 0
    out, n = text, 0
    for i, u in enumerate(links):
        s = get_short(u, log)
        if s and s != u:
            out = out.replace(u, s)
            n += 1
        if i < len(links) - 1:
            time.sleep(CALL_GAP)
    return out, n


def protect_deal(deal, log=print):
    """给转链完成的京东 deal 打 _siteContext（站上展示用短链版文案）。
    无 u.jd.com / 全失败时不写字段，前端自动回退 _originalContext。"""
    base = (deal.get("_originalContext") or deal.get("_formatContext") or "").strip()
    if not base or str(deal.get("platform")) != "2":
        return 0
    ctx, n = protect(base, log)
    if n:
        deal["_siteContext"] = ctx
    return n


if __name__ == "__main__":
    # 自检：拿一条真实链试（不碰线上数据）
    demo = "某商品好价\n下单链接：https://u.jd.com/xaADLna 快冲"
    out, n = protect(demo)
    print("替换 %d 条\n%s" % (n, out))
