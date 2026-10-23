// 红包弹层配置读取：KV key "redpack"，形如
// {"jd":"https://u.jd.com/xxx","tb":{"tpwd":"￥ CZ001 ...￥","url":"https://s.tb.cn/..."}}
// 由 redpack_fetch.py 每轮刷新写入（淘宝口令走 createConference_code 实时生成，
// 6 小时换一次，pid 必填 → 出链必绑我们推广位）；京东链接按 Boss 规则每 10 次使用重转一次。
const FALLBACK = {
  jd: "https://u.jd.com/FDFQoBI",
  tb: { tpwd: "77￥ HU926 6FiQTthHJE8￥", url: "https://m.tb.cn/h.jXgUEoC" },
};

export async function onRequest(context) {
  let data = FALLBACK;
  try {
    const v = await context.env.DEALS_KV.get("redpack");
    if (v) {
      const p = JSON.parse(v);
      if (p && (p.jd || (p.tb && p.tb.tpwd))) data = p;
    }
  } catch (e) {
    /* KV 异常/空 → 用兜底常量 */
  }
  return new Response(JSON.stringify(data), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}
