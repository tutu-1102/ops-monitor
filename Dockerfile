# -*- Dockerfile -*-
# ops-monitor 容器镜像：Python 3.13 + psutil + Flask + SQLite
#
# 面试要点：
# - 基础镜像选 slim（精简版），体积小、攻击面小（对比 python:3.13 完整版）
# - 用 --no-cache-dir 减少镜像层体积；COPY 分两步让 pip 依赖层可被缓存复用
#   （改代码重新 build 时，依赖层不重装，秒级重建）
# - data/ 目录用 VOLUME 挂载，容器重建数据不丢

FROM python:3.13-slim

# 时区设为上海（否则容器内 localtime 是 UTC，告警时间会差 8 小时）
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 先只拷贝依赖清单并安装 → 依赖层可被 Docker 缓存复用
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷贝项目代码
COPY . .

# 数据目录（SQLite 落盘处）声明为卷，持久化到宿主机
VOLUME ["/app/data"]

# Web 端口
EXPOSE 5000

# 启动入口：后台采集线程 + Flask Web 服务
CMD ["python", "run.py"]
