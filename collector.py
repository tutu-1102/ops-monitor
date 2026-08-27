# -*- coding: utf-8 -*-
"""指标采集器：基于 psutil 采集 CPU/内存/磁盘/网络指标。

面试要点：
- CPU 使用率是"瞬时值"，用间隔采样取均值更平稳（见 cpu_percent 的 interval 参数）
- 磁盘按分区采集（可能有多个盘/挂载点）
- 网络速率 = 两次采集的字节数差值 / 时间差
"""
import os
import time
import psutil


def snapshot_top_procs(n: int = 5, interval: float = 0.3) -> list:
    """抓取当前 CPU 占用最高的 n 个进程快照（告警触发时调用，事后排查用）。

    面试要点：
    - 告警不只是告诉你"出事了"，还要告诉你"是谁干的"——快照记录元凶
    - psutil 的 cpu_percent 第一次调用返回 0（只有基线），需先建立基线、
      sleep 一小段再取第二次，才是真实占用
    - 只在告警触发的"边沿"抓一次，不在每次采集都抓，避免额外开销
    """
    procs = []
    for p in psutil.process_iter(['pid', 'name']):
        try:
            p.cpu_percent(interval=None)  # 第一次调用建立基线
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    time.sleep(interval)  # 让出时间，第二次调用才得到真实占用

    rows = []
    for p in procs:
        try:
            info = p.info
            cpu = p.cpu_percent(interval=None)
            rows.append((cpu, info['pid'], info['name']))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # 先过滤掉空闲进程（PID 0 的空闲不是元凶），再排序取前 n
    rows = [r for r in rows if r[1] != 0 and r[2] != "System Idle Process"]
    rows.sort(reverse=True)
    return [
        {"pid": pid, "name": name, "cpu": round(cpu, 1)}
        for cpu, pid, name in rows[:n]
    ]


# ===== 磁盘挂载点过滤 =====
# 面试点：容器里 psutil.disk_partitions() 返回的是"容器视角"的挂载点，
# 会混入大量虚拟文件系统（overlay/tmpfs/proc 等）和 WSL2 内部路径，
# 这些不是宿主机真实分区，直接监控会刷出假告警（如只读层永远 100%）。
# 因此采集前过滤两类：
#   1) 虚拟/伪文件系统（fstype 黑名单）
#   2) 单文件 bind 挂载（挂载点是文件而非目录，如容器里的 /etc/resolv.conf）
_PSEUDO_FSTYPES = {
    # 容器/内核虚拟文件系统
    "overlay", "tmpfs", "devtmpfs", "squashfs", "proc", "sysfs",
    "cgroup", "cgroup2", "devpts", "mqueue", "ramfs", "shm",
    "securityfs", "debugfs", "tracefs", "pstore", "bpf", "configfs",
    "fusectl", "hugetlbfs", "binfmt_misc", "autofs", "nsfs", "rootfs",
    "fuse", "fuse.gvfsd-fuse",
    # 只读镜像文件系统（ISO/光盘镜像，永远 100%，不反映真实磁盘）
    "iso9660", "udf",
    # WSL2 挂载 Windows 盘的虚拟文件系统（非真实块设备，Docker Desktop 场景）
    "9p", "drvfs",
}


def _is_pseudo_mount(part) -> bool:
    """判断挂载点是否为"伪"挂载（虚拟/只读镜像文件系统、loop 回环设备或单文件 bind），应排除在磁盘监控外。"""
    fstype = (part.fstype or "").lower()
    if fstype in _PSEUDO_FSTYPES:
        return True
    # loop 回环设备：挂载的是镜像文件（如 WSL2 的 cli-tools ISO），只读、永远满
    device = (part.device or "")
    if device.startswith("/dev/loop"):
        return True
    # 单文件 bind 挂载：挂载点是一个文件（如 /etc/resolv.conf），不是分区
    if os.path.isfile(part.mountpoint):
        return True
    return False


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

        # 磁盘：遍历真实分区，过滤虚拟文件系统与单文件 bind 挂载
        disks = {}
        for part in psutil.disk_partitions():
            if _is_pseudo_mount(part):
                continue
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
