# -*- coding: utf-8 -*-
"""大淘客探针 v3：读 React 内部 props，看「转链复制」按钮的 onClick 到底干什么。"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

DTK = "dataoke.com"

JS = r"""
(function(){
  function reactProps(el){
    for (const k of Object.keys(el)) {
      if (k.startsWith('__reactProps$')) return el[k];
      if (k === '__reactProps') return el[k];
    }
    return null;
  }
  const out = [];
  const btns = document.querySelectorAll('[class*="btn1"],[class*="btn2"]');
  btns.forEach((b,i)=>{
    const p = reactProps(b);
    out.push({
      i, txt:(b.innerText||'').trim(), cls:b.className.slice(0,60),
      props: p ? Object.keys(p) : null,
      onClick: p && p.onClick ? String(p.onClick).slice(0,500) : null
    });
  });
  return JSON.stringify(out);
})();
"""


def main():
    t = jd_bot.find_page(DTK)
    if not t:
        print("没找到大淘客标签页"); return
    cdp = jd_bot.CDP(t["webSocketDebuggerUrl"])
    val = cdp.evaluate(JS, timeout=20)
    try:
        arr = json.loads(val)
    except Exception:
        print("原始:", str(val)[:1000]); cdp.close(); return
    for b in arr:
        print(f"\n#{b['i']} [{b['txt']}] cls={b['cls']}")
        print("  props keys:", b["props"])
        if b["onClick"]:
            print("  onClick:", b["onClick"][:400])
    cdp.close()


if __name__ == "__main__":
    main()
