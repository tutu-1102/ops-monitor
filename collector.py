# -*- coding: utf-8 -*-
"""指标采集器：基于 psutil 采集 CPU/内存/磁盘/网络指标。

面试要点：
- CPU 使用率是"瞬时值"，用间隔采样取均值更平稳（见 cpu_percent 的 interval 参数）
- 磁盘按分区采集（可能有多个盘/挂载点）
- 网络速率 = 两次采集的字节数差值 / 时间差
"""
import time
import psutil


class Collector:
    def __init__(self):
        self._last_net = None   # 上次网络计数
        self._last_net_time = None

    def collect(self) -> dict:
        """采集一次，返回统一结构的指标字典。"""
        now = time.time()

        # CPU：interval=1 表示 psutil 内部采样 1 秒后返回均值
        cpu_percent = psutil.cpu_percent(interval=1.0)

        # 内存（百分比 + 已用/总量 GB，供仪表盘展示）
        mem = psutil.virtual_memory()
        mem_used_gb = round(mem.used / (1024 ** 3), 1)
        mem_total_gb = round(mem.total / (1024 ** 3), 1)

        # 磁盘：遍历所有分区
        disks = {}
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks[part.mountpoint] = round(usage.percent, 1)
            except (PermissionError, OSError):
                continue  # 无权限的分区跳过（如某些系统保留分区）

        # 网络：两次采集的字节差值换算速率（字节/秒）
        net = psutil.net_io_counters()
        net_in_rate = net_out_rate = 0
        if self._last_net is not None and self._last_net_time is not None:
            dt = now - self._last_net_time
            if dt > 0:
                net_in_rate = (net.bytes_recv - self._last_net.bytes_recv) / dt
                net_out_rate = (net.bytes_sent - self._last_net.bytes_sent) / dt
        self._last_net = net
        self._last_net_time = now

        return {
            "timestamp": now,
            "cpu_percent": round(cpu_percent, 1),
            "mem_percent": round(mem.percent, 1),
            "mem_used_gb": mem_used_gb,
            "mem_total_gb": mem_total_gb,
            "disks": disks,
            "net_in_bytes": round(net_in_rate, 1),
            "net_out_bytes": round(net_out_rate, 1),
        }


if __name__ == "__main__":
    # 独立运行：采集一次并打印（调试用）
    import json
    c = Collector()
    print(json.dumps(c.collect(), ensure_ascii=False, indent=2))
