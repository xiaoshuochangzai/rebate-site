# -*- coding: utf-8 -*-
"""真实线报推送测试：连上长连接 → 向已捕获的群 chatid 推一条真实线报"""
import sys
import time

sys.path.insert(0, r"E:\Jingdong\rebate-site")
import wecom_push
import keyword_push

wecom_push.start()
for i in range(20):
    time.sleep(1)
    if wecom_push.status()["state"] == "online":
        break
print("连接状态:", wecom_push.status())

chatids = wecom_push.known_chatids()
print("已注册会话:", chatids)
if not chatids:
    sys.exit(1)

msg = keyword_push.build_sample_message()
print("样本文案:\n" + msg)
if not msg:
    sys.exit(2)

for cid in chatids:
    resp = wecom_push.send_markdown(cid, msg, chat_type=2)
    print("推送结果 chatid=%s -> %s" % (cid, resp))
    with open(r"E:\Jingdong\rebate-site\wecom_push_log.txt", "a", encoding="utf-8") as f:
        f.write("%s manual-push chatid=%s resp=%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), cid, resp))
print("DONE")
