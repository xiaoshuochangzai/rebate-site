# -*- coding: utf-8 -*-
"""红包总开关（Boss 2026-11-12 明令）：京东线报红包尾 + 网页京东/淘宝红包弹层
共用 site/redpack_switch.json 一份配置。

用法（以后 Boss 只给开始/结束时间）：
  把 start/end 填成 "YYYY-MM-DD HH:mm"（北京时间）→ 到点自动开、过点自动关；
  manual=true 强制常开（测试/临时用）；两边都空且 manual=false = 全关（当前状态）。
改 json 即生效：前端每次切 tab 都重新 fetch，Python 侧 60 秒缓存自动刷新。
"""
import json
import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(BASE_DIR, "site", "redpack_switch.json")
_CACHE = {"ts": 0.0, "val": False}


def on():
    """当前是否允许发红包尾 / 弹红包弹层。读盘失败按关闭处理（宁可不弹）。"""
    if time.time() - _CACHE["ts"] < 60:
        return _CACHE["val"]
    val = False
    try:
        with open(CONF, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("manual") is True:
            val = True
        elif d.get("start") and d.get("end"):
            t0 = time.mktime(time.strptime(str(d["start"]).strip(), "%Y-%m-%d %H:%M"))
            t1 = time.mktime(time.strptime(str(d["end"]).strip(), "%Y-%m-%d %H:%M"))
            val = t0 <= time.time() <= t1
    except Exception:
        val = False
    _CACHE["ts"] = time.time()
    _CACHE["val"] = val
    return val
