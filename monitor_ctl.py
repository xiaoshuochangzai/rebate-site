#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor_ctl.py — 线报监控统一控制（stop/start 预检/启动验证）

背景：stop/start 原 bat 用 PowerShell Get-CimInstance 按 CommandLine 匹配，
该属性偶发返回空 → 漏杀/漏检 → 双开（2026-10-12 实测两次）。
改用 psutil：cmdline 拼接判断更稳，且杀完循环验证确认死透。

用法：
  python monitor_ctl.py stop     # 杀全部监控进程（含锁PID兜底），验证死透，删锁
  python monitor_ctl.py check    # 输出 RUNNING / NOT_RUNNING（供 start 预检）
  python monitor_ctl.py verify   # 启动后轮询验证存活（30s 内出现即 OK）
"""
import sys
import time
import os

BASE = os.path.dirname(os.path.abspath(__file__))
LOCK_FILE = os.path.join(BASE, "monitor.lock")
MARK = "incremental.py"


def find_monitors():
    """返回 [(pid, name, mem_mb)]——cmdline 含 incremental.py 的 python 进程"""
    import psutil
    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
        try:
            name = (p.info["name"] or "").lower()
            if not name.startswith("python"):
                continue
            cl = " ".join(p.info["cmdline"] or [])
            if MARK in cl:
                mem = p.info["memory_info"].rss / 1048576 if p.info["memory_info"] else 0
                out.append((p.info["pid"], name, mem))
        except Exception:
            continue
    return out


def cmd_stop():
    import psutil
    killed = []
    # 第一遍：按 cmdline
    for pid, name, mem in find_monitors():
        try:
            psutil.Process(pid).kill()
            killed.append((pid, mem))
            print("  killed PID %d (%.0fMB %s)" % (pid, mem, name))
        except psutil.NoSuchProcess:
            print("  PID %d already gone" % pid)
        except Exception as e:
            print("  kill PID %d failed: %s" % (pid, str(e)[:60]))
    # 第二遍：锁文件 PID 兜底（防 cmdline 匹配漏网）
    try:
        lock_pid = int(open(LOCK_FILE, encoding="utf-8").read().strip())
        if lock_pid not in [k[0] for k in killed]:
            try:
                psutil.Process(lock_pid).kill()
                killed.append((lock_pid, 0))
                print("  killed lock PID %d (from monitor.lock)" % lock_pid)
            except psutil.NoSuchProcess:
                pass
    except Exception:
        pass
    # 验证循环：最多 6 秒，确认全部死透
    for i in range(6):
        time.sleep(1)
        left = find_monitors()
        if not left:
            break
    left = find_monitors()
    if left:
        print("WARNING: still alive after kill:")
        for pid, name, mem in left:
            print("  PID %d %.0fMB %s" % (pid, mem, name))
        print("STOP INCOMPLETE!")
        return 1
    # 删锁
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            print("  monitor.lock removed.")
    except Exception:
        pass
    print("STOP OK - all monitor processes confirmed dead.")
    return 0


def cmd_check():
    ms = find_monitors()
    if ms:
        for pid, name, mem in ms:
            print("  monitor PID %d %.0fMB %s" % (pid, mem, name))
        print("STATE=RUNNING")
        return 2
    # 锁残留（进程没了但锁在）→ 清掉
    try:
        lock_pid = int(open(LOCK_FILE, encoding="utf-8").read().strip())
        import psutil
        try:
            psutil.Process(lock_pid)
            print("  monitor alive by lock pid %d" % lock_pid)
            print("STATE=RUNNING")
            return 2
        except psutil.NoSuchProcess:
            os.remove(LOCK_FILE)
            print("  stale lock removed (pid %d dead)" % lock_pid)
    except Exception:
        pass
    print("STATE=IDLE")
    return 0


def cmd_verify():
    """启动后调用：30 秒内监控进程出现即 OK"""
    for i in range(10):
        time.sleep(3)
        ms = find_monitors()
        if ms:
            for pid, name, mem in ms:
                print("  monitor PID %d %.0fMB %s" % (pid, mem, name))
            print("START OK")
            return 0
    print("START FAILED after 30s. Check monitor_err.txt")
    return 1


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "stop":
        sys.exit(cmd_stop())
    elif cmd == "check":
        sys.exit(cmd_check())
    elif cmd == "verify":
        sys.exit(cmd_verify())
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
