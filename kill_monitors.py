# -*- coding: utf-8 -*-
"""清掉全部 incremental 监控实例。"""
import os
import subprocess
import time

import psutil

me = os.getpid()
pids = []
for p in psutil.process_iter(["pid", "name", "cmdline"]):
    try:
        if p.info["pid"] == me:
            continue
        if "python" in (p.info["name"] or "").lower() and "incremental" in " ".join(p.info["cmdline"] or []):
            pids.append(p.info["pid"])
    except Exception:
        pass
if pids:
    args = ["taskkill", "/F"]
    for x in pids:
        args += ["/PID", str(x)]
    r = subprocess.run(args, capture_output=True, text=True)
    print("taskkill:", (r.stdout or r.stderr).strip()[:200])
time.sleep(2)
left = []
for p in psutil.process_iter(["pid", "name", "cmdline"]):
    try:
        if "python" in (p.info["name"] or "").lower() and "incremental" in " ".join(p.info["cmdline"] or []):
            left.append(p.info["pid"])
    except Exception:
        pass
print("剩余监控实例:", left if left else 0)
lock = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.lock")
if os.path.exists(lock):
    os.remove(lock)
    print("monitor.lock 已清")
