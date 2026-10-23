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
  - 后台线程逐条派发：对配置的每个窗口 send_now
  - Boss 2026-10-23 明令：窗口没开 = 放弃该窗对该条的发送权（标记 done），不补发；
    三个窗口都没开时消息当轮即全部标记 done 直接出队丢弃。窗口再次打开后，
    只派发窗口打开后新进队的线报，关闭期间积压的旧线报一律不再发送
  - enabled=false 时休眠

配置（keyword_config.json）：
  "wecom_ext": {
      "enabled": true,
      "groups": ["京东+微保线报 1群", "京东羊毛线报fat①群", "京东+微保线报 2群"],
      "win_gap": 0,        # 同条线报相邻窗口间隔（0=连发，3 群 2 秒内）
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
        _STATE["win_gap"] = max(0, int(c.get("win_gap") or 0))  # 0=窗口间零间隔（Boss 2026-10-13：3 群 2 秒内发完）
    except Exception:
        _STATE["win_gap"] = 0
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
    """小随机延迟（保一点非机械感，量级毫秒级不拖速度）"""
    return random.uniform(a, b)


def _human_move(tx, ty):
    """鼠标拟人化移动（v3.2 起默认不用：焦点常驻后无需每次点击；保留备用）"""
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
        e = t * t * (3 - 2 * t)
        nx = sx + dx * e - dy * bend * t * (1 - t)
        ny = sy + dy * e + dx * bend * t * (1 - t)
        user32.SetCursorPos(int(nx), int(ny))
        time.sleep(random.uniform(0.004, 0.012))


# 独立窗口的输入框焦点是常驻的：每个窗口本会话点过一次输入框后，后续发送
# 直接「激活→粘贴→回车」，不再点鼠标（更快，且注入事件少一半）
# （v3.2b 弃用该优化：1 群首击落点偏差导致静默失败，恢复每次点击）


def send_now(title, text):
    """极速发送（v3.2b，2026-10-13）。
    v3.2b 修复：恢复「每次发送都点输入框」——v3.2 的每窗只点一次在 1 群踩雷：
    首击落点偏了之后，后续全部粘贴进错误焦点，程序返回成功但群里永远收不到。
    点击只花 ~0.15s，三群仍能压在 2 秒出头。"""
    if auto is None:
        return False, "uiautomation 未安装"
    user32 = ctypes.windll.user32
    hwnd = _find_hwnd(title)
    if not hwnd:
        return False, "独立窗口未打开: " + title

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
        time.sleep(_j(0.25, 0.40))
    user32.SetForegroundWindow(hwnd)
    time.sleep(_j(0.05, 0.09))

    c = auto.ControlFromHandle(hwnd)
    r = c.BoundingRectangle
    L, T, W, H = r.left, r.top, r.width(), r.height()
    if W <= 0 or H <= 0:
        return False, "窗口尺寸异常: " + title
    user32.SetCursorPos(int(L + W * INPUT_RX), int(T + H * INPUT_RY))
    time.sleep(_j(0.02, 0.05))
    user32.mouse_event(2, 0, 0, 0, 0)
    time.sleep(0.02)
    user32.mouse_event(4, 0, 0, 0, 0)
    time.sleep(_j(0.04, 0.08))

    auto.SetClipboardText(text)
    # waitTime=0：uiautomation 默认每次 SendKeys 后强等 0.5s（3 次白耗 1.6s），压掉
    auto.SendKeys("{Ctrl}a{Del}", waitTime=0)
    time.sleep(_j(0.01, 0.03))
    auto.SendKeys("{Ctrl}v", waitTime=0)
    time.sleep(_j(0.08, 0.13))   # 等文本落进输入框，太快会发空消息
    auto.SendKeys("{Enter}", waitTime=0)
    time.sleep(_j(0.06, 0.12))
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
        time.sleep(2)  # worker 唤醒间隔（8→2s，2026-10-13 提速：群转发时效）


def _worker_once(log=print):
    if not _STATE["enabled"] or not _STATE["groups"]:
        return
    if _STATE["max_per_day"] > 0 and _STATE["day_cnt"] >= _STATE["max_per_day"]:
        return
    # 红包文案静默窗（Boss 2026-10-17 明令）：keyword_push 发完红包场次后 2 分钟内不发线报
    try:
        import json as _json
        _rs = _json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           "redpack_state.json"), encoding="utf-8"))
        if time.time() < float(_rs.get("mute_until", 0) or 0):
            return
    except Exception:
        pass
    e = _peek()
    if not e:
        return
    # 23:27 夜闸（Boss 2026-10-16 明令）：此后线报不再派发，只放行收播公告（@所有人 那条）
    if time.strftime("%H:%M") >= "23:27" and not e.get("t", "").startswith("@所有人"):
        return
    # 条间间隔闸（相对上一次任意发送动作）：msg_gap 5s 基础 + 0~2s 微随机
    # （2026-10-13 提速：原 0~30s 随机平均白等 20s，是群转发落后的大头，已砍）
    wait = _STATE["msg_gap"] + random.randint(0, 2) - (time.time() - _STATE["last_sent"])
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
                log("wecom_ext 失败: " + msg)
            except Exception:
                pass
            # Boss 2026-10-23 明令：窗口没开即放弃——该窗错过本条，不再补发。
            # 三窗都没开时本条在当轮全部标记 done，直接出队丢弃；窗口再次打开后
            # 只派发新进队的线报，关闭期间积压的旧线报一律不再发送。
            # 其他失败（uiautomation 缺失、窗口尺寸异常）仍保留等重试。
            if msg.startswith("独立窗口未打开"):
                _mark_done(g)
                try:
                    log("wecom_ext 积压丢弃(窗口未开): %s | %s" % (g, e["t"][:30].replace("\n", " ")))
                except Exception:
                    pass
        gap = _STATE["win_gap"]
        time.sleep(gap + random.uniform(0, gap * 0.3) if gap > 0 else _j(0.02, 0.06))


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
