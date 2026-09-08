# -*- coding: utf-8 -*-
"""关键词订阅推送：新线报命中关键词 → 企业微信智能机器人（长连接 aibot_send_msg）推送。

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
import urllib.request

try:
    import wecom_push
except Exception:
    wecom_push = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "keyword_config.json")
PUSHED_FILE = os.path.join(BASE_DIR, "keyword_pushed.json")  # 最近已推送线报 id 环形记录，防重
PENDING_FILE = os.path.join(BASE_DIR, "keyword_pending.json")  # 攒着待发的命中线报（节流用）
STATE_FILE = os.path.join(BASE_DIR, "keyword_state.json")      # {"last_push": 时间戳}
MAX_PER_ROUND = 5        # 单条消息最多合并几条理报
MIN_PUSH_INTERVAL = 600  # 两次推送最小间隔（秒），默认10分钟；攒够 MAX_PER_ROUND 条可提前发
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


def _load_last_push():
    return float(_load_json(STATE_FILE, {}).get("last_push", 0) or 0)


def _save_last_push(ts):
    _save_json(STATE_FILE, {"last_push": ts})


def _fmt_one(deal):
    """转链后的完整文案，原样输出（链接什么样就什么样，不改写、不加装饰）。"""
    txt = (deal.get("_originalContext") or deal.get("_formatContext") or "").strip()
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


def flush(deals, log=print):
    """推送本轮命中关键词的新线报。deals=本轮新入库线报列表（时间倒序）。
    节流：命中先攒进 pending，攒够 MAX_PER_ROUND 条 或 距上次推送超过 min_interval 秒才发一条汇总。
    返回推送条数。每次调用都重读配置（改 keyword_config.json 热生效）。"""
    _load_config()
    if not _STATE["keywords"]:
        return 0
    pushed_ids = _load_pushed()
    pushed_set = set(pushed_ids)
    pending = _load_pending()
    pending_ids = {str(p.get("id")) for p in pending}
    for d in deals:
        did = str(d.get("id"))
        if did in pushed_set or did in pending_ids:
            continue
        if _hit_keywords(d):
            pending.append(d)
            pending_ids.add(did)
    if not pending:
        return 0
    min_iv = int(_STATE.get("min_interval") or MIN_PUSH_INTERVAL)
    now = time.time()
    due = len(pending) >= MAX_PER_ROUND or (now - _load_last_push()) >= min_iv
    if not due:
        _save_pending(pending)
        return 0
    batch = pending[:MAX_PER_ROUND]
    # 原样合并：多条线报的完整文案直接拼一起，中间空一行，不加任何改写和装饰
    blocks = [_fmt_one(d).strip() for d in batch]
    blocks = [b for b in blocks if b]
    text = "\n\n".join(blocks)
    ok, msg = _send(text, log)
    if ok:
        pushed_ids.extend(str(d.get("id")) for d in batch)
        _save_pushed(pushed_ids)
        _save_pending(pending[len(batch):])
        _save_last_push(now)
        log(f"关键词推送成功 {len(batch)} 条（{msg}）")
        return len(batch)
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
