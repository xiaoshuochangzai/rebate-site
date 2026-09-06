# -*- coding: utf-8 -*-
"""探针 v4：检查按钮元素内部属性（Vue _vei / react fiber / 事件委托祖先）。"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jd_bot

DTK = "dataoke.com"

JS = r"""
(function(){
  const b = [...document.querySelectorAll('[class*="btn2"]')].find(x=>(x.innerText||'').includes('转链复制'));
  if(!b) return JSON.stringify({err:'NO_BTN'});
  const info = {ownKeys:Object.keys(b), chain:[]};
  // 向上找 8 层，看哪层有事件相关内部属性
  let el = b, depth = 0;
  while (el && depth < 10) {
    const keys = Object.keys(el).filter(k=>!k.startsWith('__BROWSERTOOLS'));
    const interesting = keys.filter(k=>k.startsWith('__react')||k.startsWith('_vei')||k.startsWith('__vue')||k.startsWith('on'));
    let vei = null;
    if (el._vei) vei = Object.keys(el._vei);
    info.chain.push({depth, tag:el.tagName, cls:String(el.className).slice(0,50), nKeys:keys.length, interesting, vei});
    el = el.parentElement; depth++;
  }
  // document/window 上的全局变量线索
  info.globals = ['__NUXT__','__NEXT_DATA__','__VUE__','__VUE_HMR_RUNTIME__'].filter(k=>k in window);
  return JSON.stringify(info);
})();
"""


def main():
    t = jd_bot.find_page(DTK)
    if not t:
        print("没找到大淘客标签页"); return
    cdp = jd_bot.CDP(t["webSocketDebuggerUrl"])
    val = cdp.evaluate(JS, timeout=20)
    print(val if val else "空")
    cdp.close()


if __name__ == "__main__":
    main()
