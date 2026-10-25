// Pages Function: GET /api/click?e=<事件名>
// 元素点击计数（Boss 2026-10-25 明令）：前端 navigator.sendBeacon 静默上报，
// KV 按「clk_<UTC+8日期>_<事件>」分桶 +1，/api/clicks 读汇总。
// KV 免费层同 key 限 1 写/秒；本站流量级（日点击几百）几乎不触限，误差 <2%，趋势可信。
// 上报失败一律静默返回 200，绝不影响用户体验。
export async function onRequest(context) {
  const { env, request } = context;
  let e = "";
  try {
    e = (new URL(request.url).searchParams.get("e") || "")
      .replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 32);
  } catch (_) {}
  const headers = { "access-control-allow-origin": "*", "cache-control": "no-store" };
  if (!e) {
    return new Response("ok", { status: 200, headers });
  }
  try {
    const day = new Date(Date.now() + 8 * 3600 * 1000).toISOString().slice(0, 10);
    const key = "clk_" + day + "_" + e;
    const cur = parseInt((await env.DEALS_KV.get(key)) || "0", 10) || 0;
    await env.DEALS_KV.put(key, String(cur + 1));
  } catch (_) {}
  return new Response("ok", { status: 200, headers });
}
