# -*- coding: utf-8 -*-
"""企业微信智能机器人 长连接(WebSocket)主动推送模块
- aibot_subscribe 认证 + ping 心跳(30s) + 断线指数退避重连
- 捕获回调(aibot_msg_callback / 事件)中的 chatid 存 wecom_chatids.json
- 首次捕获到新会话时自动推送一条真实线报作为测试(auto_push_on_capture)
- 对外提供: start() / send_markdown(chatid, content, chat_type) / status() / known_chatids()
注意: 企微规则——用户必须先给机器人发过一条消息，机器人才能向该会话主动推送。
"""
import asyncio
import json
import os
import threading
import time
import uuid

import websockets

BASE = os.path.dirname(os.path.abspath(__file__))
WS_URL = "wss://openws.work.weixin.qq.com"
CONFIG_PATH = os.path.join(BASE, "keyword_config.json")
CHATIDS_PATH = os.path.join(BASE, "wecom_chatids.json")

_loop = None
_ws = None
_pending = {}          # req_id -> asyncio.Future
_chatids = {}          # chatid -> {"chattype":..., "time":...}
_started = False
_status = {"state": "init", "last_err": "", "since": ""}


def _load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_chatids():
    global _chatids
    try:
        with open(CHATIDS_PATH, "r", encoding="utf-8") as f:
            _chatids = json.load(f)
    except Exception:
        _chatids = {}


def _save_chatids():
    try:
        with open(CHATIDS_PATH, "w", encoding="utf-8") as f:
            json.dump(_chatids, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def status():
    return dict(_status)


def known_chatids():
    return dict(_chatids)


# ---------------- 帧处理 ----------------

def _resolve_pending(frame):
    headers = frame.get("headers") or {}
    req_id = headers.get("req_id", "")
    if req_id and req_id in _pending:
        fut = _pending.pop(req_id)
        if not fut.done():
            fut.set_result(frame)
        return True
    return False


def _on_frame(frame):
    if not isinstance(frame, dict):
        return
    if _resolve_pending(frame):
        return
    cmd = frame.get("cmd", "")
    body = frame.get("body") or {}
    if cmd in ("aibot_msg_callback", "aibot_event_callback"):
        chatid = body.get("chatid") or (body.get("chat") or {}).get("chatid")
        if chatid:
            _capture_chatid(chatid, body.get("chattype", "group"))
    elif cmd == "ping":
        # 心跳响应（errcode==0）
        pass


def _capture_chatid(chatid, chattype):
    is_new = chatid not in _chatids
    _chatids[chatid] = {"chattype": str(chattype or "group"), "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    _save_chatids()
    if is_new:
        cfg = _load_config()
        if cfg.get("auto_push_on_capture", True):
            asyncio.ensure_future(_push_sample(chatid, str(chattype or "group")))


async def _push_sample(chatid, chattype):
    """首次捕获到新会话 → 自动推一条真实线报作为端到端测试"""
    try:
        import keyword_push
        msg = keyword_push.build_sample_message()
        if not msg:
            return
        ct = 1 if chattype == "single" else 2
        resp = await _send(chatid, ct, msg)
        err = resp.get("errcode") if isinstance(resp, dict) else None
        with open(os.path.join(BASE, "wecom_push_log.txt"), "a", encoding="utf-8") as f:
            f.write("%s sample-push chatid=%s errcode=%s resp=%s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), chatid, err, json.dumps(resp, ensure_ascii=False)[:200]))
    except Exception as e:
        try:
            with open(os.path.join(BASE, "wecom_push_log.txt"), "a", encoding="utf-8") as f:
                f.write("%s sample-push ERROR chatid=%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), chatid, str(e)[:200]))
        except Exception:
            pass


# ---------------- 发送 ----------------

async def _send(chatid, chat_type, content, timeout=15):
    """发送 markdown 消息并等待响应帧"""
    ws = _ws
    if ws is None:
        return {"errcode": -1, "errmsg": "websocket not connected"}
    req_id = "msg-" + uuid.uuid4().hex
    fut = asyncio.get_event_loop().create_future()
    _pending[req_id] = fut
    frame = {
        "cmd": "aibot_send_msg",
        "headers": {"req_id": req_id},
        "body": {
            "chatid": chatid,
            "chat_type": chat_type,
            "msgtype": "markdown",
            "markdown": {"content": content},
        },
    }
    try:
        await ws.send(json.dumps(frame, ensure_ascii=False))
        resp = await asyncio.wait_for(fut, timeout=timeout)
        body = resp.get("body") if isinstance(resp.get("body"), dict) else {}
        return {
            "errcode": resp.get("errcode", body.get("errcode", -2)),
            "errmsg": resp.get("errmsg", body.get("errmsg", "")),
        }
    except asyncio.TimeoutError:
        return {"errcode": -3, "errmsg": "response timeout"}
    except Exception as e:
        return {"errcode": -4, "errmsg": str(e)[:120]}
    finally:
        _pending.pop(req_id, None)


def send_markdown(chatid, content, chat_type=2, timeout=15):
    """同步接口：向指定会话推送 markdown。chat_type: 1单聊 2群聊"""
    if _loop is None:
        return {"errcode": -5, "errmsg": "client not started"}
    fut = asyncio.run_coroutine_threadsafe(_send(chatid, chat_type, content, timeout), _loop)
    try:
        return fut.result(timeout + 5)
    except Exception as e:
        return {"errcode": -6, "errmsg": str(e)[:120]}


# ---------------- 连接主循环 ----------------

async def _heartbeat(ws):
    try:
        while True:
            await asyncio.sleep(30)
            req_id = "ping-" + uuid.uuid4().hex
            await ws.send(json.dumps({"cmd": "ping", "headers": {"req_id": req_id}}))
    except asyncio.CancelledError:
        pass
    except Exception as e:
        _status["last_err"] = "heartbeat: " + str(e)[:100]


async def _receive(ws):
    try:
        async for raw in ws:
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                _on_frame(json.loads(raw))
            except Exception:
                pass
    except asyncio.CancelledError:
        pass


async def _client():
    global _ws
    backoff = 2
    while True:
        cfg = _load_config()
        bot_id = cfg.get("bot_id", "")
        secret = cfg.get("secret", "")
        if not bot_id or not secret:
            _status["state"] = "no-config"
            await asyncio.sleep(30)
            continue
        try:
            # proxy=None 强制直连，绕开本机 HTTP_PROXY 环境变量劫持
            async with websockets.connect(WS_URL, ping_interval=None, proxy=None) as ws:
                _ws = ws
                hb = asyncio.ensure_future(_heartbeat(ws))
                recv = asyncio.ensure_future(_receive(ws))
                # 认证（接收循环已启动，能读到响应）
                req_id = "sub-" + uuid.uuid4().hex
                fut = asyncio.get_event_loop().create_future()
                _pending[req_id] = fut
                await ws.send(json.dumps({
                    "cmd": "aibot_subscribe",
                    "headers": {"req_id": req_id},
                    "body": {"bot_id": bot_id, "secret": secret},
                }))
                resp = await asyncio.wait_for(fut, timeout=10)
                _pending.pop(req_id, None)
                if resp.get("errcode") != 0:
                    raise RuntimeError("subscribe failed: %s" % resp.get("errmsg", ""))
                _status["state"] = "online"
                _status["since"] = time.strftime("%Y-%m-%d %H:%M:%S")
                _status["last_err"] = ""
                backoff = 2
                try:
                    await recv  # 连接存续期间一直收
                finally:
                    hb.cancel()
                    recv.cancel()
        except Exception as e:
            _ws = None
            _status["state"] = "reconnect"
            _status["last_err"] = str(e)[:150]
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


def _run():
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _load_chatids()
    _loop.run_until_complete(_client())


def start():
    """启动后台长连接线程（幂等）"""
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_run, daemon=True, name="wecom-push")
    t.start()
