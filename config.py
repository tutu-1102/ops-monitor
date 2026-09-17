# -*- coding: utf-8 -*-
"""全局配置：采集周期、数据保留、告警阈值、通知渠道。

敏感信息（钉钉 Webhook / SMTP 密码）一律从环境变量或 .env 文件读取，
不硬编码进本文件 —— 保证仓库里永远没有真实密钥（面试点：配置与代码分离）。
加载优先级：进程环境变量 > .env 文件 > 空（未配置则自动降级为控制台模式）。
"""
import os

# ===== 轻量 .env 加载（不引入 python-dotenv 依赖）=====
# 仅处理 KEY=VALUE 单行、忽略 # 注释与空行；已存在的环境变量不被覆盖。
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _load_dotenv(path: str):
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # 环境变量优先，不覆盖已显式设置的值
            os.environ.setdefault(key, value)


_load_dotenv(_ENV_PATH)


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# ===== 采集 =====
COLLECT_INTERVAL = 5          # 采集周期（秒）
CPU_SAMPLE_INTERVAL = 1.0     # CPU 采样窗口（秒），取窗口内均值更平稳

# ===== 数据 =====
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "metrics.db")
RETENTION_DAYS = 7            # 历史数据保留天数，过期自动清理

# ===== 告警阈值 =====
ALERT_RULES = {
    "P0": {"metric": "cpu_percent",  "threshold": 95, "sustain": 2},   # 连续2次采样超95%
    "P1": {"metric": "mem_percent",  "threshold": 90, "sustain": 1},
    "P2": {"metric": "disk_percent", "threshold": 85, "sustain": 1},
}

# ===== 通知渠道（从环境变量 / .env 读取，留空则自动降级为控制台模式）=====
DINGTALK_WEBHOOK = _env("DINGTALK_WEBHOOK")          # 钉钉机器人 Webhook 地址
SMTP_HOST = _env("SMTP_HOST")                         # 例: smtp.qq.com
SMTP_PORT = int(_env("SMTP_PORT", "465") or 465)
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")                 # QQ邮箱为授权码
ALERT_EMAIL_TO = [x for x in _env("ALERT_EMAIL_TO").split(",") if x.strip()]
# 校园数字孪生告警是否走同一套通知渠道（生成器压测时可设 0 关掉，避免刷屏）
CAMPUS_NOTIFY = _env("CAMPUS_NOTIFY", "1") not in ("0", "false", "False", "")

# ===== Web =====
WEB_HOST = _env("WEB_HOST", "0.0.0.0")
WEB_PORT = int(_env("WEB_PORT", "5000") or 5000)
