# -*- coding: utf-8 -*-
"""专用「转链机器人」浏览器：独立 Chrome 实例 + CDP 直连。

设计目的：转链自动化完全跑在一台**独立**的 Chrome 里（独立 profile、独立
调试端口 9222、窗口最小化），不碰用户正在用的主浏览器，不抢焦点、不切标签。

一次登录后 cookie 存在 E:\\Jingdong\\.jd-bot-profile 里，之后每次调用直接复用，
无需再登录，甚至可以无窗口运行。
"""
import json
import os
import subprocess
import time
import urllib.request

import websocket  # websocket-client

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(BASE_DIR, ".jd-bot-profile")
PORT = 9222
URL = "https://union.jd.com/proManager/custompromotion"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Users\23058\AppData\Local\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome():
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def is_running(port=PORT, timeout=2):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def launch(headless=False):
    """启动专用浏览器实例（独立 profile，不影响用户主浏览器）。"""
    exe = find_chrome()
    if not exe:
        raise RuntimeError("没找到 Chrome/Edge，请手动安装或改 CHROME_CANDIDATES")
    os.makedirs(PROFILE_DIR, exist_ok=True)
    args = [
        exe,
        f"--remote-debugging-port={PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate",
        "--window-size=1400,900",
        "--window-position=60,60",
        "--remote-allow-origins=*",  # Chrome 111+ 必须，否则 CDP 握手 403
    ]
    if headless:
        args.append("--headless=new")
    args.append(URL)
    # DETACHED_PROCESS + 新进程组：让浏览器独立于调用方存活
    subprocess.Popen(args, close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    for _ in range(40):
        time.sleep(1)
        if is_running():
            return True
    return False


def ensure_browser(headless=False):
    if is_running():
        return True
    return launch(headless=headless)


def targets(port=PORT):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
        return json.loads(r.read().decode())


def find_page(keyword="union.jd.com"):
    for t in targets():
        if t.get("type") == "page" and keyword in (t.get("url") or ""):
            return t
    return None


class CDP:
    """最小 CDP 客户端：只做 evaluate / navigate。"""

    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=120, suppress_origin=True)
        self._id = 0

    def send(self, method, params=None, timeout=120):
        self._id += 1
        self.ws.settimeout(timeout)
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"CDP error: {msg['error']}")
                return msg.get("result", {})
            # 非本请求的事件消息直接丢弃

    def evaluate(self, expression, timeout=120):
        r = self.send("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        }, timeout=timeout)
        res = r.get("result", {})
        if res.get("type") == "string":
            return res.get("value")
        return res.get("value", res)

    def navigate(self, url):
        self.send("Page.navigate", {"url": url})
        time.sleep(3)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def connect_browser(keyword="union.jd.com", headless=False):
    """连上专用浏览器并定位万能转链页面。"""
    if not ensure_browser(headless=headless):
        raise RuntimeError("专用浏览器启动失败（端口 9222 未响应）")
    t = find_page(keyword)
    if not t:
        c = CDP(targets()[0]["webSocketDebuggerUrl"])
        c.navigate(URL)
        c.close()
        time.sleep(4)
        t = find_page(keyword)
    if not t:
        raise RuntimeError("没找到万能转链页面")
    return CDP(t["webSocketDebuggerUrl"]), t


def check_login(cdp):
    txt = cdp.evaluate("document.body ? document.body.innerText.slice(0,300) : ''", timeout=20) or ""
    if "登录" in txt and "万能转链" not in txt:
        return False
    return True


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        v = is_running()
        print("运行中:", bool(v), (v or {}).get("Browser", ""))
        t = find_page() if v else None
        print("万能转链页:", (t or {}).get("url", "无"))
    elif cmd == "start":
        print("启动:", "OK" if launch() else "FAIL")
    elif cmd == "login":
        cdp, t = connect_browser()
        print("页面:", t.get("url"))
        print("已登录:", check_login(cdp))
        cdp.close()
