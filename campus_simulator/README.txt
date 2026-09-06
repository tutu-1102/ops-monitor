校园数据生成器（campus_simulator）
================================

定位：独立的“传感器/网关”模拟器，与监控服务解耦——只通过 HTTP 上报数据，
      不直接读写数据库，也不被浏览器/Unity 连接。可单独启停、单独修改。

文件：
  campus_sim.py            生成器主程序（只用 Python 标准库，无需 pip 安装）
  启动校园数据生成器.bat     专用启动器（双击即可）

启动顺序：
  1) 先启动监控服务：双击 ..\启动监控-免Docker.bat
  2) 再双击本目录的 启动校园数据生成器.bat
  （或直接双击上级目录的 一键启动校园演示-免Docker.bat，两步合一）

命令行用法（在本目录打开终端）：
  py campus_sim.py                      按真实时间、每 2 秒一轮
  py campus_sim.py --interval 1         每 1 秒一轮
  py campus_sim.py --speed 120          120 倍速，快速演示全天曲线
  py campus_sim.py --fault-prob 0.2     提高故障注入概率
  py campus_sim.py --url http://IP:5000 上报到其它主机

说明：楼栋/指标目录与曲线复用上级 campus_config.py（只读），保证生成端、
      服务端、Unity 三端的 10 栋楼与 4 项指标口径一致。
