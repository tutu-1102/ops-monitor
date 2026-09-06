@echo off
chcp 65001 >nul
cd /d "%~dp0"
title campus_sim 校园数据生成器
echo ============================================================
echo   每 1~2 秒向监控服务上报 10 栋楼数据（请先启动监控服务）
echo   Ctrl+C 停止；倍速演示: py campus_sim.py --speed 120
echo ============================================================
echo.
py campus_sim.py --interval 1 %*
echo.
echo ** 生成器已退出，若上方有报错请截图发给我 **
pause
