# -*- coding: utf-8 -*-
"""wecom_peek v2 —— 桌面切换 + 看门狗（2026-10-15）
两个实例，各管一面（Windows 热键不跨桌面生效，必须两边各装一个）：
  默认模式（跑在主桌面）：
    - 热键 Ctrl+Alt+Z → 切到 WecomPush 隐身桌面
    - 看门狗：每 8s 检查隐身桌面里的 WXWork，死了自动复活
  返回模式 --return（生在隐身桌面）：
    - 热键 Ctrl+Alt+Q → 切回主桌面（必须装在隐身桌面里才响应）
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes as wt

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
GENERIC_ALL = 0x10000000
DESKTOP_NAME = "WecomPush"
BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "wecom_peek.log")
PYW = r"C:\Users\23058\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
WXWORK_EXE = r"D:\Program Files (x86)\WXWork\WXWork.exe"
WXWORK_DIR = r"D:\Program Files (x86)\WXWork"

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
WM_HOTKEY = 0x0312


def log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%m-%d %H:%M:%S"), m))
    except Exception:
        pass


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR),
                ("lpTitle", wt.LPWSTR), ("dwX", wt.DWORD), ("dwY", wt.DWORD),
                ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD), ("dwXCountChars", wt.DWORD),
                ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
                ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD), ("lpReserved2", ctypes.c_void_p),
                ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


def spawn_hidden(exe, args=None, cwd=None):
    """生到隐身桌面（供看门狗复活用）"""
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = DESKTOP_NAME
    pi = PROCESS_INFORMATION()
    cmd = exe if not args else '%s %s' % (exe, args)
    ok = kernel32.CreateProcessW(exe, cmd, None, None, False, 0, None, cwd,
                                 ctypes.byref(si), ctypes.byref(pi))
    return bool(ok), (pi.dwProcessId if ok else 0)


def find_pid(name):
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % name, "/FO", "CSV"],
                             capture_output=True, creationflags=0x08000000).stdout.decode("gbk", "ignore")
        for line in out.splitlines():
            if line.startswith('"%s"' % name):
                return int(line.split('","')[1])
    except Exception:
        pass
    return None


def hidden_wxwork_windows():
    h = user32.OpenDesktopW(DESKTOP_NAME, 0, False, GENERIC_ALL)
    if not h:
        return -1
    n = [0]
    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(hwnd, lp):
        c = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, c, 256)
        if c.value in ("WeWorkWindow", "WwStandaloneConversationWnd"):
            n[0] += 1
        return True
    user32.EnumDesktopWindows(h, CMPFUNC(cb), 0)
    return n[0]


def watchdog():
    """隐身桌面栈保活：企微死了自动复活（worker 死亡靠 flag+监控侧兜底，见下）"""
    while True:
        try:
            time.sleep(8)
            if user32.OpenDesktopW(DESKTOP_NAME, 0, False, GENERIC_ALL) == 0:
                continue
            wx_pid = find_pid("WXWork.exe")
            if wx_pid is None:
                ok, pid = spawn_hidden(WXWORK_EXE, None, WXWORK_DIR)
                log("看门狗: 复活企微 %s" % ("OK PID=%d" % pid if ok else "FAIL"))
            wk_alive = False
            try:
                import psutil
                for pr in psutil.process_iter(["name", "cmdline"]):
                    if (pr.info["name"] or "").lower() == "pythonw.exe" and "wext_worker" in " ".join(pr.info["cmdline"] or []):
                        wk_alive = True
                        break
            except Exception:
                wk_alive = True
            if not wk_alive:
                ok, pid = spawn_hidden(PYW, '-u "%s" --as-worker' % os.path.join(BASE, "wext_worker.py"), BASE)
                log("看门狗: 复活 wext_worker %s" % ("OK PID=%d" % pid if ok else "FAIL"))
        except Exception as e:
            log("看门狗异常: %s" % str(e)[:120])


def main_mode():
    """主桌面侧：进隐身热键 + 看门狗"""
    hpush = user32.OpenDesktopW(DESKTOP_NAME, 0, False, GENERIC_ALL)
    if not hpush:
        log("WecomPush 桌面不存在（先跑 wecom_hidden.py start），退出")
        return 1
    if not user32.RegisterHotKey(None, 1, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, 0x5A):
        log("主桌面热键 Ctrl+Alt+Z 注册失败（被占用）")
        return 1
    threading.Thread(target=watchdog, daemon=True).start()
    log("[主桌面] Ctrl+Alt+Z 就绪（进隐身）+ 看门狗已启动")
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY and msg.wParam == 1:
            if user32.SwitchDesktop(hpush):
                log("[主桌面] → 切到隐身桌面")
    return 0


def return_mode():
    """隐身桌面侧：返回热键 Ctrl+Alt+Q（必须生在隐身桌面才响应）"""
    hdefault = user32.OpenDesktopW("Default", 0, False, GENERIC_ALL)
    if not hdefault:
        log("打开 Default 桌面失败")
        return 1
    if not user32.RegisterHotKey(None, 2, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, 0x51):
        log("隐身桌面热键 Ctrl+Alt+Q 注册失败（被占用）")
        return 1
    log("[隐身桌面] Ctrl+Alt+Q 就绪（回主桌面）")
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY and msg.wParam == 2:
            if user32.SwitchDesktop(hdefault):
                log("[隐身桌面] → 切回主桌面")
    return 0


if __name__ == "__main__":
    if "--return" in sys.argv:
        sys.exit(return_mode())
    sys.exit(main_mode())
