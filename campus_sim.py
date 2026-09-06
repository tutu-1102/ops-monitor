# -*- coding: utf-8 -*-
"""校园数字孪生 —— 模拟数据生成器（独立小程序）。

扮演“传感器/网关”角色：按 campus_config 里 10 栋楼的楼型曲线，
每隔 INTERVAL 秒生成 4 个业务指标（人流/用电/室温/网络），通过 HTTP POST
上报给 ops-monitor 的 /api/campus/ingest；再由告警系统入库、判定，
并同步给浏览器校园仪表盘与 Unity（它们只读，不直连本程序）。

数据规律与 Unity 端 SimulatedMetricProvider 完全一致（同一条日内高斯曲线），
另带“偶发故障注入”：小概率让某楼某指标短时冲到严重区间，触发告警后自动恢复，
用于演示 告警→3D楼体变红→恢复 的完整闭环。

只用标准库（urllib），无需 pip 安装；用法：
    py campus_sim.py                 # 连本机 5000，按真实时间
    py campus_sim.py --speed 120     # 虚拟时钟 120 倍速，快速看全天曲线
    py campus_sim.py --url http://127.0.0.1:5000 --interval 2
"""
import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request

import campus_config


class CampusSimulator:
    def __init__(self, url, interval, speed, start_hour, fault_prob, max_faults):
        self.url = url.rstrip("/") + "/api/campus/ingest"
        self.interval = interval
        self.speed = speed
        # 虚拟时钟（小时）：默认从当前真实时刻起步
        self.clock = start_hour if start_hour is not None else time.localtime().tm_hour + time.localtime().tm_min / 60
        self.fault_prob = fault_prob          # 每 tick 每楼起故障的概率
        self.max_faults = max_faults          # 全局同时存在的故障上限
        # (node,key) -> 剩余持续 tick 数
        self.faults = {}
        self.rng = {node: random.Random(hash(node) & 0xffffffff) for node in campus_config.NODE_IDS}
        self.ok = 0
        self.fail = 0

    # ---------- 单指标采样（对齐 Unity Generate） ----------
    def _gen(self, node, key, t):
        meta = campus_config.METRICS[key]
        curve = campus_config.building_curve(node)
        act = campus_config.activity(curve, t)
        factor = meta["baseline"] + (1 - meta["baseline"]) * act
        v = meta["min"] + (meta["max"] - meta["min"]) * factor
        amp = (meta["max"] - meta["min"]) * meta["noise"]
        v += self.rng[node].uniform(-amp, amp)

        # 故障注入：把值抬到严重阈值之上
        if self.faults.get((node, key), 0) > 0:
            crit = meta["critical"]
            v = crit + (meta["max"] - crit) * self.rng[node].uniform(0.35, 1.0)

        v = max(meta["min"], min(meta["max"], v))
        return round(v, meta["decimals"])

    def _update_faults(self):
        # 递减现有故障
        for k in list(self.faults):
            self.faults[k] -= 1
            if self.faults[k] <= 0:
                del self.faults[k]
        # 小概率新增故障
        for node in campus_config.NODE_IDS:
            if len(self.faults) >= self.max_faults:
                break
            if self.rng[node].random() < self.fault_prob:
                key = self.rng[node].choice(campus_config.METRIC_ORDER)
                if (node, key) not in self.faults:
                    self.faults[(node, key)] = self.rng[node].randint(5, 12)

    def _post(self, node, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200

    def tick(self):
        self._update_faults()
        t = self.clock
        firing = sorted({n for (n, _k) in self.faults})
        for node in campus_config.NODE_IDS:
            metrics = {k: self._gen(node, k, t) for k in campus_config.METRIC_ORDER}
            payload = {"node": node, "ts": time.time(), "clockHour": round(t, 2), "metrics": metrics}
            try:
                if self._post(node, payload):
                    self.ok += 1
                else:
                    self.fail += 1
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                self.fail += 1
                print(f"[生成器] 上报失败({node}): {e} —— 请确认 ops-monitor 已启动(py run.py)", flush=True)
                time.sleep(1.0)
        hh = int(t) % 24
        mm = int((t - int(t)) * 60)
        print(f"[生成器] 虚拟时刻 {hh:02d}:{mm:02d} | 本轮 10 楼已上报 | 成功 {self.ok} 失败 {self.fail}"
              + (f" | 故障楼: {','.join(firing)}" if firing else ""), flush=True)

    def run(self):
        print(f"[生成器] 启动：目标 {self.url}，周期 {self.interval}s，时钟倍率 x{self.speed}", flush=True)
        last = time.time()
        while True:
            self.tick()
            now = time.time()
            self.clock = (self.clock + self.speed * (now - last) / 3600.0) % 24
            last = now
            time.sleep(self.interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:5000")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--speed", type=float, default=1.0, help="虚拟时钟倍率（1=真实时间，120=2分钟过1小时）")
    ap.add_argument("--hour", type=float, default=None, help="强制起始时刻 0~24")
    ap.add_argument("--fault-prob", type=float, default=0.015)
    ap.add_argument("--max-faults", type=int, default=2)
    args = ap.parse_args()
    CampusSimulator(args.url, args.interval, args.speed, args.hour,
                    args.fault_prob, args.max_faults).run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[生成器] 已停止", flush=True)
        sys.exit(0)
