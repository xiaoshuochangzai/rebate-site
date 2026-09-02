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


URL = "https://union.jd.com/proManager/custompromotion"


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

  let clicked = false;
  for (const b of document.querySelectorAll('button')) {
    if ((b.innerText||'').includes('获取推广链接') && !b.disabled) {
      b.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
      b.click();
      clicked = true;
      break;
    }
  }
  if (!clicked) return JSON.stringify({err:'NO_BUTTON'});

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
    """把一段线报文本送进万能转链，返回 ConvertSuperLink 解析后的 data 字段。"""
    _ensure_jd_tab()
    js = CONVERT_JS.replace("__TEXT__", json.dumps(material_text, ensure_ascii=False))
    res = relay_drive.evaluate(js, timeout=timeout)
    if not res.get("success"):
        return {"ok": False, "msg": "浏览器操控失败：" + str(res)[:200]}
    val = res.get("result", {}).get("value", "")
    try:
        parsed = json.loads(val)
    except Exception:
        return {"ok": False, "msg": "响应解析失败：" + val[:300]}
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
    """从好单库 deal 构造万能转链的输入文本：标题 + 商品链接。
    券链接不传，因为券不会被转链且会触发 failed 提示。"""
    title = deal.get("title") or deal.get("short_title") or "京东商品"
    lines = [title]
    for it in deal.get("list", []) or []:
        item_id = it.get("item_id") or ""
        if item_id.startswith("http"):
            lines.append(item_id)
        elif item_id:
            lines.append("https://item.jd.com/" + item_id + ".html")
    return "\n".join(lines).strip()


def convert_all_browser(deals, cfg=None):
    """逐条调用万能转链。返回 (enriched_deals, stats)。"""
    stats = {"ok": 0, "fail": 0, "skipped": 0}
    out = []
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
        print(f"  [{i+1}/{len(deals)}] 转链：{deal.get('title') or deal.get('short_title') or '?'[:30]}")
        r = convert_text(text)
        if not r.get("ok"):
            print(f"    ✗ {r.get('msg', '')[:80]}")
            stats["fail"] += 1
            out.append({**deal, "_converted": False, "_msg": r.get("msg", "")})
            continue
        data = r["data"]
        imgs = [normalize_jd_image(u) for u in (data.get("imgList") or [])]
        imgs = [u for u in imgs if u][:3]
        # 提取 formatContext 中的抢购链接
        promo = data.get("promotionUrl") or ""
        if not promo and data.get("formatContext"):
            import re as _re
            m = _re.search(r'https?://[^\s]+', data["formatContext"])
            if m:
                promo = m.group(0)
        # 把返利链接塞进每条 item
        for it in deal.get("list", []) or []:
            it["url"] = promo or it.get("coupon_url") or it.get("item_id")
            it["converted"] = bool(promo)
        deal["_formatContext"] = data.get("formatContext") or ""
        deal["_images"] = imgs
        deal["_price"] = data.get("price")
        deal["_purchasePrice"] = data.get("purchasePrice")
        deal["_couponAfterPrice"] = data.get("couponAfterPrice")
        deal["_shortTitle"] = data.get("shortTitle") or data.get("wlUnitPrice") or ""
        if imgs and not deal.get("images"):
            deal["images"] = imgs
        stats["ok" if promo else "fail"] += 1
        print(f"    ✓ 到手 ¥{data.get('couponAfterPrice') or data.get('purchasePrice') or '?'} | {promo[:50]}")
        out.append(deal)
    return out, stats


if __name__ == "__main__":
    sample = ("京东实时线报\n先领满400-80优惠卷：\n"
              "https://coupon.m.jd.com/coupons/show.action?linkKey=AAROH_xIpeffAs_-naABEFoe-xrm84x0GcVfr318zQczVIzkHx-DudzFix7t8YgLg8QJBJ2Ne2YjKzaGluxUyNBqD9hwwg&to=m.jd.com\n"
              "Dickies 秋季男款休闲鞋\nPLUS拍下296.8元\nhttps://u.jd.com/x1dhWMD")
    out = convert_text(sample)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:1500])