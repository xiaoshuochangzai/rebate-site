# -*- coding: utf-8 -*-
"""Cloudflare KV 直写工具：把全量线报数据推到 KV，页面经 /api/deals 实时读取。

免 CF 构建。token 存在仓库外的 E:\\Jingdong\\Cloudflare key.txt（不会进 git）。
网络策略与 git_push 相同：直连 → 50111 → 7890 三路重试。
"""
import json
import os
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE_DIR, "cf_config.json"), encoding="utf-8"))

_OPENER_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_OPENER_PROXY = None  # 懒加载


def _token():
    with open(CFG["token_file"], encoding="utf-8") as f:
        return f.read().strip()


def _open_req(req, timeout=30):
    """直连优先，失败走 7890 代理。req 已带 method/headers。"""
    req.add_header("Authorization", f"Bearer {_token()}")
    req.add_header("Content-Type", "application/json")
    try:
        return _OPENER_DIRECT.open(req, timeout=timeout)
    except Exception:
        global _OPENER_PROXY
        if _OPENER_PROXY is None:
            _OPENER_PROXY = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": "http://127.0.0.1:7890",
                                             "https": "http://127.0.0.1:7890"}))
        return _OPENER_PROXY.open(req, timeout=timeout)


def put_deals(deals):
    """把 deals 全量写入 KV（单 key 覆盖写）。返回 (ok, msg)。"""
    url = (f"https://api.cloudflare.com/client/v4/accounts/{CFG['account_id']}"
           f"/storage/kv/namespaces/{CFG['namespace_id']}/values/{CFG['kv_key']}")
    payload = json.dumps(deals, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="PUT")  # KV 写入必须 PUT
    try:
        with _open_req(req) as r:
            d = json.loads(r.read().decode("utf-8"))
        return (bool(d.get("success")), str(d.get("errors", ""))[:150])
    except Exception as e:
        return False, str(e)[:150]


def seed_from_local():
    """用本地 site/deals.json 播种 KV（首次上线用）。"""
    deals = json.load(open(os.path.join(BASE_DIR, "site", "deals.json"), encoding="utf-8"))
    return put_deals(deals)


if __name__ == "__main__":
    ok, msg = seed_from_local()
    print("KV 播种:", "成功" if ok else f"失败 {msg}")
