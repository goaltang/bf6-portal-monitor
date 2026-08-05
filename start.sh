#!/bin/bash
# BF6 Portal 监控启动脚本
# 用法: bash start.sh          启动监控（若已在跑则提示）
#       bash start.sh stop     停止监控
#       bash start.sh status   查看状态
#       bash start.sh log      看最新日志

cd "$(dirname "$0")"

case "${1:-start}" in
  start)
    if pgrep -f "bf6_portal_monitor.py" > /dev/null; then
      echo "已在运行 (PID: $(pgrep -f bf6_portal_monitor.py))"
      exit 0
    fi
    export PYTHONUTF8=1  # 强制 Python IO 走 UTF-8，与程序内 stdout 编码加固双保险
    nohup python3 bf6_portal_monitor.py >> monitor.log 2>&1 &
    sleep 2
    if pgrep -f "bf6_portal_monitor.py" > /dev/null; then
      echo "✅ 已启动 (PID: $(pgrep -f bf6_portal_monitor.py))"
      tail -3 monitor.log
    else
      echo "❌ 启动失败, 看 monitor.log"
      exit 1
    fi
    ;;
  stop)
    pkill -f "bf6_portal_monitor.py" && echo "已停止" || echo "没有在跑"
    ;;
  status)
    if pgrep -f "bf6_portal_monitor.py" > /dev/null; then
      echo "运行中 (PID: $(pgrep -f bf6_portal_monitor.py))"
      tail -5 monitor.log
    else
      echo "未运行"
    fi
    ;;
  log)
    tail -30 monitor.log
    ;;
  *)
    echo "用法: bash start.sh [start|stop|status|log]"
    ;;
esac
