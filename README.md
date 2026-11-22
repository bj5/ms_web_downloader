# ModelScope Web Downloader

基于 FastAPI 的 ModelScope 模型网页下载器：在浏览器中搜索/选择模型，提交下载任务，后台异步下载到本地目录，并可查看每个模型的任务状态。

## 目录结构

```
ms_web_downloader/
├── app/
│   ├── main.py              # FastAPI 应用、ModelScope 搜索、后台下载任务
│   └── templates/index.html # 前端页面（Tailwind + 原生 JS）
├── models/                  # 挂载到容器 /models 的下载目录
├── .env                     # 环境变量（不入库）
├── .env.example
├── .gitignore
├── docker-compose.yml       # web-app + redis
└── Dockerfile
```

## 快速开始

编辑 `.env`（填入 `MODELSCOPE_API_KEY`，可选），然后：

```bash
docker compose up -d --build   # 同时启动 web-app 与 redis
```

打开浏览器访问 http://localhost:8000 。

如果 Docker Hub 无法访问，可改用镜像源拉取基础镜像：

```bash
docker pull docker.m.daocloud.io/library/python:3.9-slim
docker tag docker.m.daocloud.io/library/python:3.9-slim python:3.9-slim
```

（`Dockerfile` 使用官方 `python:3.9-slim`；上面的方式仅作为访问 Docker Hub 受阻时的替代方案，也可以在 `~/.docker/daemon.json` 里配置 registry mirror。）

## 环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `MODELSCOPE_API_KEY` | ModelScope 访问令牌，可在 https://modelscope.cn 获取。目前代码仅读取、尚未使用；需要下载受限模型时须显式调用 `HubApi.login()` | 空 |
| `DOWNLOAD_DIR` | 容器内下载目录，对应宿主机的 `./models` | `/models` |
| `PORT` | 仅作记录，当前未被程序读取，端口在 `Dockerfile` 与 `docker-compose.yml` 中固定为 8000 | `8000` |
| `REDIS_URL` | 状态存储的 Redis 连接串，`redis-py` 格式 | `redis://redis:6379/0` |

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | 模型列表页面 |
| `GET` | `/api/models?query=<关键词>` | 调用 ModelScope OpenAPI 搜索（`https://modelscope.cn/openapi/v1/models`），返回 `id`/`name`/`description`/`license`/`downloads`/`file_size_gb`；空关键词返回 OpenAPI 的默认列表 |
| `POST` | `/api/download` | 提交下载任务，请求体 `{"model_id": "Qwen/Qwen2-7B-Instruct"}`，立即返回，后台异步执行 |
| `GET` | `/api/status` | 从 Redis hash `download_status` 读取任务状态（`Downloading...` / `Completed` / `Failed: <原因>`）；Redis 不可用返回 503 |

示例：

```bash
# 搜索（页面搜索框走的就是这个接口）
curl 'http://localhost:8000/api/models?query=MiniMax-H3-Image'

# 下载
curl -X POST -H 'Content-Type: application/json' \
     -d '{"model_id":"MiniMax/MiniMax-H3-Image"}' \
     http://localhost:8000/api/download

curl http://localhost:8000/api/status
```

## 说明与已知限制

- **状态存储在 Redis**：hash `download_status`（field = model_id，value = 状态），数据落在 `redis_data` 卷，web 容器重启后状态仍在；字段没有 TTL，如需自动清理可改为每个模型一个带过期时间的 key。
- **后台任务仍是进程内线程池**：容器重启会中断进行中的下载，Redis 里的状态会停留在 `Downloading...`；要真正解耦需要队列（如 Celery / RQ）。
- **模型列表完全来自 ModelScope OpenAPI**（已移除内置演示数据）：页面在浏览器加载时请求 `/api/models`，离线时列表为空；搜索失败返回 502 `{"detail": "..."}`。
- **搜索命中的模型可能非常大**：例如 `MiniMax/MiniMax-H3-Image` 仓库约 204 GB（Comfy-Org 重打包版约 142 GB），需要足够的磁盘空间；它的 text encoder 在另一个仓库 `MiniMax/MiniMax-H3`，`snapshot_download` 不会自动拉取。
- **受限模型需要登录**：`MODELSCOPE_API_KEY` 当前未参与任何请求，私有或受限仓库会返回 401/403。
- **下载目录权限**：容器以 root 写入 `./models`，宿主普通用户无法直接删除这些文件，可在 compose 中映射 `user:` 或改用命名卷。
- **并发**：Redis 的字段写入是原子的，不再有进程内字典加锁问题；但同一模型重复提交时后写入的状态会覆盖前一个，多个 worker 需要自行约定（例如 `SETNX` 或队列消息）。

## 运行而不使用 Docker

```bash
pip install fastapi uvicorn jinja2 modelscope requests redis
export REDIS_URL=redis://localhost:6379/0   # 需要本地已有可用的 Redis
cd app && python main.py
```
