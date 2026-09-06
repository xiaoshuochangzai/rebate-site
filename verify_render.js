// 模拟前端 cardHtml 的文案区渲染，验证：每张卡片内链接不重复、数量正常
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
DEALS.forEach(d => {
  const seenLink = {};
  let promoPushed = false;
  const rendered = [];
  (d.list || []).forEach(it => {
    const c = pickCoupon(it);
    if (c && !seenLink[c]) { seenLink[c] = 1; rendered.push(c); }
    if (isHttp(it.item_id) && !promoPushed) {
      const u = isHttp(it.url) ? it.url : it.item_id;
      if (u && !seenLink[u]) { seenLink[u] = 1; rendered.push(u); }
      promoPushed = true;
    }
  });
  if (!promoPushed) {
    const u = ((d.list || []).map(it => it.url).find(x => isHttp(x))) || '';
    if (u && !seenLink[u]) rendered.push(u);
  }
  const textN = (d.list || []).filter(it => it.content).length;
  const flag = rendered.length !== new Set(rendered).size ? ' ← 有重复!' : '';
  if (flag) problems++;
  console.log(`${d.id} 文案行:${textN} 链接数:${rendered.length}${flag}`);
});
console.log(problems === 0 ? '全部卡片无重复链接 ✓' : `发现 ${problems} 张卡有重复`);
