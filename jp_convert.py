# -*- coding: utf-8 -*-
"""精品库(jingpinku.com)智能转链引擎：走已登录专用浏览器的页面「转链」按钮流程。

接口形态与 jd_convert_browser.convert_all_browser 保持一致（drop-in 替换）：
    out, stats = jp_convert.convert_all_browser(deals)
转链结果就地写入：it.url（佣金链接）、coupon_url 长链替换、deal['_originalContext']（完整转换文案）。
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

JP_URL = "https://www.jingpinku.com/tools/chain_link.do"
_DELAY = float(os.environ.get("JP_CONV_DELAY", "4"))

URL_RE = re.compile(r'https?://[^\s，,。；、）】\u3011]+')

# ---- 登录态失效熔断（Boss 2026-09-11：登录掉了别再反复开关浏览器） ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGIN_LOST_FILE = os.path.join(BASE_DIR, "jp_login_lost.txt")
LOGIN_COOLDOWN = 1800          # 登录态失效后 30 分钟内不再尝试转链/重启浏览器
_LOGIN = {"lost_at": 0.0}


def _mark_login_lost(reason=""):
    now = time.time()
    if not _LOGIN["lost_at"]:
        _LOGIN["lost_at"] = now
        print(f"    !! 精品库登录态失效（{reason[:40]}）——停止本轮全部转链，"
              f"{LOGIN_COOLDOWN//60} 分钟内不再重启浏览器", flush=True)
        print("    !! 处理：打开自动化浏览器登录 jingpinku.com 后，删除 jp_login_lost.txt 或重启监控", flush=True)
        try:
            with open(LOGIN_LOST_FILE, "w", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)) + " " + reason[:80])
        except Exception:
            pass


def _login_lost():
    """登录态是否处于失效冷却期（冷却结束自动恢复尝试）。"""
    t = _LOGIN["lost_at"]
    if not t:
        # 进程首次启动：若磁盘上有未过期的标记文件（上次留下的），也认
        try:
            with open(LOGIN_LOST_FILE, encoding="utf-8") as f:
                s = f.read().strip()
            m = time.mktime(time.strptime(s[:19], "%Y-%m-%d %H:%M:%S"))
            _LOGIN["lost_at"] = m
            t = m
        except Exception:
            return False
    if time.time() - t < LOGIN_COOLDOWN:
        return True
    # 冷却结束：清标记，恢复尝试
    _LOGIN["lost_at"] = 0.0
    try:
        os.remove(LOGIN_LOST_FILE)
    except Exception:
        pass
    return False


def _is_login_error(d):
    """页面返回的失败信息是否属于「未登录/被踢/风控频繁」。"""
    if not isinstance(d, dict):
        return False
    s = str(d.get("toast") or "")
    if d.get("err") in ("NO_PAGE", "NO_BUTTON"):
        return True
    return any(k in s for k in ("登录", "频繁", "验证", "风控"))


def _kill_bot_browser():
    if os.name != "nt":
        return
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -like '*jd-bot-profile*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, timeout=30)
    except Exception:
        pass


def _find_jp_target():
    """只认精品库【转链页 chain_link】，避免首页被误当转链页（首页没有输入框会 NO_PAGE，
    进而触发无谓的「通道异常自愈」重启浏览器 —— Boss 2026-09-11 反馈的反复开关浏览器来源之一）。"""
    for t in jd_bot.targets():
        u = t.get("url") or ""
        if t.get("type") == "page" and "jingpinku.com" in u and "chain_link" in u:
            return t
    return None


def _get_cdp():
    if not jd_bot.is_running():
        jd_bot.launch()
        time.sleep(3)
    t = _find_jp_target()
    if not t:
        pages = [x for x in jd_bot.targets() if x.get("type") == "page"]
        if not pages:
            raise RuntimeError("浏览器没有标签页")
        # 优先复用已经在 jingpinku 域下的标签页（如被重定向到首页的那个），把它导航回转链页；
        # 没有才退而用第一个标签页。避免误改用户其它标签页。
        jp_like = next((x for x in pages if "jingpinku.com" in (x.get("url") or "")), None)
        page = jp_like or pages[0]
        cdp0 = jd_bot.CDP(page["webSocketDebuggerUrl"])
        cdp0.navigate(JP_URL)
        cdp0.close()
        time.sleep(5)
        t = _find_jp_target()
        if not t:
            raise RuntimeError("精品库转链页打开失败")
    return jd_bot.CDP(t["webSocketDebuggerUrl"])


_CONVERT_JS = r'''
(async () => {
  const ta = document.querySelector('.toolContent_left');
  if (!ta) return JSON.stringify({err:'NO_PAGE', url: location.href.slice(0,80)});
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(ta, __M__);
  ta.dispatchEvent(new Event('input', {bubbles:true}));
  await new Promise(r=>setTimeout(r,400));
  const right = document.querySelector('.toolContent_right');
  if (right) right.innerText = '';
  const btn = document.querySelector('.transferrinButton');
  if (!btn) return JSON.stringify({err:'NO_BUTTON'});
  btn.click();
  for (let i=0;i<40;i++) {
    const txt = (document.querySelector('.toolContent_right')||{innerText:''}).innerText.trim();
    if (txt) return JSON.stringify({ok:true, out:txt});
    await new Promise(r=>setTimeout(r,500));
  }
  const m = (document.body.innerText.match(/[^\n]*(登录|频繁|错误|失败|联盟)[^\n]*/)||[''])[0];
  return JSON.stringify({ok:false, out:'', toast:m.slice(0,100)});
})()
'''


def _page_convert(cdp, material):
    js = _CONVERT_JS.replace("__M__", json.dumps(material, ensure_ascii=False))
    val = cdp.evaluate(js, timeout=90)
    d = json.loads(val)
    if d.get("err"):
        raise RuntimeError(d["err"])
    return d


def build_material(deal):
    """原始线报全量文案（文字 + 券链 + 商品链，按原顺序）。"""
    lines = []
    for it in deal.get("list", []) or []:
        c = (it.get("content") or "").strip()
        if c:
            lines.append(c)
        cu = (it.get("coupon_url") or "").strip()
        if cu:
            lines.append(cu)
        iid = (it.get("item_id") or "").strip()
        if iid:
            lines.append(iid if iid.startswith("http")
                         else "https://item.jd.com/" + iid + ".html")
    return "\n".join(lines).strip()


def apply_output(deal, out_text):
    """按出现顺序把转换后的链接映射回各条目。"""
    orig = []
    for it in deal.get("list", []) or []:
        m = URL_RE.search(it.get("coupon_url") or "")
        if m:
            orig.append(("coupon", m.group(0)))
        iid = (it.get("item_id") or "").strip()
        if iid.startswith("http"):
            orig.append(("item", iid))
    out_urls = URL_RE.findall(out_text)
    for (kind, ourl), nurl in zip(orig, out_urls):
        if kind == "coupon":
            for it in deal.get("list", []) or []:
                if ourl in (it.get("coupon_url") or ""):
                    it["coupon_url"] = it["coupon_url"].replace(ourl, nurl)
        else:
            for it in deal.get("list", []) or []:
                if (it.get("item_id") or "").strip() == ourl:
                    it["url"] = nurl
                    it["converted"] = True
    # 没配上对的商品条目：统一给第一个转链
    promo = next((u for u in out_urls if "u.jd.com" in u), "")
    for it in deal.get("list", []) or []:
        if not it.get("url"):
            iid = (it.get("item_id") or "").strip()
            if iid.startswith("http"):
                it["url"] = promo or iid
                it["converted"] = bool(promo)
    deal["_originalContext"] = out_text


def convert_all_browser(deals, cfg=None, on_progress=None):
    """批量转链（drop-in：与 jd_convert_browser 同签名同返回）。"""
    stats = {"ok": 0, "fail": 0, "skipped": 0}
    out = []
    # 登录态失效冷却期内：直接跳过，不碰浏览器（防反复开关，Boss 2026-09-11）
    if _login_lost():
        print(f"  !! 精品库登录态失效冷却中，跳过本轮转链（{len(deals)} 条留待转队列）", flush=True)
        stats["skipped"] = len(deals)
        return deals, stats
    cdp = _get_cdp()
    last_kill = 0.0  # 浏览器重启冷却（防通道抖动时反复启关浏览器，Boss 2026-09-07）
    for i, deal in enumerate(deals):
        material = build_material(deal)
        print(f"  [{i+1}/{len(deals)}] 精品库转链：{material.splitlines()[0][:30]}", flush=True)
        try:
            d = _page_convert(cdp, material)
            if d.get("ok") and d.get("out"):
                apply_output(deal, d["out"])
                stats["ok"] += 1
                print(f"    ✓ {d['out'].splitlines()[0][:40]}", flush=True)
            else:
                stats["fail"] += 1
                print(f"    ✗ {str(d.get('toast') or d)[:80]}", flush=True)
                if _is_login_error(d):
                    _mark_login_lost(str(d.get("toast") or ""))
                    stats["skipped"] += len(deals) - i - 1
                    break          # 登录掉了：整轮放弃，别再一条条试、别再重启浏览器
        except Exception as e:
            if _login_lost():
                stats["skipped"] += len(deals) - i
                break
            # 通道僵死自愈：浏览器重启带 180s 冷却，冷却期内只重连通道（防反复启关）
            print(f"    ! 通道异常自愈：{str(e)[:60]}", flush=True)
            try:
                cdp.close()
            except Exception:
                pass
            now = time.time()
            if now - last_kill >= 180:
                last_kill = now
                _kill_bot_browser()
                time.sleep(2)
                jd_bot.launch()
                time.sleep(4)
            else:
                print("    ! 浏览器重启冷却中（180s 内不重复启关），仅重连通道", flush=True)
                time.sleep(5)
            try:
                cdp = _get_cdp()
            except Exception:
                pass
            try:
                d = _page_convert(cdp, material)
                if d.get("ok") and d.get("out"):
                    apply_output(deal, d["out"])
                    stats["ok"] += 1
                    print(f"    ✓(自愈) {d['out'].splitlines()[0][:40]}", flush=True)
                else:
                    stats["fail"] += 1
                    print(f"    ✗ {str(d)[:80]}", flush=True)
                    if _is_login_error(d):
                        _mark_login_lost(str(d.get("toast") or ""))
                        stats["skipped"] += len(deals) - i - 1
                        break
            except Exception as e2:
                stats["fail"] += 1
                print(f"    ✗ 自愈后仍失败：{str(e2)[:80]}", flush=True)
                try:
                    cdp = _get_cdp()
                except Exception:
                    pass
        if _login_lost():
            break
        out.append(deal)
        if on_progress:
            try:
                on_progress(out, stats)
            except Exception:
                pass
        time.sleep(_DELAY)
    return out, stats


if __name__ == "__main__":
    demo = {"id": "test", "list": [
        {"content": "测试商品", "item_id": "https://u.jd.com/xOOuON9", "coupon_url": ""},
    ]}
    out, stats = convert_all_browser([demo])
    print(stats, json.dumps(out[0], ensure_ascii=False)[:300])
