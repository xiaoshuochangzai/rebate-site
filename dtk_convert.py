# -*- coding: utf-8 -*-
"""大淘客淘宝线报引擎 v4（纯 API 直调版，2026-09-06 定案）。

架构：
- 线报列表：读 dataoke.com/xp/xb 页面 DOM + React fiber（只读，不点击、不 reload）
- 转链：纯 Python requests 直调 dtkapi/taobaoapi/pwd-analysis（网页「转链复制」按钮
  背后的同一个接口，2026-09-06 实测 1.2s/条，返回 tpwd=带返利新淘口令 + short_url
  + goods_info{到手价, 主图}）
- 鉴权：登录态 jaw_uid cookie（前端代码 getToken() 就是读它），从机器人浏览器 CDP
  捞取并缓存 1 小时；遇 code=1000（登录已过期）自动重捞重试一次

红线：转不上（无 tpwd）绝不上站。
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests

import jd_bot

DTK_URL = "https://www.dataoke.com/xp/xb"
API_URL = "https://dtkapi.ffquan.cn/taobaoapi/pwd-analysis"
XB_LIST_URL = "https://dtkapi.ffquan.cn/dtk-go-goods-center/group-xb/xb-list"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# 旧淘口令整块：括号/斜杠包着的 10~13 位口令核 + 可选渠道码尾巴（AA00/AC01/MU918/CZ6806 等）
TOKEN_RE = re.compile(
    r"[（(【\[/¥￥]\s*[A-Za-z0-9]{10,13}\s*[）)】\]/（(]?"
    r"(?:\s*[（(【\[/]?\s*[A-Z]{2}\s*\d{1,6}\s*[）)】\]/]?)?"
)


# ---------- jaw_uid cookie 管理 ----------
_JAW = {"v": "", "ts": 0.0}


def _refresh_jaw():
    """从机器人浏览器捞 jaw_uid cookie（CDP，不开页面、不点击）。"""
    d = Dtk()
    try:
        r = d.call("Network.getCookies", {"urls": ["https://www.dataoke.com"]})
        for c in r.get("cookies", []):
            if c["name"] == "jaw_uid" and c.get("value"):
                _JAW["v"] = c["value"]
                _JAW["ts"] = time.time()
                return _JAW["v"]
    finally:
        d.close()
    raise RuntimeError("捞不到 jaw_uid cookie（机器人浏览器没在运行或未登录大淘客）")


def _get_jaw():
    if _JAW["v"] and time.time() - _JAW["ts"] < 3600:
        return _JAW["v"]
    return _refresh_jaw()


# ---------- 纯 API 转链 ----------
def direct_convert(text, retry=True):
    """直调 pwd-analysis：整段文案进 → data 出（tpwd/short_url/goods_info）。
    成功返回 data(dict)，没解析出口令/失败返回 None。"""
    jaw = _get_jaw()
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.dataoke.com",
        "Referer": "https://www.dataoke.com/xp/xb",
        "Accept": "application/json, text/plain, */*",
    }
    url = API_URL + "?jaw_uid=" + urllib.parse.quote(jaw)
    r = requests.post(url, data="content=" + urllib.parse.quote(text or ""),
                      headers=headers, timeout=15)
    j = r.json()
    code = str(j.get("code"))
    if code == "1000" and retry:
        _refresh_jaw()  # 登录态过期，重捞 cookie 再试一次
        return direct_convert(text, retry=False)
    if code != "1":
        raise RuntimeError(f"dtkapi code={code} {str(j.get('msg'))[:60]}")
    data = j.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        d0 = data[0]
    elif isinstance(data, dict) and data:
        d0 = data
    else:
        return None
    if not d0.get("tpwd"):
        return None
    return d0


# ---------- 线报列表：纯 API（2026-09-06 定案） ----------
# 页面 DOM 的自动刷新依赖 Chrome 定时器，监控断连 30s 后标签即被冻结，
# DOM 永远停留在冻结时刻 → 淘宝「假死」。改直调 xb-list 接口（实测裸调即可用），
# 字段与页面 fiber 数据完全一致（material_original/material_show/pic/create_time）。
def fetch_tips_api(pages=2):
    """纯 requests 拉大淘客线报列表。返回 tip 列表；接口异常返回 None（让调用方走 DOM 兜底）。"""
    tips = []
    for page in range(1, max(1, pages) + 1):
        try:
            r = requests.get(XB_LIST_URL,
                             params={"platform": 0, "page": page, "cid": 0, "size": 12},
                             headers={"User-Agent": UA}, timeout=15)
            j = r.json()
            lst = ((j.get("data") or {}).get("list")) or []
        except Exception:
            return None if page == 1 else tips
        if not isinstance(lst, list) or not lst:
            break
        for it in lst:
            if not isinstance(it, dict):
                continue
            texts, imgs, origs = [], [], []
            for b in (it.get("material_show") or []):
                if not b:
                    continue
                if b.get("type") == 2 and b.get("content"):
                    imgs.append(str(b["content"]))
                elif b.get("content"):
                    texts.append(str(b["content"]))
            for b in (it.get("material_original") or []):
                if b and b.get("type") != 2 and b.get("content"):
                    origs.append(str(b["content"]))
            pic = imgs[0] or it.get("pic") or it.get("head_img") or ""
            if pic and not pic.startswith("http"):
                pic = "https:" + pic if pic.startswith("//") else pic
            imgs = [("https:" + x if x.startswith("//") else x) if isinstance(x, str) and not x.startswith("http") else x
                    for x in imgs]
            tips.append({
                "id": str(it.get("id") or ""),
                "title": (it.get("title") or "").strip(),
                "rel": "",
                "text": "\n".join(texts),
                "orig": "\n".join(origs),
                "imgs": imgs,
                "pic": pic,
                "price": it.get("price") or "",
                "create_time": it.get("create_time") or "",
            })
        time.sleep(0.4)
    return tips


def convert_tip(tip):
    """模块级转链入口（与 Dtk.convert_tip 同一逻辑；该方法不依赖浏览器实例）。"""
    return Dtk.convert_tip(None, tip)


# ---------- 浏览器连接（只用于读线报列表兜底 / 捞 cookie） ----------
class Dtk:
    def __init__(self):
        self.t = self._find_or_open()
        self._connect()

    def _find_or_open(self):
        t = jd_bot.find_page("dataoke.com")
        if t:
            return t
        ver = jd_bot.is_running()
        if not ver:
            raise RuntimeError("机器人浏览器没在运行")
        c = jd_bot.CDP(ver["webSocketDebuggerUrl"])
        c.send("Target.createTarget", {"url": DTK_URL})
        c.close()
        for _ in range(15):
            time.sleep(1)
            t = jd_bot.find_page("dataoke.com")
            if t:
                return t
        raise RuntimeError("打开大淘客标签页失败")

    def _connect(self):
        self.ws = jd_bot.websocket.create_connection(self.t["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
        self.mid = [0]
        self._pending = []
        self._reqs = {}
        self._req_posts = {}
        self._tb_bodies = []
        self._used_rids = {}
        self._last_tips = []
        self.debug = False
        self.call("Network.enable")
        self._anti_throttle()

    def _anti_throttle(self):
        """反节流三件套：窗口被遮挡时 Chrome 冻结定时器，页面列表会停止自动更新。"""
        try:
            self.call("Page.setWebLifecycleState", {"state": "active"})
        except Exception:
            pass
        try:
            self.call("Emulation.setFocusEmulationEnabled", {"enabled": True})
        except Exception:
            pass
        try:
            self.ev("""(function(){
              Object.defineProperty(document, 'visibilityState', {get: () => 'visible', configurable: true});
              Object.defineProperty(document, 'hidden', {get: () => false, configurable: true});
              document.dispatchEvent(new Event('visibilitychange'));
              return 1;
            })()""", timeout=15)
        except Exception:
            pass

    def reload(self, wait=8):
        """重载页面（一般不需要了；列表自动更新）。"""
        self.call("Page.navigate", {"url": DTK_URL})
        time.sleep(wait)
        self._connect()

    # ---- CDP 基础 ----
    def _handle_event(self, m):
        meth = m.get("method", "")
        prm = m.get("params", {})
        if meth == "Network.requestWillBeSent":
            self._reqs[prm["requestId"]] = prm["request"]["url"]
            req = prm["request"]
            pd = req.get("postData") or ""
            if not pd and req.get("postDataEntries"):
                import base64
                try:
                    pd = "".join(
                        base64.b64decode(e.get("bytes", "")).decode("utf-8", "ignore")
                        for e in req["postDataEntries"]
                    )
                except Exception:
                    pd = ""
            if pd:
                self._req_posts[prm["requestId"]] = pd

    def call(self, method, params=None, timeout=30):
        self.mid[0] += 1
        self.ws.settimeout(timeout)
        self.ws.send(json.dumps({"id": self.mid[0], "method": method, "params": params or {}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.mid[0]:
                if "error" in m:
                    raise RuntimeError(f"CDP {method}: {m['error']}")
                return m.get("result", {})
            self._pending.append(m)

    def _drain(self, timeout=0.05):
        while self._pending:
            try:
                self._handle_event(self._pending.pop(0))
            except Exception:
                pass
        try:
            self.ws.settimeout(timeout)
            while True:
                self._handle_event(json.loads(self.ws.recv()))
        except Exception:
            pass
        finally:
            try:
                self.ws.settimeout(60)
            except Exception:
                pass

    def ev(self, expression, timeout=25):
        return self.call("Runtime.evaluate",
                         {"expression": expression, "awaitPromise": True, "returnByValue": True},
                         timeout)["result"]["value"]

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass

    # ---- 业务 ----
    def fetch_tips(self):
        """拉当前页面线报（只读 DOM+fiber，不点击）：id/title/rel/text/orig/imgs/pic/price。"""
        val = self.ev(r"""
(function(){
  const cards = document.querySelectorAll('[class*="tip-grid-style-tiplist"]');
  const out = [];
  cards.forEach((c)=>{
    const btn = [...c.querySelectorAll('[class*="btn2"]')].find(b=>(b.innerText||'').includes('转链复制'));
    if(!btn) return;
    let fiber=null;
    for (const k of Object.keys(c)) if (k.startsWith('__reactInternalInstance$')) fiber=c[k];
    let it = {}, f = fiber, depth = 0;
    while (f && depth < 40) {
      let h = f.memoizedState, hn = 0;
      while (h && hn < 30) {
        const ms = h.memoizedState;
        if (ms && typeof ms === 'object') {
          for (const k of Object.keys(ms)) {
            const v = ms[k];
            if (Array.isArray(v) && v.length && v[0] && typeof v[0]==='object' &&
                ('material_original' in v[0] || 'pic' in v[0] || 'material_show' in v[0])) {
              it = v[0]; break;
            }
          }
        }
        if (it.id !== undefined) break;
        h = h.next; hn++;
      }
      if (it.id !== undefined) break;
      f = f.return; depth++;
    }
    const tEl = c.querySelector('[class*="title"]');
    const rEl = c.querySelector('[class*="time"]');
    const blocks = it.material_show || it.material_original || [];
    const texts = [], imgs = [];
    (Array.isArray(blocks) ? blocks : []).forEach(b=>{
      if (!b) return;
      if (b.type === 2 && b.content) imgs.push(b.content);
      else if (b.content) texts.push(String(b.content));
    });
    // 展示层把原淘口令藏成 [淘宝请转链]，material_original 才是真实原文（含口令）
    const oblocks = it.material_original || [];
    const origs = [];
    (Array.isArray(oblocks) ? oblocks : []).forEach(b=>{
      if (!b) return;
      if (b.type !== 2 && b.content) origs.push(String(b.content));
    });
    const domText = (c.innerText||'').slice(0,800);
    out.push({
      id: btn.dataset.id || String(out.length),
      title: (it.title || (tEl?tEl.innerText:'') || '').trim(),
      rel: (rEl?rEl.innerText:'').trim(),
      text: texts.join('\n') || domText,
      orig: origs.join('\n'),
      imgs: imgs,
      pic: imgs[0] || it.pic || it.head_img || '',
      price: it.price || '',
      create_time: it.create_time || ''
    });
  });
  return JSON.stringify(out);
})()""", timeout=25)
        tips = json.loads(val or "[]")
        for t in tips:
            if t.get("pic") and not t["pic"].startswith("http"):
                t["pic"] = "https:" + t["pic"] if t["pic"].startswith("//") else t["pic"]
        self._last_tips = tips
        return tips

    def convert_tip(self, tip):
        """纯 API 转链一条线报。返回 dict{text, pict, price}；失败返回 None。"""
        text = tip.get("orig") or tip.get("text") or ""
        if not text.strip():
            return None
        d0 = direct_convert(text)
        if not d0:
            return None
        tpwd = (d0.get("tpwd") or "").strip()
        if not tpwd:
            return None
        # 旧口令整块替换成新口令（没有口令的文案则走后面的追加）
        out = TOKEN_RE.sub(tpwd, text, count=1)
        out = re.sub(r"<i>\s*#?\s*淘宝请转链\s*</i>", " ", out)
        out = re.sub(r"[#＃\[【]?\s*淘宝请转链\s*[》\]】]?", " ", out)
        out = re.sub(r"[ \t]+\n", "\n", out)
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        if tpwd not in out:
            out += "\n" + tpwd
        surl = d0.get("short_url") or ""
        if surl and surl not in out:
            out += "\n" + surl
        if tpwd not in out:
            return None  # 终检：成品里必须有带返利的新口令
        g = d0.get("goods_info") or {}
        pict = g.get("pict_url") or tip.get("pic") or ""
        price = g.get("final_promotion_price") or tip.get("price") or ""
        return {"text": out, "pict": pict, "price": price}


def rel_to_abs(rel):
    """「3分钟前」→ 绝对时间字符串。"""
    now = time.time()
    for unit, sec in (("秒", 1), ("分钟", 60), ("小时", 3600), ("天", 86400)):
        m = re.search(r"(\d+)\s*" + unit, rel or "")
        if m:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - int(m.group(1)) * sec))
    return time.strftime("%Y-%m-%d %H:%M:%S")


def to_deal(tip, converted):
    """转成与 build_site.normalize 同构的 deal。converted 可为 dict{text,pict,price} 或纯文案。"""
    tip_imgs = [x for x in (tip.get("imgs") or []) if isinstance(x, str)]
    for i, x in enumerate(tip_imgs):
        if not x.startswith("http") and x.startswith("//"):
            tip_imgs[i] = "https:" + x
    if isinstance(converted, dict):
        body = converted.get("text") or tip.get("text") or ""
        pict = converted.get("pict") or ""
        price = converted.get("price") or ""
    else:
        body = converted or tip.get("text") or ""
        pict = tip.get("pic") or ""
        price = tip.get("price") or ""
    if pict and not pict.startswith("http"):
        pict = "https:" + pict if pict.startswith("//") else pict
    # 只收线报自带图片（Boss 2026-09-07：转链接口的商品主图常是淘宝 listing 的场景图，
    # 插进头部会凭空多一张；仅当线报一张图都没有时才用主图兜底）
    images = tip_imgs if tip_imgs else ([pict] if pict else [])
    tid = tip.get("id") or hashlib.md5((tip.get("title", "") + str(tip.get("text", ""))[:100]).encode("utf-8")).hexdigest()[:12]
    t = str(tip.get("create_time") or "")
    try:
        if t.isdigit():
            tim = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(t)))
        elif re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", t):
            tim = t  # xb-list 接口返回的绝对时间直接用
        else:
            tim = rel_to_abs(tip.get("rel", ""))
    except Exception:
        tim = rel_to_abs(tip.get("rel", ""))
    return {
        "id": "dtk_" + str(tid),
        "platform": "1",
        "platform_name": "淘宝",
        "cate": "大淘客线报",
        "time": tim,
        "images": images,
        "price": price,
        "list": [{"content": body, "item_id": "", "coupon_url": ""}],
        "_originalContext": body,
    }


if __name__ == "__main__":
    d = Dtk()
    try:
        tips = d.fetch_tips()
        print(f"页面上 {len(tips)} 条线报")
        for t in tips[:3]:
            print(" -", t["id"], "|", t["title"][:30], "| 图:", len(t["imgs"]), "|", t["rel"])
        if tips:
            t0 = tips[0]
            print("\n单条测试：", t0["title"][:40])
            t1 = time.time()
            out = d.convert_tip(t0)
            print("耗时: %.1fs" % (time.time() - t1))
            if out:
                print("✅ 成品文案:")
                print(out["text"])
                print("图片:", (out["pict"] or "")[:80], "| 到手价:", out["price"])
            else:
                print("❌ 未转上")
    finally:
        d.close()
