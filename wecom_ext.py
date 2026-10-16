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
import ctypes.wintypes

try:
    import uiautomation as auto
except ImportError:
    auto = None

BASE = os.path.dirname(os.path.abspath(__file__))
QUEUE_FILE = os.path.join(BASE, "wext_queue.json")
STATE_FILE = os.path.join(BASE, "wext_state.json")
LOCK = threading.Lock()

# v4（2026-10-16，Boss 明令回归主窗口 RPA）：不再依赖独立聊天窗口，
# 直接在企微主窗口里「Ctrl+F 搜群 → 回车进群 → 点输入框 → 粘贴 → 回车」。
# 已知风险（Boss 知情）：主窗口连发曾触发「远程操控行为」验证（10-12，2 分钟 2 条），
# 靠 msg_gap 节流 + 独立窗口时代的低频纪律压制。
MAIN_CLASS = "WeWorkWindow"
INPUT_RX, INPUT_RY = 0.60, 0.89   # 输入框在主窗口内的相对位置（主窗口含左侧栏，偏右）
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


def _find_main():
    """找企微主窗口（WeWorkWindow）。
    实测（2026-10-16）：企微开 4 个同类窗口——3 个不可见辅助窗（0,0 同尺寸）+ 1 个真主窗；
    主窗最小化到托盘时 visible=1、iconic=1、被挪到屏幕外 (-25600)。所以筛选只认
    IsWindowVisible，iconic 交给 send_now 的 SW_RESTORE 恢复；可见窗里优先非最小化的。"""
    user32 = ctypes.windll.user32
    vis, vis_iconic = [], []

    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))

    def cb(h, _):
        buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(h, buf, 64)
        if buf.value == MAIN_CLASS and user32.IsWindowVisible(h):
            r = ctypes.wintypes.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            if (r.right - r.left) > 300:
                (vis if not user32.IsIconic(h) else vis_iconic).append(h)
        return True

    user32.EnumWindows(CMPFUNC(cb), None)
    if vis:
        return vis[0]
    if vis_iconic:
        return vis_iconic[0]
    return 0


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
    """主窗口 RPA 发送（v4，2026-10-16，Boss 明令恢复最初方案，直发真实线报不做测试）。
    流程：激活主窗口 → Ctrl+F 搜索 → 粘贴群名 → 回车进群 → 点输入框 → 粘贴文案 → 回车。
    防假成功：焦点切不上主窗口直接报失败（隐身桌面静默失败的教训）。"""
    if auto is None:
        return False, "uiautomation 未安装"
    user32 = ctypes.windll.user32
    hwnd = _find_main()
    if not hwnd:
        return False, "企微主窗口未打开"

    prev_fg = user32.GetForegroundWindow()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)   # SW_RESTORE：从托盘最小化恢复（窗口可能仍停在 -25600 屏幕外）
        time.sleep(_j(0.25, 0.40))
        rr = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rr))
        if rr.left < -20000 or rr.left >= user32.GetSystemMetrics(0):
            user32.MoveWindow(hwnd, 60, 60, 1000, 720, True)   # 强制挪回屏幕内
            time.sleep(_j(0.15, 0.25))
    user32.SetForegroundWindow(hwnd)
    time.sleep(_j(0.06, 0.10))
    if user32.GetForegroundWindow() != hwnd:
        return False, "焦点切换失败(主窗口未激活)"

    r = auto.ControlFromHandle(hwnd).BoundingRectangle
    L, T, W, H = r.left, r.top, r.width(), r.height()
    if W <= 0 or H <= 0:
        return False, "主窗口尺寸异常"

    prev_clip = _clip_get()
    try:
        # 1) Ctrl+F 呼出搜索，粘贴群名（打字注入逐字符标记多，粘贴只一次 Ctrl+V）
        auto.SendKeys("{Ctrl}f", waitTime=0)
        time.sleep(_j(0.25, 0.40))
        auto.SetClipboardText(title)
        auto.SendKeys("{Ctrl}a{Del}", waitTime=0)
        time.sleep(_j(0.02, 0.04))
        auto.SendKeys("{Ctrl}v", waitTime=0)
        time.sleep(_j(0.60, 0.90))   # 等搜索结果出来
        auto.SendKeys("{Enter}", waitTime=0)
        time.sleep(_j(0.50, 0.75))   # 等会话打开
        # 2) 点聊天输入框（主窗口含左侧栏，输入框偏右下）
        user32.SetCursorPos(int(L + W * INPUT_RX), int(T + H * INPUT_RY))
        time.sleep(_j(0.02, 0.05))
        user32.mouse_event(2, 0, 0, 0, 0)
        time.sleep(0.02)
        user32.mouse_event(4, 0, 0, 0, 0)
        time.sleep(_j(0.04, 0.08))
        # 3) 清空残留 → 粘贴文案 → 回车发送
        auto.SendKeys("{Ctrl}a{Del}", waitTime=0)
        time.sleep(_j(0.01, 0.03))
        auto.SetClipboardText(text)
        auto.SendKeys("{Ctrl}v", waitTime=0)
        time.sleep(_j(0.08, 0.13))   # 等文本落进输入框，太快会发空消息
        auto.SendKeys("{Enter}", waitTime=0)
        time.sleep(_j(0.06, 0.12))
    finally:
        _clip_put(prev_clip)   # 无论成败，把 Boss 的剪贴板还回去
    # 焦点归还（失败不影响发送结果）
    try:
        if prev_fg and user32.IsWindow(prev_fg):
            user32.SetForegroundWindow(prev_fg)
    except Exception:
        pass
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
    e = _peek()
    if not e:
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
                log("wecom_ext 失败(跳过该窗): " + msg)
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
