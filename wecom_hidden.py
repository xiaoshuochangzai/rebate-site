# -*- coding: utf-8 -*-
"""企微隐身桌面控制器（2026-10-15）
原理：Windows CreateDesktop 原生隐藏桌面 —— 企微主号 + wecom_ext 派发 worker
整体跑在 WecomPush 隐藏桌面里，Boss 主桌面零窗口/零焦点/零鼠标冲突。
热键 Ctrl+Alt+Z（wecom_peek.py）一键切换查看。

子命令：start / stop / status
"""
import ctypes, json, os, subprocess, sys, time
from ctypes import wintypes as wt

BASE = os.path.dirname(os.path.abspath(__file__))
DESKTOP_NAME = "WecomPush"
WXWORK_EXE = r"D:\Program Files (x86)\WXWork\WXWork.exe"
WXWORK_DIR = r"D:\Program Files (x86)\WXWork"
PYW = r"C:\Users\23058\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe"
STATE_FILE = os.path.join(BASE, "wecom_hidden.json")
FLAG_EXTERNAL = os.path.join(BASE, "wext_worker_external.flag")
LOG_FILE = os.path.join(BASE, "wecom_hidden.log")

GENERIC_ALL = 0x10000000
STILL_ACTIVE = 259

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


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


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)


def get_desktop(create=True):
    h = user32.OpenDesktopW(DESKTOP_NAME, 0, False, GENERIC_ALL)
    if h:
        return h
    if create:
        return user32.CreateDesktopW(DESKTOP_NAME, None, None, 0, GENERIC_ALL, None)
    return None


def spawn_on_desktop(exe, args=None, cwd=None):
    """在隐藏桌面上启动进程，返回 (ok, pi, pid)"""
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    si.lpDesktop = DESKTOP_NAME
    pi = PROCESS_INFORMATION()
    cmd = exe if not args else '%s %s' % (exe, args)
    ok = kernel32.CreateProcessW(exe, cmd, None, None, False, 0, None, cwd,
                                 ctypes.byref(si), ctypes.byref(pi))
    return bool(ok), pi, (pi.dwProcessId if ok else 0)


def alive(pid):
    if not pid:
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    code = wt.DWORD()
    kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    kernel32.CloseHandle(h)
    return code.value == STILL_ACTIVE


def kill(pid):
    if pid and alive(pid):
        PROCESS_TERMINATE = 0x0001
        h = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
        if h:
            kernel32.TerminateProcess(h, 0)
            kernel32.CloseHandle(h)
            time.sleep(0.3)


def hidden_wxwork_windows():
    h = get_desktop(create=False)
    if not h:
        return []
    out = []
    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(hwnd, lp):
        c = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, c, 256)
        if c.value in ("WeWorkWindow", "WwStandaloneConversationWnd", "PerryShadowWnd"):
            t = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, t, 256)
            out.append((c.value, t.value))
        return True
    user32.EnumDesktopWindows(h, CMPFUNC(cb), 0)
    return out


def main_wxwork_windows():
    """主桌面(Default)上有没有企微窗口 —— 有则说明主桌面还跑着一个企微"""
    out = []
    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(hwnd, lp):
        c = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, c, 256)
        if c.value in ("WeWorkWindow", "WwStandaloneConversationWnd"):
            out.append(c.value)
        return True
    hdef = user32.OpenDesktopW("Default", 0, False, GENERIC_ALL)
    if hdef:
        user32.EnumDesktopWindows(hdef, CMPFUNC(cb), 0)
    return out


def cmd_start():
    st = load_state()
    # 清理残留的旧 peek 进程（避免旧热键占位导致新热键注册失败）
    try:
        import psutil
        for pr in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                nm = (pr.info.get("name") or "").lower()
                cl = " ".join(pr.info.get("cmdline") or [])
                if nm == "pythonw.exe" and "wecom_peek" in cl:
                    pr.kill()
                    log("清理残留 peek PID=%d" % pr.info["pid"])
            except Exception:
                pass
    except ImportError:
        pass
    if alive(st.get("wxwork_pid")) or alive(st.get("worker_pid")):
        log("隐身桌面已在运行（wxwork=%s worker=%s），无需重复启动" %
            (st.get("wxwork_pid"), st.get("worker_pid")))
        return 0
    if main_wxwork_windows():
        log("主桌面企微还在运行，先关闭它（taskkill WXWork.exe）")
        subprocess.run(["taskkill", "/IM", "WXWork.exe", "/F"],
                       creationflags=0x08000000, capture_output=True)
        time.sleep(2)
    # 1. 桌面
    h = get_desktop(create=True)
    if not h:
        log("创建/打开隐藏桌面失败")
        return 1
    # 2. 企微主号生在隐藏桌面（已有登录态会自动登录）
    ok, pi, pid = spawn_on_desktop(WXWORK_EXE, None, WXWORK_DIR)
    if not ok:
        log("企微启动失败 err=%d" % kernel32.GetLastError())
        return 1
    log("企微已生在隐藏桌面 PID=%d" % pid)
    # 3. 等主窗口
    windows = []
    for i in range(12):
        time.sleep(2.5)
        windows = hidden_wxwork_windows()
        if any(c == "WeWorkWindow" for c, _ in windows):
            break
    if not any(c == "WeWorkWindow" for c, _ in windows):
        log("30 秒内未见企微主窗口，可能首次需要登录——用 Ctrl+Alt+Z 切过去扫码")
    else:
        log("企微窗口就绪：%d 个企微类窗口" % len(windows))
    # 4. 对外 worker 标记（监控进程内派发线程自动休眠）
    with open(FLAG_EXTERNAL, "w", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    # 5. 派发 worker 也生在隐藏桌面
    ok2, pi2, pid2 = spawn_on_desktop(PYW, '-u "%s" --as-worker' %
                                      os.path.join(BASE, "wext_worker.py"), BASE)
    if not ok2:
        log("wext_worker 启动失败 err=%d" % kernel32.GetLastError())
        return 1
    log("wext_worker 已生在隐藏桌面 PID=%d" % pid2)
    # 6a. 返回热键（Ctrl+Alt+Q）必须生在隐身桌面才响应（热键不跨桌面）
    ok3, pi3, pid3 = spawn_on_desktop(PYW, '-u "%s" --return' % os.path.join(BASE, "wecom_peek.py"))
    log("返回热键(Ctrl+Alt+Q)已生在隐身桌面 PID=%d" % pid3 if ok3 else "返回热键启动失败")
    # 6b. 主桌面侧：进隐身热键(Ctrl+Alt+Z) + 看门狗（普通方式，留在主桌面）
    p = subprocess.Popen([PYW, "-u", os.path.join(BASE, "wecom_peek.py")],
                         cwd=BASE, creationflags=0x08000000)
    pid4 = p.pid
    log("wecom_peek 主桌面侧(进隐身+看门狗)已启动 PID=%d" % pid4)
    save_state({"wxwork_pid": pid, "worker_pid": pid2, "peek_pid": pid3, "peek_main_pid": pid4})
    log("全部就绪。热键 Ctrl+Alt+Z 切换查看隐藏桌面里的企微。")
    return 0


def cmd_stop():
    st = load_state()
    kill(st.get("worker_pid"))
    kill(st.get("peek_pid"))
    kill(st.get("peek_main_pid"))
    kill(st.get("wxwork_pid"))
    # 兜底：按名清一次
    subprocess.run(["taskkill", "/IM", "WXWork.exe", "/F"],
                   creationflags=0x08000000, capture_output=True)
    if os.path.exists(FLAG_EXTERNAL):
        os.remove(FLAG_EXTERNAL)  # 撤掉标记后，监控进程内派发线程自动苏醒接管
    save_state({})
    log("隐身桌面已停止；监控自带派发线程将自动恢复接管（无需重启监控）")
    return 0


def cmd_status():
    st = load_state()
    wx = alive(st.get("wxwork_pid"))
    wk = alive(st.get("worker_pid"))
    pk = alive(st.get("peek_pid"))
    wins = hidden_wxwork_windows()
    print("wxwork=%s worker=%s peek=%s | 隐藏桌面企微窗口=%d 个" %
          ("运行中" if wx else "停止", "运行中" if wk else "停止",
           "运行中" if pk else "停止", len(wins)))
    for c, t in wins[:8]:
        print("  [%s] %s" % (c, t))
    return 0


def load_state():
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except Exception:
        return {}


def save_state(d):
    json.dump(d, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    sys.exit({"start": cmd_start, "stop": cmd_stop, "status": cmd_status}.get(
        cmd, cmd_status)())
