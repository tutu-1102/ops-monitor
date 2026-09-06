@echo off
cd /d "%~dp0"
title ops-monitor 监控服务（免Docker）
echo ============================================================
echo   监控服务（本地 Python 直跑，不需要 Docker）
echo   主机仪表盘 : http://localhost:5000
echo   校园孪生页 : http://localhost:5000/campus
echo   关闭本窗口即停止服务
echo ============================================================
echo.
py run.py
echo.
echo ** 服务已退出，若上方有报错请截图发给我 **
pause
