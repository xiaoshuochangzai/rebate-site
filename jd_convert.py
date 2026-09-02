# -*- coding: utf-8 -*-
"""京东联盟转链模块。

接口：jd.union.open.promotion.bysubunionid.get（导购媒体/推广位获取推广链接）
参数规范：{"promotionCodeReq": {"materialId": <商品链接/券链接/skuId>, "unionId": <联盟ID>, "subUnionId": <自定义追踪串>, "positionId": <推广位ID>, "chainType": 3}}
签名：secret + 各参数按字典序拼接 + secret，md5 后转大写

适用应用类型：导购媒体（如微信群、微博、博客、个人站等渠道），不需要网站/APP类应用的siteId。
"""
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(BASE_DIR, "link_cache.json")


def _load_cfg():
    with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def _load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def call_api(method, param_json, cfg):
    jd = cfg["jd"]
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    params = {
        "method": method,
        "app_key": jd["app_key"],
        "timestamp": ts,
        "format": "json",
        "v": "1.0",
        "sign_method": "md5",
        "360buy_param_json": json.dumps(param_json, ensure_ascii=False, separators=(",", ":")),
    }
    sign_src = jd["app_secret"] + "".join(f"{k}{v}" for k, v in sorted(params.items())) + jd["app_secret"]
    params["sign"] = hashlib.md5(sign_src.encode("utf-8")).hexdigest().upper()
    data = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items())
    req = urllib.request.Request(jd["gateway"], data=data.encode("utf-8"),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def convert_jd_link(material: str, cfg, cache) -> dict:
    """把京东商品/券链接转为推广链接。返回 {"ok":bool,"url":str,"msg":str}"""
    if material in cache:
        return cache[material]
    jd = cfg["jd"]
    result = {"ok": False, "url": material, "msg": "未转链"}
    if not jd.get("enabled"):
        result["msg"] = "转链未启用"
        return result
    req = {"promotionCodeReq": {
        "materialId": material,
        "unionId": jd.get("union_id", ""),
        "subUnionId": jd.get("sub_union_id", ""),
        "positionId": str(jd.get("position_id", "")),
        "chainType": int(jd.get("chain_type", 3)),
    }}
    try:
        resp = call_api(jd["method"], req, cfg)
        key = [k for k in resp if k.endswith("_responce")]
        body = resp[key[0]] if key else {}
        raw = body.get("getResult", "")
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            data = {}
        if isinstance(data, dict) and data.get("code") == 200:
            result = {"ok": True, "url": data.get("data", {}).get("clickURL") or material,
                      "msg": "转链成功"}
        else:
            result["msg"] = f"转链失败: {data.get('message') if isinstance(data, dict) else raw}"
    except Exception as e:
        result["msg"] = f"转链异常: {e}"
    cache[material] = result
    return result


def convert_all(deals, cfg):
    """批量转链：只处理平台为京东(platform=2)的链接"""
    cache = _load_cache()
    stats = {"ok": 0, "fail": 0, "skipped": 0}
    for deal in deals:
        if str(deal.get("platform")) != "2":
            for it in deal.get("list", []):
                if it.get("coupon_url") or it.get("item_id"):
                    it["url"] = it.get("coupon_url") or it.get("item_id")
                    it["converted"] = False
                    stats["skipped"] += 1
            continue
        for it in deal.get("list", []):
            target = it.get("coupon_url") or it.get("item_id")
            if not target:
                continue
            r = convert_jd_link(target, cfg, cache)
            it["url"] = r["url"]
            it["converted"] = r["ok"]
            it["convert_msg"] = r["msg"]
            stats["ok" if r["ok"] else "fail"] += 1
    _save_cache(cache)
    return stats
