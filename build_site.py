# -*- coding: utf-8 -*-
"""好单库线报爬虫 + 转链 + 静态站生成。

流程：
1. 抓取 haodanku 线报接口（JSON，无需登录）
2. 归一化：平台 / 时间 / 文案行 / 商品链接 / 券链接 / 图片
3. 京东链接走联盟「万能转链」（浏览器自动化，无 API 权限要求）
4. 生成 site/index.html（数据内嵌，单文件可直接部署）+ site/deals.json
"""
import json
import os
import time
import urllib.request

import jd_convert_browser as jd_convert

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.join(BASE_DIR, "site")
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Referer": "https://www.haodanku.com/activity/tip_off",
    "X-Requested-With": "XMLHttpRequest",
}
PLATFORM_MAP = {"1": "淘宝", "2": "京东", "3": "飞猪"}


def fetch_page(cfg, page_no):
    url = (f"{cfg['crawl']['source']}?page_no={page_no}"
           f"&page_size={cfg['crawl']['page_size']}&is_images=1")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def normalize(item):
    lines = []
    for it in item.get("list", []) or []:
        lines.append({
            "content": it.get("content") or "",
            "item_id": it.get("item_id") or "",
            "coupon_url": it.get("coupon_url") or "",
        })
    return {
        "id": item.get("wire_id", ""),
        "platform": str(item.get("platform", "")),
        "platform_name": PLATFORM_MAP.get(str(item.get("platform")), item.get("cate_id", "其他")),
        "cate": item.get("cate_id", ""),
        "time": item.get("starttime", ""),
        "images": item.get("images", []) or [],
        "list": lines,
    }


def build_html(deals, cfg, convert_stats):
    data_json = json.dumps(deals, ensure_ascii=False)
    stats = json.dumps(convert_stats, ensure_ascii=False)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    ts_hm = time.strftime("%H:%M")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>实时优惠线报</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--text:#1f2329;--sub:#8a9099;--line:#eceef1;--jd:#e1251b;--tb:#ff5000;--ok:#11a34a}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}}
header{{position:sticky;top:0;z-index:9;background:#fff;border-bottom:1px solid var(--line);padding:12px 16px}}
h1{{margin:0 0 8px;font-size:18px}}
.bar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.chip{{padding:5px 14px;border:1px solid var(--line);border-radius:16px;background:#fff;cursor:pointer;font-size:13px}}
.chip.on{{background:var(--text);color:#fff;border-color:var(--text)}}
input#kw{{flex:1;min-width:140px;padding:6px 12px;border:1px solid var(--line);border-radius:16px;outline:none}}
.meta{{color:var(--sub);font-size:12px;margin-top:6px}}
main{{padding:16px;display:grid;gap:16px;grid-template-columns:repeat(4,1fr)}}
@media(max-width:1100px){{main{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:640px){{main{{grid-template-columns:repeat(2,1fr)}}}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;display:flex;flex-direction:column;transition:transform .2s,box-shadow .2s}}
.card:hover{{transform:translateY(-2px);box-shadow:0 4px 14px rgba(0,0,0,.08)}}
.head{{display:flex;justify-content:flex-start;align-items:center;margin-bottom:8px}}
.time{{color:var(--sub);font-size:12px}}
.imgs{{display:flex;gap:6px;overflow:auto;margin-bottom:10px}}
.imgs img{{width:100%;height:auto;aspect-ratio:1/1;object-fit:cover;border-radius:8px;border:1px solid var(--line);flex:0 0 30%}}
.line{{margin:5px 0}}
.btn{{display:inline-block;padding:5px 12px;border-radius:6px;background:var(--text);color:#fff;text-decoration:none;font-size:13px}}
.btn.coupon{{background:var(--tb)}}
.actions{{margin-top:12px;display:flex;gap:8px}}
.copy{{flex:1;padding:7px;border:1px solid var(--line);background:#fff;border-radius:6px;cursor:pointer;font-size:13px}}
.note{{color:var(--sub);font-size:11px;margin-top:8px}}
.price{{color:var(--jd);font-weight:bold;font-size:26px;margin:2px 0 6px;line-height:1.2}}
.price small{{color:var(--sub);font-weight:normal;font-size:13px;text-decoration:line-through;margin-left:8px}}
.rlink{{margin-top:auto;padding-top:8px;font-size:11px;color:var(--sub);word-break:break-all;cursor:pointer;border-top:1px dashed var(--line)}}
.rlink:hover{{color:var(--jd)}}
footer{{padding:20px;text-align:center;color:var(--sub);font-size:12px}}
#toast{{position:fixed;left:50%;bottom:40px;transform:translateX(-50%);background:#111;color:#fff;padding:10px 18px;border-radius:20px;font-size:14px;opacity:0;transition:opacity .3s;pointer-events:none;z-index:99}}
#top{{position:fixed;right:22px;bottom:32px;width:44px;height:44px;border-radius:50%;background:var(--jd);color:#fff;border:none;font-size:20px;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.22);display:none;z-index:98}}
</style>
</head>
<body>
<header>
  <h1>实时优惠线报</h1>
  <div class="bar">
    <span class="chip on" data-p="all">全部</span>
    <span class="chip" data-p="2">京东</span>
    <input id="kw" placeholder="搜索商品关键词">
  </div>
  <div class="meta">实时更新 · 截至 {ts_hm} · 今日已收录 <b id="cnt">0</b> 条 · 转链成功 {convert_stats.get('ok',0)} 条</div>
</header>
<main id="list"></main>
<footer>数据每小时自动更新 · 双击卡片复制整条文an · 单击底部链接复制返利链接</footer>
<button id="top" title="回到顶部">↑</button>
<script>
const DEALS = {data_json};
const STATS = {stats};
let filter = 'all', kw = '';
function esc(s){{return String(s||'').replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]);}}
function cls(p){{return p==='2'?'jd':(p==='1'?'tb':'other');}}
function rel(t){{
  if(!t) return '';
  const d = new Date(String(t).replace(/-/g,'/'));
  if (isNaN(d.getTime())) return String(t);
  const s = (Date.now()-d.getTime())/1000;
  if (s < 60) return '刚刚';
  if (s < 3600) return Math.floor(s/60)+'分钟前';
  if (s < 86400) return Math.floor(s/3600)+'小时前';
  return Math.floor(s/86400)+'天前';
}}
function render(){{
  const list = DEALS.filter(d=>(filter==='all'||d.platform===filter)
    && (!kw || JSON.stringify(d).toLowerCase().includes(kw.toLowerCase())));
  document.getElementById('cnt').textContent = list.length;
  document.getElementById('list').innerHTML = list.map(d=>{{
    const imgs = (d.images && d.images.length) ? `<div class="imgs">${{d.images.slice(0,4).map(u=>`<img src="${{esc(u)}}" referrerpolicy="no-referrer" loading="lazy">`).join('')}}</div>`:'';
    // 优先用 _formatContext（万能转链给的完整文案），否则用原始 list 拼
    const copyText = d._formatContext || (d.list.map(it=>it.content||it.url||it.coupon_url||'').filter(Boolean).join('\\n'));
    const lines = d.list.map(it=>{{
      if(it.item_id || it.coupon_url){{
        const href = it.url || it.coupon_url || it.item_id;
        const label = it.coupon_url ? '立即领券' : '抢购商品';
        const bcls = it.coupon_url ? 'btn coupon' : 'btn';
        return `<div class="line"><a class="${{bcls}}" href="${{esc(href)}}" target="_blank" rel="noopener">${{label}}</a></div>`;
      }}
      return `<div class="line">${{esc(it.content)}}</div>`;
    }}).join('');
    // 价格：京东的有 _couponAfterPrice
    let priceHtml = '';
    if (d._couponAfterPrice && d.platform === '2') {{
      const old = d.price && d.price > d._couponAfterPrice ? `<small>¥${{d.price}}</small>` : '';
      priceHtml = `<div class="price">到手 ¥${{d._couponAfterPrice}}${{old}}</div>`;
    }}
    // 返利链接：取第一个已转链的 u.jd.com 短链
    const rebate = (d.list||[]).map(it=>it.url||'').filter(u=>u && u.indexOf('u.jd.com')>=0)[0] || '';
    const rlink = rebate ? `<div class="rlink" data-text="${{esc(rebate)}}" title="点击复制返利链接">${{esc(rebate)}}</div>` : '';
    return `<div class="card" data-text="${{esc(copyText)}}" title="双击复制文案">
      <div class="head"><span class="time">${{esc(rel(d.time))}}</span></div>
      ${{imgs}}${{priceHtml}}${{lines}}${{rlink}}
    </div>`;
  }}).join('');
}}
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{{
  document.querySelectorAll('.chip').forEach(x=>x.classList.remove('on'));
  c.classList.add('on'); filter=c.dataset.p; render();
}});
document.getElementById('kw').oninput=e=>{{kw=e.target.value.trim(); render();}};
function toast(msg){{
  let t=document.getElementById('toast');
  if(!t){{t=document.createElement('div');t.id='toast';document.body.appendChild(t);}}
  t.textContent=msg; t.style.opacity='1'; clearTimeout(t.__h); t.__h=setTimeout(()=>t.style.opacity='0',1200);
}}
document.getElementById('list').addEventListener('dblclick',e=>{{
  const card=e.target.closest('.card'); if(!card) return;
  if(e.target.closest('a')) return;
  navigator.clipboard.writeText(card.dataset.text.replace(/\\\\n/g,'\\n')).then(()=>toast('已复制文案 ✓'));
}});
document.getElementById('list').addEventListener('click',e=>{{
  if(e.target.classList.contains('rlink')){{
    navigator.clipboard.writeText(e.target.dataset.text).then(()=>toast('返利链接已复制 ✓'));
  }}
}});
const topBtn=document.getElementById('top');
window.addEventListener('scroll',()=>{{topBtn.style.display = window.scrollY>400?'block':'none';}});
topBtn.onclick=()=>window.scrollTo({{top:0,behavior:'smooth'}});
render();
</script>
</body>
</html>
"""


def main(raw=False):
    with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    os.makedirs(SITE_DIR, exist_ok=True)

    # 自适应抓取：从第1页往后翻，直到整页都早于今日0点为止
    today0 = time.strftime("%Y-%m-%d 00:00:00")
    deals, seen = [], set()
    page = 1
    while page <= 60:  # 安全上限：60页×20条=1200条
        try:
            data = fetch_page(cfg, page)["data"]
        except Exception as e:
            print(f"[warn] 第{page}页抓取失败: {e}")
            break
        items = data.get("items", []) or []
        if not items:
            break
        expired = 0
        for i in items:
            n = normalize(i)
            if n["id"] in seen:
                continue
            seen.add(n["id"])
            if n["time"] >= today0:
                deals.append(n)
            else:
                expired += 1
        print(f"第{page}页: 累计今日{len(deals)}条 (本页早于0点{expired}条)")
        if expired == len(items):  # 整页都过期，抓完今日了
            break
        page += 1
        time.sleep(0.5)
    print(f"今日({today0}起)线报共 {len(deals)} 条")

    # 抓完立刻落盘，防止后面转链挂掉把抓取成果也丢了
    with open(os.path.join(SITE_DIR, "deals.json"), "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=1)

    if raw:
        stats = {"ok": 0, "fail": 0, "skipped": 0}
        print("[raw 模式] 跳过转链，直接展示原始线报")
    else:
        # 增量进度回调：每转完一条落盘 deals.json；每20条或3分钟做一次 git 增量推送
        import subprocess as _sp

        def _git(*args):
            env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
            _sp.run(["git", *args], cwd=BASE_DIR, capture_output=True, env=env)

        push_state = {"n": 0, "last": time.time()}

        def on_progress(done_deals, stats):
            try:
                with open(os.path.join(SITE_DIR, "deals.json"), "w", encoding="utf-8") as f:
                    json.dump(done_deals, f, ensure_ascii=False, indent=1)
            except Exception as e:
                print(f"  [warn] 落盘失败: {e}")
            push_state["n"] += 1
            if push_state["n"] % 20 == 0 or time.time() - push_state["last"] > 180:
                try:
                    html = build_html(done_deals, cfg, stats)
                    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
                        f.write(html)
                    _git("add", "-A")
                    _git("commit", "-m", "data: incremental update")
                    _git("push", "origin", "main")
                    push_state["last"] = time.time()
                    print("  [push] 增量部署完成")
                except Exception as e:
                    print(f"  [warn] 增量推送失败: {e}")

        try:
            deals, stats = jd_convert.convert_all_browser(deals, cfg, on_progress=on_progress)
        except Exception as e:
            print(f"[warn] 浏览器转链失败（{e}），原样保留链接")
            stats = {"ok": 0, "fail": len(deals), "skipped": 0}
    print(f"转链结果: {stats}")

    with open(os.path.join(SITE_DIR, "deals.json"), "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=1)
    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_html(deals, cfg, stats))
    print(f"已生成 {os.path.join(SITE_DIR, 'index.html')}")
    return deals, stats


if __name__ == "__main__":
    import sys
    main(raw="--raw" in sys.argv)
