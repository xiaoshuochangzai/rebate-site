# -*- coding: utf-8 -*-
"""分步探针：定位转链链路卡在哪一环。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["JD_CONV_DELAY"] = "8"
print("A: 开始导入模块", flush=True)
import jd_bot
import jd_convert_browser as jc
print("B: 模块导入完成", flush=True)

print("C: 连接浏览器...", flush=True)
cdp, t = jd_bot.connect_browser()
print("D: 已连上:", t.get("url", "")[:80], flush=True)

print("E: 小测试 evaluate 1+1 ...", flush=True)
print("   结果:", cdp.evaluate("1+1", timeout=15), flush=True)

print("F: 发起一次真实转链（简单商品文案）...", flush=True)
r = jc.convert_text("测试商品 京东自营\nhttps://item.jd.com/100012043978.html")
print("G: 转链返回 ok=", r.get("ok"), " msg=", str(r.get("msg", ""))[:80], flush=True)
if r.get("ok"):
    d = r["data"]
    print("   promotionUrl:", d.get("promotionUrl"), flush=True)
cdp.close()
print("H: 完成", flush=True)
