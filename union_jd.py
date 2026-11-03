# -*- coding: utf-8 -*-
"""京东联盟「源头线报」采集器（Boss 2026-11-03 明令：好单库京东线报断供，用联盟素材库顶着）。

原理：监控的转链浏览器（CDP 127.0.0.1:9222）里已登录 union.jd.com（Boss 扫码维持登录态）。
页面点击分类/排序才会请求 api.m.jd.com functionId=unionHedlineList（带 h5st 签名），
脚本不做签名、不裸调——模拟真人动作：找到素材库页 → 鼠标移动 → 点击一个分类 tab →
CDP Network 域捕获页面自己发出的响应体（最真实的流量形态）。

拟人化/风控纪律（Boss 2026-11-03 明令「动作模拟真实、避免触发风控」）：
  - 每 4 分钟最多一轮采集动作（UNION_POLL_MIN_SEC）
  - 每轮最多 1 次导航/点击；鼠标先 mouseMoved 停顿随机 0.4~1.2s 再按下/抬起
  - 分类按顺序轮换（像真人逐个逛分类），不重复猛点同一个
  - 不 reload、不连发 fetch 重放（旧 h5st URL 重放路线废弃）
预案：
  - 登录态失效（跳 passport/index 登录页）→ 置 union_login_lost.txt + 日志提醒 Boss 扫码
  - 找不到素材库页 → 模拟点击左侧「源头线报」菜单（真实用户路径），失败才 Page.navigate
"""
import json
import os
import random
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CDP_HTTP = "http://127.0.0.1:9222"
STATE_FILE = os.path.join(BASE_DIR, "union_seen.json")            # {"seen": [id...], "base": true}
LOGIN_LOST_FILE = os.path.join(BASE_DIR, "union_login_lost.txt")  # 登录态熔断标记
UNION_POLL_MIN_SEC = 600   # 拟人化限速：两轮采集动作最少间隔 10 分钟（Boss 风控要求；实测动作密了会出「访问频繁」）
UNION_COOLDOWN_SEC = 1800  # 撞到「访问频繁」提示后的冷却：30 分钟内不做任何动作
CAPTURE_WAIT_SEC = 9       # 点击后等页面自己发请求并收响应的窗口

_seen_cache = None
_ws = None
_last_poll = 0.0
_cooldown_until = 0.0      # 风控冷却截止时刻
_cate_idx = [0]            # 分类/排序轮换游标
_wslib = None


def _get_wslib():
    """延迟 import websocket-client（CDP 用到时才需要；监控 venv 已装）。"""
    global _wslib
    if _wslib is None:
        import websocket
        _wslib = websocket
    return _wslib


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


def _mark_login_lost():
    try:
        with open(LOGIN_LOST_FILE, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass


class Tab(object):
    """一个 CDP 标签页会话：Runtime.evaluate / Page / Network / 拟人点击。"""

    def __init__(self, ws_url):
        self.ws = _get_wslib().create_connection(ws_url, timeout=40, suppress_origin=True)
        self.ws.settimeout(40)
        self._id = 0

    def call(self, method, params=None, timeout=None):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        if timeout:
            self.ws.settimeout(timeout)
        try:
            while True:
                m = json.loads(self.ws.recv())
                if m.get("id") == self._id:
                    return m.get("result") or {}
        finally:
            self.ws.settimeout(40)

    def ev(self, expr, await_promise=True):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": await_promise})
        res = r.get("result") or {}
        if "value" in res:
            return res["value"]
        return res.get("description")

    def human_click(self, x, y):
        """拟人点击：鼠标移动过去 → 随机停顿 → 按下 → 抬起。"""
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": int(x), "y": int(y)})
        time.sleep(random.uniform(0.4, 1.2))
        for t in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent",
                      {"type": t, "x": int(x) + random.randint(-2, 2), "y": int(y) + random.randint(-1, 1),
                       "button": "left", "clickCount": 1})
            time.sleep(random.uniform(0.06, 0.15))

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def _find_union_tab():
    """返回已登录的 union.jd.com 标签页（任意页），没有返回 None。"""
    try:
        tabs = json.load(urllib.request.urlopen(CDP_HTTP + "/json", timeout=10))
        for t in tabs:
            if t.get("type") == "page" and "union.jd.com" in (t.get("url") or ""):
                return t
    except Exception:
        pass
    return None


def _is_login_page(url, txt):
    u = url or ""
    if "passport" in u or ("union.jd.com/index" in u and "登录" in (txt or "")):
        return True
    t = txt or ""
    return ("扫码登录" in t and "请使用京东商城账号登录" in t)


def _goto_material(tab):
    """确保页面在素材库：优先模拟点左侧「源头线报」菜单（真实路径），失败才直接导航。"""
    url = tab.ev("location.href") or ""
    if "materialLibrary" in url:
        return True
    pos = tab.ev(r'''
(() => {
  const els = [...document.querySelectorAll('span,div,a,li')].filter(
    e => e.childElementCount === 0 && e.textContent.trim() === '源头线报');
  if (!els.length) return null;
  const r = els[0].getBoundingClientRect();
  return (r.width && r.height) ? JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2}) : null;
})()
''', await_promise=False)
    if pos:
        try:
            p = json.loads(pos)
            tab.human_click(p["x"], p["y"])
        except Exception:
            return False
    else:
        tab.call("Page.navigate", {"url": "https://union.jd.com/proManager/materialLibrary"})
    # 等素材库渲染出分类栏（「全部」按钮出现），最多 ~16s
    for _ in range(8):
        time.sleep(2)
        ok = tab.ev(r'''
(() => {
  const els = [...document.querySelectorAll('span,div,a,li')].filter(
    e => e.childElementCount === 0 && e.textContent.trim() === '全部');
  return els.length ? 'YES' : 'NO';
})()
''', await_promise=False)
        if ok == "YES":
            return True
    return "materialLibrary" in (tab.ev("location.href") or "")


def _capture_by_click(tab, log):
    """拟人化抓一轮：鼠标点一个分类 tab（轮换），Network 域收页面自发请求的响应体。"""
    # 分类名列表（从 DOM 动态取，取不到就用默认顺序）
    cats = tab.ev(r'''
(() => {
  const names = ['全部'];
  const els = [...document.querySelectorAll('span,div,a,li')].filter(
    e => e.childElementCount === 0);
  for (const e of els) {
    const t = e.textContent.trim();
    if (t && t.length <= 8 && !names.includes(t) && names.length < 14 &&
        /水饮|清洁|纸品|护理|生鲜|电器|食品|粮油|服饰|内衣|母婴|户外|数码|家居/.test(t)) {
      names.push(t);
    }
  }
  return JSON.stringify(names);
})()
''', await_promise=False) or '["全部"]'
    try:
        cats = json.loads(cats)
    except Exception:
        cats = ["全部"]
    if _cate_idx[0] >= len(cats):
        _cate_idx[0] = 0
    target = cats[_cate_idx[0]]
    _cate_idx[0] += 1

    pos = tab.ev('''
(() => {
  const t = %s;
  const els = [...document.querySelectorAll('span,div,a,li')].filter(
    e => e.childElementCount === 0 && e.textContent.trim() === t);
  if (!els.length) return null;
  const r = els[0].getBoundingClientRect();
  return (r.width && r.height) ? JSON.stringify({x: r.x + r.width / 2, y: r.y + r.height / 2}) : null;
})()
''' % json.dumps(target), await_promise=False)
    if not pos:
        return {}
    try:
        p = json.loads(pos)
    except Exception:
        return {}

    tab.call("Network.enable")
    bodies = []
    tab.human_click(p["x"], p["y"])
    deadline = time.time() + CAPTURE_WAIT_SEC
    seen_rid = set()
    while time.time() < deadline:
        try:
            tab.ws.settimeout(1.5)
            m = json.loads(tab.ws.recv())
        except Exception:
            continue
        if m.get("method") == "Network.responseReceived":
            resp = m["params"]["response"]
            url = resp.get("url") or ""
            if "unionHedlineList" in url or ("getHeadlineList" in url):
                rid = m["params"]["requestId"]
                if rid in seen_rid:
                    continue
                seen_rid.add(rid)
                try:
                    body = tab.call("Network.getResponseBody", {"requestId": rid}, timeout=10)
                    b = body.get("body") or ""
                    if body.get("base64Encoded"):
                        import base64
                        b = base64.b64decode(b).decode("utf-8", "ignore")
                    if b.strip():
                        bodies.append(b)
                except Exception:
                    continue
    log(f"联盟线报：点击[{target}] 捕获 {len(bodies)} 个响应")
    merged = {}
    for b in bodies:
        try:
            j = json.loads(b)
        except Exception:
            continue
        data = j.get("data") if isinstance(j, dict) else None
        if isinstance(data, list):
            for it in data:
                gid = str(it.get("id") or "")
                if gid and gid not in merged:
                    merged[gid] = it
    return merged


def poll_union(log=print):
    """拉一轮联盟源头线报（拟人化：10 分钟限速 + 每轮一次点击 + 风控冷却）。返回新条目 deals。"""
    global _last_poll, _cooldown_until
    now = time.time()
    if now < _cooldown_until:
        return []          # 风控冷却中，什么都不做
    if now - _last_poll < UNION_POLL_MIN_SEC:
        return []
    _last_poll = now

    tinfo = _find_union_tab()
    if not tinfo:
        log("联盟线报：浏览器里没有 union.jd.com 标签页（浏览器没开？），本轮跳过")
        return []
    tab = Tab(tinfo["webSocketDebuggerUrl"])
    merged = {}
    try:
        url = tab.ev("location.href") or ""
        txt = tab.ev("document.body.innerText.replace(/\\s+/g,' ').slice(0,500)") or ""
        if _is_login_page(url, txt):
            _mark_login_lost()
            log("联盟线报：登录态失效（跳登录页），已置熔断标记——请 Boss 重新扫码登录 union.jd.com")
            return []
        if "访问频繁" in txt:
            _cooldown_until = time.time() + UNION_COOLDOWN_SEC
            log("联盟线报：页面出现「访问频繁」（触发风控），冷却 30 分钟内不做任何动作")
            return []
        try:
            os.remove(LOGIN_LOST_FILE)
        except OSError:
            pass
        if not _goto_material(tab):
            log("联盟线报：素材库页打不开/没渲染出分类栏，本轮跳过")
            return []
        merged = _capture_by_click(tab, log)
    except Exception as e:
        log(f"联盟线报采集异常：{str(e)[:90]}")
    finally:
        tab.close()
    if not merged:
        return []

    seen = _seen()
    fresh = [it for gid, it in merged.items() if gid not in seen["seen"]]
    if not seen.get("base"):
        seen["seen"] = list(merged.keys())
        seen["base"] = True
        _seen_save()
        log(f"联盟线报：基线已建立（现存 {len(seen['seen'])} 条全部跳过，只采之后新增的）")
        return []

    out = []
    for it in fresh:
        deal = to_deal(it)
        if deal:
            out.append(deal)
        seen["seen"].append(str(it.get("id")))
    if len(seen["seen"]) > 5000:
        seen["seen"] = seen["seen"][-5000:]
    _seen_save()
    if out:
        log(f"联盟线报：采到 {len(out)} 条新线报")
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
        "_union": 1,
    }


if __name__ == "__main__":
    for d in poll_union(lambda m: print(m)):
        print(json.dumps(d, ensure_ascii=False)[:200])
