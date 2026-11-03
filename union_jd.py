# -*- coding: utf-8 -*-
"""京东联盟「源头线报」采集器（Boss 2026-11-03 明令：好单库京东线报断供，用联盟素材库顶着）。

原理：监控的转链浏览器（CDP 127.0.0.1:9222）里已登录 union.jd.com/proManager/materialLibrary
（账号 bonghyesun）。页面自身会请求 api.m.jd.com/api?functionId=unionHedlineList（带 h5st 签名），
本脚本不在脚本侧拼签名，而是 CDP 在页面上下文里 fetch 重放页面刚发过的接口 URL
（cookie/h5st 全由页面自带），拿到的 data[] 就是成品线报：
  {id, content(整段文案，自带 3.cn 领券链 + u.jd.com 官方短链), couponInfoList, orderPrice, materialList, skuList}

产出条目为 deals 同构结构（platform=2 京东实时线报），文案自带官方链 → 无需精品库转链。

风险预案：
  - h5st 时效：重放失败（返回非 200/空）→ Page.reload 重载页面触发新请求 → 重取 URL 再试
  - 登录态失效：页面跳 passport → 置磁盘 union_login_lost.txt，监控日志提醒 Boss 扫码
  - 分类：页面默认加载若干 firstCateId 的请求，把 performance 里的全部 unionHedlineList URL 都重放一遍（去重参数）
"""
import json
import os
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CDP_HTTP = "http://127.0.0.1:9222"
STATE_FILE = os.path.join(BASE_DIR, "union_seen.json")          # {"seen": [id...], "base": true}
LOGIN_LOST_FILE = os.path.join(BASE_DIR, "union_login_lost.txt")  # 登录态熔断标记

_seen_cache = None
_ws = None


def _wslib():
    """延迟 import websocket-client（监控 python 可能没装；CDP 用到时才需要）。"""
    global _ws
    if _ws is None:
        import websocket  # 隔离 venv 已装
        _ws = websocket
    return _ws


def _seen():
    global _seen_cache
    if _seen_cache is None:
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                _seen_cache = json.load(f)
        except Exception:
            _seen_cache = {"seen": [], "base": False}
    return _seen_cache


def _seen_save():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(_seen_cache, f, ensure_ascii=False)
    except Exception:
        pass


def _cdp_tab():
    """找到素材库标签页；没有就开一个。返回 webSocketDebuggerUrl 或 None。"""
    try:
        tabs = json.load(urllib.request.urlopen(CDP_HTTP + "/json", timeout=10))
        for t in tabs:
            if t.get("type") == "page" and "materialLibrary" in (t.get("url") or ""):
                return t["webSocketDebuggerUrl"]
    except Exception:
        return None
    try:
        req = urllib.request.Request(CDP_HTTP + "/json/new?https://union.jd.com/proManager/materialLibrary", method="PUT")
        t = json.load(urllib.request.urlopen(req, timeout=10))
        time.sleep(6)  # 等首屏
        return t.get("webSocketDebuggerUrl")
    except Exception:
        return None


class _Tab(object):
    """一个 CDP 标签页会话（Runtime.evaluate / Page.reload）。"""

    def __init__(self, ws_url):
        self.ws = _wslib().create_connection(ws_url, timeout=30, suppress_origin=True)
        self._id = 0

    def call(self, method, params=None):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self._id:
                return m.get("result") or {}

    def ev(self, expr, await_promise=True):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": await_promise})
        res = (r.get("result") or {})
        if "value" in res:
            return res["value"]
        if res.get("subtype") == "error" or "exceptionDetails" in r:
            return None
        return res.get("description")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def _login_ok(tab):
    url = tab.ev("location.href") or ""
    if "passport" in url or "login" in url:
        return False
    txt = tab.ev("(document.body.innerText.match(/扫码登录|账号登录|请先登录/g)||[]).join(',')") or ""
    return "扫码登录" not in txt and "账号登录" not in txt


def _fetch_headlines(tab):
    """页面上下文里 fetch 重放 performance 里所有 unionHedlineList URL，返回 {cate_key: [item...]}。"""
    expr = r'''
(async () => {
  const urls = [...new Set(performance.getEntriesByType('resource')
      .map(e => e.name).filter(u => u.includes('unionHedlineList')))];
  const out = {};
  for (const u of urls) {
    try {
      const r = await fetch(u, {credentials: 'include'});
      const j = await r.json();
      if (j && j.code === 200 && Array.isArray(j.data)) {
        const m = u.match(/firstCateId%22%3A(\d+)/);
        const key = m ? m[1] : (u.match(/firstCateId":"?(\d+)/) ? u.match(/firstCateId":"?(\d+)/)[1] : 'all');
        out[key] = j.data;
      }
    } catch (e) {}
  }
  return JSON.stringify(out);
})()
'''
    raw = tab.ev(expr)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _mark_login_lost():
    try:
        with open(LOGIN_LOST_FILE, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass


def poll_union(log=print):
    """拉一轮联盟源头线报，返回新条目列表（deals 同构）。首跑建基线全跳过。"""
    ws_url = _cdp_tab()
    if not ws_url:
        log("联盟线报：找不到/开不了素材库标签页（CDP 9222 不通？），本轮跳过")
        return []
    tab = _Tab(ws_url)
    items = {}
    try:
        if not _login_ok(tab):
            _mark_login_lost()
            log("联盟线报：素材库页登录态失效（跳 passport），已置熔断标记——请 Boss 在浏览器里重新登录 union.jd.com")
            return []
        try:
            os.remove(LOGIN_LOST_FILE)
        except OSError:
            pass
        items = _fetch_headlines(tab)
        if not items:
            # h5st 过期或页面刚开没发过请求 → 重载页面触发新 XHR，等 6s 再试一次
            tab.call("Page.enable")
            tab.call("Page.reload", {"ignoreCache": False})
            time.sleep(6)
            items = _fetch_headlines(tab)
    finally:
        tab.close()
    if not items:
        log("联盟线报：本轮重放接口无数据（h5st 过期重载也失败？），跳过")
        return []

    seen = _seen()
    merged = {}
    for _cate, lst in items.items():
        for it in lst:
            gid = str(it.get("id") or "")
            if gid and gid not in merged:
                merged[gid] = it

    fresh = [it for gid, it in merged.items() if gid not in seen["seen"]]
    if not seen.get("base"):
        seen["seen"] = list(merged.keys())
        seen["base"] = True
        _seen_save()
        log(f"联盟线报：基线已建立（现存 {len(seen['seen'])} 条全部跳过，只采之后新增的）")
        return []

    out = []
    for it in fresh:
        gid = str(it.get("id"))
        deal = to_deal(it)
        if deal:
            out.append(deal)
        seen["seen"].append(gid)
    # seen 防膨胀：只留最近 5000 个
    if len(seen["seen"]) > 5000:
        seen["seen"] = seen["seen"][-5000:]
    _seen_save()
    if fresh:
        log(f"联盟线报：采到 {len(out)} 条新线报（重放 {len(items)} 个分类接口）")
    return out


def to_deal(item):
    """联盟线报条目 → deals 同构 deal。文案自带官方 u.jd.com/3.cn 链 → 无需转链，直接上。"""
    import re
    content = (item.get("content") or "").strip()
    if not content:
        return None
    rows = []
    for ln in content.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        m = re.search(r"https?://\S+", ln)
        if not m:
            rows.append({"content": ln, "item_id": "", "coupon_url": ""})
            continue
        link = m.group(0).rstrip("，。）)！!】\"'")
        before = ln[: m.start()].strip()
        after = ln[m.end():].strip()
        if before:
            rows.append({"content": before, "item_id": "", "coupon_url": ""})
        rows.append({"content": after, "item_id": link, "coupon_url": "", "url": link, "converted": True})
    if not rows:
        return None
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "id": "union_%s" % item.get("id"),
        "platform": "2",
        "platform_name": "京东",
        "cate": "京东实时线报",
        "time": now,
        "images": list(item.get("materialList") or [])[:1],
        "list": rows,
        "_addedAt": now,
        "_union": 1,  # 标记来源：京东联盟素材库
    }


if __name__ == "__main__":
    def _p(m):
        print(m)
    for d in poll_union(_p):
        print(json.dumps(d, ensure_ascii=False)[:200])
