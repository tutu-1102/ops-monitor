# -*- coding: utf-8 -*-
"""全局配置：采集周期、数据保留、告警阈值、通知渠道。"""
import os

# ===== 采集 =====
COLLECT_INTERVAL = 5          # 采集周期（秒）
CPU_SAMPLE_INTERVAL = 1.0     # CPU 采样窗口（秒），取窗口内均值更平稳

# ===== 数据 =====
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "metrics.db")
RETENTION_DAYS = 7            # 历史数据保留天数，过期自动清理

# ===== 告警阈值（里程碑 3 使用）=====
ALERT_RULES = {
    "P0": {"metric": "cpu_percent",  "threshold": 95, "sustain": 2},   # 连续2次采样超95%
    "P1": {"metric": "mem_percent",  "threshold": 90, "sustain": 1},
    "P2": {"metric": "disk_percent", "threshold": 85, "sustain": 1},
}

# ===== 通知渠道（里程碑 3 使用，填入真实值后启用）=====
DINGTALK_WEBHOOK = ""         # 钉钉机器人 Webhook 地址
SMTP_HOST = ""                # 例: smtp.qq.com
SMTP_PORT = 465
SMTP_USER = ""
SMTP_PASSWORD = ""            # QQ邮箱为授权码
ALERT_EMAIL_TO = [""]

# ===== Web =====
WEB_HOST = "0.0.0.0"
WEB_PORT = 5000
