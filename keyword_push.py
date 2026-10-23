# -*- coding: utf-8 -*-
"""线报推送：京东新线报全推（不限关键词，Boss 2026-09-11 明令）+ 淘宝命中关键词才推 → 企业微信智能机器人。

配置文件 keyword_config.json（与本文件同目录）：
{
  "bot_id": "aibot的BotID",
  "secret": "长连接专用Secret",
  "keywords": ["洗衣液", "纸尿裤"],
  "chatids": [],                      // 可选：指定推送的会话；留空则推给所有已交互过的会话
  "auto_push_on_capture": true        // 首次有会话跟机器人互动时，自动推一条真实线报当测试
}

推送目标会话 chatid 从回调自动捕获：用户在群里 @机器人 或单聊发任意一条消息即可注册。
企微规则：用户必须先给机器人发过消息，机器人才能向该会话主动推送（30条/分钟、1000条/小时）。

纪律：
- 只有「新入库」的线报才进入推送队列（存量/重启不重推）
- 每轮最多合并成 1 条 markdown 消息，最多 MAX_PER_ROUND 条，防轰炸
- 推送失败只记日志不重试（下一轮新线报继续，不阻塞主流程）
"""
import json
import os
import time
import re
import urllib.request

try:
    import wecom_push
except Exception:
    wecom_push = None

try:
    import wecom_ext
except Exception:
    wecom_ext = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "keyword_config.json")
PUSHED_FILE = os.path.join(BASE_DIR, "keyword_pushed.json")  # 最近已推送线报 id 环形记录，防重
PENDING_FILE = os.path.join(BASE_DIR, "keyword_pending.json")  # 攒着待发的命中线报（节流用）
STATE_FILE = os.path.join(BASE_DIR, "keyword_state.json")      # {"last_push": 时间戳}
MAX_PER_ROUND = 10       # 单轮最多合并几条线报（京东7 + 淘宝3，按 Boss 70%/30% 配比）
JD_QUOTA = 7             # 每轮京东最多推几条（70%）——各守各的配额，一边没货不多发另一边
TB_QUOTA = 3             # 每轮淘宝最多推几条（30%）
TB_SEP = "——"            # 淘宝多条合并时每条线报之间的分隔行（Boss 2026-09-11 明令，方便看清哪到哪是一条）
JD_TAG = "【京东】"       # 京东线报消息开头平台标识（Boss 2026-09-16 明令）
TB_TAG = "【淘宝】"       # 淘宝必推榜消息开头平台标识（Boss 2026-10-16 明令）
FOOTER_EVERY = 5         # 京东每发满 5 条消息才带一次底部站链尾，其余不带（Boss 2026-09-16 明令）
TB_FOOTER_EVERY = 2      # 淘宝每 2 条带一次双11破价站链尾（Boss 2026-10-16 明令，替代旧「淘宝无尾」规则）

# ---- 23:27 夜闸（Boss 2026-10-16 明令：电脑 23:30 自动关机）----
NIGHTGATE_HM = "23:27"   # 此刻起停发一切线报，改发一次收播公告；次日 0 点自动恢复
NIGHT_MSG = "@所有人 今日劲爆低价线报都在下面网站，不要错过\nhttps://shengqian.cyou/"

# ---- 双11红包场次播报（Boss 2026-10-17 明令）----
# 数据源：好单库活动日历接口（message_text=官方原文文案，含时间点），每天自动刷新+快照兜底
# 发送规则：京东「10点」场 10:59 发（Boss 指定）；其它带时间场次提前 1 分钟；无时间（全天型）默认 10:59；
#          0 点场跳过（电脑 23:30 关机，前一天 23:59 守不了）。发出后全局静默 2 分钟不发线报。
CAL_URL = "https://www.haodanku.com/ActivityApi/getCalandar?id=24"
CAL_SNAPSHOT = os.path.join(BASE_DIR, "hd_calandar_snapshot.json")
REDPACK_STATE = os.path.join(BASE_DIR, "redpack_state.json")
REDPACK_JD_URL = "https://u.jd.com/FDFQoBI"   # 京享红包兜底链接（Boss 提供）
REDPACK_SRC_URL = "https://u.jd.com/FDFQoBI"  # 重转源：京享红包活动原始链接
REDPACK_REFRESH_EVERY = 10  # 每 10 次使用重转一次（Boss 2026-10-19 明令；campaign=t_1001330651 是他联盟 ID，转链正常才带）
REDPACK_TB_TAIL = "淘宝红包口令：77￥ HU926 6FiQTthHJE8￥（复制后打开淘宝APP自动弹出）\nhttps://m.tb.cn/h.jXgUEoC"


def _tb_redpack_tail():
    """淘宝红包尾文案：优先用实时生成的口令+短链（redpack_fetch 写 site/redpack.json）。

    微信内点 s.tb.cn / m.tb.cn 只会落到淘宝H5登录页（微信拦 tbopen:// scheme），
    所以以「口令」为主，链接作为非微信环境的直跳入口。
    """
    try:
        with open(os.path.join(BASE_DIR, "site", "redpack.json"), encoding="utf-8") as f:
            tb = (json.load(f) or {}).get("tb") or {}
        tpwd, url = tb.get("tpwd"), tb.get("url")
        if tpwd and url:
            return "淘宝红包口令：%s（复制后打开淘宝APP自动弹出）\n%s" % (tpwd, url)
    except Exception:
        pass
    return REDPACK_TB_TAIL
REDPACK_MUTE_SEC = 120   # 文案发出后 2 分钟线报静默（Boss 明令）
_RP_CACHE = {"cal": None}
REDPACK_EVERY = 1        # 京东每 2 条带一次红包推广（Boss 2026-10-13 明令）
REDPACK_URL = "https://u.jd.com/FrBoSd3"
# 钩子按线报内容匹配（Boss 2026-10-13 明令：与线报文案相配，嵌入无违和）：
# 提取线报特征（凑单/首单/plus/赠/券/价格）→ 选对应钩子组，组内按天轮换；无特征走默认池
REDPACK_HOOKS = {
    "coupon": ["凑单前先领，凑得更划算", "领完这张再去凑单", "叠上这张，凑单更省", "这张不领，凑单白凑"],
    "first": ["首单叠上这个，更划算", "首单价之上还能再省"],
    "plus": ["plus 会员再叠一层", "plus 下单前先领这个"],
    "gift": ["赠品之外，还能再省一笔"],
    "juan": ["这张不领，等于多花钱", "再领一张，减得更多"],
    "price": ["到手价还能再低一点", "叠上它，比页面价还低", "券后还能再省一笔"],
    "default": ["还能再叠一层优惠", "一单一领，天天都能省", "多领一张，多省一笔"],
}


def _pick_hook(text):
    """按线报内容选钩子：特征优先级 凑单>首单>plus>赠>券>价格>默认；组内按天轮换。"""
    import datetime
    r = datetime.date.today().toordinal()

    def pick(lst):
        return lst[r % len(lst)]

    if "凑单" in text:
        return pick(REDPACK_HOOKS["coupon"])
    if "首单" in text:
        return pick(REDPACK_HOOKS["first"])
    if "plus" in text.lower():
        return pick(REDPACK_HOOKS["plus"])
    if "赠" in text or "返" in text:
        return pick(REDPACK_HOOKS["gift"])
    if "券" in text or "奍" in text or "卷" in text or "榮" in text:
        return pick(REDPACK_HOOKS["juan"])
    if re.search(r"\d+(\.\d+)?元|【\d+(\.\d+)?】", text):
        return pick(REDPACK_HOOKS["price"])
    return pick(REDPACK_HOOKS["default"])


def _apply_redpack(text):
    """嵌入红包钩子：插在第一条链接行之后（混进券堆，与线报融为一体）。"""
    hook = _pick_hook(text)
    out, inserted = [], False
    for ln in text.split("\n"):
        out.append(ln)
        if not inserted and ("http://" in ln or "https://" in ln):
            out.append(hook)
            out.append(REDPACK_URL)
            inserted = True
    if not inserted:
        out += [hook, REDPACK_URL]
    return "\n".join(out)
JD_SEND_GAP = 2.0        # 逐条发送间隔（秒）。0.6 太密：停摆恢复后 7 条连发 4 秒内打完=「一发就一串」（Boss 2026-10-13 明令修）；2s 间隔把突发摊平
MIN_PUSH_INTERVAL = 600  # 两次推送最小间隔（秒），默认10分钟；攒够 MAX_PER_ROUND 条可提前发
STALE_AFTER = 1800       # 积压超 30 分钟的待推线报直接丢弃不发（对齐 wecom_ext DROP_AFTER；主循环停摆恢复后防旧货倾泻成串，Boss 2026-10-13 明令「不发就不发，一发就一串是毛病」）
WEBHOOK_MAX = 1800       # 企微 text 消息单条上限 2048 字节，这里留余量
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 绕开本机代理

_STATE = {"keywords": [], "chatids": [], "loaded": False}


def _load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f) or {}
        kws = cfg.get("keywords") or []
        _STATE["keywords"] = [str(k).strip().lower() for k in kws if str(k).strip()]
        _STATE["chatids"] = [str(c).strip() for c in (cfg.get("chatids") or []) if str(c).strip()]
        _STATE["webhook"] = (cfg.get("webhook") or "").strip()
        _STATE["channel"] = (cfg.get("channel") or ("webhook" if _STATE["webhook"] else "longconn")).strip()
        _wext = cfg.get("wecom_ext") or {}
        if wecom_ext is not None:
            wecom_ext.configure(_wext)
        try:
            _STATE["min_interval"] = int(cfg.get("min_interval") or MIN_PUSH_INTERVAL)
        except Exception:
            _STATE["min_interval"] = MIN_PUSH_INTERVAL
    except Exception:
        _STATE["keywords"] = []
        _STATE["chatids"] = []
    _STATE["loaded"] = True
    return _STATE


def reload_config():
    """关键词改了配置文件后调用即可热生效（无需重启监控）。"""
    return _load_config()


def start():
    """监控进程启动时调用。只有 channel=longconn 才拉起企微长连接线程（webhook 通道不需要）。"""
    _load_config()
    if _STATE.get("channel") == "longconn" and wecom_push is not None:
        wecom_push.start()
    if wecom_ext is not None:
        wecom_ext.start()


def _copy_text(deal):
    parts = []
    for it in deal.get("list", []):
        if it.get("content"):
            parts.append(it["content"])
    return "\n".join(parts).strip()


def _hit_keywords(deal):
    """返回命中的关键词列表（空列表=不命中）。"""
    if not _STATE["keywords"]:
        return []
    text = (_copy_text(deal) + " " + (deal.get("cate") or "")).lower()
    return [k for k in _STATE["keywords"] if k in text]


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or default
    except Exception:
        return default


def _save_json(path, obj):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    except Exception:
        pass


def _load_pushed():
    return _load_json(PUSHED_FILE, [])


def _save_pushed(ids):
    # 环形保留最近 2000 条，防文件无限膨胀
    _save_json(PUSHED_FILE, ids[-2000:])


def _load_pending():
    return _load_json(PENDING_FILE, [])


def _save_pending(items):
    _save_json(PENDING_FILE, items[-200:])


def _load_state():
    return _load_json(STATE_FILE, {}) or {}


def _load_last_push():
    return float(_load_state().get("last_push", 0) or 0)


def _save_last_push(ts):
    st = _load_state()
    st["last_push"] = ts
    _save_json(STATE_FILE, st)


def _bump_sent(n=1):
    """累计已发消息条数（用于「每 5 条才带一次站链尾」），返回本次发完后的累计值。"""
    st = _load_state()
    st["sent_cnt"] = int(st.get("sent_cnt", 0) or 0) + n
    _save_json(STATE_FILE, st)
    return st["sent_cnt"]


def _load_sent():
    return int(_load_state().get("sent_cnt", 0) or 0)


def _bump_tb_sent(n=1):
    """淘宝已发条数（用于「每 2 条带一次站链尾」，Boss 2026-10-16 明令），返回本次发完后的累计值。"""
    st = _load_state()
    st["tb_sent_cnt"] = int(st.get("tb_sent_cnt", 0) or 0) + n
    _save_json(STATE_FILE, st)
    return st["tb_sent_cnt"]


def _get_redpack_link(log=print):
    """京享红包尾链接：每 10 次使用重转一次（Boss 2026-10-19 明令）。
    转链源固定为 Boss 提供的活动原始链接 REDPACK_SRC_URL；经精品库登录账号
    （联盟 ID t_1001330651）出链。短链跳转全加密（u.jd.com/jda?e=..&p=..），
    服务端验不了 campaign 参数，以「转链通道成功出 u.jd.com 新短链」为准——
    通道就是商品转链同一账号，出链必然绑他联盟 ID。
    转链失败沿用旧链接，绝不阻塞推送。计数存 keyword_state.json 重启接着数。"""
    st = _load_state()
    link = (st.get("redpack_link") or "").strip()
    used = int(st.get("redpack_used", 0) or 0)
    if (not link) or used >= REDPACK_REFRESH_EVERY:
        new = ""
        try:
            import jp_api
            ok, out, _imgs = jp_api.convert_material(REDPACK_SRC_URL)
            if ok and out:
                m = re.search(r"https?://u\.jd\.com/\w+", out)
                if m:
                    new = m.group(0)
        except Exception as e:
            log(f"京享红包重转异常（沿用旧链接）：{str(e)[:60]}")
        if new:
            log(f"京享红包链接已重转：{new}（旧：{link or '无'}，已用 {used} 次）")
            link = new
            used = 0
        else:
            log(f"京享红包重转未出新链（沿用 {link or REDPACK_JD_URL}）")
    st = _load_state()
    st["redpack_link"] = link
    st["redpack_used"] = used + 1
    _save_json(STATE_FILE, st)
    return link or REDPACK_JD_URL


def _fmt_one(deal):
    """转链后的完整文案，原样输出（链接什么样就什么样，不改写、不加装饰）。
    Boss 2026-09-12 明令：京东优先用 _siteContext（悦拜短链版），企微群里不再出裸 u.jd.com；
    淘宝/无保护的旧数据自动回退 _originalContext 原文。"""
    txt = (deal.get("_siteContext") or deal.get("_originalContext") or deal.get("_formatContext") or "").strip()
    if txt:
        return txt
    parts = []
    for it in deal.get("list", []):
        v = it.get("content") or it.get("url") or it.get("coupon_url") or it.get("item_id") or ""
        v = (v or "").strip()
        if v:
            parts.append(v)
    return "\n".join(parts).strip()


def _targets():
    """推送目标：配置指定 chatids 优先；否则推给所有已交互会话。"""
    if _STATE["chatids"]:
        return _STATE["chatids"]
    return list(wecom_push.known_chatids().keys())


def _chunks(text, limit=WEBHOOK_MAX):
    """按行切分，保证每片不超过 limit 字节（企微 text 单条上限 2048 字节）。"""
    out, cur = [], ""
    for ln in text.split("\n"):
        add = (cur + "\n" + ln) if cur else ln
        if len(add.encode("utf-8")) > limit and cur:
            out.append(cur)
            cur = ln
        else:
            cur = add
    if cur:
        out.append(cur)
    return out


def _send_webhook(text):
    """群机器人 webhook：text 消息原样发（链接保持原样），超长自动分片。"""
    wh = _STATE.get("webhook", "")
    if not wh:
        return False, "webhook 未配置"
    results, ok_all = [], True
    for c in _chunks(text):
        payload = json.dumps({"msgtype": "text", "text": {"content": c}}).encode("utf-8")
        req = urllib.request.Request(wh, data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with OPENER.open(req, timeout=10) as r:
                d = json.loads(r.read().decode("utf-8"))
            if d.get("errcode") == 0:
                results.append("ok")
                if wecom_ext is not None:
                    wecom_ext.enqueue(c)   # 同步入外部群队列（低频派发，wecom_ext 自控）
            else:
                ok_all = False
                results.append(f"errcode={d.get('errcode')} {str(d.get('errmsg'))[:60]}")
        except Exception as e:
            ok_all = False
            results.append(str(e)[:80])
        time.sleep(0.4)
    return ok_all, (f"{len(results)}片 " + "; ".join(results))


def _send(text, log=print):
    if _STATE.get("channel") == "webhook" or _STATE.get("webhook"):
        return _send_webhook(text)
    if wecom_push is None:
        return False, "未配置 webhook，也没有长连接模块"
    targets = _targets()
    if not targets:
        return False, "还没有任何会话跟机器人互动过（在群里@机器人或单聊发条消息即可注册）"
    results = []
    ok_any = False
    for chatid in targets:
        chattype = (wecom_push.known_chatids().get(chatid) or {}).get("chattype", "group")
        ct = 1 if chattype == "single" else 2
        resp = wecom_push.send_markdown(chatid, text[:4000], chat_type=ct)
        err = resp.get("errcode")
        results.append(f"{chatid[:12]}…={err}")
        if err == 0:
            ok_any = True
    return ok_any, "; ".join(results)


def _age_sec(d):
    """条目入站至今的秒数。
    京东用 time（haodanku 发布时间）——重启/停摆积压的旧线报入站时间是当下，
    用 _addedAt 会把 3 小时前的旧货当新鲜货倾泻进群（2026-10-13 停摆 3.4h 实锤）；
    淘宝/必推榜 add_time 是入榜时间（可能几天前），语义不可靠，用 _addedAt 优先。"""
    import datetime as _dt
    keys = ("time",) if str(d.get("platform")) == "2" else ("_addedAt", "time")
    for k in keys:
        s = str(d.get(k) or "").strip()
        try:
            return time.time() - _dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()
        except Exception:
            continue
    return None


def _drop_stale(items, log=print):
    """过滤掉超 STALE_AFTER 的陈旧积压（直接丢弃，不再推送）。"""
    keep, dropped = [], 0
    for d in items:
        age = _age_sec(d)
        if age is None or age > STALE_AFTER:
            dropped += 1
            continue
        keep.append(d)
    if dropped:
        log(f"丢弃陈旧积压 {dropped} 条（超{STALE_AFTER // 60}分钟不入群，防一发一串；网站照常可查）")
    return keep


def _send_announce(log=print):
    """收播公告：主群 webhook 真正 @所有人（mentioned_list），外部群走 RPA 队列（纯文本）。
    返回 True=主群确认送达（errcode==0）。"""
    wh = _STATE.get("webhook", "")
    ok = False
    results = []
    if wh:
        try:
            payload = json.dumps({"msgtype": "text", "text": {
                "content": NIGHT_MSG, "mentioned_list": ["@all"]}}).encode("utf-8")
            req = urllib.request.Request(wh, data=payload,
                                         headers={"Content-Type": "application/json"})
            with OPENER.open(req, timeout=10) as r:
                d = json.loads(r.read().decode("utf-8"))
            ok = (d.get("errcode") == 0)
            results.append("主群@" + ("ok" if ok else f"err{d.get('errcode')}"))
        except Exception as e:
            results.append("主群fail:" + str(e)[:50])
    else:
        results.append("无webhook")
    if wecom_ext is not None:
        wecom_ext.enqueue(NIGHT_MSG)
        results.append("外部群已入队")
    log("[夜闸] 收播公告: " + " | ".join(results))
    return ok


def _night_gate(log=print):
    """23:27-24:00 夜闸期：发一次收播公告（发成功才记当天已发，失败下轮重试），
    并拦下所有线报推送。返回 True=处于夜闸期。由监控主循环每轮无条件调用（night_tick），
    不能只挂在 flush 里——23:27 后没有新线报时 flush 不会被调，公告就发不出去（10-16 晚踩坑）。"""
    if time.strftime("%H:%M") < NIGHTGATE_HM:
        return False
    today = time.strftime("%Y-%m-%d")
    st = _load_state()
    if st.get("announced_on") != today:
        if _send_announce(log):
            st["announced_on"] = today
            _save_json(STATE_FILE, st)
    return True


night_tick = _night_gate   # 监控主循环每轮无条件调用的别名


# ============ 双11红包场次播报 ============

def _rp_load_state():
    try:
        return json.load(open(REDPACK_STATE, encoding="utf-8"))
    except Exception:
        return {}


def _rp_save_state(st):
    try:
        json.dump(st, open(REDPACK_STATE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


def redpack_mute():
    """线报静默窗：红包文案发出后 2 分钟内 True（wecom_ext 也直接读文件用）。"""
    try:
        st = json.load(open(REDPACK_STATE, encoding="utf-8"))
        return time.time() < float(st.get("mute_until", 0) or 0)
    except Exception:
        return False


def _rp_fetch_calendar():
    """抓好单库日历接口；失败读快照。每天首次 tick 刷新一次。"""
    try:
        req = urllib.request.Request(CAL_URL, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
            "Referer": "https://www.haodanku.com/Activity/index?id=24",
            "X-Requested-With": "XMLHttpRequest"})
        with OPENER.open(req, timeout=15) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d.get("code") == 200 and (d.get("data") or {}).get("calendar"):
            json.dump(d["data"], open(CAL_SNAPSHOT, "w", encoding="utf-8"), ensure_ascii=False)
            return d["data"]
    except Exception:
        pass
    try:
        return json.load(open(CAL_SNAPSHOT, encoding="utf-8"))
    except Exception:
        return None


def _rp_slot_from_text(mmdd, plat, text):
    """单段官方文案 → N 个场次（一句文案可含多个时间点，如「10点/20点，准点加码」）。"""
    t = text.strip().strip('！!。；;')
    if not t:
        return []
    times = []
    for m in re.finditer(r"(\d{1,2}):(\d{2})", t):    # 「20:00-20:15」型
        times.append(int(m.group(1)))
    for m in re.finditer(r"(\d{1,2})点", t):          # 「10点」「20点」「10点-24点」型
        times.append(int(m.group(1)))
    if not times:
        return [("10:59", mmdd, plat, t)]             # 全天型默认 10:59
    out, seen = [], set()
    for hh in times:
        if hh in seen:
            continue
        seen.add(hh)
        if hh == 0 or hh >= 23:
            continue   # 0点/23点后：电脑 23:30 关机守不了，跳过
        if plat == "jd" and hh == 10:
            out.append(("10:59", mmdd, plat, t))      # Boss 指定：京东10点场 10:59 发
        else:
            out.append((f"{hh - 1:02d}:59", mmdd, plat, t))   # 其它场次提前1分钟
    return out


def _rp_parse_slots(data, today_str):
    """日历 → 场次列表。只保留今天的场次（明天的不用天天算）。"""
    if isinstance(data, dict) and "data" in data and "calendar" not in data:
        data = data["data"]   # 快照可能存的是整个响应体，剥一层
    slots, month = [], "10"
    for x in data.get("calendar", []):
        if x.get("type") == "month":
            month = (x.get("date") or "10").replace("月", "") or "10"
            continue
        if x.get("type") != "day":
            continue
        day = str(x.get("date"))
        try:
            mmdd = today_str[5:] if day == "今" else f"{int(month):02d}-{int(day):02d}"
        except Exception:
            continue
        msg = x.get("message_text") or ""
        for tag, plat in (("【京东】", "jd"), ("【天猫】", "tb")):
            if tag not in msg:
                continue
            for seg in msg.split("<br/>"):
                if tag not in seg:
                    continue
                body = seg.split(tag, 1)[1]
                for part in re.split(r"活动[①②③④]：", body):
                    slots.extend(_rp_slot_from_text(mmdd, plat, part))
    return slots


def redpack_tick(log=print):
    """监控主循环每轮调用：到点的红包场次发一次官方文案+平台红包入口，然后静默 2 分钟。"""
    today = time.strftime("%Y-%m-%d")
    st = _rp_load_state()
    if st.get("cal_day") != today:
        data = _rp_fetch_calendar()
        if data:
            st["cal_day"] = today
            _rp_save_state(st)
            _RP_CACHE["cal"] = data
        else:
            data = _RP_CACHE.get("cal")
    else:
        data = _RP_CACHE.get("cal")
    if not data:
        return
    slots = [s for s in _rp_parse_slots(data, today) if s[1] == today[5:]]
    if not slots:
        return
    now_hm = time.strftime("%H:%M")
    fired = st.setdefault("fired", {})
    for hhmm, mmdd, plat, text in slots:
        if now_hm < hhmm:
            continue   # 还没到点
        key = f"{mmdd}:{plat}:{hhmm}"
        if fired.get(key):
            continue
        # 错过太久（>15分钟）直接放弃，过期引导发了没意义
        if (time.time() - time.mktime(time.strptime(f"{today} {hhmm}", "%Y-%m-%d %H:%M"))) > 900:
            fired[key] = 1
            _rp_save_state(st)
            continue
        if plat == "jd":
            msg = "【京东】" + text + "\n京东红包入口：" + REDPACK_JD_URL
        else:
            msg = "【淘宝】" + text + "\n" + _tb_redpack_tail()
        ok, info = _send(msg, log)
        if ok:
            fired[key] = 1
            st["mute_until"] = time.time() + REDPACK_MUTE_SEC   # 发出后静默 2 分钟
        elif now_hm <= hhmm:
            pass   # 还在场次窗口内，下轮重试
        else:
            fired[key] = 1   # 超时且失败，放弃
        _rp_save_state(st)
        log(f"[红包场次] {mmdd} {hhmm} {plat} -> {'ok' if ok else 'fail:' + str(info)[:60]}")
        time.sleep(0.4)


def flush(deals, log=print):
    """推送本轮新线报（京东全推；淘宝需命中关键词）。deals=本轮新入库线报列表（时间倒序）。
    节流：先进 pending，攒够 MAX_PER_ROUND 条 或 距上次推送超过 min_interval 秒才发；
    发送时按 70/30 配比（京东≤7 + 淘宝≤3）。
    返回推送条数。每次调用都重读配置（改 keyword_config.json 热生效）。"""
    _load_config()
    # 23:27 夜闸（Boss 2026-10-16 明令）：此后停发线报，改发收播公告，电脑 23:30 关机
    if _night_gate(log=log):
        return 0
    # 京东不限关键词，必推榜新品也不看关键词；两者都没有时才因为没有关键词直接返回
    if not _STATE["keywords"] and not any(d.get("_bitui") for d in deals):
        return 0
    pushed_ids = _load_pushed()
    pushed_set = set(pushed_ids)
    pending = _drop_stale(_load_pending(), log=log)  # 老积压先丢弃，防停摆恢复后旧货倾泻成串
    pending_ids = {str(p.get("id")) for p in pending}
    for d in _drop_stale(deals, log=log):
        did = str(d.get("id"))
        if did in pushed_set or did in pending_ids:
            continue
        # Boss 2026-09-11 13:13 明令：京东不限关键词，有新线报就推
        # Boss 2026-09-16 明令：淘宝只推必推榜新品（_bitui 标记），线报不再按关键词推
        if str(d.get("platform")) == "2" or d.get("_bitui"):
            pending.append(d)
            pending_ids.add(did)
    if not pending:
        return 0
    # 红包文案静默窗（Boss 2026-10-17 明令）：发出后 2 分钟不发线报；新线报照常入队，静默结束补发
    if redpack_mute():
        _save_pending(pending)
        return 0
    min_iv = int(_STATE.get("min_interval") or MIN_PUSH_INTERVAL)
    now = time.time()
    has_jd = any(str(d.get("platform")) == "2" for d in pending)
    # Boss 2026-09-11 13:31 明令：京东「有新就发」——队列里有京东待推即立即推送，
    # 不受「攒满 MAX_PER_ROUND 条」/「10 分钟间隔」限制；淘宝仍按间隔节流，随京东一起发出
    due = has_jd or len(pending) >= MAX_PER_ROUND or (now - _load_last_push()) >= min_iv
    if not due:
        _save_pending(pending)
        return 0
    # 按 70/30 配比选取（Boss 2026-09-11 明令：京东70%、淘宝30%）
    # 京东最多 7 条、淘宝最多 3 条，各守各的配额不互补（互补会破 30% 上限）；没选上的留 pending 下轮继续
    FOOTER = "————\n更多线报访问AI好价线报\nhttps://shengqian.cyou/"
    jd_pool = [d for d in pending if str(d.get("platform")) == "2"]
    tb_pool = [d for d in pending if str(d.get("platform")) != "2"]
    jd = jd_pool[:JD_QUOTA]
    tb = tb_pool[:TB_QUOTA]
    if not jd and not tb:
        _save_pending(pending)
        return 0
    sent_ids, msgs, ok_any = [], [], False
    # Boss 2026-09-16 明令：京东线报一条一条单独发，不再两条以上合并成一条
    for d in jd:
        t = _fmt_one(d).strip()
        if not t:
            sent_ids.append(str(d.get("id")))  # 空文案没得发，直接标已推，防死循环
            continue
        sent_cnt = _bump_sent()  # 站链尾/红包尾都靠这个计数（重启接着数）
        # Boss 2026-10-16 明令：京享红包不再插进消息中间，改成每 2 条在【最后】垫红包尾；
        # 红包尾和每 5 条的旧站链尾都指向 shengqian.cyou，带红包尾的那条就不再叠旧站链尾
        if sent_cnt % REDPACK_EVERY == 0:
            tail = "\n————\n下单前先领京东红包，更省钱\n" + _get_redpack_link(log=log)
        elif sent_cnt % FOOTER_EVERY == 0:
            tail = "\n" + FOOTER
        else:
            tail = ""
        ok, msg = _send(JD_TAG + t + tail, log)
        msgs.append(f"京东1条({'红包尾' if sent_cnt % REDPACK_EVERY == 0 else ('站尾' if tail else '无尾')})({msg})")
        if ok:
            sent_ids.append(str(d.get("id")))
            ok_any = True
        time.sleep(JD_SEND_GAP)
    # Boss 2026-10-07 明令：淘宝（必推榜）也改成一条一条单独发，不再多条合并
    # Boss 2026-10-16 明令：每条开头加【淘宝】；每 2 条在尾巴加双11破价站链尾（替代旧「淘宝无尾」）
    TB_FOOTER = "————\n更多双11破价好物，访问线报网\nhttps://shengqian.cyou/"
    for d in tb:
        t = _fmt_one(d).strip()
        # Boss 2026-10-12 明令：s.click 一律滤掉（含必推榜积压的旧文案），只留淘口令
        t = "\n".join(ln for ln in t.split("\n") if "s.click.taobao.com" not in ln).strip()
        if not t:
            sent_ids.append(str(d.get("id")))  # 空文案没得发，直接标已推，防死循环
            continue
        tb_cnt = _bump_tb_sent()   # 独立计数，重启接着数（与京东 sent_cnt 分开）
        tail = "\n" + TB_FOOTER if tb_cnt % TB_FOOTER_EVERY == 0 else ""
        ok, msg = _send(TB_TAG + t + tail, log)
        msgs.append(f"淘宝1条({'带尾' if tail else '无尾'})({msg})")
        if ok:
            sent_ids.append(str(d.get("id")))
            ok_any = True
        time.sleep(JD_SEND_GAP)
    if ok_any:
        pushed_ids.extend(sent_ids)
        _save_pushed(pushed_ids)
        sent_set = set(sent_ids)
        _save_pending([p for p in pending if str(p.get("id")) not in sent_set])
        _save_last_push(now)
        log(f"关键词推送成功 {len(sent_ids)} 条（{' | '.join(msgs)}）")
        return len(sent_ids)
    log(f"关键词推送失败：{msg}（{len(pending)} 条留到下一轮重试）")
    _save_pending(pending)
    return 0


def build_sample_message():
    """取 deals.json 最新一条带链接的真实线报，拼 markdown（首次捕获会话时自动推）。"""
    deals = []
    for rel in ("deals.json", os.path.join("site", "deals.json")):
        try:
            with open(os.path.join(BASE_DIR, rel), encoding="utf-8") as f:
                deals = json.load(f)
            break
        except Exception:
            continue
    if not deals:
        return ""
    for d in deals[:50]:
        text = _copy_text(d)
        if not text:
            continue
        has_link = any((it.get("url") or it.get("coupon_url") or "").startswith("http")
                       for it in d.get("list", []))
        if not has_link:
            continue
        return "**🔔 线报推送已接通（测试消息）**\n\n" + _fmt_one(d)
    return ""


def test_push(log=print):
    """不经过关键词，直接推一条任意线报，验证长连接通道通不通。"""
    _load_config()
    wecom_push.start()
    msg = build_sample_message() or "**🔔 关键词推送链路测试**\n> 收到此条 = 机器人通道 OK"
    ok, msg2 = _send(msg, log)
    log(("测试推送成功 ✓ " if ok else "测试推送失败 ✗ ") + msg2)
    return ok


if __name__ == "__main__":
    _load_config()
    print("keywords:", _STATE["keywords"])
    print("chatids(file):", list(wecom_push.known_chatids().keys()))
    test_push()
