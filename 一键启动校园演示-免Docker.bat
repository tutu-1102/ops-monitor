@echo off
chcp 65001 >nul
cd /d "D:\DeepSeek\ops-monitor"
echo [1/3] 启动监控服务（新窗口，免Docker）...
start "ops-monitor 服务" cmd /k py run.py
timeout /t 5 /nobreak >nul

echo [2/3] 启动校园数据生成器（新窗口）...
start "campus_sim 生成器" cmd /k py campus_sim.py
timeout /t 3 /nobreak >nul

echo [3/3] 打开校园数字孪生仪表盘...
start "" http://localhost:5000/campus
echo.
echo 已全部启动。停止时关闭弹出的两个黑色窗口即可。
timeout /t 4 /nobreak >nul
