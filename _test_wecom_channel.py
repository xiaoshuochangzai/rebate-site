# -*- coding: utf-8 -*-
"""企微长连接通道验证：认证 → 假chatid探测（验证帧格式被接受）"""
import sys
import time

sys.path.insert(0, r"E:\Jingdong\rebate-site")
import wecom_push

wecom_push.start()
print("等待认证...")
ok = False
for i in range(20):
    time.sleep(1)
    st = wecom_push.status()
    if st["state"] == "online":
        ok = True
        break
    if st["state"] == "no-config":
        print("配置缺失"); break
print("状态:", st, "耗时%s秒" % (i + 1))
if not ok:
    sys.exit(1)

# 探测：假 chatid，验证 aibot_send_msg 帧格式被服务端接受（预期 errcode!=0，但不是格式错误）
resp = wecom_push.send_markdown("probe_invalid_chatid_test", "**探测** 通道格式验证", chat_type=1)
print("探测响应:", resp)
resp2 = wecom_push.send_markdown("probe_invalid_chatid_test", "**探测** 通道格式验证", chat_type=2)
print("探测响应(群):", resp2)
print("chatids:", wecom_push.known_chatids())
print("DONE")
