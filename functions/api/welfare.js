// 双11福利清单实时读取：KV key "welfare"（welfare_auto.py 每 10 分钟整包写入）。
// KV 无数据时返回 404，前端自动回退静态 welfare.json。
export async function onRequest(context) {
  const v = await context.env.DEALS_KV.get("welfare");
  if (!v) {
    return new Response(JSON.stringify({ error: "no welfare data" }), {
      status: 404,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  }
  return new Response(v, {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
