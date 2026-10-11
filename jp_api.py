# -*- coding: utf-8 -*-
"""精品库转链 · 纯 API 引擎（Boss 2026-10-11 拍板：脱离浏览器 UI，抓包接口直调）。

接口（2026-10-11 CDP 抓包实锤，与页面【转链】按钮同源）：
    POST https://www.jingpinku.com/tools/chain_link
    body: content=<urlencoded 原始文案>&rid=&t=<毫秒时间戳>
    headers: X-Requested-With: XMLHttpRequest
             Referer: https://www.jingpinku.com/tools/chain_link.do
             Cookie: <登录态，CDP Network.getCookies 捞取，缓存 1h>
    响应: {"code":"0","msg":"","data":"<转链后全文案>","images":[商品主图...]}

设计：
- 浏览器只在「捞 cookie」时用（一次性短连接，不碰页面按钮 → UI 熔断问题基本绝迹）
- code 非 "0" / 网络异常：强制重捞 cookie 再试一次，仍失败交由上层 UI 兜底
- 单条实测 0.92s（浏览器 UI 版 20s+）
"""
import json
import os
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_URL = "https://www.jingpinku.com/tools/chain_link"
REFERER = "https://www.jingpinku.com/tools/chain_link.do"
COOKIE_CACHE = os.path.join(BASE_DIR, "jp_cookie.json")
COOKIE_TTL = 3600  # cookie 缓存 1 小时（掉了会自动重捞）
API_TIMEOUT = 25

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 直连 opener：精品库本站无需代理，且要防本机 HTTP_PROXY 劫持
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_cookie = {"v": None, "ts": 0.0}


def _read_cache():
    try:
        with open(COOKIE_CACHE, encoding="utf-8") as f:
            d = json.load(f)
        return str(d.get("cookie") or ""), float(d.get("ts") or 0)
    except Exception:
        return "", 0.0


def _write_cache(cookie):
    try:
        with open(COOKIE_CACHE, "w", encoding="utf-8") as f:
            json.dump({"cookie": cookie, "ts": time.time()}, f)
    except Exception:
        pass


def _fish_cookie():
    """CDP 从已登录的精品库标签页捞 cookie（不碰页面 UI）。"""
    import jd_bot
    from websocket import create_connection
    if not jd_bot.is_running():
        jd_bot.launch()
        time.sleep(3)
    target = None
    for t in jd_bot.targets():
        if t.get("type") == "page" and "jingpinku.com" in (t.get("url") or ""):
            target = t
            break
    if not target:
        # 没有精品库标签页：借用第一个标签页导航过去（与 jp_convert._get_cdp 同策略）
        pages = [x for x in jd_bot.targets() if x.get("type") == "page"]
        if not pages:
            raise RuntimeError("浏览器没有标签页，无法捞 cookie")
        target = pages[0]
        ws0 = create_connection(target["webSocketDebuggerUrl"], timeout=10)
        ws0.send(json.dumps({"id": 1, "method": "Page.navigate",
                             "params": {"url": REFERER}}))
        time.sleep(5)
        ws0.close()
        for t in jd_bot.targets():
            if t.get("type") == "page" and "jingpinku.com" in (t.get("url") or ""):
                target = t
                break
    ws = create_connection(target["webSocketDebuggerUrl"], timeout=10)
    try:
        ws.send(json.dumps({"id": 1, "method": "Network.getCookies",
                            "params": {"urls": ["https://www.jingpinku.com/"]}}))
        while True:
            m = json.loads(ws.recv())
            if m.get("id") == 1:
                cookies = m["result"]["cookies"]
                break
    finally:
        try:
            ws.close()
        except Exception:
            pass
    if not cookies:
        raise RuntimeError("精品库域下没有 cookie（可能真掉登录了）")
    hdr = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    _cookie["v"], _cookie["ts"] = hdr, time.time()
    _write_cache(hdr)
    return hdr


def get_cookie(force=False):
    if not force:
        if _cookie["v"] and time.time() - _cookie["ts"] < COOKIE_TTL:
            return _cookie["v"]
        c, ts = _read_cache()
        if c and time.time() - ts < COOKIE_TTL:
            _cookie["v"], _cookie["ts"] = c, ts
            return c
    return _fish_cookie()


def _convert_raw(material, cookie):
    """单次直调。返回 (code, data, images, msg)。HTTP 层异常直接抛。"""
    body = urllib.parse.urlencode({"content": material, "rid": "",
                                   "t": int(time.time() * 1000)}).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    req.add_header("X-Requested-With", "XMLHttpRequest")
    req.add_header("Referer", REFERER)
    req.add_header("User-Agent", _UA)
    req.add_header("Cookie", cookie)
    with _OPENER.open(req, timeout=API_TIMEOUT) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    return (str(d.get("code")), d.get("data") or "",
            d.get("images") or [], str(d.get("msg") or ""))


def convert_material(material):
    """转一条。返回 (ok, out_text, images)。code 非 "0"/网络异常 → 重捞 cookie 重试一次。"""
    last = ""
    for attempt in (0, 1):
        try:
            code, data, images, msg = _convert_raw(material, get_cookie(force=attempt > 0))
        except Exception as e:
            last = f"API 异常：{str(e)[:80]}"
            time.sleep(1)
            continue
        if code == "0" and data:
            return True, data, images
        last = f"API code={code} {msg}".strip()
        time.sleep(1)  # 重捞 cookie 前稍等
    return False, last, []


if __name__ == "__main__":
    demo = "测试商品\nhttps://u.jd.com/xOOuON9"
    t0 = time.time()
    ok, out, imgs = convert_material(demo)
    print(f"耗时 {time.time() - t0:.2f}s  ok={ok}")
    print("out:", out[:200])
    print(f"images: {len(imgs)} 张")
