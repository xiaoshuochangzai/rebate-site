# -*- coding: utf-8 -*-
"""好单库线报爬虫 + 转链 + 静态站生成。

流程：
1. 抓取 haodanku 线报接口（JSON，无需登录）
2. 归一化：平台 / 时间 / 文案行 / 商品链接 / 券链接 / 图片
3. 京东链接走联盟转链（可关闭，关闭时用原链接）
4. 生成 site/index.html（数据内嵌，单文件可直接部署）+ site/deals.json
"""
import json
import os
import time
import urllib.request

import jd_convert

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
main{{padding:16px;display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(320px,1fr))}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}}
.head{{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}}
.tag{{font-size:12px;padding:2px 8px;border-radius:4px;color:#fff}}
.tag.jd{{background:var(--jd)}} .tag.tb{{background:var(--tb)}} .tag.other{{background:#8a9099}}
.time{{color:var(--sub);font-size:12px}}
.imgs{{display:flex;gap:6px;overflow:auto;margin-bottom:10px}}
.imgs img{{width:88px;height:88px;object-fit:cover;border-radius:8px;border:1px solid var(--line)}}
.line{{margin:5px 0}}
.btn{{display:inline-block;padding:5px 12px;border-radius:6px;background:var(--text);color:#fff;text-decoration:none;font-size:13px}}
.btn.coupon{{background:var(--tb)}}
.actions{{margin-top:12px;display:flex;gap:8px}}
.copy{{flex:1;padding:7px;border:1px solid var(--line);background:#fff;border-radius:6px;cursor:pointer;font-size:13px}}
.note{{color:var(--sub);font-size:11px;margin-top:8px}}
.converted{{color:var(--ok);font-size:11px}}
footer{{padding:20px;text-align:center;color:var(--sub);font-size:12px}}
</style>
</head>
<body>
<header>
  <h1>实时优惠线报</h1>
  <div class="bar">
    <span class="chip on" data-p="all">全部</span>
    <span class="chip" data-p="2">京东</span>
    <span class="chip" data-p="1">淘宝</span>
    <span class="chip" data-p="3">飞猪</span>
    <input id="kw" placeholder="搜索商品关键词">
  </div>
  <div class="meta">更新于 {ts} · 共 <b id="cnt">0</b> 条 · 转链成功 {convert_stats.get('ok',0)} 条</div>
</header>
<main id="list"></main>
<footer>数据更新每小时一次 · 点击「复制文案」可一键复制整条线报</footer>
<script>
const DEALS = {data_json};
const STATS = {stats};
let filter = 'all', kw = '';
function esc(s){{return String(s||'').replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]);}}
function cls(p){{return p==='2'?'jd':(p==='1'?'tb':'other');}}
function render(){{
  const list = DEALS.filter(d=>(filter==='all'||d.platform===filter)
    && (!kw || JSON.stringify(d).toLowerCase().includes(kw.toLowerCase())));
  document.getElementById('cnt').textContent = list.length;
  document.getElementById('list').innerHTML = list.map(d=>{{
    const imgs = d.images.length? `<div class="imgs">${{d.images.slice(0,4).map(u=>`<img src="${{esc(u)}}" referrerpolicy="no-referrer">`).join('')}}</div>`:'';
    const lines = d.list.map(it=>{{
      if(it.item_id || it.coupon_url){{
        const href = it.url || it.coupon_url || it.item_id;
        const label = it.coupon_url ? '立即领券' : '抢购商品';
        const bcls = it.coupon_url ? 'btn coupon' : 'btn';
        const mark = it.converted ? '<span class="converted">已转链</span>' : '';
        return `<div class="line"><a class="${{bcls}}" href="${{esc(href)}}" target="_blank" rel="noopener">${{label}}</a> ${{mark}}</div>`;
      }}
      return `<div class="line">${{esc(it.content)}}</div>`;
    }}).join('');
    const text = (d.cate||d.platform_name) + '\\n' + d.list.map(it=>it.content||it.url||it.coupon_url||'').filter(Boolean).join('\\n');
    return `<div class="card">
      <div class="head"><span class="tag ${{cls(d.platform)}}">${{esc(d.platform_name)}}</span><span class="time">${{esc(d.time)}}</span></div>
      ${{imgs}}${{lines}}
      <div class="actions"><button class="copy" data-text="${{esc(text)}}">复制文案</button></div>
    </div>`;
  }}).join('');
}}
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{{
  document.querySelectorAll('.chip').forEach(x=>x.classList.remove('on'));
  c.classList.add('on'); filter=c.dataset.p; render();
}});
document.getElementById('kw').oninput=e=>{{kw=e.target.value.trim(); render();}};
document.getElementById('list').addEventListener('click',e=>{{
  if(e.target.classList.contains('copy')){{
    navigator.clipboard.writeText(e.target.dataset.text.replace(/\\\\n/g,'\\n')).then(()=>{{
      const t=e.target.textContent; e.target.textContent='已复制 ✓';
      setTimeout(()=>e.target.textContent=t,1200);
    }});
  }}
}});
render();
</script>
</body>
</html>
"""


def main():
    with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    os.makedirs(SITE_DIR, exist_ok=True)

    deals = []
    for page in range(1, cfg["crawl"]["pages"] + 1):
        try:
            data = fetch_page(cfg, page)["data"]
            deals.extend(normalize(i) for i in data.get("items", []))
        except Exception as e:
            print(f"[warn] 第{page}页抓取失败: {e}")
    print(f"抓取线报 {len(deals)} 条")

    stats = jd_convert.convert_all(deals, cfg)
    print(f"转链结果: {stats}")

    with open(os.path.join(SITE_DIR, "deals.json"), "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=1)
    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_html(deals, cfg, stats))
    print(f"已生成 {os.path.join(SITE_DIR, 'index.html')}")
    return deals, stats


if __name__ == "__main__":
    main()
