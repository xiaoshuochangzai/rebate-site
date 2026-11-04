# -*- coding: utf-8 -*-
"""券后价格统一门槛（Boss 2026-11-05 明令）：全部线报券后 ≤100 元；
佣金高的适当放宽上浮 10%（佣金额 ≥10 元 → 最宽 ≤110 元）。

淘宝轮动池登记（_tb_comm_ok）、池内超价清理、低价好物榜采集（_filter_rank）
共用本模块，一处改口径全链路生效。拼多多另有更严的 ≤50 上限，不受影响。
"""

PRICE_CAP = 100.0        # 券后价基础上限
PRICE_CAP_MAX = 110.0    # 佣金高时的放宽上限（上浮 10%）
PRICE_CAP_COMM = 10.0    # 「佣金高」的口径：预估佣金额 ≥10 元


def price_ok(price, comm_amount):
    """券后价是否过关：≤100 直接过；100~110 需佣金额 ≥10；>110 一律拦。
    price/comm_amount 解析失败按不过处理（调用方先保证是 float）。"""
    try:
        p = float(price or 0)
        c = float(comm_amount or 0)
    except Exception:
        return False
    if p <= 0:
        return False
    if p <= PRICE_CAP:
        return True
    return p <= PRICE_CAP_MAX and c >= PRICE_CAP_COMM


def over_cap(price):
    """是否超出最宽上限（>110，池内清理用，不判佣金——超出即清）。"""
    try:
        return float(price or 0) > PRICE_CAP_MAX
    except Exception:
        return False
