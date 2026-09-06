@echo off
chcp 65001 >nul
cd /d "D:\DeepSeek\ops-monitor"
title campus_sim 校园数据生成器
echo ============================================================
echo   校园模拟数据生成器：每 2 秒向监控服务上报 10 栋楼数据
echo   请先启动“启动监控-免Docker.bat”
echo   可选倍速参数： py campus_sim.py --speed 120 （2分钟过1小时）
echo   Ctrl+C 停止
echo ============================================================
echo.
py campus_sim.py %*
pause
