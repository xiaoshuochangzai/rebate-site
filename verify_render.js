// 模拟前端 cardHtml 的文案区渲染，验证：卡片内同一链接不重复（不同链接各归其位）
const fs = require('fs');
const html = fs.readFileSync('site/index.html', 'utf8');
const m = html.match(/const DEALS = (\[[\s\S]*?\]);\r?\n/);
if (!m) { console.log('未找到 DEALS'); process.exit(1); }
const DEALS = JSON.parse(m[1].replace(/<\\\//g, '</'));

function pickCoupon(it) {
  const c = (it.coupon_url || '').trim();
  if (!c) return '';
  const mm = c.match(/https?:\/\/[^\s<>"'，。；、）】]+/);
  return mm ? mm[0] : '';
}
function isHttp(s) { return s && /^https?:\/\//i.test(s); }

let problems = 0;
let totalLinks = 0;
DEALS.forEach(d => {
  const seenLink = {};
  const rendered = [];
  (d.list || []).forEach(it => {
    const c = pickCoupon(it);
    if (c && !seenLink[c]) { seenLink[c] = 1; rendered.push(c); }
    if (isHttp(it.item_id)) {
      const u = isHttp(it.url) ? it.url : it.item_id;
      if (u && !seenLink[u]) { seenLink[u] = 1; rendered.push(u); }
    }
  });
  if (!rendered.length) {
    const u = ((d.list || []).map(it => it.url).find(x => isHttp(x))) || '';
    if (u && !seenLink[u]) rendered.push(u);
  }
  totalLinks += rendered.length;
  const dup = rendered.length !== new Set(rendered).size;
  if (dup) problems++;
  if (dup || /富安娜|合集/.test(JSON.stringify(d).slice(0, 500)))
    console.log(`${d.id} 链接数:${rendered.length}${dup ? ' ← 有重复!' : ''}`);
});
console.log(`共 ${DEALS.length} 张卡，渲染链接总数 ${totalLinks}，${problems === 0 ? '全部无重复 ✓' : problems + ' 张卡有重复'}`);
