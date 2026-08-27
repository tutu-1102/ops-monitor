@echo off
chcp 65001 >nul
title 运维监控系统 - 启动器
echo ============================================
echo   运维监控系统 (ops-monitor) 启动器
echo ============================================
echo.

REM 进入项目目录
cd /d "D:\DeepSeek\ops-monitor"

REM 检查 Docker 引擎是否运行
docker info >nul 2>&1
if errorlevel 1 (
    echo [错误] Docker 引擎未运行，正在尝试启动 Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo 请等待 Docker Desktop 完全启动（右下角鲸鱼图标不再转圈）后，再双击本文件一次。
    echo.
    pause
    exit /b 1
)

echo [1/4] Docker 引擎已就绪

REM 检查是否已有旧容器在跑（避免端口冲突）
docker ps --filter "name=ops-monitor" --format "{{.Names}}" | findstr /C:"ops-monitor" >nul
if %errorlevel%==0 (
    echo [提示] 检测到已有 ops-monitor 容器在运行，直接打开界面...
    goto open
)

echo [2/4] 构建并启动容器（首次需下载镜像，请耐心等待）...
docker compose up -d --build
if errorlevel 1 (
    echo.
    echo [错误] 启动失败，请把上面的报错信息截图给 AI 排查。
    pause
    exit /b 1
)

echo [3/4] 等待服务就绪...
timeout /t 8 /nobreak >nul

:open
echo [4/4] 打开监控面板 http://localhost:5000
start "" http://localhost:5000
echo.
echo ============================================
echo   启动完成！浏览器已打开监控面板。
echo   如需停止服务：在项目目录运行 docker compose down
echo ============================================
echo.
timeout /t 5 /nobreak >nul
