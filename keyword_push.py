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

import wecom_push

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "keyword_config.json")
PUSHED_FILE = os.path.join(BASE_DIR, "keyword_pushed.json")  # 最近已推送线报 id 环形记录，防重
MAX_PER_ROUND = 5

_STATE = {"keywords": [], "chatids": [], "loaded": False}


def _load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f) or {}
        kws = cfg.get("keywords") or []
        _STATE["keywords"] = [str(k).strip().lower() for k in kws if str(k).strip()]
        _STATE["chatids"] = [str(c).strip() for c in (cfg.get("chatids") or []) if str(c).strip()]
    except Exception:
        _STATE["keywords"] = []
        _STATE["chatids"] = []
    _STATE["loaded"] = True
    return _STATE


def reload_config():
    """关键词改了配置文件后调用即可热生效（无需重启监控）。"""
    return _load_config()


def start():
    """监控进程启动时调用：拉起企微长连接后台线程（幂等）。"""
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


def _load_pushed():
    try:
        with open(PUSHED_FILE, encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def _save_pushed(ids):
    # 环形保留最近 2000 条，防文件无限膨胀
    try:
        with open(PUSHED_FILE, "w", encoding="utf-8") as f:
            json.dump(ids[-2000:], f, ensure_ascii=False)
    except Exception:
        pass


def _fmt_one(deal):
    plat = "京东" if str(deal.get("platform")) == "2" else "淘宝"
    price = deal.get("_couponAfterPrice") or deal.get("price") or ""
    price_s = f" ¥{price}" if price else ""
    text = _copy_text(deal)
    first_line = text.split("\n")[0][:60] if text else (deal.get("cate") or "")
    t = (deal.get("time") or "")[5:16]
    link = ""
    for it in deal.get("list", []):
        for k in ("url", "coupon_url"):
            v = it.get(k) or ""
            if v.startswith("http"):
                link = v
                break
        if link:
            break
    body = f"**[{plat}]{price_s}** {first_line}\n> {t}"
    if link:
        body += f"\n> [下单链接]({link})"
    return body


def _targets():
    """推送目标：配置指定 chatids 优先；否则推给所有已交互会话。"""
    if _STATE["chatids"]:
        return _STATE["chatids"]
    return list(wecom_push.known_chatids().keys())


def _send(text, log=print):
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
    返回推送条数。每次调用都重读配置（改 keyword_config.json 热生效）。"""
    _load_config()
    if not _STATE["keywords"]:
        return 0
    pushed_ids = _load_pushed()
    pushed_set = set(pushed_ids)
    hits = []
    seen_kw = {}
    for d in deals:
        did = str(d.get("id"))
        if did in pushed_set:
            continue
        kws = _hit_keywords(d)
        if kws:
            hits.append((kws, d))
            for k in kws:
                seen_kw.setdefault(k, 0)
                seen_kw[k] += 1
    if not hits:
        return 0
    hits = hits[:MAX_PER_ROUND]
    lines = [f"**🔔 关键词线报提醒**（{time.strftime('%H:%M')}）"]
    all_kw = "、".join(sorted(seen_kw.keys()))
    lines.append(f"命中关键词：**{all_kw}**")
    lines.append("")
    for kws, d in hits:
        lines.append(_fmt_one(d))
        lines.append("")
    ok, msg = _send("\n".join(lines), log)
    if ok:
        pushed_ids.extend(str(d.get("id")) for _, d in hits)
        _save_pushed(pushed_ids)
        log(f"关键词推送成功 {len(hits)} 条（命中：{all_kw} | {msg}）")
        return len(hits)
    log(f"关键词推送失败：{msg}")
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
