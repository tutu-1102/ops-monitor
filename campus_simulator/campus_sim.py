# -*- coding: utf-8 -*-
"""校园数字孪生 —— 模拟数据生成器（独立小程序，物理化版本）。

扮演“传感器/网关”角色：按 campus_config 里 10 栋楼的楼型，生成更贴近真实世界的
4 个业务指标（人流/用电/室温/网络），通过 HTTP POST 上报给 ops-monitor 的
/api/campus/ingest；再由告警系统入库、判定，并同步给浏览器校园仪表盘与 Unity
（它们只读，不直连本程序）。

与早期“4 指标共用一条人数曲线 + 白噪声”的简化版相比，本版做了合理化：
  1. 指标解耦、各有物理规律：
     - 人流 occupancy：楼型作息曲线（人数 presence），叠加工作日/周末与分楼差异；
     - 用电 power：恒定基础负载（设备/冰箱/服务器不关）+ 随人数变化的负荷
       + 午后空调、傍晚照明分量；食堂用电比人流提前约 0.7h（后厨备餐）；
     - 网络 network：骨干底流 + 随人数增长的接入流量 + 宿舍夜间娱乐高峰；
     - 室温 temp：室外气温日正弦（午后高、凌晨低）+ 人群散热，经一阶热惯性低通
       滤波缓慢变化（不会逐秒乱跳），空调把室温拉回设定点附近；
  2. AR(1) 自相关平滑噪声替代每秒独立白噪声，看起来像真实传感器的缓慢漂移；
  3. 工作日/周末节律不同（教学楼周末近乎空置，体育馆/宿舍周末更活跃）；
  4. 每栋楼有确定性的“体量系数”，同楼型也不会数值雷同；
  5. 故障注入改为缓升—保持—缓降，更像真实设备异常，仍会越过严重阈值触发告警。

只用标准库（urllib），无需 pip 安装；用法：
    py campus_sim.py                  # 连本机 5000，按真实时间与真实星期
    py campus_sim.py --speed 120      # 虚拟时钟 120 倍速，快速看全天曲线
    py campus_sim.py --weekend        # 强制按周末节律（演示用）
    py campus_sim.py --url http://127.0.0.1:5000 --interval 2
"""
import argparse
import json
import math
import random
import sys
import time
import urllib.error
import urllib.request

# 本程序独立放在 campus_simulator/ 子目录；共享的楼栋/指标目录 campus_config.py 在上一级。
# 无论从哪个工作目录启动，都能据本文件位置找到它；若将来整体拷出、并把 campus_config 放在
# 本目录旁，普通 import 也能命中——生成器与监控本体仅通过这一只读配置和 HTTP 接口耦合。
import os
_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

import campus_config
from campus_config import _bump, activity, METRICS, METRIC_ORDER, NODE_IDS


# 各楼型的物理系数：用电/网络 = 基础底流 + 人数贡献系数
TYPE_COEF = {
    "teaching": {"power_base": 0.16, "kp": 0.50, "net_base": 0.08, "kn": 0.50},
    "dorm":     {"power_base": 0.22, "kp": 0.42, "net_base": 0.10, "kn": 0.42},
    "canteen":  {"power_base": 0.12, "kp": 0.50, "net_base": 0.07, "kn": 0.25},
    "library":  {"power_base": 0.15, "kp": 0.48, "net_base": 0.09, "kn": 0.50},
    "sports":   {"power_base": 0.10, "kp": 0.55, "net_base": 0.06, "kn": 0.30},
    "flat":     {"power_base": 0.15, "kp": 0.45, "net_base": 0.08, "kn": 0.40},
}

# 周末相对工作日的“在楼人数”系数（教学楼几乎空置，体育馆/宿舍更活跃）
WEEKEND_FACTOR = {
    "teaching": 0.15, "canteen": 0.70, "library": 0.90,
    "sports": 1.30, "dorm": 1.25, "flat": 1.0,
}

# 各指标平滑噪声幅度（真实单位）
NOISE_AMP = {"occupancy": 1.5, "power": 8.0, "temp": 0.15, "network": 10.0}


def _clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


class CampusSimulator:
    def __init__(self, url, interval, speed, start_hour, fault_prob, max_faults, force_weekend=False):
        self.url = url.rstrip("/") + "/api/campus/ingest"
        self.interval = interval
        self.speed = speed
        # 虚拟时钟（小时）：默认从当前真实时刻起步
        self.clock = start_hour if start_hour is not None else time.localtime().tm_hour + time.localtime().tm_min / 60
        # 虚拟星期（周一=0 … 周日=6），随虚拟时钟跨天推进
        self.vday = time.localtime().tm_wday
        self.force_weekend = force_weekend
        self.fault_prob = fault_prob          # 每 tick 每楼起故障的概率
        self.max_faults = max_faults          # 全局同时存在的故障上限
        # (node,key) -> [剩余tick, 总tick]，便于做缓升/缓降包络
        self.faults = {}
        self.rng = {node: random.Random(hash(node) & 0xffffffff) for node in NODE_IDS}
        # 每栋楼确定性“体量系数”，让同楼型的楼数值略有差异（0.90~1.05）
        self.scale = {node: self.rng[node].uniform(0.90, 1.05) for node in NODE_IDS}
        # AR(1) 平滑噪声状态：(node,key) -> 上一拍噪声
        self.smooth = {}
        # 室温热惯性状态：node -> 上一拍室温
        self.temp_state = {}
        self.ok = 0
        self.fail = 0

    @property
    def is_weekend(self):
        return self.force_weekend or self.vday >= 5

    # ---------- 平滑噪声（一阶自回归，替代逐秒独立白噪声） ----------
    def _noise(self, node, key):
        amp = NOISE_AMP[key]
        prev = self.smooth.get((node, key), 0.0)
        white = self.rng[node].uniform(-amp, amp)
        cur = 0.8 * prev + 0.2 * white          # 强自相关，缓慢漂移
        self.smooth[(node, key)] = _clamp(cur, -amp, amp)
        return cur

    # ---------- 在楼人数（0~1）：作息曲线 × 周末 × 体量 ----------
    def _people(self, curve, node, t):
        people = activity(curve, t)
        if self.is_weekend:
            people *= WEEKEND_FACTOR.get(curve, 1.0)
        people *= self.scale[node]
        return _clamp(people, 0.0, 1.0)

    # ---------- 单指标物理模型 ----------
    def _gen(self, node, key, t, people):
        curve = campus_config.building_curve(node)
        meta = METRICS[key]
        lo, hi = meta["min"], meta["max"]
        coef = TYPE_COEF.get(curve, TYPE_COEF["flat"])
        v = 0.0

        if key == "occupancy":
            # 空置也有约 2~3% 底值（值班/零星人员），繁忙封顶约 79%（低于 80 预警线，正常运行不告警）
            v = 3.0 + people * 76.0 + self._noise(node, key)

        elif key == "power":
            # 用电 = 基础负载 + 人数负荷 + 午后空调 + 傍晚照明
            drive = activity("canteen", t + 0.7) if curve == "canteen" else people  # 食堂备餐提前
            hvac = 0.10 * _bump(t, 14, 4.0)
            light = 0.05 * _bump(t, 19, 2.2)
            frac = coef["power_base"] + coef["kp"] * drive + hvac + light
            v = _clamp(frac, 0.0, 0.90) * hi + self._noise(node, key)

        elif key == "network":
            # 网络 = 骨干底流 + 随人数接入 + 宿舍夜间娱乐高峰
            evening = 0.18 * _bump(t, 21, 2.6) if curve == "dorm" else 0.05 * _bump(t, 20, 3.0)
            frac = coef["net_base"] + coef["kn"] * people + evening
            v = _clamp(frac, 0.0, 0.92) * hi + self._noise(node, key)

        elif key == "temp":
            # 室外日正弦：约 5 时最低、15 时最高；室内受空调设定点与人群散热影响
            tout = 22.0 + 4.0 * math.sin((t - 9.0) / 24.0 * 2.0 * math.pi)
            target = 24.0 + 0.5 * (tout - 22.0) + 1.5 * people
            prev = self.temp_state.get(node, target)
            cur = prev + 0.25 * (target - prev)        # 一阶热惯性，缓慢逼近
            self.temp_state[node] = cur
            v = cur + self._noise(node, key)

        # 故障注入：缓升—保持—缓降地越过严重阈值
        if (node, key) in self.faults:
            rem, tot = self.faults[(node, key)]
            progress = tot - rem
            env = min(1.0, progress / 2.0, rem / 2.0)  # 首尾各 2 tick 过渡，中间=1
            env = _clamp(env, 0.0, 1.0)
            crit = meta["critical"]
            if key == "temp":
                fault_target = crit + self.rng[node].uniform(0.5, 1.5)
            else:
                fault_target = crit + (hi - crit) * self.rng[node].uniform(0.35, 1.0)
            v = v + (fault_target - v) * env

        return round(_clamp(v, lo, hi), meta["decimals"])

    def _update_faults(self):
        # 递减现有故障
        for k in list(self.faults):
            self.faults[k][0] -= 1
            if self.faults[k][0] <= 0:
                del self.faults[k]
        # 小概率新增故障
        for node in NODE_IDS:
            if len(self.faults) >= self.max_faults:
                break
            if self.rng[node].random() < self.fault_prob:
                key = self.rng[node].choice(METRIC_ORDER)
                if (node, key) not in self.faults:
                    tot = self.rng[node].randint(5, 12)
                    self.faults[(node, key)] = [tot, tot]

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
        for node in NODE_IDS:
            curve = campus_config.building_curve(node)
            people = self._people(curve, node, t)
            metrics = {k: self._gen(node, k, t, people) for k in METRIC_ORDER}
            payload = {"node": node, "ts": time.time(), "clockHour": round(t, 2),
                       "weekend": self.is_weekend, "metrics": metrics}
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
        wk = "周末" if self.is_weekend else "工作日"
        print(f"[生成器] {wk} 虚拟时刻 {hh:02d}:{mm:02d} | 本轮 10 楼已上报 | 成功 {self.ok} 失败 {self.fail}"
              + (f" | 故障楼: {','.join(firing)}" if firing else ""), flush=True)

    def run(self):
        print(f"[生成器] 启动：目标 {self.url}，周期 {self.interval}s，时钟倍率 x{self.speed}"
              + ("（强制周末）" if self.force_weekend else ""), flush=True)
        last = time.time()
        while True:
            self.tick()
            now = time.time()
            old = self.clock
            self.clock = (self.clock + self.speed * (now - last) / 3600.0) % 24
            if self.clock < old:                       # 跨天，虚拟星期前进
                self.vday = (self.vday + 1) % 7
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
    ap.add_argument("--weekend", action="store_true", help="强制按周末节律生成（演示用）")
    args = ap.parse_args()
    CampusSimulator(args.url, args.interval, args.speed, args.hour,
                    args.fault_prob, args.max_faults, args.weekend).run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[生成器] 已停止", flush=True)
        sys.exit(0)
