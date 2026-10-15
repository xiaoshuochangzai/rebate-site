# -*- coding: utf-8 -*-
"""wext_worker.py —— wecom_ext 派发 worker（生在 WecomPush 隐藏桌面里运行）。
与监控进程解耦：监控只往 wext_queue.json 入队（webhook 成功后），
本进程在隐藏桌面里出队并发送到企微独立会话窗口。
启动参数 --as-worker：自设 WEXT_WORKER=1，绕过外部接管休眠检查。
"""
import os
import sys
import time
import json

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
os.environ["WEXT_WORKER"] = "1"          # 必须在 import wecom_ext 之前
sys.path.insert(0, BASE)

import wecom_ext  # noqa: E402


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    try:
        with open(os.path.join(BASE, "wext_worker.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main():
    # 读 keyword_config.json 的 wecom_ext 段（与监控同源，改配置两边热生效）
    cfg = {}
    try:
        with open(os.path.join(BASE, "keyword_config.json"), encoding="utf-8") as f:
            cfg = (json.load(f) or {}).get("wecom_ext") or {}
    except Exception:
        pass
    wecom_ext.configure(cfg)
    log("worker 启动 enabled=%s groups=%s" % (wecom_ext._STATE["enabled"],
                                              wecom_ext._STATE["groups"]))
    wecom_ext.start(log=log)
    # CoInitialize 后 start() 已起线程；本进程常驻保活
    while True:
        time.sleep(30)
        log("heartbeat enabled=%s" % wecom_ext._STATE["enabled"])


if __name__ == "__main__":
    main()
