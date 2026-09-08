# -*- coding: utf-8 -*-
"""关键词订阅推送：新线报命中关键词 → 企业微信群机器人 webhook 推送。

配置文件 keyword_config.json（与本文件同目录）：
{
  "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx",
  "keywords": ["洗衣液", "纸尿裤"]
}

纪律：
- 只有「新入库」的线报才进入推送队列（存量/重启不重推）
- 每轮最多合并成 1 条 markdown 消息，最多 MAX_PER_ROUND 条，防轰炸
- webhook 失败只记日志不重试（下一轮新线报继续，不阻塞主流程）
"""
import json
import os
import re
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "keyword_config.json")
PUSHED_FILE = os.path.join(BASE_DIR, "keyword_pushed.json")  # 最近已推送线报 id 环形记录，防重
MAX_PER_ROUND = 5
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_STATE = {"webhook": "", "keywords": [], "loaded": False}


def _load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f) or {}
        _STATE["webhook"] = (cfg.get("webhook") or "").strip()
        kws = cfg.get("keywords") or []
        _STATE["keywords"] = [str(k).strip().lower() for k in kws if str(k).strip()]
    except Exception:
        _STATE["webhook"] = ""
        _STATE["keywords"] = []
    _STATE["loaded"] = True
    return _STATE


def reload_config():
    """关键词/webhook 改了配置文件后调用即可热生效（无需重启监控）。"""
    return _load_config()


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


def _send_markdown(text):
    if not _STATE["webhook"]:
        return False, "webhook 未配置"
    payload = json.dumps({"msgtype": "markdown", "markdown": {"content": text[:4000]}}).encode("utf-8")
    req = urllib.request.Request(_STATE["webhook"], data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d.get("errcode") == 0:
            return True, "ok"
        return False, f"errcode={d.get('errcode')} {str(d.get('errmsg'))[:80]}"
    except Exception as e:
        return False, str(e)[:120]


def _fmt_one(deal):
    plat = "京东" if str(deal.get("platform")) == "2" else "淘宝"
    price = deal.get("_couponAfterPrice") or deal.get("price") or ""
    price_s = f" ¥{price}" if price else ""
    first_line = _copy_text(deal).split("\n")[0][:60] if _copy_text(deal) else (deal.get("cate") or "")
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


def flush(deals, log=print):
    """推送本轮命中关键词的新线报。deals=本轮新入库线报列表（时间倒序）。
    返回推送条数。每次调用都重读配置（改 keyword_config.json 热生效）。"""
    _load_config()
    if not _STATE["webhook"] or not _STATE["keywords"]:
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
    lines.append(f"命中：<font color=\"warning\">{all_kw}</font>")
    lines.append("")
    for kws, d in hits:
        lines.append(_fmt_one(d))
        lines.append("")
    ok, msg = _send_markdown("\n".join(lines))
    if ok:
        pushed_ids.extend(str(d.get("id")) for _, d in hits)
        _save_pushed(pushed_ids)
        log(f"关键词推送成功 {len(hits)} 条（命中：{all_kw}）")
        return len(hits)
    log(f"关键词推送失败：{msg}")
    return 0


def test_push(log=print):
    """不经过关键词，直接推一条任意线报，验证 webhook 通不通。"""
    if not _STATE["loaded"]:
        _load_config()
    if not _STATE["webhook"]:
        log("webhook 未配置（keyword_config.json 里填 webhook 字段）")
        return False
    ok, msg = _send_markdown("**🔔 关键词推送链路测试**\n> 收到此条 = 机器人通道 OK")
    log(("测试推送成功 ✓ " if ok else "测试推送失败 ✗ ") + msg)
    return ok


if __name__ == "__main__":
    _load_config()
    print("webhook:", (_STATE["webhook"][:60] + "...") if _STATE["webhook"] else "未配置")
    print("keywords:", _STATE["keywords"])
    test_push()
