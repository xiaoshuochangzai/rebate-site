# -*- coding: utf-8 -*-
"""大淘客线报「转链复制」引擎（镜像 jp_convert.py 的定位）。

数据源：dataoke.com/xp/xb 线报页（已登录、已绑返利，profile 常驻）
转链：真实鼠标点击每张卡的「转链复制」→ 页面调 pwd-analysis →
     剪贴板里出现绑定 Boss 返利的成品文案（淘口令已替换）
前置：每次会话先 CDP 授权剪贴板读写（Boss 曾误拒过弹窗，CDP 授权免点击）

红线：转链失败（剪贴板没变化）的线报绝不上站。
"""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

DTK_URL = "https://www.dataoke.com/xp/xb"
POLL_SEC = 12  # 单条转链最长等待


def _find_tab():
    return jd_bot.find_page("dataoke.com")


def _open_tab():
    t = _find_tab()
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
        t = _find_tab()
        if t:
            return t
    raise RuntimeError("打开大淘客标签页失败")


def grant_clipboard(ws_call):
    """CDP 授权剪贴板读写（每次会话调一次即可）。"""
    try:
        ws_call("Browser.grantPermissions", {
            "permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"],
            "origin": "https://www.dataoke.com",
        })
        return True
    except Exception:
        return False


class Dtk:
    """大淘客转链器。用法：
        d = Dtk()
        tips = d.fetch_tips()          # [{key,title,rel,content}]
        text = d.convert_tip(tips[0])  # 成品文案（失败返回 None）
    """

    def __init__(self):
        self.t = _open_tab()
        self.ws = jd_bot.websocket.create_connection(self.t["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
        self.mid = [0]
        self._granted = False

    # ---- CDP 基础 ----
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
    def ensure_granted(self):
        if not self._granted:
            if not grant_clipboard(self.call):
                raise RuntimeError("剪贴板授权失败")
            self._granted = True

    def fetch_tips(self):
        """解析 DOM 返回线报列表（页面上当前可见的）。"""
        val = self.ev(r"""
(function(){
  const out = [];
  document.querySelectorAll('[class*="tip-grid-style-tiplist"]').forEach((c,i)=>{
    const q = s => c.querySelector('[class*="'+s+'"]');
    const tEl = q('title'), tmEl = q('time');
    const btns = [...c.querySelectorAll('[class*="btn2"]')];
    const convBtn = btns.find(b=>(b.innerText||'').includes('转链复制'));
    // 文案 = 标题行之后、按钮之前的文本
    const full = (c.innerText||'');
    out.push({
      idx: i,
      title: tEl ? tEl.innerText.trim() : '',
      rel: tmEl ? tmEl.innerText.trim() : '',
      text: full.slice(0, 800),
      hasBtn: !!convBtn
    });
  });
  return JSON.stringify(out);
})()""", timeout=20)
        return json.loads(val or "[]")

    def _click_convert(self, idx):
        """真实鼠标点击第 idx 张卡的「转链复制」。"""
        loc = json.loads(self.ev(r"""
(function(){
  const cards = document.querySelectorAll('[class*="tip-grid-style-tiplist"]');
  const c = cards[%d];
  if(!c) return '{}';
  const btn = [...c.querySelectorAll('[class*="btn2"]')].find(b=>(b.innerText||'').includes('转链复制'));
  if(!btn) return '{}';
  c.scrollIntoView({block:'center'});
  const r = btn.getBoundingClientRect();
  return JSON.stringify({x:r.x+r.width/2, y:r.y+r.height/2});
})()""" % idx, timeout=20) or "{}")
        if not loc:
            return False
        self.call("Page.bringToFront")
        time.sleep(0.5)
        x, y = loc["x"], loc["y"]
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none", "buttons": 0})
        time.sleep(0.25)
        self.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1, "buttons": 1})
        time.sleep(0.12)
        self.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1, "buttons": 0})
        return True

    def _read_clip(self):
        # readText 要求文档有焦点，先 bringToFront
        try:
            self.call("Page.bringToFront")
            time.sleep(0.3)
        except Exception:
            pass
        return self.ev("navigator.clipboard.readText().then(t=>t).catch(e=>'__DENY__:'+e.message)", timeout=15)

    def convert_tip(self, tip):
        """转链一条线报，返回成品文案；失败返回 None。"""
        self.ensure_granted()
        pre = self._read_clip()
        if pre.startswith("__DENY__"):
            raise RuntimeError("剪贴板权限丢失：" + pre[:80])
        if not self._click_convert(tip["idx"]):
            return None
        deadline = time.time() + POLL_SEC
        last = pre
        while time.time() < deadline:
            time.sleep(0.8)
            cur = self._read_clip()
            if cur.startswith("__DENY__"):
                time.sleep(0.5); continue
            last = cur
            # 页面先复制原文、再覆盖为转链后文案；转链完成时剪贴板会再次变化。
            # 稳妥判定：与点击前不同 且 长度像文案（>30）
            if cur != pre and len(cur.strip()) > 30:
                return cur.strip()
        return last.strip() if last != pre else None


def rel_to_abs(rel):
    """「3分钟前」→ 绝对时间字符串。"""
    import re
    now = time.time()
    m = re.search(r"(\d+)\s*秒", rel or "")
    if m: return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - int(m.group(1))))
    m = re.search(r"(\d+)\s*分钟", rel or "")
    if m: return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - int(m.group(1)) * 60))
    m = re.search(r"(\d+)\s*小时", rel or "")
    if m: return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - int(m.group(1)) * 3600))
    m = re.search(r"(\d+)\s*天", rel or "")
    if m: return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - int(m.group(1)) * 86400))
    return time.strftime("%Y-%m-%d %H:%M:%S")


def to_deal(tip, converted_text):
    """转成与 build_site.normalize 同构的 deal。"""
    body = converted_text or tip["text"]
    did = "dtk_" + hashlib.md5((tip["title"] + "|" + tip["text"][:120]).encode("utf-8")).hexdigest()[:12]
    return {
        "id": did,
        "platform": "1",
        "platform_name": "淘宝",
        "cate": "大淘客线报",
        "time": rel_to_abs(tip.get("rel", "")),
        "images": [],
        "list": [{"content": body, "item_id": "", "coupon_url": ""}],
        "_originalContext": body,
    }


if __name__ == "__main__":
    d = Dtk()
    try:
        tips = d.fetch_tips()
        print(f"页面上 {len(tips)} 条线报")
        if tips:
            t0 = tips[0]
            print("单条测试：", t0["title"][:40], "|", t0["rel"])
            out = d.convert_tip(t0)
            if out:
                print("\n✅ 转链成功，成品文案：\n" + out[:500])
                print("\n→ deal 结构预览：")
                dl = to_deal(t0, out)
                print(json.dumps({k: v for k, v in dl.items() if k != "list"}, ensure_ascii=False, indent=1))
            else:
                print("❌ 转链失败（剪贴板无变化），不上站")
    finally:
        d.close()
