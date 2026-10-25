// Pages Function: GET /api/clicks
// 读全部点击计数 D1 精确版（Boss 2026-10-25 升级）：GROUP BY day, ev 聚合返回。
// {
//   "detail": { "2026-10-25_banner_tb": 37, ... },   // 按天+事件明细
//   "total":  { "banner_tb": 52, "banner_jd": 33, ... } // 按事件合计
// }
export async function onRequest(context) {
  const { env } = context;
  const detail = {};
  const total = {};
  try {
    const r = await env.CLICKS_DB.prepare(
      "SELECT day, ev, COUNT(*) AS c FROM clicks GROUP BY day, ev ORDER BY day DESC, c DESC"
    ).all();
    for (const row of (r.results || [])) {
      if (!row.ev) continue;
      detail[row.day + "_" + row.ev] = row.c;
      total[row.ev] = (total[row.ev] || 0) + row.c;
    }
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e) }), {
      status: 500,
      headers: { "content-type": "application/json; charset=utf-8" },
    });
  }
  return new Response(JSON.stringify({ detail, total }, null, 1), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": "*",
      "cache-control": "no-store",
    },
  });
}
