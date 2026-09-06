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
    for t in jd_bot.targets():
        if t.get("type") == "page" and "jingpinku.com" in (t.get("url") or ""):
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
        cdp0 = jd_bot.CDP(pages[0]["webSocketDebuggerUrl"])
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
    cdp = _get_cdp()
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
        except Exception as e:
            # 通道僵死自愈：重启专用浏览器再试一次
            print(f"    ! 通道异常自愈：{str(e)[:60]}", flush=True)
            try:
                cdp.close()
            except Exception:
                pass
            _kill_bot_browser()
            time.sleep(2)
            jd_bot.launch()
            time.sleep(4)
            try:
                cdp = _get_cdp()
                d = _page_convert(cdp, material)
                if d.get("ok") and d.get("out"):
                    apply_output(deal, d["out"])
                    stats["ok"] += 1
                    print(f"    ✓(自愈) {d['out'].splitlines()[0][:40]}", flush=True)
                else:
                    stats["fail"] += 1
                    print(f"    ✗ {str(d)[:80]}", flush=True)
            except Exception as e2:
                stats["fail"] += 1
                print(f"    ✗ 自愈后仍失败：{str(e2)[:80]}", flush=True)
                try:
                    cdp = _get_cdp()
                except Exception:
                    pass
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
