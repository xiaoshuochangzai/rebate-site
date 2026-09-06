#!/bin/bash
# 多路由自动重试推送：网络一恢复就自动把今日数据推上线
cd /e/Jingdong/rebate-site
LOG=push_retry.log
echo "[$(date '+%H:%M:%S')] 自动推送重试开始" > $LOG
for round in $(seq 1 60); do
  # 路线1：直连（绕过所有代理）
  out=$(env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy GIT_TERMINAL_PROMPT=0 git push origin main 2>&1)
  if echo "$out" | grep -qE "main -> main|Everything up-to-date"; then
    echo "[$(date '+%H:%M:%S')] PUSH_OK 直连: $out" >> $LOG; exit 0
  fi
  # 路线2：WorkBuddy内置代理
  out=$(HTTPS_PROXY=http://127.0.0.1:50111 HTTP_PROXY=http://127.0.0.1:50111 GIT_TERMINAL_PROMPT=0 git push origin main 2>&1)
  if echo "$out" | grep -qE "main -> main|Everything up-to-date"; then
    echo "[$(date '+%H:%M:%S')] PUSH_OK 代理50111: $out" >> $LOG; exit 0
  fi
  # 路线3：Clash
  out=$(HTTPS_PROXY=http://127.0.0.1:7890 HTTP_PROXY=http://127.0.0.1:7890 GIT_TERMINAL_PROMPT=0 git push origin main 2>&1)
  if echo "$out" | grep -qE "main -> main|Everything up-to-date"; then
    echo "[$(date '+%H:%M:%S')] PUSH_OK Clash7890: $out" >> $LOG; exit 0
  fi
  echo "[$(date '+%H:%M:%S')] 第${round}轮失败: $(echo "$out" | tail -1 | cut -c1-80)" >> $LOG
  sleep 30
done
echo "[$(date '+%H:%M:%S')] 60轮全部失败，放弃" >> $LOG
exit 1
