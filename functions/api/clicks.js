// Pages Function: GET /api/clicks
// 读全部点击计数（Boss 2026-10-25 明令）：KV list 前缀 clk_ 聚合返回。
// {
//   "detail": { "2026-10-25_banner_tb": 37, ... },   // 按天+事件明细
//   "total":  { "banner_tb": 52, "banner_jd": 33, ... } // 按事件合计
// }
export async function onRequest(context) {
  const { env } = context;
  const detail = {};
  const total = {};
  try {
    let cursor;
    do {
      const r = await env.DEALS_KV.list({ prefix: "clk_", cursor: cursor, limit: 1000 });
      for (const k of (r.keys || [])) {
        const name = k.name;                       // clk_2026-10-25_banner_tb
        const v = parseInt((await env.DEALS_KV.get(name)) || "0", 10) || 0;
        const day = name.slice(4, 14);             // 2026-10-25
        const ev = name.slice(15);                 // banner_tb
        if (!ev) continue;
        detail[day + "_" + ev] = v;
        total[ev] = (total[ev] || 0) + v;
      }
      cursor = r.list_complete ? undefined : r.cursor;
    } while (cursor);
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
