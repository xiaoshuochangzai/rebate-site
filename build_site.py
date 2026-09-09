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
ONLY_PLATFORMS = {"1", "2"}


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
@media(max-width:640px){.topbar-inner{padding:8px 12px;gap:10px}}

/* ---------- 筛选 / 实时条 ---------- */
.wrap{max-width:1230px;margin:0 auto;padding:14px 20px 40px}
.screen{background:#fff;border:1px solid #E7EDF9;border-radius:14px;padding:12px 18px;
box-shadow:0 2px 10px rgba(17,55,178,.05)}
.screen-item{display:flex;align-items:center;flex-wrap:wrap;gap:14px;min-height:44px}
.screen-item .title{font-size:14px;color:#8a909c;margin-right:2px;font-weight:500;letter-spacing:.5px}
.screen-item ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:10px}
.screen-item ul li{font-size:16px;font-weight:500;letter-spacing:1px;color:#5a6270;cursor:pointer;
padding:7px 26px;border-radius:999px;transition:.18s;border:1px solid #E3E8F2;background:#fff}
.screen-item ul li:hover{color:var(--brand);border-color:#B9C6F2;background:#F5F8FF}
.screen-item ul li.active{background:var(--brand);color:#fff;font-weight:600;border-color:var(--brand);
box-shadow:0 4px 12px rgba(60,75,238,.28)}

/* ---------- 关键词搜索（筛选行右侧） ---------- */
.srch{margin-left:auto;display:flex;align-items:center;position:relative}
.srch input{width:280px;height:40px;padding:0 78px 0 16px;background:#FAFBFF;
border:1px solid #E0E6F2;border-radius:999px;outline:none;font-size:14px;color:#333;transition:.18s}
.srch input::placeholder{color:#aab1bd}
.srch input:focus{border-color:var(--brand);background:#fff;box-shadow:0 0 0 3px rgba(60,75,238,.1)}
.srch .sbtn{position:absolute;right:4px;top:4px;height:32px;padding:0 18px;border:0;
border-radius:999px;background:var(--brand);color:#fff;font-size:13px;font-weight:500;cursor:pointer;
transition:.18s}
.srch .sbtn:hover{background:#2f3ddb;box-shadow:0 3px 10px rgba(60,75,238,.3)}
@media(max-width:780px){.srch{margin-left:0;width:100%}.srch input{width:100%}}
/* ---------- 实时状态条 ---------- */
.rtbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;background:#fff;
margin:14px 0 4px;padding:13px 18px;border:1px solid #EBEFF7;border-radius:14px;
box-shadow:0 2px 10px rgba(17,55,178,.05)}
.rt-live{display:inline-flex;align-items:center;gap:7px;font-size:14px;font-weight:600;color:#E12319}
.rt-dot{width:8px;height:8px;border-radius:50%;background:#E12319;animation:rtpulse 1.8s infinite}
@keyframes rtpulse{0%{box-shadow:0 0 0 0 rgba(225,35,25,.45)}70%{box-shadow:0 0 0 8px rgba(225,35,25,0)}
100%{box-shadow:0 0 0 0 rgba(225,35,25,0)}}
.rt-sep{width:1px;height:16px;background:#E6EAF2}
.rt-txt{font-size:14px;color:#6b7280}
.rt-num{display:inline-block;color:#FFD98A;font-weight:700;font-size:14px;background:#212121;
padding:1px 9px;margin:0 5px;border-radius:6px;vertical-align:middle;letter-spacing:.5px}
.rt-refresh{margin-left:auto;display:inline-flex;align-items:center;gap:6px;padding:7px 20px;
border:1px solid #FFC9C4;border-radius:999px;color:#E12319;background:#FFF7F6;
font-size:13px;font-weight:600;cursor:pointer;transition:.18s}
.rt-refresh:hover{background:#E12319;color:#fff;border-color:#E12319;box-shadow:0 4px 12px rgba(225,35,25,.25)}
.rt-refresh::before{content:"";width:12px;height:12px;border:1.6px solid currentColor;
border-top-color:transparent;border-radius:50%;display:inline-block}
@media(max-width:780px){.rt-refresh{margin-left:0}}

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
.content-section-item{padding:11px 13px 8px;flex:1;display:flex;flex-direction:column}
.price{color:var(--jd);font-size:22px;font-weight:800;line-height:1.2;margin-bottom:6px}
.price i{font-size:13px;font-style:normal;font-weight:600}
.price s{color:#b6bbc3;font-size:12px;font-weight:400;margin-left:6px}
.content-box{font-size:13px;line-height:1.8;color:#34373d;word-break:break-word;
max-height:196px;overflow:hidden;transition:max-height .3s}
.report-item:hover .content-box{max-height:640px}
.content-box .ct{white-space:pre-line}
.content-box .ct .pj{color:var(--jd);font-weight:800;font-size:17px}
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

/* 淘宝卡：左内容右图片（学大淘客排版，有几张图用几张） */
.tb-wrap{display:flex;flex:1;min-height:0}
.tb-left{flex:1;min-width:0;display:flex;flex-direction:column;padding:11px 10px 8px 13px}
.tb-right{width:92px;flex-shrink:0;display:flex;flex-direction:column;gap:2px;
background:#f7f8fa;border-left:1px solid #F0F1F4;
max-height:196px;overflow:hidden;transition:max-height .3s}
.report-item:hover .tb-right{max-height:1200px}  /* 悬停全展开，折叠幅度与左侧文案(196px)一致 */
.tb-right img{width:100%;aspect-ratio:1/1;object-fit:cover;display:block}
.tb-right .noimg{flex:1;min-height:60px;display:flex;align-items:center;justify-content:center;
color:#c8ccd4;font-size:11px}
@media(max-width:420px){.tb-right{width:70px}}

/* 淘宝卡底角【复制链接】+ 图片灯箱 */
.cpylink{margin-left:auto;font-size:11px;color:#3C6FE8;cursor:pointer;white-space:nowrap;
padding:2px 9px;border:1px solid #D9DFED;border-radius:10px}
.cpylink:hover{color:var(--jd);border-color:var(--jd)}
#lightbox{position:fixed;inset:0;background:rgba(0,0,0,.78);display:none;z-index:98;
cursor:zoom-out;align-items:center;justify-content:center}
#lightbox.show{display:flex}
#lightbox img{max-width:92vw;max-height:92vh;border-radius:6px;box-shadow:0 10px 40px rgba(0,0,0,.5)}

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
  </div>
</div>

<div class="wrap">
  <div class="screen">
    <div class="screen-item">
      <div class="title">平台</div>
      <ul id="plat"></ul>
      <div class="srch">
        <input id="kw" placeholder="搜索商品关键词，如：蓝月亮" autocomplete="off">
        <button class="sbtn" id="btnSearch">搜索</button>
      </div>
    </div>
  </div>

  <div class="rtbar">
    <span class="rt-live"><i class="rt-dot"></i>实时更新</span>
    <span class="rt-sep"></span>
    <span class="rt-txt">截止 <b class="rt-num">__TS_HM__</b></span>
    <span class="rt-sep"></span>
    <span class="rt-txt">今日更新 <b class="rt-num" id="cnt">0</b> 条</span>
    <span class="rt-sep"></span>
    <span class="rt-txt">累计收录线报 <b class="rt-num" id="total">0</b> 条</span>
    <a class="rt-refresh" href="javascript:;" id="btnRefresh" title="刷新当前平台最新线报">刷新</a>
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
<div id="lightbox"><img alt=""></div>
<div id="toast"></div>

<script>
let DEALS = __DATA__;
const PAGE_SIZE = 60;
let filter = '2', kw = '', shown = 0;  // 默认京东（京东第一、淘宝第二，无「全部」）
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
  if(d._originalContext) return d._originalContext;
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
function linkOf(d){
  const m = copyTextOf(d).match(/https?:\\/\\/[^\\s"'，。；、）】\\n]+/);
  return m ? m[0] : '';
}
function cardHtml(d){
  let priceHtml = '';
  if(d._couponAfterPrice){
    const old = (d.price && d.price > d._couponAfterPrice) ? '<s>¥'+esc(d.price)+'</s>' : '';
    priceHtml = '<div class="price"><i>到手 ¥</i>'+esc(d._couponAfterPrice)+old+'</div>';
  }

  // 精品库式呈现：文案文字 + 链接原文。去重规则 = 同一条链接只出一次，
  // 不同链接（合集类多商品）各自出现在自己的文案位置
  const body = [];
  const seenLink = {};
  (d.list||[]).forEach(it=>{
    if(it.content){
      let t = esc(it.content);
      // 仅京东：元前数字（如 10.9元）放大+红
      if(d.platform==='2') t = t.replace(/(\\d+(?:\\.\\d+)?)元/g, '<span class="pj">$1元<\\/span>');
      body.push('<div class="ct">'+t+'</div>');
    }
    const c = pickCoupon(it);
    if(c && !seenLink[c]){ seenLink[c]=1;
      body.push('<a class="lnk" href="'+esc(c)+'" target="_blank" rel="noopener">'+esc(c)+'</a>'); }
    // 商品链接位：原始 item_id 是链接的条目，渲染转链后的链接（去重按 URL）
    if(it.item_id && /^https?:\\/\\//i.test(it.item_id)){
      const u = (it.url && /^https?:\\/\\//i.test(it.url)) ? it.url : it.item_id;
      if(u && !seenLink[u]){ seenLink[u]=1;
        body.push('<a class="lnk" href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(u)+'</a>'); }
    }
  });
  // 兜底：有转链链接但原始数据没有商品链接位（纯券线报转出来的）
  {
    const u = ((d.list||[]).map(it=>it.url).find(x=>x && /^https?:\\/\\//i.test(x))) || '';
    if(u && !seenLink[u]){
      body.push('<a class="lnk" href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(u)+'</a>');
    }
  }
  const box = '<div class="content-box">'+(body.length?body.join(''):'<div class="ct">（无文案）</div>')+'</div>';
  const info = '<div class="content-section-info">'
    + '<div class="attr"><span class="pf '+pfCls(d.platform)+'">'+pfTxt(d.platform)+'</span>'
    + '<span class="reltime">'+esc(rel(d._addedAt || d.time))+'</span></div>'
    + '</div>';

  // 淘宝卡：左边线报内容、右边图片（有几张图用几张），学大淘客排版；底角【复制链接】
  if(d.platform === '1'){
    const imgs = (d.images && d.images.length) ? d.images : [];
    const right = imgs.length
      ? imgs.map(u=>'<img src="'+esc(u)+'" referrerpolicy="no-referrer" loading="lazy" alt="">').join('')
      : '<div class="noimg">暂无图片</div>';
    const infoTb = '<div class="content-section-info">'
      + '<div class="attr"><span class="pf '+pfCls(d.platform)+'">'+pfTxt(d.platform)+'</span>'
      + '<span class="reltime">'+esc(rel(d._addedAt || d.time))+'</span></div>'
      + '<a class="cpylink" href="javascript:;" title="复制完整文案">复制文案</a>'
      + '</div>';
    return '<div class="report-item" data-text="'+esc(copyTextOf(d))+'" data-link="'+esc(linkOf(d))+'">'
      + '<div class="tb-wrap">'
      +   '<div class="tb-left">'+priceHtml+box+infoTb+'</div>'
      +   '<div class="tb-right">'+right+'</div>'
      + '</div></div>';
  }

  // 京东等其他平台：上图下文
  const img = (d.images && d.images.length)
    ? '<img src="'+esc(d.images[0])+'" referrerpolicy="no-referrer" loading="lazy" alt="">'
    : '<div class="noimg">暂无图片</div>';
  return '<div class="report-item" data-text="'+esc(copyTextOf(d))+'">'
    + '<div class="image-section">'+img+'</div>'
    + '<div class="content-section">'
    +   '<div class="content-section-item">'
    +     priceHtml + box + info
    +   '</div>'
    + '</div>'
    + '</div>';
}

function matched(){
  const k = kw.toLowerCase();
  const pool = DEALS.filter(d=>{
    // 顶搜 = 跨全平台（淘宝+京东）；只在无关键词时才按当前分类筛
    if(!k && filter!=='all' && d.platform!==filter) return false;
    if(!k) return true;
    return copyTextOf(d).toLowerCase().indexOf(k)>=0 || (d.cate||'').toLowerCase().indexOf(k)>=0;
  });
  if(!k) return pool;
  // 分级：关键词在卡头（前两行=主打商品名）的是强匹配排前面；
  // 长文汇总卡（一条塞十几个商品）深处才提到的排后面，避免搜「洗衣液」冒出花生油卡
  const strong = [], weak = [];
  pool.forEach(d=>{
    const head = copyTextOf(d).toLowerCase().split('\\n').slice(0, 2).join('\\n');
    (head.indexOf(k)>=0 ? strong : weak).push(d);
  });
  return strong.concat(weak);
}
let cur = [];
function render(reset){
  const list = document.getElementById('list');
  if(reset){ cur = matched(); shown = 0; list.innerHTML=''; }
  document.getElementById('cnt').textContent = cur.length;
  document.getElementById('total').textContent = DEALS.length;
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
  const li = e.target.closest('li'); if(!li || li.classList.contains('active')) return;
  document.querySelectorAll('#plat li').forEach(x=>x.classList.remove('active'));
  li.classList.add('active'); filter = li.dataset.p;
  render(true);      // 先用现有数据立即渲染，避免白屏
  refreshData();     // 切换分类 = 刷新（拉最新数据重绘当前平台）
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
  if(e.target.closest('a') || e.target.tagName==='IMG') return;
  const card = e.target.closest('.report-item'); if(!card) return;
  copy(card.dataset.text, '文案已复制 ✓');
});
// 底角【复制文案】（淘宝卡）：复制完整成品文案，与双击卡片等效
listEl.addEventListener('click', e=>{
  const c = e.target.closest('.cpylink');
  if(c){
    e.stopPropagation(); e.preventDefault();
    const card = c.closest('.report-item');
    copy((card && card.dataset.text) || '', '文案已复制 ✓');
    return;
  }
  // 图片点击放大（灯箱），点空白处关闭
  if(e.target.tagName==='IMG' && e.target.closest('.report-item')){
    e.stopPropagation(); e.preventDefault();
    const lb = document.getElementById('lightbox');
    lb.innerHTML = '<img src="'+e.target.src+'" referrerpolicy="no-referrer" alt="">';
    lb.classList.add('show');
  }
});
document.getElementById('lightbox').addEventListener('click', function(){
  this.classList.remove('show');
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

// 平台筛选：京东第一、淘宝第二，不要「全部」分类
const PNAME = {'1':'淘宝','2':'京东','3':'飞猪'};
const PORDER = ['2','1'];
function buildTabs(){
  const seen = {};
  DEALS.forEach(d=>{ if(d.platform) seen[d.platform]=1; });
  const arr = PORDER.filter(p=>seen[p]);
  Object.keys(seen).forEach(p=>{ if(arr.indexOf(p)<0) arr.push(p); });
  document.getElementById('plat').innerHTML = arr.map(p=>
    '<li data-p="'+esc(p)+'"'+(p===String(filter)?' class="active"':'')+'>'+esc(PNAME[p]||p)+'</li>').join('');
}
buildTabs();
render(true);

// 刷新 = 从 KV 接口拉最新数据、重绘当前平台（不整页 reload，不重置分类）
function refreshData(){
  return fetch('/api/deals?ts='+Date.now(), {cache:'no-store'})
    .then(r=>r.ok ? r.json() : null)
    .then(fresh=>{
      if(!Array.isArray(fresh) || !fresh.length) return false;
      const oldTop = DEALS.length ? String(DEALS[0].id) : '';
      const newTop = String(fresh[0].id||'');
      const changed = (newTop !== oldTop) || fresh.length !== DEALS.length;
      DEALS = fresh;
      buildTabs();
      render(true);
      return changed;
    })
    .catch(()=>false);
}
// 防御：元素缺失也不许炸掉后续脚本（上次就是这里 null 报错把首屏刷新带死的）
const btnRefreshEl = document.getElementById('btnRefresh');
if(btnRefreshEl){
  btnRefreshEl.onclick = function(){
    const a = this; a.textContent = '刷新中…';
    refreshData().then(c=>{
      a.textContent = '刷新';
      toast(c ? '已更新到最新线报 ✓' : '已是最新');
    });
  };
}
// 首屏渲染后自动拉一次最新数据
refreshData().then(()=>{ // 数据落定后同步顶部「截止」时间，别让它停留在构建时刻
  const ts = document.querySelector('.rt-num');
  if(ts) ts.textContent = new Date().toTimeString().slice(0,5);
});
</script>
</body>
</html>
"""


EMBED_MAX = 500  # 首屏只内嵌最新 500 条（其余走 /api/deals 加载），防 HTML 随 7 天数据无限变肥


def build_html(deals, cfg, convert_stats):
    data_json = json.dumps(deals[:EMBED_MAX], ensure_ascii=False).replace("</", "<\\/")
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    ts_hm = time.strftime("%H:%M")
    return (TPL
            .replace("__DATA__", data_json)
            .replace("__TS_HM__", ts_hm)
            .replace("__TS__", ts))


def merge_with_existing(fetched, existing_path=None):
    """fetched（今日抓取）与存量 deals.json 按 id 合并：存量的已转链条目
    （带 _originalContext/_formatContext/converted 标记）优先保留，防止
    直跑 main() 时抓取不完整把历史清空。返回合并后的全量列表（时间倒序）。"""
    path = existing_path or os.path.join(SITE_DIR, "deals.json")
    try:
        with open(path, encoding="utf-8") as f:
            existing = json.load(f) or []
    except Exception:
        existing = []
    if not existing:
        return fetched
    def converted(d):
        return bool(d.get("_originalContext") or d.get("_formatContext")
                    or any(it.get("converted") or it.get("url") for it in d.get("list", [])))
    by_id = {}
    for d in existing:            # 存量只保留转上链的（与「没转上链绝不上站」红线一致）
        if converted(d):
            by_id[str(d.get("id"))] = d
    for d in fetched:             # 今日抓取的可覆盖同 id 旧数据（转链结果更新）
        by_id[str(d.get("id"))] = d
    merged = sorted(by_id.values(), key=lambda x: x.get("time", ""), reverse=True)
    print(f"合并存量: {len(existing)} + 抓取 {len(fetched)} -> {len(merged)} 条")
    return merged


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

    # 安全阀（2026-09-07 清空事故）：main() 只抓「今日」线报，历史全在存量文件里。
    # 抓取一旦中途断页（代理 502 等），今日列表会只剩几条——直接覆盖会把全库清空。
    # 所以落盘前必须与存量按 id 合并：存量已转链条目一律保留，抓取结果只做补充/更新。
    deals = merge_with_existing(deals)

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
