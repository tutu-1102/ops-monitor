# -*- coding: utf-8 -*-
"""告警链路演练脚本：喂假数据给真实告警引擎，端到端验证状态机 + 降噪 + 通知 + 入库。

用法（在 ops-monitor 目录下）：
    python scripts/trigger_test.py              # 完整演练：触发→静默→恢复，全部恢复
    python scripts/trigger_test.py --leave-active   # 额外留一条 P1 内存告警在"告警中"状态，方便截图演示横幅

演练剧本（与告警引擎解耦：本脚本用独立的引擎实例，不影响正在运行的服务）：
    1. CPU 96% → 超阈值但未达连续 2 次，不告警（验证 sustain 防抖）
    2. CPU 97% → 连续第 2 次 → 触发 P0，发首条通知
    3. CPU 98% → 仍在告警中 → 只更新峰值，不重复通知（验证降噪）
    4. CPU 40% → 恢复，发恢复通知
    5. 内存 92% → 触发 P1（sustain=1，立即触发）
    6. 内存 88% → 恢复 P1
    （--leave-active 时跳过第 6 步，P1 保持告警中）
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import alert  # noqa: E402


def fake_metric(cpu=None, mem=None, disks=None):
    return {
        "timestamp": time.time(),
        "cpu_percent": cpu,
        "mem_percent": mem,
        "disks": disks or {},
        "net_in_bytes": 0,
        "net_out_bytes": 0,
    }


def main():
    leave_active = "--leave-active" in sys.argv
    engine = alert.AlertEngine()
    print("=" * 60)
    print("告警链路演练开始（真实引擎 + 真实入库 + 真实通知模块）")
    print("=" * 60, flush=True)

    steps = [
        ("CPU 96%（第 1 次超阈值）", fake_metric(cpu=96.0), 2),
        ("CPU 97%（第 2 次超阈值，应触发 P0）", fake_metric(cpu=97.0), 2),
        ("CPU 98%（持续告警，应静默不重复通知）", fake_metric(cpu=98.0), 2),
        ("CPU 40%（恢复，应发恢复通知）", fake_metric(cpu=40.0), 2),
        ("内存 92%（应触发 P1）", fake_metric(cpu=40.0, mem=92.0), 2),
    ]
    if not leave_active:
        steps.append(("内存 88%（应恢复 P1）", fake_metric(cpu=40.0, mem=88.0), 2))

    for name, metric, wait in steps:
        print(f"\n>>> {name}", flush=True)
        engine.check(metric)
        time.sleep(wait)

    print("\n" + "=" * 60)
    print("演练完成。查看结果：")
    print("  1. 打开 http://127.0.0.1:5000 看页面告警区（横幅 + 最近告警列表）")
    print("  2. GET http://127.0.0.1:5000/api/alerts 看告警历史 JSON")
    print("  3. 观察控制台：P0 只发了'触发'和'恢复'两条通知，中间 98% 被降噪")
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
