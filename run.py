# -*- coding: utf-8 -*-
"""启动入口：后台采集线程 + Web 服务。

面试要点：为什么用线程？
- 采集是周期性任务，Web 服务要能随时响应请求
- 单进程 + 线程最简；生产环境可用 systemd/supervisor 守护（扩展话题）
"""
import threading
import time
import config
import collector
import storage


def collect_loop():
    """后台采集线程：每隔 COLLECT_INTERVAL 秒采集并入库。"""
    c = collector.Collector()
    # 首次采集用于初始化网络速率基线（不准确，直接丢弃）
    c.collect()
    last_cleanup = time.time()

    while True:
        metric = c.collect()
        storage.save(metric)
        print(f"[采集] CPU={metric['cpu_percent']}% 内存={metric['mem_percent']}% "
              f"磁盘={metric['disks']}", flush=True)

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

    import app
    app.app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)
