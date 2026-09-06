# -*- coding: utf-8 -*-
"""探针 v9：下载页面全部 JS bundle，本地 grep pwd-analysis / 转链逻辑。"""
import sys, os, json, re, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

DTK = "dataoke.com"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_dtk_js")
os.makedirs(OUT, exist_ok=True)

OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
OP.addheaders = [("User-Agent", "Mozilla/5.0")]


def main():
    t = jd_bot.find_page(DTK)
    if not t:
        print("没找到大淘客标签页"); return
    cdp = jd_bot.CDP(t["webSocketDebuggerUrl"])
    val = cdp.evaluate(r"""
JSON.stringify([...document.scripts].map(s=>s.src).filter(Boolean));
""", timeout=20)
    srcs = json.loads(val)
    print(f"共 {len(srcs)} 个外链脚本")
    hits = []
    for u in srcs:
        try:
            with OP.open(u, timeout=20) as r:
                js = r.read().decode("utf-8", "ignore")
        except Exception as e:
            print("  下载失败", u[:100], e)
            continue
        name = u.split("/")[-1].split("?")[0][:60]
        path = os.path.join(OUT, name)
        with open(path, "w", encoding="utf-8", errors="ignore") as f:
            f.write(js)
        for kw in ["pwd-analysis", "pwdAnalysis", "转链复制", "radar-goods", "taobaoapi"]:
            if kw in js:
                hits.append((name, kw, len(js)))
                print(f"  ✅ {name} ({len(js)//1024}KB) 含 {kw}")
    if not hits:
        print("无命中，列出脚本:")
        for u in srcs:
            print("  ", u[:120])
    cdp.close()


if __name__ == "__main__":
    main()
