# -*- coding: utf-8 -*-
"""长连接订阅测试：验证 Bot ID / Secret 有效性。跑 15 秒打印结果后退出。"""
import asyncio
import json
import uuid

import websockets

WSS = "wss://openws.work.weixin.qq.com"
BOT_ID = "aib0KciTbWqJpoFkKpr07lcy5ohqrVQ2S2a"
SECRET = "Gu4wlikGg13T1eSzAMsOv1ycCloGRZYQtXVJASVP8yc"


async def main():
    result = {"connected": False, "subscribed": False, "errcode": None, "errmsg": "", "events": []}
    try:
        async with websockets.connect(WSS, open_timeout=15) as ws:
            result["connected"] = True
            sub = {
                "cmd": "aibot_subscribe",
                "headers": {"req_id": uuid.uuid4().hex},
                "body": {"bot_id": BOT_ID, "secret": SECRET},
            }
            await ws.send(json.dumps(sub))
            print(">> subscribe sent")
            try:
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15)
                    data = json.loads(raw)
                    print("<<", json.dumps(data, ensure_ascii=False)[:300])
                    if data.get("headers", {}).get("req_id") == sub["headers"]["req_id"] or data.get("cmd") in (
                            "aibot_subscribe",):
                        result["errcode"] = data.get("errcode")
                        result["errmsg"] = data.get("errmsg", "")
                        if data.get("errcode") == 0:
                            result["subscribed"] = True
                            print("== SUBSCRIBE OK ==")
                    else:
                        result["events"].append(data.get("cmd"))
            except asyncio.TimeoutError:
                print("== 15s no more messages, done ==")
    except Exception as e:
        result["errmsg"] = f"{type(e).__name__}: {str(e)[:150]}"
    print(json.dumps(result, ensure_ascii=False))


asyncio.run(main())
