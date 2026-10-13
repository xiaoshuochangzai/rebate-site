"""精品库账密自动登录（Boss 2026-10-13 明令：掉登录自动重登，不再依赖浏览器/人工）。

POST https://www.jingpinku.com/auth/login.do  form: {phone, password, isChild=0}
响应 JSON {code:"0"=成功, msg, data:"member"|"attract"...}，会话 cookie 走 Set-Cookie。
登录页无验证码/短信/滑块（2026-10-13 实测），纯账密直登。

- 凭证存 jp_login.json（已 gitignore，永不入库、日志里只打字段数不打内容）
- 会话 cookie 写 jp_cookie.json（与 jp_api 共用同一份缓存，格式一致）
- isChild 固定 0：Boss 明令「不要勾选子账号登录」
"""
import json
import os
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRED_FILE = os.path.join(BASE_DIR, "jp_login.json")
SESSION_FILE = os.path.join(BASE_DIR, "jp_cookie.json")  # 与 jp_api 共用缓存

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_LOGIN_URL = "https://www.jingpinku.com/auth/login.do"
# 复用未过期缓存的窗口：10 分钟内不重复登录（正常 cookie TTL 1h，由 jp_api 管理）
_REUSE_WINDOW = 600
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 直连，绕本机代理


def _creds():
    with open(CRED_FILE, encoding="utf-8") as f:
        d = json.load(f)
    return str(d.get("phone") or ""), str(d.get("password") or "")


def login(force=False):
    """账密登录。成功返回 cookie header 字符串并写 jp_cookie.json 缓存；失败抛 RuntimeError。
    缓存新鲜且不 force 时直接复用（避免每次转链失败都打一次登录接口）。"""
    if not force:
        try:
            with open(SESSION_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("cookie") and time.time() - float(d.get("ts") or 0) < _REUSE_WINDOW:
                return str(d["cookie"])
        except Exception:
            pass
    phone, pwd = _creds()
    if not phone or not pwd:
        raise RuntimeError("jp_login.json 缺账号或密码")
    body = urllib.parse.urlencode(
        {"phone": phone, "password": pwd, "isChild": 0}).encode("utf-8")
    req = urllib.request.Request(
        _LOGIN_URL, data=body, method="POST",
        headers={"User-Agent": _UA,
                 "Content-Type": "application/x-www-form-urlencoded",
                 "Referer": "https://www.jingpinku.com/auth/login.do",
                 "Origin": "https://www.jingpinku.com",
                 "X-Requested-With": "XMLHttpRequest",
                 "Accept": "application/json, text/javascript, */*; q=0.01"})
    resp = _OPENER.open(req, timeout=15)
    j = json.loads(resp.read().decode("utf-8", "ignore"))
    if str(j.get("code")) != "0":
        raise RuntimeError(f"登录失败 code={j.get('code')} msg={str(j.get('msg'))[:60]}")
    # 收 Set-Cookie（同名去重，拼成请求头形态）
    seen, parts = set(), []
    for hv in resp.headers.get_all("Set-Cookie") or []:
        kv = hv.split(";", 1)[0].strip()
        name = kv.split("=", 1)[0].strip()
        if kv and name and name not in seen:
            seen.add(name)
            parts.append(kv)
    hdr = "; ".join(parts)
    if not hdr:
        raise RuntimeError("登录成功但响应未带会话 cookie")
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump({"cookie": hdr, "ts": time.time(), "src": "autologin"}, f)
    return hdr


if __name__ == "__main__":
    c = login(force=True)
    print(f"自动登录成功，cookie {len(c.split('; '))} 个字段（内容不打印）")
