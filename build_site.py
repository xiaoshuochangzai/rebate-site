# -*- coding: utf-8 -*-
"""好单库线报爬虫 + 转链 + 静态站生成。

流程：
1. 抓取 haodanku 线报接口（JSON，无需登录）
2. 归一化：平台 / 时间 / 文案行 / 商品链接 / 券链接 / 图片
3. 京东链接走联盟「万能转链」（浏览器自动化，无 API 权限要求）
4. 生成 site/index.html（数据内嵌，单文件可直接部署）+ site/deals.json

UI 参考京品库线报页（卡片网格 + 实时更新条 + 底部属性/时间行），
去掉顶部 banner 与「来源」筛选，并做分页加载、双击复制等优化。
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
# 现阶段只上京东线报；以后要恢复淘宝/飞猪，改成 {"1", "2", "3"} 或设为空集合即可
ONLY_PLATFORMS = {"2"}


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


TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>好价线报 · 实时更新</title>
<meta name="description" content="京东实时优惠线报，每小时自动更新，复制文案即可发单">
<style>
:root{--bg:#f4f6fa;--card:#fff;--text:#23262b;--sub:#9aa0a8;--line:#eef0f4;
--jd:#E12319;--tb:#ff5000;--fz:#ff8f1f;--brand:#3C4BEE;--shadow:0 10px 30px 0 rgba(17,55,178,.09)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}
a{text-decoration:none}

/* ---------- 顶部栏（无 banner） ---------- */
.topbar{position:sticky;top:0;z-index:20;background:#fff;border-bottom:1px solid var(--line);
box-shadow:0 2px 8px rgba(17,55,178,.04)}
.topbar-inner{max-width:1230px;margin:0 auto;padding:10px 20px;display:flex;align-items:center;gap:20px}
.logo{font-size:19px;font-weight:800;letter-spacing:.5px;
background:linear-gradient(90deg,#FF7D00,#FF0A00);-webkit-background-clip:text;background-clip:text;
color:transparent;white-space:nowrap}
.logo small{display:inline-block;font-size:10px;font-weight:500;color:#c3c8d0;
-webkit-text-fill-color:#c3c8d0;margin-left:6px;letter-spacing:1px}
.search{margin-left:auto;display:flex;align-items:center;position:relative}
.search input{width:300px;height:34px;padding:0 70px 0 12px;background:#F9FBFF;
border:1px solid #D9DFED;border-radius:9px;outline:none;font-size:13px;color:#333}
.search input:focus{border-color:#b9c6f2}
.search .sbtn{position:absolute;right:1px;top:1px;height:32px;padding:0 16px;border:0;
border-radius:0 9px 9px 0;background:#F0F4FF;color:var(--brand);font-size:13px;cursor:pointer}
@media(max-width:640px){.topbar-inner{padding:8px 12px;gap:10px}.search input{width:100%}}

/* ---------- 筛选 / 实时条 ---------- */
.wrap{max-width:1230px;margin:0 auto;padding:14px 20px 40px}
.screen{background:#fff;border:2px solid #E7EDF9;border-radius:8px;padding:8px 18px}
.screen-item{display:flex;align-items:center;flex-wrap:wrap;min-height:32px;line-height:32px}
.screen-item .title{font-size:12px;color:#666;margin-right:6px}
.screen-item ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap}
.screen-item ul li{margin:0 10px 0 0;font-size:12px;color:#606266;cursor:pointer;
padding:0 5px;border-radius:2px;transition:.15s}
.screen-item ul li:hover{color:var(--brand)}
.screen-item ul li.active{background:#E0EDFF;color:var(--brand);font-weight:500}

.report-realtime{display:inline-flex;align-items:center;background:#fff;padding:6px 14px;
margin:14px 0 4px;box-shadow:inset 2px 2px 3px 0 #e7eaee;border-radius:4px;font-size:13px;color:#555}
.report-realtime .realtime{color:#f53245;font-weight:600;margin-right:10px}
.report-realtime .wire{display:inline-block;width:1px;height:14px;background:#dde3ea;margin-right:10px}
.report-realtime .time,.report-realtime .num{display:inline-block;color:#ead2a7;font-weight:500;
background:#212121;padding:0 6px;margin:0 3px;border-radius:4px;vertical-align:middle}

/* ---------- 卡片网格 ---------- */
.report-list{display:grid;grid-template-columns:repeat(4,1fr);gap:20px;margin-top:12px}
@media(max-width:1100px){.report-list{grid-template-columns:repeat(3,1fr)}}
@media(max-width:780px){.report-list{grid-template-columns:repeat(2,1fr);gap:12px}}
@media(max-width:420px){.report-list{grid-template-columns:repeat(2,1fr);gap:8px}}

.report-item{background:var(--card);border-radius:8px;box-shadow:var(--shadow);
display:flex;flex-direction:column;overflow:hidden;transition:transform .26s,box-shadow .26s;cursor:pointer}
.report-item:hover{transform:translateY(-6px);box-shadow:0 16px 38px 0 rgba(17,55,178,.18);z-index:5}
.image-section{position:relative;background:#f7f8fa}
.image-section img{width:100%;aspect-ratio:1/1;object-fit:cover;display:block}
.image-section .noimg{aspect-ratio:1/1;display:flex;align-items:center;justify-content:center;
color:#c8ccd4;font-size:12px}

.content-section{position:relative;flex:1;display:flex;flex-direction:column}
.turn-link{position:absolute;left:0;right:0;top:0;transform:translateY(-100%);height:38px;
background:linear-gradient(90deg,#FF7D00 0%,#FF0A00 100%);color:#fff;font-size:15px;
display:flex;justify-content:center;align-items:center;opacity:0;transition:opacity .25s;letter-spacing:1px}
.report-item:hover .turn-link{opacity:.96}

.content-section-item{padding:11px 13px 8px;flex:1;display:flex;flex-direction:column}
.price{color:var(--jd);font-size:22px;font-weight:800;line-height:1.2;margin-bottom:6px}
.price i{font-size:13px;font-style:normal;font-weight:600}
.price s{color:#b6bbc3;font-size:12px;font-weight:400;margin-left:6px}
.content-box{font-size:13px;line-height:1.8;color:#34373d;word-break:break-word;
max-height:196px;overflow:hidden;transition:max-height .3s}
.report-item:hover .content-box{max-height:640px}
.content-box .ct{white-space:pre-line}
.content-box a.lnk{display:block;font-size:12px;line-height:1.7;color:#3C6FE8;
word-break:break-all;margin:1px 0;text-decoration:none}
.content-box a.lnk:hover{color:var(--jd);text-decoration:underline}

.content-section-info{margin-top:auto;padding-top:8px;min-height:38px;display:flex;
justify-content:space-between;align-items:center;border-top:1px solid #F0F1F4}
.attr{display:flex;align-items:center;gap:6px}
.pf{width:20px;height:20px;border-radius:3px;font-size:11px;color:#fff;font-weight:600;
display:flex;align-items:center;justify-content:center}
.pf.jd{background:var(--jd)}.pf.tb{background:var(--tb)}.pf.fz{background:var(--fz)}.pf.ot{background:#a6abb3}
.reltime{color:#9aa0a8;font-size:12px;margin-left:2px}

.more{margin:26px auto 0;width:150px;height:34px;line-height:34px;text-align:center;color:#8d939b;
font-size:13px;background:#fff;border-radius:17px;box-shadow:var(--shadow);cursor:pointer}
.more:hover{color:var(--brand)}
.empty{display:none;text-align:center;color:#9aa0a8;font-size:14px;padding:60px 0}
footer{padding:26px 20px 34px;text-align:center;color:#a8aeb6;font-size:12px;line-height:1.9}

#toast{position:fixed;left:50%;bottom:52px;transform:translateX(-50%) translateY(8px);background:#212121;
color:#fff;padding:10px 20px;border-radius:22px;font-size:14px;opacity:0;transition:.28s;
pointer-events:none;z-index:99}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
#top{position:fixed;right:24px;bottom:34px;width:44px;height:44px;border-radius:50%;
background:linear-gradient(90deg,#FF7D00,#FF0A00);color:#fff;border:0;font-size:20px;cursor:pointer;
box-shadow:0 4px 14px rgba(255,45,0,.35);display:none;z-index:30}
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-inner">
    <a class="logo" href="/">好价线报<small>HAOJIA</small></a>
    <div class="search">
      <input id="kw" placeholder="输入商品关键词搜索线报" autocomplete="off">
      <button class="sbtn" id="btnSearch">搜索</button>
    </div>
  </div>
</div>

<div class="wrap">
  <div class="screen">
    <div class="screen-item">
      <div class="title">平台：</div>
      <ul id="plat"></ul>
    </div>
  </div>

  <div class="report-realtime">
    <span class="realtime">实时更新</span><span class="wire"></span>截止
    <span class="time">__TS_HM__</span>今日已经更新<span class="num" id="cnt">0</span>条
  </div>

  <div class="report-list" id="list"></div>
  <div class="more" id="more" style="display:none">加载更多</div>
  <div class="empty" id="empty">没有匹配的线报，换个关键词试试</div>
</div>

<footer>
  数据每小时自动更新 · 双击卡片（或点顶部红条）复制完整文案<br>
  好价线报 · __TS__
</footer>

<button id="top" title="回到顶部">↑</button>
<div id="toast"></div>

<script>
const DEALS = __DATA__;
const PAGE_SIZE = 60;
let filter = 'all', kw = '', shown = 0;
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function rel(t){
  if(!t) return '';
  const d = new Date(String(t).replace(/-/g,'/'));
  if(isNaN(d.getTime())) return String(t);
  const s = (Date.now()-d.getTime())/1000;
  if(s < 60) return '刚刚';
  if(s < 3600) return Math.floor(s/60)+'分钟前';
  if(s < 86400) return Math.floor(s/3600)+'小时前';
  return Math.floor(s/86400)+'天前';
}
const RE = /(https?:\\/\\/[^\\s<>"'，。；、）】]+)/g;
function linkify(s){
  return esc(s).replace(RE, m=>'<a href="'+m+'" target="_blank" rel="noopener">'+m+'</a>');
}
function pfCls(p){return p==='2'?'jd':(p==='1'?'tb':(p==='3'?'fz':'ot'));}
function pfTxt(p){return p==='2'?'JD':(p==='1'?'TB':(p==='3'?'FZ':'?'));}

function pickLink(it){
  const raw = (it.item_id||'').trim();
  if(/^https?:\\/\\//i.test(raw)) return raw;
  return '';
}
function pickCoupon(it){
  const c = (it.coupon_url||'').trim();
  if(!c) return '';
  const m = c.match(/https?:\\/\\/[^\\s<>"'，。；、）】]+/);
  return m ? m[0] : '';
}
function copyTextOf(d){
  if(d._formatContext) return d._formatContext;
  const parts = [];
  (d.list||[]).forEach(it=>{
    if(it.content) parts.push(it.content);
    // 转链后写入的 it.url 优先，否则用原始 item_id / coupon_url
    const u = (it.url && /^https?:\\/\\//i.test(it.url)) ? it.url : pickLink(it);
    if(u) parts.push(u);
    const c = pickCoupon(it);
    if(c && c !== u) parts.push(c);
  });
  return parts.join('\\n');
}
function cardHtml(d){
  const img = (d.images && d.images.length)
    ? '<img src="'+esc(d.images[0])+'" referrerpolicy="no-referrer" loading="lazy" alt="">'
    : '<div class="noimg">暂无图片</div>';

  let priceHtml = '';
  if(d._couponAfterPrice){
    const old = (d.price && d.price > d._couponAfterPrice) ? '<s>¥'+esc(d.price)+'</s>' : '';
    priceHtml = '<div class="price"><i>到手 ¥</i>'+esc(d._couponAfterPrice)+old+'</div>';
  }

  // 精品库式呈现：文案文字 + 链接原文，不做任何按钮
  const body = [];
  (d.list||[]).forEach(it=>{
    if(it.content) body.push('<div class="ct">'+esc(it.content)+'</div>');
    const u = (it.url && /^https?:\\/\\//i.test(it.url)) ? it.url : pickLink(it);
    if(u) body.push('<a class="lnk" href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(u)+'</a>');
    const c = pickCoupon(it);
    if(c) body.push('<a class="lnk" href="'+esc(c)+'" target="_blank" rel="noopener">'+esc(c)+'</a>');
  });
  const box = '<div class="content-box">'+(body.length?body.join(''):'<div class="ct">（无文案）</div>')+'</div>';

  return '<div class="report-item" data-text="'+esc(copyTextOf(d))+'">'
    + '<div class="image-section">'+img+'</div>'
    + '<div class="content-section">'
    +   '<div class="turn-link">一键复制文案</div>'
    +   '<div class="content-section-item">'
    +     priceHtml + box
    +     '<div class="content-section-info">'
    +       '<div class="attr"><span class="pf '+pfCls(d.platform)+'">'+pfTxt(d.platform)+'</span>'
    +       '<span class="reltime">'+esc(rel(d.time))+'</span></div>'
    +     '</div>'
    +   '</div>'
    + '</div>'
    + '</div>';
}

function matched(){
  const k = kw.toLowerCase();
  return DEALS.filter(d=>{
    if(filter!=='all' && d.platform!==filter) return false;
    if(!k) return true;
    return copyTextOf(d).toLowerCase().indexOf(k)>=0 || (d.cate||'').toLowerCase().indexOf(k)>=0;
  });
}
let cur = [];
function render(reset){
  const list = document.getElementById('list');
  if(reset){ cur = matched(); shown = 0; list.innerHTML=''; }
  document.getElementById('cnt').textContent = cur.length;
  document.getElementById('empty').style.display = cur.length ? 'none' : 'block';
  const slice = cur.slice(shown, shown+PAGE_SIZE);
  list.insertAdjacentHTML('beforeend', slice.map(cardHtml).join(''));
  shown += slice.length;
  document.getElementById('more').style.display = shown < cur.length ? 'block' : 'none';
}

function toast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(t.__h); t.__h = setTimeout(()=>t.classList.remove('show'), 1300);
}
function copy(str, tip){
  if(navigator.clipboard && window.isSecureContext){
    navigator.clipboard.writeText(str).then(()=>toast(tip||'已复制 ✓'), ()=>fallback(str, tip));
  } else fallback(str, tip);
}
function fallback(str, tip){
  const ta = document.createElement('textarea');
  ta.value = str; ta.style.position='fixed'; ta.style.opacity='0';
  document.body.appendChild(ta); ta.select();
  try{ document.execCommand('copy'); toast(tip||'已复制 ✓'); }catch(e){ toast('复制失败，请手动选择'); }
  document.body.removeChild(ta);
}

document.getElementById('plat').addEventListener('click', e=>{
  const li = e.target.closest('li'); if(!li) return;
  document.querySelectorAll('#plat li').forEach(x=>x.classList.remove('active'));
  li.classList.add('active'); filter = li.dataset.p; render(true);
});
const kwInput = document.getElementById('kw');
let timer;
kwInput.addEventListener('input', e=>{
  clearTimeout(timer);
  timer = setTimeout(()=>{ kw = e.target.value.trim(); render(true); }, 200);
});
document.getElementById('btnSearch').onclick = ()=>{ kw = kwInput.value.trim(); render(true); };
kwInput.addEventListener('keydown', e=>{ if(e.key==='Enter'){ kw=kwInput.value.trim(); render(true);} });

const listEl = document.getElementById('list');
listEl.addEventListener('dblclick', e=>{
  if(e.target.closest('a')) return;
  const card = e.target.closest('.report-item'); if(!card) return;
  copy(card.dataset.text, '文案已复制 ✓');
});
document.getElementById('more').onclick = ()=>render(false);

const topBtn = document.getElementById('top');
window.addEventListener('scroll', ()=>{
  topBtn.style.display = window.scrollY > 500 ? 'block' : 'none';
  if(window.innerHeight + window.scrollY > document.body.offsetHeight - 800){
    if(document.getElementById('more').style.display === 'block') render(false);
  }
});
topBtn.onclick = ()=>window.scrollTo({top:0,behavior:'smooth'});

// 平台筛选项：按数据中实际存在的平台动态生成（只上京东时就只剩「全部/京东」）
const PNAME = {'1':'淘宝','2':'京东','3':'飞猪'};
(function(){
  const seen = {}, arr = [];
  DEALS.forEach(d=>{ if(d.platform && !seen[d.platform]){ seen[d.platform]=1; arr.push(d.platform); } });
  arr.sort();
  document.getElementById('plat').innerHTML =
    '<li class="active" data-p="all">全部</li>'
    + arr.map(p=>'<li data-p="'+esc(p)+'">'+esc(PNAME[p]||p)+'</li>').join('');
})();
render(true);
</script>
</body>
</html>
"""


def build_html(deals, cfg, convert_stats):
    data_json = json.dumps(deals, ensure_ascii=False).replace("</", "<\\/")
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    ts_hm = time.strftime("%H:%M")
    return (TPL
            .replace("__DATA__", data_json)
            .replace("__TS_HM__", ts_hm)
            .replace("__TS__", ts))


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

    if ONLY_PLATFORMS:
        before = len(deals)
        deals = [d for d in deals if d["platform"] in ONLY_PLATFORMS]
        names = "/".join(PLATFORM_MAP.get(p, p) for p in sorted(ONLY_PLATFORMS))
        print(f"平台过滤: {before} -> {len(deals)} 条（仅保留 {names}）")

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
