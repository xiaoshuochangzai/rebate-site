# -*- coding: utf-8 -*-
"""淘宝超级红包：实时生成淘口令 + 推广短链（2026-10-23 上线）。

为什么必须实时生成（实测结论）：
1. 微信 WebView 屏蔽 tbopen:// scheme 与 Universal Link，H5 无法直接拉起淘宝 App。
   淘宝的 s.tb.cn / s.click.taobao.com 都是「靠 JS 调 scheme 的 H5 中间页」，
   在微信里点开会停在淘宝 H5 → 未登录 → **弹登录页**（这就是之前「跳登录页」的根因）。
   行业标准解法 = 复制淘口令 → 用户切到淘宝 App → 淘宝读剪贴板自动弹红包。
   好单库 gather_new.min.js 的 be() 就是这么做的（link 传空串，恒走复制口令）。
2. 写死的口令会过期，且不保证绑我们推广位。

接口：好单库 v2 createConference_code（POST form-urlencoded）
  参数：apikey + pid + tb_name + activity_id + title + get_taoword=1 + domain
  返回：data.tao_code（淘口令）/ data.link（s.tb.cn 短链）/ data.url（长链）
  pid 必填（缺失报「缺少必要参数pid，title」）→ 出链必绑我们推广位；
  每次调用口令都不同，实时生成不会过期。
  ⚠️ 该接口只吃 POST，GET 会返回「您未在白名单内」。

产物：site/redpack.json + CF KV "redpack"（前端 /api/redpack 读）
"""
import json
import os
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

APIKEY = "9AC3C71D776A"
PID = "mm_2130470034_3434000269_116316900171"
TB_NAME = "淘淘淘淘yh"
API_CHECK = "https://v2.api.haodanku.com/checkAd"
API_CONF = "https://v2.api.haodanku.com/createConference_code"
CODE = "pXVDTx"                     # 好单库红包活动 code
STATE = "redpack_tb_state.json"   # 注意：不能叫 redpack_state.json（与 keyword_push 撞名互相覆盖）
OUT = os.path.join("site", "redpack.json")
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.42")
REFRESH_SEC = 6 * 3600             # 口令 6 小时换一次（KV 写量 4 次/天）
FALLBACK = {"tpwd": "77￥ HU926 6FiQTthHJE8￥", "url": "https://m.tb.cn/h.jXgUEoC"}


def _http_json(url, data=None, timeout=25):
    headers = {"User-Agent": UA}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(st):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
    except Exception:
        pass


def gen_tb():
    """实时生成淘宝红包口令 + 短链。返回 dict：{tpwd, url, raw_url, activity_id}"""
    cfg = _http_json(API_CHECK + "?" + urllib.parse.urlencode({"code": CODE, "fq": "web"}))
    data = (cfg.get("data") or {})
    act_id = data.get("activity_id") or "20150318020007201"
    act_name = data.get("activity_name") or "双11超级红包"
    p = {"apikey": APIKEY, "pid": PID, "tb_name": TB_NAME,
         "activity_id": act_id, "title": act_name, "get_taoword": 1,
         "domain": "shengqian.cyou"}
    r = _http_json(API_CONF, data=p)
    if r.get("code") != 200:
        raise RuntimeError("createConference_code code=%s msg=%s" % (r.get("code"), r.get("msg")))
    d = r.get("data") or {}
    tpwd = d.get("tao_code") or ""
    link = d.get("link") or ""
    if not tpwd:
        raise RuntimeError("无 tao_code: %s" % json.dumps(d, ensure_ascii=False)[:120])
    return {"tpwd": tpwd, "url": link or d.get("url") or "",
            "raw_url": d.get("url") or "", "activity_id": act_id,
            "activity_name": act_name, "gen_at": int(time.time())}


def refresh(force=False, log=print):
    """刷新红包配置：淘宝口令（6 小时有效）+ 京东链接（沿用精品库通道重转）。"""
    st = _load_state()
    tb = st.get("tb") or {}
    fresh = (not force and tb.get("tpwd")
             and time.time() - float(tb.get("gen_at") or 0) < REFRESH_SEC)
    if fresh:
        tb_new = tb
        tb_msg = "口令未过期，复用"
    else:
        try:
            tb_new = gen_tb()
            tb_msg = "新口令 %s" % tb_new["tpwd"]
        except Exception as e:
            tb_new = dict(tb) or dict(FALLBACK)
            tb_new.setdefault("gen_at", int(time.time()))
            tb_msg = "生成失败沿用旧值(%s)" % str(e)[:60]

    jd = st.get("jd") or "https://u.jd.com/FDFQoBI"
    try:
        import keyword_push
        jd = keyword_push._get_redpack_link(log=log) or jd
    except Exception as e:
        tb_msg += " | 京东重转异常 %s" % str(e)[:50]

    rp = {"jd": jd,
          "tb": {"tpwd": tb_new.get("tpwd") or FALLBACK["tpwd"],
                 "url": tb_new.get("url") or FALLBACK["url"]},
          "tb_updated": tb_new.get("gen_at") or 0}
    try:
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(rp, f, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        tb_msg += " | 落盘异常 %s" % str(e)[:50]

    st["tb"] = tb_new
    st["jd"] = jd
    _save_state(st)

    kv_msg = "KV跳过"
    try:
        import cf_kv
        ok, msg = cf_kv.put_redpack(rp)
        kv_msg = "KV %s" % ("成功" if ok else "失败:" + str(msg)[:60])
    except Exception as e:
        kv_msg = "KV异常 %s" % str(e)[:60]

    log("[redpack] %s | %s | %s | 淘宝 %s" % (tb_msg, kv_msg, rp["tb"]["url"], rp["tb"]["tpwd"]))
    return rp


if __name__ == "__main__":
    print(json.dumps(refresh(force=True), ensure_ascii=False, indent=1))
