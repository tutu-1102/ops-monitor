# 部署文档（里程碑 5 · Docker 化）

## 一、本地 Docker 部署（Windows / Linux 通用）

```bash
# 1. 构建镜像
docker build -t ops-monitor .

# 2. 运行（后台，挂载数据目录，5000 端口）
docker run -d --name ops-monitor \
  -p 5000:5000 \
  -v "$(pwd)/data:/app/data" \
  --restart unless-stopped \
  ops-monitor

# 3. 看日志
docker logs -f ops-monitor
```

或用编排文件（推荐）：

```bash
docker compose up -d --build
docker compose logs -f
docker compose down
```

浏览器打开 `http://localhost:5000`。

## 二、云服务器上线（找工作前 1~2 个月再做）

```bash
# 服务器上（Ubuntu 为例）
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
git clone <你的仓库地址> ops-monitor && cd ops-monitor
docker compose up -d --build
```

- 配置安全组：放行 5000 端口
- 可选：Nginx 反代 + HTTPS 证书，暴露到公网域名

## 三、⚠️ 关键面试点：容器里监控"宿主机"的坑

这是本项目的核心难点，也是加分项。**Docker 容器默认有独立的 PID / 网络 / 文件系统命名空间**，直接 `docker run` 跑监控，会出现：

| 指标 | 容器内默认能看到什么 | 问题 |
|------|---------------------|------|
| CPU | `/proc/stat` 是**宿主机全局**的 | 其实能看宿主机 CPU ✅ |
| 内存 | `/proc/meminfo` 是宿主机全局的 | 其实能看宿主机内存 ✅ |
| **磁盘** | 只看得到**容器自己的 overlay 文件系统** | ❌ 看不到宿主机 C:/D: 等分区 |
| **网络** | 只看得到**容器自己的 veth 网卡** | ❌ 看不到宿主机真实网卡流量 |

**结论**：普通 `docker run` 跑监控，CPU/内存凑合能用，但磁盘和网络是错的——它监控的是"容器"，不是"服务器"。

### 正确姿势（监控宿主机需要穿透命名空间）

```bash
docker run -d --name ops-monitor \
  --pid=host \
  --network=host \
  -v /:/hostfs:ro \
  -p 5000:5000 \
  ops-monitor
```

> ⚠️ **Windows 注意事项**：Docker Desktop（Windows/Mac 版）底层是 WSL2/Hyper-V 虚拟机，
> **不支持 `--network=host`**（host 网络模式是 Linux 原生特性）。所以在 Windows 本地，
> 只能验证「镜像能 build、能跑、页面能开」，**真正验证宿主机监控穿透必须在 Linux 服务器上做**。
> 这也是为什么这个项目最终要上 Linux 的原因之一。

- `--pid=host`：共享宿主机 PID 命名空间，psutil 才能看到宿主机全部进程（进程快照才准）
- `--network=host`：共享宿主机网络，才能读到真实网卡流量
- `-v /:/hostfs:ro`：把宿主机根目录只读挂进来，磁盘分区才能读到真实容量

**这个坑正是运维岗最爱的追问**："你的监控是跑在容器里的，那它怎么监控宿主机本身？"——能答出命名空间穿透（pid/network/挂载），直接体现你的 Linux 底层功力。

## 四、生产级增强方向（可选，面试加分）

- 用 systemd 管理 `docker compose`（`systemctl enable docker` + restart policy）
- 数据备份：SQLite 定期 `docker cp` 或挂载到对象存储
- 多节点：每台被监控机装 agent（本机采集），中心端聚合，避免单容器穿透的复杂性
