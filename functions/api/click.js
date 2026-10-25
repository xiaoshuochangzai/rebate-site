// Pages Function: GET /api/click?e=<事件名>
// 点击计数 D1 精确版（Boss 2026-10-25 升级）：每次点击 INSERT 一行，零丢失
// （KV 版同 key 限 1 写/秒有少量丢失；本站流量上 D1 后无误差，免费额度 10 万写/天）。
// D1 绑定名 CLICKS_DB；表 clicks(day TEXT, ev TEXT) 由本函数懒建（IF NOT EXISTS 幂等）。
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
    const db = env.CLICKS_DB;
    await db.prepare("CREATE TABLE IF NOT EXISTS clicks (day TEXT NOT NULL, ev TEXT NOT NULL)")
      .run();
    await db.prepare("INSERT INTO clicks (day, ev) VALUES (?, ?)").bind(day, e).run();
  } catch (_) {}
  return new Response("ok", { status: 200, headers });
}
