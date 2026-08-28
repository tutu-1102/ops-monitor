# -*- coding: utf-8 -*-
"""启动入口：后台采集线程 + Web 服务。

面试要点：为什么用线程？
- 采集是周期性任务，Web 服务要能随时响应请求
- 单进程 + 线程最简；生产环境可用 systemd/supervisor 守护（扩展话题）

里程碑 6（多节点）：本机作为「中心端 + 本机节点」，后台线程采集本机指标
（node=hostname）直接入库并判定；其他节点通过 agent.py 上报到 /api/ingest。
"""
import socket
import threading
import time

import app as webapp
import config
import collector
import storage


def collect_loop():
    """后台采集线程：每隔 COLLECT_INTERVAL 秒采集本机、入库、告警检查。"""
    c = collector.Collector()
    node = socket.gethostname()   # 本机节点标识
    # 复用中心端唯一告警引擎（与 agent 上报共用，状态按 node 隔离）
    engine = webapp.engine
    # 首次采集用于初始化网络速率基线（不准确，直接丢弃）
    c.collect()
    last_cleanup = time.time()

    while True:
        metric = c.collect()
        storage.save(metric, node)
        print(f"[采集] [{node}] CPU={metric['cpu_percent']}% 内存={metric['mem_percent']}% "
              f"磁盘={metric['disks']}", flush=True)

        # 告警检查单独 try/except：告警模块出问题绝不能拖垮采集主链路
        try:
            engine.check(metric, node)
        except Exception as e:
            print(f"[告警引擎] 检查异常（不影响采集）: {e}", flush=True)

        # 每天清理一次过期数据
        if time.time() - last_cleanup > 86400:
            storage.cleanup()
            last_cleanup = time.time()

        time.sleep(config.COLLECT_INTERVAL)


if __name__ == "__main__":
    print("启动监控系统：后台采集线程 + Web 服务")
    print(f"采集周期: {config.COLLECT_INTERVAL}s | 数据保留: {config.RETENTION_DAYS} 天")
    print(f"访问 http://127.0.0.1:{config.WEB_PORT}")

    t = threading.Thread(target=collect_loop, daemon=True)
    t.start()

    webapp.app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)
