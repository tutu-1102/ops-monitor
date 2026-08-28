# -*- coding: utf-8 -*-
"""多节点监控 agent：在被监控机器上运行，采集本机指标并上报中心端。

用法：
    python agent.py                          # 默认上报 http://127.0.0.1:5000
    python agent.py --server http://10.0.0.1:5000 --node web-01 --interval 5

参数（均可省略，取默认值）：
    --server    中心端地址（默认 http://127.0.0.1:5000）
    --node      本节点标识（默认主机名）
    --interval  上报周期秒（默认取 config.COLLECT_INTERVAL）

面试要点：
- 这就是 Zabbix agent / Prometheus exporter 的「主动上报」思路：被监控端推数据，
  中心端统一存储 + 判定告警
- 复用 collector.Collector 采集逻辑，agent 和中心端本机共用同一套采集代码
- 用标准库 urllib 上报，不引入 requests 依赖
"""
import argparse
import json
import socket
import time
import urllib.request

import config
import collector


def main():
    ap = argparse.ArgumentParser(description="ops-monitor agent（上报本机指标到中心端）")
    ap.add_argument("--server", default="http://127.0.0.1:5000",
                    help="中心端地址（默认 http://127.0.0.1:5000）")
    ap.add_argument("--node", default=None, help="节点标识（默认主机名）")
    ap.add_argument("--interval", type=int, default=None, help="上报周期秒（默认取 config）")
    args = ap.parse_args()

    server = args.server.rstrip("/")
    node = args.node or socket.gethostname()
    interval = args.interval or config.COLLECT_INTERVAL

    c = collector.Collector()
    # 首次采集建立网络速率基线（丢弃，首次网络速率恒为 0）
    c.collect()

    print(f"[agent] 节点={node} 上报到 {server} 周期={interval}s", flush=True)
    while True:
        metric = c.collect()
        payload = json.dumps({"node": node, "metric": metric}).encode("utf-8")
        req = urllib.request.Request(
            server + "/api/ingest", data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
            print(f"[agent] 上报成功 CPU={metric['cpu_percent']}% "
                  f"内存={metric['mem_percent']}%", flush=True)
        except Exception as e:
            print(f"[agent] 上报失败: {e}", flush=True)

        time.sleep(interval)


if __name__ == "__main__":
    main()
