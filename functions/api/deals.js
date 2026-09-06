// Pages Function: GET /api/deals
// 从 KV 实时读线报数据，监控端直接写 KV，无需 CF 构建。
export async function onRequest(context) {
  const { env } = context;
  let v = null;
  try {
    v = await env.DEALS_KV.get("deals");
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e) }), {
      status: 500,
      headers: { "content-type": "application/json; charset=utf-8" },
    });
  }
  return new Response(v || "[]", {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "access-control-allow-origin": "*",
    },
  });
}
