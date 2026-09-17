# -*- coding: utf-8 -*-
"""校园告警端到端演练：触发 P0 → 持续降噪 → 恢复。

用法（服务已启动）:
    py scripts/trigger_campus_test.py
"""
import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"
NODE = "North_Teaching"


def post(metrics):
    body = json.dumps({"node": NODE, "metrics": metrics}).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/api/campus/ingest", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest():
    with urllib.request.urlopen(BASE + "/api/campus/latest", timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    print("== 1) 首次越限（暂不告警，1/2）==")
    print(post({"occupancy": 96.0, "power": 100, "temp": 24, "network": 50}))
    time.sleep(0.2)

    print("== 2) 第二次越限（应触发 P0 + 通知）==")
    print(post({"occupancy": 97.0, "power": 100, "temp": 24, "network": 50}))
    time.sleep(0.3)

    print("== 3) 持续更高值（只更新峰值，不重复通知）==")
    print(post({"occupancy": 99.0, "power": 100, "temp": 24, "network": 50}))
    time.sleep(0.3)

    d = latest()
    n = next(x for x in d["nodes"] if x["id"] == NODE)
    print(f"latest: occ={n['occupancy']} worst={n['worstStatus']} alerts={n['activeAlerts']}")

    print("== 4) 回落正常（应发恢复通知）==")
    print(post({"occupancy": 20.0, "power": 100, "temp": 24, "network": 50}))
    time.sleep(0.3)

    d = latest()
    n = next(x for x in d["nodes"] if x["id"] == NODE)
    print(f"after recover: occ={n['occupancy']} worst={n['worstStatus']} alerts={n['activeAlerts']}")
    print("演练完成（看服务控制台/钉钉是否各出现触发+恢复各一条）")


if __name__ == "__main__":
    main()
