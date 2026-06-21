#!/bin/bash
# 二郎神 cron 心跳告警
# crontab: */5 * * * * bash /opt/youke/scripts/heartbeat.sh
set -euo pipefail

THRESHOLD_MIN=15
LOGDIR="${LOGDIR:-/var/log}"
WATCHDOG_LOG="$LOGDIR/migao-watchdog.log"

for svc in agent verify; do
    LOG="$LOGDIR/migao-$svc.log"
    if [ -f "$LOG" ]; then
        LAST=$(stat -c %Y "$LOG" 2>/dev/null || echo 0)
        AGE=$(( ($(date +%s) - LAST) / 60 ))
        if [ "$AGE" -gt "$THRESHOLD_MIN" ]; then
            echo "[$(date)] 🚨 migao-$svc 无心跳 ${AGE} 分钟" >> "$WATCHDOG_LOG"
        fi
    fi
done

# 锁文件超时告警
for lock in /tmp/migao-agent.lock /tmp/migao-verify.lock; do
    if [ -f "$lock" ]; then
        LOCK_AGE=$(( ($(date +%s) - $(stat -c %Y "$lock" 2>/dev/null || echo 0)) / 60 ))
        if [ "$LOCK_AGE" -gt 30 ]; then
            echo "[$(date)] 🚨 $lock 锁超过 ${LOCK_AGE} 分钟，可能死锁" >> "$WATCHDOG_LOG"
        fi
    fi
done
