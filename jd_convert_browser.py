# -*- coding: utf-8 -*-
"""通过本地浏览器中继操控京东联盟「万能转链」网页版，把好单库抓来的原始线报文本
批量转成带返利链接 + 商品图 + 价格的格式化数据。

底层 API：京东联盟 web 后端 ConvertSuperLink（api.m.jd.com），h5st 由浏览器自动生成。
本模块不直接调用任何 Open Platform 接口，避开了 403「无访问权限」和 2000 配额限制。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import relay_drive

# 优先走「专用转链浏览器」（独立 Chrome + CDP，不干扰用户主浏览器）；
# 专用浏览器没起来时，自动回退到中继续航模式。
try:
    import jd_bot
except Exception:  # pragma: no cover
    jd_bot = None

_CDP = None


def _get_cdp():
    """拿到专用浏览器的 CDP 连接（带复用与失效重连）。"""
    global _CDP
    if jd_bot is None:
        return None
    if _CDP is not None:
        try:
            _CDP.evaluate("1", timeout=10)
            return _CDP
        except Exception:
            _CDP = None
    try:
        if not jd_bot.is_running():
            return None
        cdp, _t = jd_bot.connect_browser()
        _CDP = cdp
        return _CDP
    except Exception:
        return None


URL = "https://union.jd.com/proManager/custompromotion"

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "link_cache.json")
_cache = None


def _cache_load():
    global _cache
    if _cache is None:
        try:
            with open(CACHE_FILE, encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def _cache_save():
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False)
    except Exception as e:
        print(f"[warn] 缓存写入失败: {e}")


def _find_jd_tab():
    info = relay_drive.list_tabs()
    tabs = info.get("tabs", []) or []
    for t in tabs:
        u = t.get("url", "")
        if "union.jd.com/proManager/custompromotion" in u:
            return t
    return None


def _ensure_jd_tab():
    tab = _find_jd_tab()
    if not tab:
        raise RuntimeError(
            f"浏览器没开万能转链页面。请先打开 {URL} 并保持登录，再跑一次。"
        )
    relay_drive.switch_tab(tab["id"])
    time.sleep(1)
    return tab


CONVERT_JS = r"""
(async () => {
  const MATERIAL = __TEXT__;
  window.__resp = [];
  const of = window.fetch;
  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : input.url;
    const p = of.apply(this, arguments);
    p.then(r => {
      r.clone().text().then(t => {
        window.__resp.push({k:'f', u:url, s:r.status, b:t.slice(0,12000)});
      }).catch(()=>{});
    }).catch(()=>{});
    return p;
  };
  const XO = XMLHttpRequest.prototype.open;
  const XS = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(m, url) {
    this.__cap = {k:'x', m, u:url, body:'', resp:''};
    return XO.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function(b) {
    if (this.__cap) {
      this.__cap.body = (b||'').slice(0,1500);
      const orig = this.onreadystatechange;
      this.onreadystatechange = function() {
        if (this.readyState === 4) {
          this.__cap.resp = (this.responseText||'').slice(0,12000);
          this.__cap.status = this.status;
        }
        if (orig) orig.apply(this, arguments);
      };
      window.__resp.push(this.__cap);
    }
    return XS.apply(this, arguments);
  };

  for (let i=0;i<20;i++) {
    const ta = document.querySelectorAll('textarea')[0];
    if (ta && ta.offsetParent !== null) break;
    await new Promise(r => setTimeout(r, 300));
  }
  const tas = document.querySelectorAll('textarea');
  const ta = tas[0];
  if (!ta) return JSON.stringify({err:'NO_TEXTAREA', taCount: tas.length});

  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(ta, MATERIAL);
  ta.dispatchEvent(new Event('input', {bubbles:true}));
  ta.dispatchEvent(new Event('change', {bubbles:true}));
  // React 受控组件需要一拍才能把按钮从 disabled 放开
  await new Promise(r => setTimeout(r, 500));
  ta.focus();

  let clicked = false;
  for (let w=0; w<12 && !clicked; w++) {
    for (const b of document.querySelectorAll('button')) {
      if ((b.innerText||'').includes('获取推广链接') && !b.disabled) {
        b.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
        b.click();
        clicked = true;
        break;
      }
    }
    if (!clicked) {
      // 再补一次填充，防止受控组件把值吞了
      setter.call(ta, MATERIAL);
      ta.dispatchEvent(new Event('input', {bubbles:true}));
      await new Promise(r => setTimeout(r, 300));
    }
  }
  if (!clicked) {
    const diag = Array.from(document.querySelectorAll('button'))
      .map(function(b){ return (b.innerText||'').trim().split('\n').join(' ') + '|dis=' + b.disabled; })
      .filter(Boolean).slice(0, 10);
    return JSON.stringify({err:'NO_BUTTON', taValueLen:(ta.value||'').length, btns:diag});
  }

  let target = null;
  for (let i=0;i<50;i++) {
    target = window.__resp.find(x => x.u && x.u.includes('ConvertSuperLink') && x.resp);
    if (target) break;
    await new Promise(r => setTimeout(r, 200));
  }
  if (!target) return JSON.stringify({err:'NO_RESPONSE', respCount: window.__resp.length});

  return target.resp;
})();
"""


def convert_text(material_text, timeout=30):
    """把一段线报文本送进万能转链，返回 ConvertSuperLink 解析后的 data 字段。

    驱动方式：优先 CDP 专用浏览器（不干扰用户），失败才用中继续航。
    """
    js = CONVERT_JS.replace("__TEXT__", json.dumps(material_text, ensure_ascii=False))
    cdp = _get_cdp()
    if cdp is not None:
        try:
            val = cdp.evaluate(js, timeout=max(timeout, 60))
        except Exception as e:
            return {"ok": False, "msg": "专用浏览器转链异常：" + str(e)[:200]}
    else:
        _ensure_jd_tab()
        res = relay_drive.evaluate(js, timeout=timeout)
        if not res.get("success"):
            return {"ok": False, "msg": "浏览器操控失败：" + str(res)[:200]}
        val = res.get("result", {}).get("value", "")
    try:
        parsed = json.loads(val)
    except Exception:
        return {"ok": False, "msg": "响应解析失败：" + str(val)[:300]}
    if isinstance(parsed, dict) and "err" in parsed:
        return {"ok": False, "msg": parsed["err"]}
    try:
        body = json.loads(parsed) if isinstance(parsed, str) else parsed
    except Exception:
        body = parsed
    if not isinstance(body, dict) or body.get("code") != 200:
        return {"ok": False, "msg": "上游返回非 200: " + str(body)[:300]}
    return {"ok": True, "data": body.get("data", {})}


def normalize_jd_image(url):
    if not url:
        return ""
    if url.startswith("http"):
        return url
    if url.startswith("jfs/"):
        return "https://img12.360buyimg.com/imgtools/" + url
    return url


def _build_material(deal):
    """从好单库 deal 构造万能转链的输入文本。
    按 Boss 要求：抓到的原始线报（文字 + 券链接 + 商品链接）全量按原始顺序复制进去，
    就是好单库「复制文案」的原样内容。"""
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


def convert_all_browser(deals, cfg=None, on_progress=None):
    """逐条调用万能转链。返回 (enriched_deals, stats)。

    - 每条之间默认间隔 2.5 秒（环境变量 JD_CONV_DELAY 可调），防限流
    - 检测到「访问频繁/NO_RESPONSE」自动退避 120s*attempt 重试（最多3次）
    - 转链结果按 material 文本 md5 缓存到 link_cache.json，重跑秒回
    - on_progress(done_deals, stats)：每完成一条回调（用于增量落盘/推送）
    """
    import hashlib

    stats = {"ok": 0, "fail": 0, "skipped": 0}
    out = []
    delay = float(os.environ.get("JD_CONV_DELAY", "2.5"))
    cache = _cache_load()

    def apply_result(deal, data):
        imgs = [normalize_jd_image(u) for u in (data.get("imgList") or [])]
        imgs = [u for u in imgs if u][:3]
        promo = data.get("promotionUrl") or ""
        if not promo and data.get("formatContext"):
            import re as _re
            m = _re.search(r'https?://[^\s]+', data["formatContext"])
            if m:
                promo = m.group(0)
        for it in deal.get("list", []) or []:
            it["url"] = promo or it.get("coupon_url") or it.get("item_id")
            it["converted"] = bool(promo)
        # 券长链(coupon.m.jd.com) → 3.cn 短链：partialSuccessMsg 里的原始长链
        # 与 failedUrlList 短链按出现顺序一一对应
        import re as _re
        shorts = [s for s in (data.get("failedUrlList") or []) if isinstance(s, str)]
        longs = _re.findall(r'https?://[^\s\[\]】，,\s]+', data.get("partialSuccessMsg") or "")
        seen, uniq_longs = set(), []
        for u in longs:
            if u not in seen:
                seen.add(u)
                uniq_longs.append(u)
        for lo, sh in zip(uniq_longs, shorts):
            for it in deal.get("list", []) or []:
                cu = it.get("coupon_url") or ""
                if lo in cu:
                    it["coupon_url"] = cu.replace(lo, sh)
        deal["_originalContext"] = data.get("originalContext") or ""
        deal["_formatContext"] = data.get("formatContext") or ""
        deal["_images"] = imgs
        deal["_price"] = data.get("price")
        deal["_purchasePrice"] = data.get("purchasePrice")
        deal["_couponAfterPrice"] = data.get("couponAfterPrice")
        deal["_shortTitle"] = data.get("shortTitle") or data.get("wlUnitPrice") or ""
        if imgs and not deal.get("images"):
            deal["images"] = imgs
        return promo

    for i, deal in enumerate(deals):
        if str(deal.get("platform")) != "2":
            for it in deal.get("list", []) or []:
                if it.get("coupon_url") or it.get("item_id"):
                    it["url"] = it.get("coupon_url") or it.get("item_id")
                    it["converted"] = False
                    stats["skipped"] += 1
            out.append(deal)
            continue
        text = _build_material(deal)
        if not text:
            out.append({**deal, "_converted": False})
            stats["fail"] += 1
            continue
        print(f"  [{i+1}/{len(deals)}] 转链：{_build_material(deal).splitlines()[0][:30]}")
        key = hashlib.md5(text.encode("utf-8")).hexdigest()
        cached = cache.get(key)
        if cached:
            promo = apply_result(deal, cached)
            stats["ok" if promo else "fail"] += 1
            print(f"    ✓(缓存) {promo[:50]}")
            out.append(deal)
            if on_progress:
                try:
                    on_progress(out, stats)
                except Exception as e:
                    print(f"    [warn] progress: {e}")
            continue

        attempt = 0
        while True:
            r = convert_text(text)
            if r.get("ok"):
                data = r["data"]
                cache[key] = data
                _cache_save()
                promo = apply_result(deal, data)
                stats["ok" if promo else "fail"] += 1
                print(f"    ✓ 到手 ¥{data.get('couponAfterPrice') or data.get('purchasePrice') or '?'} | {promo[:50]}")
                out.append(deal)
                break
            msg = str(r.get("msg", ""))
            attempt += 1
            if ("频繁" in msg) or ("NO_RESPONSE" in msg) or ("NO_BUTTON" in msg):
                if attempt <= 3:
                    wait = 120 * attempt
                    print(f"    ⏳ 疑似限流（{msg[:60]}），暂停 {wait}s 后重试 {attempt}/3")
                    time.sleep(wait)
                    continue
            print(f"    ✗ {msg[:100]}")
            stats["fail"] += 1
            out.append({**deal, "_converted": False, "_msg": msg})
            break

        if on_progress:
            try:
                on_progress(out, stats)
            except Exception as e:
                print(f"    [warn] progress: {e}")
        time.sleep(delay)
    return out, stats


if __name__ == "__main__":
    sample = ("京东实时线报\n先领满400-80优惠卷：\n"
              "https://coupon.m.jd.com/coupons/show.action?linkKey=AAROH_xIpeffAs_-naABEFoe-xrm84x0GcVfr318zQczVIzkHx-DudzFix7t8YgLg8QJBJ2Ne2YjKzaGluxUyNBqD9hwwg&to=m.jd.com\n"
              "Dickies 秋季男款休闲鞋\nPLUS拍下296.8元\nhttps://u.jd.com/x1dhWMD")
    out = convert_text(sample)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:1500])