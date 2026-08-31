@echo off
title 运维监控系统 - 停止器
echo ============================================
echo   运维监控系统 (ops-monitor) 停止器
echo ============================================
echo.

cd /d "D:\DeepSeek\ops-monitor"

docker ps --filter "name=ops-monitor" --format "{{.Names}}" | findstr /C:"ops-monitor" >nul
if %errorlevel%==1 (
    echo [提示] 当前没有正在运行的 ops-monitor 容器。
    timeout /t 3 /nobreak >nul
    exit /b 0
)

echo 正在停止容器（数据保留在 data 目录，不会丢失）...
docker compose down
echo.
echo 已停止。
timeout /t 3 /nobreak >nul
