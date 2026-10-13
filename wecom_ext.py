#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wecom_ext.py — 企微外部群通道 v3.1：多独立窗口矩阵分发 + 拟人化发送

风控分析（2026-10-13，Boss 手动转发 100+ 条零触发的反例修正了频率理论）：
  「远程操控行为」的判据不是频率，是输入来源：
  - 手动操作 = 真 HID 设备事件，系统层面就是真人，怎么发都没事
  - 模拟输入 = 无设备注入（hDevice=NULL + LLKHF_INJECTED），打分特征
  → 拟人化只能修「时序/轨迹」层（机械节奏、鼠标瞬移、固定落点），
    注入标记与后台抢焦点是系统层烙印抹不掉；靠低频+拟人化把综合分压在阈值下。

实测结论（2026-10-12/13）：
  - 主窗口 2 分钟连发 2 次自动化输入 → 触发「远程操控行为」验证
  - 独立窗口低频发送跑一天多、上百条 → 零触发
  - 独立窗口全自绘（UIA 断在 PerryShadowWnd、零子 HWND）→ 无真后台通道

工作方式：
  - keyword_push webhook 成功后文案入队 wext_queue.json
  - 后台线程逐条派发：对配置的每个窗口 send_now；窗口没开 → 跳过该窗（条目标记 done，
    未发的窗下轮补发）；全部窗口发完才出队
  - enabled=false 时休眠

配置（keyword_config.json）：
  "wecom_ext": {
      "enabled": true,
      "groups": ["京东+微保线报 1群", "京东羊毛线报fat①群", "京东+微保线报 2群"],
      "win_gap": 1,        # 同条线报相邻窗口间隔（实际 +0~2s 随机）
      "msg_gap": 5,        # 两条线报之间最小间隔（实际 +0~30s 随机）
      "max_per_day": 0     # 每日线报条数上限（0=不限）
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


def _j(a, b):
    """随机延迟，替代固定 sleep（拟人化：机器节奏是打分特征之一）"""
    return random.uniform(a, b)


def _human_move(tx, ty):
    """鼠标拟人化移动：从当前位置沿带弧度的缓动路径多步滑到目标，不瞬移。
    （瞬移 = 打分特征之一；真人移动鼠标有轨迹有加减速）"""
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    sx, sy = float(pt.x), float(pt.y)
    dx, dy = tx - sx, ty - sy
    if abs(dx) < 3 and abs(dy) < 3:
        return
    steps = random.randint(18, 32)
    bend = random.uniform(0.10, 0.25) * (1 if random.random() < 0.5 else -1)
    for i in range(1, steps + 1):
        t = i / steps
        e = t * t * (3 - 2 * t)  # smoothstep 缓动（慢-快-慢）
        nx = sx + dx * e - dy * bend * t * (1 - t)
        ny = sy + dy * e + dx * bend * t * (1 - t)
        user32.SetCursorPos(int(nx), int(ny))
        time.sleep(random.uniform(0.004, 0.012))


def send_now(title, text):
    """拟人化发送（v3.1，2026-10-13）：
    ① 鼠标沿弧线滑入、落点在输入框区域随机（不瞬移、不固定坐标）
    ② 按下-抬起有真人间隔；每步随机延迟，无固定节奏
    ③ 粘贴后停顿「检查一眼」再回车
    无法消除项：SendInput 注入标记 + 后台进程抢焦点（系统层烙印）。"""
    if auto is None:
        return False, "uiautomation 未安装"
    user32 = ctypes.windll.user32
    hwnd = _find_hwnd(title)
    if not hwnd:
        return False, "独立窗口未打开: " + title

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
        time.sleep(_j(0.6, 1.2))
    user32.SetForegroundWindow(hwnd)
    time.sleep(_j(0.4, 0.9))  # 激活后像人一样先停一下再动手

    c = auto.ControlFromHandle(hwnd)
    r = c.BoundingRectangle
    L, T, W, H = r.left, r.top, r.width(), r.height()
    if W <= 0 or H <= 0:
        return False, "窗口尺寸异常: " + title

    # 落点在输入框区域随机化（±8%横向 / ±2%纵向），不再每次同一坐标
    x = int(L + W * (INPUT_RX + random.uniform(-0.08, 0.08)))
    y = int(T + H * (INPUT_RY + random.uniform(-0.02, 0.02)))
    _human_move(x, y)
    time.sleep(_j(0.10, 0.30))
    user32.mouse_event(2, 0, 0, 0, 0)   # 按下
    time.sleep(_j(0.03, 0.09))          # 真人按下到抬起有间隔
    user32.mouse_event(4, 0, 0, 0, 0)   # 抬起
    time.sleep(_j(0.30, 0.70))

    auto.SetClipboardText(text)
    auto.SendKeys("{Ctrl}a{Del}")
    time.sleep(_j(0.15, 0.45))
    auto.SendKeys("{Ctrl}v")
    time.sleep(_j(0.40, 0.90))          # 粘贴后像人一样检查一眼再发
    auto.SendKeys("{Enter}")
    time.sleep(_j(0.50, 1.00))
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
