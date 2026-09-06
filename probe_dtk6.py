# -*- coding: utf-8 -*-
"""探针 v6：沿 fiber 向上找 onClick。"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

DTK = "dataoke.com"

JS = r"""
(function(){
  const b = [...document.querySelectorAll('[class*="btn2"]')].find(x=>(x.innerText||'').includes('转链复制'));
  if(!b) return JSON.stringify({err:'NO_BTN'});
  let fiber = null;
  for (const k of Object.keys(b)) {
    if (k.startsWith('__reactInternalInstance$')) fiber = b[k];
  }
  if(!fiber) return JSON.stringify({err:'NO_FIBER'});
  const found = [];
  let f = fiber, depth = 0;
  while (f && depth < 40) {
    const p = f.memoizedProps;
    if (p && p.onClick) {
      found.push({
        depth,
        comp: (f.elementType && String(f.elementType).slice(0,80)) || (f.type && (f.type.displayName||f.type.name||'anon')) || '?',
        src: p.onClick.toString().slice(0,1500)
      });
    }
    f = f.return; depth++;
  }
  return JSON.stringify(found);
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
        for f in arr:
            print(f"\n=== depth {f['depth']} comp={f['comp']} ===")
            print(f["src"][:1200])
    except Exception:
        print("原始:", str(val)[:1500])
    cdp.close()


if __name__ == "__main__":
    main()
