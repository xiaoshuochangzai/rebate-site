#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cf_daily_stats.py — 线报站（shengqian.cyou）Cloudflare 访问日报（真人口径设备统计）

数据源：CF GraphQL httpRequestsAdaptiveGroups（token: E:/Jingdong/cf_analytics_token.txt）
口径（2026-10-12 深挖后定稿）：
  - 去重单位 = 唯一 IP（比 CF sum.visits 准：同访客跨 colo 拆组会重复计数）
  - 机器人   = UA 明示 bot/爬虫/扫描器/脚本（python/curl/go/空UA 等）
  - 疑似代理爬虫 = 真人 UA 但 ①电脑端且节点在欧洲机房（AMS/LHR/CDG/FRA——国内用户不可能）
                  ②或 IP 属代理池段（180.163.x 上海 IDC 等）——实测 7 天里电脑端 85%+ 是这类
  - 真人     = 真人 UA 且非疑似代理爬虫（手机端节点 SJC/HKG/ICN/SIN 属正常国内入口）
  - 只统计 path="/"（首页打开），排除 /api/deals 轮询噪音
推送：keyword_config.json 的 webhook（企微群机器人 text 消息）

用法：
  python cf_daily_stats.py                # 本地打印昨日 + 近7天，不推送
  python cf_daily_stats.py --push         # 打印并推送企微
  python cf_daily_stats.py --days 14
  python cf_daily_stats.py --quiet --push # 自动化用
"""
import json
import os
import re
import ssl
import sys
import datetime
import urllib.request
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = r"E:\Jingdong\cf_analytics_token.txt"
ZONE_TAG = "4d361ffc6ffc65fc49cef2302efc7de6"
CFG_FILE = os.path.join(BASE, "keyword_config.json")
GQL_URL = "https://api.cloudflare.com/client/v4/graphql"
PROXY = "http://127.0.0.1:7890"

GQL = """query ($zone: String!, $from: Date!, $to: Date!) {
  viewer {
    zones(filter: {zoneTag: $zone}) {
      httpRequestsAdaptiveGroups(
        limit: 10000,
        filter: {date_geq: $from, date_leq: $to, clientRequestPath: "/"}
        orderBy: [count_DESC]
      ) {
        dimensions { date clientDeviceType userAgent clientIP coloCode }
        count
      }
    }
  }
}"""

# ---------------------------------------------------------------- UA 分类
BOT_RE = re.compile(
    r'bot|spider|crawl|scrap|slurp|curl|python|wget|go-http|java/|okhttp'
    r'|httpclient|libwww|headless|zgrab|masscan|nikto|nmap|acunetix|sqlmap'
    r'|openssh|axios|node\.js|winhttp|autoit|fiddler|postman|insomnia|libcurl'
    r'|apache-httpclient|googlehc|healthcheck|uptime|monitor|semrush|ahrefs'
    r'|mj12|dotbot|petalbot|yisou|bytespider|censys|sonar|l9scan|palo|specter'
    r'|redirectmap|wordpress|wp-|shell|exploit|scan|fuzz|dirbuster|gobuster'
    r'|wfuzz|nuclei|ffuf|httpx|user-agent:',
    re.I,
)

HUMAN_FAMS = [
    (r'\bEdg(?:e|A|iOS)?/', 'Edge'),
    (r'OPR/|Opera', 'Opera'),
    (r'Firefox/', 'Firefox'),
    (r'MicroMessenger/', '微信内置'),
    (r'MQQBrowser/', 'QQ浏览器'),
    (r'HuaweiBrowser/', '华为浏览器'),
    (r'HeyTapBrowser/', 'OPPO浏览器'),
    (r'VivoBrowser/', 'vivo浏览器'),
    (r'XiaoMi/MiuiBrowser/', '小米浏览器'),
    (r'BaiduBoxApp|baidubrowser|BaiduApp', '百度系'),
    (r'UCBrowser|UCWEB', 'UC浏览器'),
    (r'Quark/', '夸克'),
    (r'DingTalk/', '钉钉内置'),
    (r'AlipayClient', '支付宝内置'),
    (r'Chrome/\d+', 'Chrome'),
    (r'Safari/\d+', 'Safari'),
]

# 欧洲机房节点：国内真实用户几乎不可能从这里接入（实测 desktop 假流量 85%+ 集中于此）
EU_COLOS = {'AMS', 'LHR', 'CDG', 'FRA', 'MRS', 'MAD', 'MIL', 'WAW', 'VIE', 'ARN', 'CPH', 'DUB'}
# 已实测确认的代理池 IP 段（前两段）
PROXY_SEGMENTS = {'180.163', '94.154', '45.138', '93.123'}


def ua_class(ua):
    if not ua or len(ua) < 25:
        return ('bot', '空/超短UA')
    if BOT_RE.search(ua):
        m = re.search(r'([\w.\-+/]+)(?:/\d[\w.\-]*)?\s*$', ua.strip())
        short = m.group(1) if m and len(m.group(1)) <= 30 else ua[:24]
        return ('bot', short)
    for pat, fam in HUMAN_FAMS:
        if re.search(pat, ua):
            return ('human', fam)
    return ('bot', '未知UA:' + ua[:20])


def ip_segment(ip):
    if ':' in ip:
        return 'IPv6'
    return '.'.join(ip.split('.')[:2])


# ---------------------------------------------------------------- 网络
def _opener(proxy=None):
    if proxy:
        ph = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
    else:
        ph = urllib.request.ProxyHandler({})
    return urllib.request.build_opener(ph, urllib.request.HTTPSHandler(
        context=ssl.create_default_context()))


def gql_query(token, variables, timeout=60):
    body = json.dumps({'query': GQL, 'variables': variables}).encode()
    req = urllib.request.Request(GQL_URL, data=body, method='POST')
    req.add_header('Authorization', 'Bearer ' + token)
    req.add_header('Content-Type', 'application/json')
    req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
    last_err = None
    for op in (_opener(None), _opener(PROXY)):
        try:
            with op.open(req, timeout=timeout) as r:
                data = json.loads(r.read().decode())
            if data.get('errors'):
                raise RuntimeError('GQL errors: ' + json.dumps(data['errors'], ensure_ascii=False)[:300])
            return data
        except Exception as e:  # noqa
            last_err = e
    raise last_err


# ---------------------------------------------------------------- 统计
def fetch(token, d_from, d_to):
    variables = {'zone': ZONE_TAG, 'from': d_from.isoformat(), 'to': d_to.isoformat()}
    data = gql_query(token, variables)
    groups = data['data']['viewer']['zones'][0]['httpRequestsAdaptiveGroups']
    # res[date][cls][dev] = {'req': n, 'ipcolo': {ip: 主colo}, 'fam': {family: req}}
    res = {}
    for g in groups:
        d = g['dimensions']
        dev = (d.get('clientDeviceType') or 'unknown')
        ua = d.get('userAgent') or ''
        ip = d.get('clientIP') or 'unknown'
        colo = d.get('coloCode') or '?'
        cls, fam = ua_class(ua)
        n = int(g.get('count', 0))
        day = res.setdefault(d['date'], {})
        bucket = day.setdefault(cls, {}).setdefault(dev, {'req': 0, 'ipcolo': {}, 'fam': {}})
        bucket['req'] += n
        if ip not in bucket['ipcolo'] or n >= 1:
            bucket['ipcolo'][ip] = colo if ip not in bucket['ipcolo'] else bucket['ipcolo'][ip]
        bucket['fam'][fam] = bucket['fam'].get(fam, 0) + n
    return res


def split_desktop(bucket):
    """desktop 真人桶 → (疑似爬虫IP集合, 疑似真人IP集合)"""
    fake, real = set(), set()
    for ip, colo in bucket['ipcolo'].items():
        if colo in EU_COLOS or ip_segment(ip) in PROXY_SEGMENTS:
            fake.add(ip)
        else:
            real.add(ip)
    return fake, real


def day_summary(res_d):
    """返回 dict：mobile_real, desktop_real, desktop_fake, bot, 明细"""
    out = {'mobile_real': 0, 'desktop_real': 0, 'desktop_fake': 0,
           'tablet_real': 0, 'bot': 0, 'bot_ua': Counter(), 'detail': []}
    human = res_d.get('human', {})
    bot = res_d.get('bot', {})
    out['mobile_real'] = len(human.get('mobile', {}).get('ipcolo', {}))
    out['tablet_real'] = len(human.get('tablet', {}).get('ipcolo', {}))
    d_b = human.get('desktop')
    if d_b:
        fake, real = split_desktop(d_b)
        out['desktop_real'] = len(real)
        out['desktop_fake'] = len(fake)
    out['bot'] = sum(len(v['ipcolo']) for v in bot.values())
    for v in bot.values():
        for fam, n in v['fam'].items():
            out['bot_ua'][fam] += n
    return out


def fmt_day(dstr, res_d):
    d = datetime.date.fromisoformat(dstr)
    wk = '一二三四五六日'[d.weekday()]
    s = day_summary(res_d)
    real_total = s['mobile_real'] + s['desktop_real'] + s['tablet_real']
    lines = ['【%d-%02d-%02d 周%s】' % (d.year, d.month, d.day, wk)]
    lines.append('✅真人（IP去重）：手机 %d | 电脑 %d | 平板 %d，合计 %d'
                 % (s['mobile_real'], s['desktop_real'], s['tablet_real'], real_total))
    lines.append('🎭伪装真人爬虫（电脑端欧洲节点/代理池）：%d IP' % s['desktop_fake'])
    lines.append('🤖明示机器人：%d IP' % s['bot'])
    top = [f for f, _ in s['bot_ua'].most_common(3)]
    if top:
        lines.append('机器人主力：' + '、'.join(top))
    return '\n'.join(lines), s


def fmt_totals(res, days_sorted, summaries):
    mr = sum(x['mobile_real'] for x in summaries)
    dr = sum(x['desktop_real'] for x in summaries)
    df = sum(x['desktop_fake'] for x in summaries)
    bt = sum(x['bot'] for x in summaries)
    n = len(days_sorted) or 1
    return ('—— %d天累计（IP去重/天）——\n'
            '真人手机：%.1f IP/天\n'
            '真人电脑：%.1f IP/天（剔除爬虫后）\n'
            '伪装爬虫（电脑）：%.1f IP/天\n'
            '明示机器人：%.1f IP/天'
            % (n, mr / n, dr / n, df / n, bt / n))


# ---------------------------------------------------------------- 推送
def load_webhook():
    cfg = json.load(open(CFG_FILE, encoding='utf-8'))
    return (cfg.get('webhook') or '').strip()


def send_webhook(text, webhook):
    def _post(t):
        body = json.dumps({'msgtype': 'text', 'text': {'content': t}}).encode('utf-8')
        req = urllib.request.Request(webhook, data=body, method='POST')
        req.add_header('Content-Type', 'application/json')
        last = None
        for op in (_opener(None), _opener(PROXY)):
            try:
                with op.open(req, timeout=20) as r:
                    out = json.loads(r.read().decode())
                    if out.get('errcode') == 0:
                        return True, ''
                    return False, 'errcode=%s' % out
            except Exception as e:  # noqa
                last = e
        return False, str(last)

    chunks, cur = [], ''
    for line in text.split('\n'):
        cand = (cur + '\n' + line) if cur else line
        if len(cand.encode('utf-8')) > 1800:
            chunks.append(cur)
            cur = line
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    errs = []
    for c in chunks:
        ok, msg = _post(c)
        if not ok:
            errs.append(msg)
    return (not errs), '; '.join(errs)


# ---------------------------------------------------------------- main
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--push', action='store_true')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    token = open(TOKEN_FILE, encoding='utf-8').read().strip()
    today = datetime.date.today()
    d_to = today - datetime.timedelta(days=1)
    d_from = d_to - datetime.timedelta(days=args.days - 1)

    res = fetch(token, d_from, d_to)
    days_sorted = sorted(res.keys())
    if not args.quiet:
        print('拉取 %s ~ %s，共 %d 天有数据' % (d_from, d_to, len(days_sorted)))

    blocks, summaries = [], {}
    for dstr in reversed(days_sorted):
        txt, s = fmt_day(dstr, res[dstr])
        summaries[dstr] = s
        blocks.append(txt)
        if not args.quiet:
            print(txt)
            print()

    total_txt = fmt_totals(res, days_sorted, [summaries[d] for d in days_sorted])
    if not args.quiet:
        print(total_txt)

    if args.push:
        head = '📈 线报站访问日报（真人口径·IP去重）'
        body = head + '\n' + total_txt + '\n\n' + '\n\n'.join(blocks[:3])
        wh = load_webhook()
        if not wh:
            print('!! webhook 未配置，未推送')
            return 1
        ok, msg = send_webhook(body, wh)
        print('推送:', 'OK' if ok else 'FAIL ' + msg)
        return 0 if ok else 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
