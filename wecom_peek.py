# -*- coding: utf-8 -*-
"""wecom_peek.py —— 隐身桌面查看热键（跑在主桌面）。
热键 Ctrl+Alt+Z：主桌面 <-> WecomPush 隐藏桌面 一键切换。
想看隐身企微时切过去，看完再按一次切回。日志: wecom_peek.log
"""
import ctypes
import os
import time
from ctypes import wintypes as wt

user32 = ctypes.windll.user32
GENERIC_ALL = 0x10000000
BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "wecom_peek.log")

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
VK_Z = 0x5A
WM_HOTKEY = 0x0312


def log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
    except Exception:
        pass


def main():
    hpush = user32.OpenDesktopW("WecomPush", 0, False, GENERIC_ALL)
    if not hpush:
        log("WecomPush 桌面不存在（wecom_hidden.py start 还没跑过），退出")
        return 1
    hdefault = user32.OpenDesktopW("Default", 0, False, GENERIC_ALL)
    if not user32.RegisterHotKey(None, 1, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, VK_Z):
        log("注册热键失败（可能被别的程序占用），退出")
        return 1
    log("热键 Ctrl+Alt+Z 就绪，当前=主桌面")
    on_push = False
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY and msg.wParam == 1:
            target = hpush if not on_push else hdefault
            if user32.SwitchDesktop(target):
                on_push = not on_push
                log("切换到 %s" % ("WecomPush(隐身企微)" if on_push else "主桌面"))
            else:
                log("SwitchDesktop 失败")


if __name__ == "__main__":
    sys_exit = main()
    import sys as _s
    _s.exit(sys_exit)
