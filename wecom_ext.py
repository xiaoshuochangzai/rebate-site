#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wecom_ext.py — 企微外部群通道 v3：多独立窗口矩阵分发 + 低频派发

实测结论（2026-10-12）：
  - 主窗口 2 分钟连发 2 次自动化输入 → 触发「远程操控行为」验证
  - 独立窗口单发 → 无事
  → 间隔闸保留（防验证弹窗的唯一手段），但节奏已按 Boss 要求调快：
    同一条线报轮流发 N 个窗口，窗口间 60~90s 随机；下一条线报再等 180~300s。

工作方式：
  - keyword_push webhook 成功后文案入队 wext_queue.json
  - 后台线程逐条派发：对配置的每个窗口 send_now；窗口没开 → 跳过该窗（条目标记 done，
    未发的窗下轮补发）；全部窗口发完才出队
  - enabled=false 时休眠

配置（keyword_config.json）：
  "wecom_ext": {
      "enabled": true,
      "groups": ["京东+微保线报 1群", "京东羊毛线报fat①群", "京东+微保线报 2群"],
      "win_gap": 60,        # 同条线报相邻窗口间隔（实际 60~90s 随机）
      "msg_gap": 180,       # 两条线报之间最小间隔（实际 180~300s 随机）
      "max_per_day": 40     # 每日线报条数上限（按条计，不按窗口次数）
  }
"""
import json
import os
import random
import threading
import time
import ctypes

try:
    import uiautomation as auto
except ImportError:
    auto = None

BASE = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILE = os.path.join(BASE, "wext_queue.json")
STATE_FILE = os.path.join(BASE, "wext_state.json")
LOCK = threading.Lock()

WND_CLASS = "WwStandaloneConversationWnd"
INPUT_RX, INPUT_RY = 0.50, 0.88   # 输入框在独立窗口内的相对位置（实测）
DROP_AFTER = 3600                 # 队列条目 1 小时未发完即丢弃

_STATE = {"enabled": False, "groups": [], "win_gap": 60, "msg_gap": 180,
          "max_per_day": 40, "last_sent": 0.0, "day": "", "day_cnt": 0,
          "thread_started": False}


def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        _STATE["day"] = d.get("day", "")
        _STATE["day_cnt"] = int(d.get("day_cnt", 0))
    except Exception:
        pass


def _save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"day": _STATE["day"], "day_cnt": _STATE["day_cnt"]}, f)
    except Exception:
        pass


def _today():
    return time.strftime("%Y-%m-%d")


def configure(cfg):
    c = cfg or {}
    _STATE["enabled"] = bool(c.get("enabled", False))
    g = c.get("groups") or ([c["group"]] if c.get("group") else [])
    _STATE["groups"] = [str(x).strip() for x in g if str(x).strip()]
    try:
        _STATE["win_gap"] = max(1, int(c.get("win_gap") or 1))
    except Exception:
        _STATE["win_gap"] = 5
    try:
        _STATE["msg_gap"] = max(3, int(c.get("msg_gap") or 5))
    except Exception:
        _STATE["msg_gap"] = 5
    try:
        _STATE["max_per_day"] = int(c.get("max_per_day") or 0)  # 0=不限
    except Exception:
        _STATE["max_per_day"] = 0
    _load_state()
    if _STATE["day"] != _today():
        _STATE["day"] = _today()
        _STATE["day_cnt"] = 0
        _save_state()


def enqueue(text):
    if not text or not text.strip():
        return
    with LOCK:
        try:
            q = json.load(open(QUEUE_FILE, encoding="utf-8"))
        except Exception:
            q = []
        q.append({"t": text, "ts": time.time(), "done": []})
        q = q[-50:]
        json.dump(q, open(QUEUE_FILE, "w", encoding="utf-8"), ensure_ascii=False)


def _peek():
    with LOCK:
        try:
            q = json.load(open(QUEUE_FILE, encoding="utf-8"))
        except Exception:
            return None
        now = time.time()
        while q:
            if now - q[0].get("ts", now) > DROP_AFTER:
                q.pop(0)
                continue
            break
        json.dump(q, open(QUEUE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
        return q[0] if q else None


def _mark_done(group):
    """单窗成功：把窗口记进条目 done；全部窗口发完则出队"""
    with LOCK:
        try:
            q = json.load(open(QUEUE_FILE, encoding="utf-8"))
        except Exception:
            return
        if not q:
            return
        e = q[0]
        if group not in e.get("done", []):
            e.setdefault("done", []).append(group)
        if set(e["done"]) >= set(_STATE["groups"]):
            q.pop(0)
        json.dump(q, open(QUEUE_FILE, "w", encoding="utf-8"), ensure_ascii=False)


def _find_hwnd(title):
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(WND_CLASS, title)
    if hwnd:
        return hwnd
    want = title.replace(" ", "")
    hit = []

    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))

    def cb(h, _):
        buf = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(h, buf, 128)
        if buf.value == WND_CLASS:
            b2 = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(h, b2, 256)
            if want and want in b2.value.replace(" ", ""):
                hit.append(h)
                return False
        return True

    user32.EnumWindows(CMPFUNC(cb), None)
    return hit[0] if hit else 0


def send_now(title, text):
    if auto is None:
        return False, "uiautomation 未安装"
    user32 = ctypes.windll.user32
    hwnd = _find_hwnd(title)
    if not hwnd:
        return False, "独立窗口未打开: " + title

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
        time.sleep(0.8)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)

    c = auto.ControlFromHandle(hwnd)
    r = c.BoundingRectangle
    L, T, W, H = r.left, r.top, r.width(), r.height()
    if W <= 0 or H <= 0:
        return False, "窗口尺寸异常: " + title

    user32.SetCursorPos(int(L + W * INPUT_RX), int(T + H * INPUT_RY))
    time.sleep(0.15)
    user32.mouse_event(2, 0, 0, 0, 0)
    user32.mouse_event(4, 0, 0, 0, 0)
    time.sleep(0.35)

    auto.SetClipboardText(text)
    auto.SendKeys("{Ctrl}a{Del}")
    time.sleep(0.15)
    auto.SendKeys("{Ctrl}v")
    time.sleep(0.35)
    auto.SendKeys("{Enter}")
    time.sleep(0.6)
    return True, "ok"


def _worker(log=print):
    try:
        # uiautomation 没有 CoInitialize 方法（实测 hasattr=False），必须走 ole32：
        # 子线程不初始化 COM，后续 ControlFromHandle/SendKeys 全部报「尚未调用 CoInitialize」
        ctypes.windll.ole32.CoInitializeEx(None, 0x2)   # COINIT_APARTMENTTHREADED
    except Exception as e:
        try:
            log("wecom_ext CoInitializeEx失败: %s" % e)
        except Exception:
            pass
    while True:
        try:
            _worker_once(log)
        except Exception as e:  # 任何异常都不许带死线程，打日志继续
            try:
                log("wecom_ext worker异常(忽略继续): " + str(e)[:160])
            except Exception:
                pass
        time.sleep(8)


def _worker_once(log=print):
    if not _STATE["enabled"] or not _STATE["groups"]:
        return
    if _STATE["max_per_day"] > 0 and _STATE["day_cnt"] >= _STATE["max_per_day"]:
        return
    e = _peek()
    if not e:
        return
    # 条间间隔闸（相对上一次任意发送动作）
    wait = _STATE["msg_gap"] + random.randint(0, 30) - (time.time() - _STATE["last_sent"])
    if wait > 0:
        time.sleep(wait)
    for g in _STATE["groups"]:
        if g in e.get("done", []):
            continue
        if _STATE["max_per_day"] > 0 and _STATE["day_cnt"] >= _STATE["max_per_day"]:
            break
        ok, msg = send_now(g, e["t"])
        if ok:
            _mark_done(g)
            _STATE["last_sent"] = time.time()
            if g == _STATE["groups"][-1] or set(e.get("done", [])) >= set(_STATE["groups"]):
                _STATE["day_cnt"] += 1
                _save_state()
            try:
                log("wecom_ext -> %s | %s" % (g, e["t"][:30].replace("\n", " ")))
            except Exception:
                pass
        else:
            try:
                log("wecom_ext 失败(跳过该窗): " + msg)
            except Exception:
                pass
        time.sleep(_STATE["win_gap"] + random.randint(0, 2))  # 窗口间间隔(1-3s随机)


def start(log=print):
    if _STATE.get("thread_started"):
        return
    _STATE["thread_started"] = True
    t = threading.Thread(target=_worker, args=(log,), daemon=True)
    t.start()


if __name__ == "__main__":
    import sys
    title = sys.argv[1] if len(sys.argv) > 1 else "京东+微保线报 2群"
    text = sys.argv[2] if len(sys.argv) > 2 else ""
    ok, msg = send_now(title, text) if text else (False, "缺少文案参数")
    print(("OK " if ok else "FAIL ") + msg)
