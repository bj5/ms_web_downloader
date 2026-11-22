# ModelScope Web Downloader

基于 FastAPI 的 ModelScope 模型网页下载器：在浏览器中搜索/选择模型，提交下载任务，后台异步下载到本地目录，并可查看每个模型的任务状态。

## 目录结构

```
ms_web_downloader/
├── app/
│   ├── main.py              # FastAPI 应用、ModelScope 搜索、带进度的后台下载
│   └── templates/index.html # 前端页面（Tailwind + 原生 JS）
├── .env                     # 环境变量（不入库）
├── .env.example
├── .gitignore
├── docker-compose.yml       # web-app + redis
└── Dockerfile
```

下载目录由 `MODEL_HOST_DIR`（宿主机路径）挂载到容器的 `/models`，默认是仓库里的 `./models`；本机 `.env` 已指向 `/opt/hdd/my/models`。

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
| `MODELSCOPE_API_KEY` | ModelScope 访问令牌（https://modelscope.cn 获取）。启动时若为真实值会调用 `HubApi.login()`，受限/私有仓库才需要 | `your_api_key_here`（占位符时跳过登录） |
| `DOWNLOAD_DIR` | 容器内的下载目录，对应挂载点 | `/models` |
| `MODEL_HOST_DIR` | 宿主机上的实际下载目录，挂载到容器 `/models` | `./models` |
| `HOST_UID` / `HOST_GID` | 容器运行身份。非 root 运行可让下载文件归属当前用户（配合 `HOME=/tmp`） | `1000` / `1000` |
| `PORT` | 仅作记录，当前未被程序读取，端口在 `Dockerfile` 与 `docker-compose.yml` 中固定为 8000 | `8000` |
| `REDIS_URL` | 状态存储的 Redis 连接串，`redis-py` 格式 | `redis://redis:6379/0` |

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | 模型列表页面 |
| `GET` | `/api/models?query=<关键词>` | 调用 ModelScope OpenAPI 搜索（`https://modelscope.cn/openapi/v1/models`），返回 `id`/`name`/`description`/`license`/`downloads`/`file_size_gb`；空关键词返回 OpenAPI 的默认列表 |
| `POST` | `/api/download` | 提交下载任务，请求体 `{"model_id": "Qwen/Qwen2-7B-Instruct"}`，立即返回，后台异步执行 |
| `GET` | `/api/status` | 从 Redis hash `download_status` 读取每个模型的进度 JSON：`state`、`files_total`、`files_done`、`bytes_total`、`bytes_done`、`current_file`；Redis 不可用返回 503 |

`state` 取值：`Downloading` / `Completed` / `Failed: <原因>`。

```json
{
  "iic/nlp_gte_sentence-embedding_chinese-small": {
    "model_id": "iic/nlp_gte_sentence-embedding_chinese-small",
    "state": "Completed",
    "files_total": 10,
    "files_done": 10,
    "bytes_total": 60983656,
    "bytes_done": 60983656,
    "current_file": "vocab.txt"
  },
  "Comfy-Org/MiniMax-H3": {
    "model_id": "Comfy-Org/MiniMax-H3",
    "state": "Downloading",
    "files_total": 41,
    "files_done": 4,
    "bytes_total": 534682335839,
    "bytes_done": 13555990528,
    "current_file": "diffusion_models/minimax_h3_fl2va_bf16.safetensors"
  }
}
```

页面上的状态区每 3 秒轮询这个接口，渲染文件数、字节数与进度条。

`bytes_done` 包含正在下载的文件已写入的字节：下载线程旁有一个监控线程，读取 modelscope 写入中的临时文件（`MODEL_HOST_DIR/._____temp/<model_id>/<文件路径>`），每 `PROGRESS_FLUSH_SECONDS`（默认 2 秒）把进度写回 Redis，所以单个大文件下载过程中百分比也会走动。

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

- **状态存储在 Redis**：hash `download_status`（field = model_id，value = 进度 JSON），数据落在 `redis_data` 卷，web 容器重启后状态仍在；字段没有 TTL，如需自动清理可改为每个模型一个带过期时间的 key。
- **进度粒度**：每个文件完成后 `files_done` 才 +1；正在下载的文件按临时文件实际大小估算（每 2 秒上报一次），所以百分比会走动。若 modelscope 命中缓存直接跳过下载，估算值为 0 直到该文件完成。单个文件内没有真正的传输速率数据，详细 tqdm 输出只在容器日志里。
- **缓存元数据**：modelscope 会在每个仓库目录写 `.mdl` / `.msc`，并在 `MODEL_HOST_DIR` 根目录写 `.lock` / `._____temp`。用其他工具（hf CLI、llama.cpp）预先下载的文件没有这些元数据，modelscope 会重新下载一遍。
- **后台任务仍是进程内线程池**：容器重启会中断进行中的下载，Redis 里的状态会停留在 `Downloading...`（重启后这条记录不会自动清理，需要 `HDEL download_status <model_id>`）；要真正解耦需要队列（如 Celery / RQ）。中断后已完成的文件命中缓存跳过；未完成的文件在 `._____temp` 里留下部分数据，重新提交会**续传**（modelscope 用 `Range: bytes=<已下载长度>-` 从部分文件继续），所以重启容器不会丢失正在下载的文件，前提是不要删除 `._____temp` 里的内容。重启后 Redis 里的旧记录不会自动清理（`bytes_done` 是重启前的值），重新提交任务即恢复真实进度。
- **模型列表完全来自 ModelScope OpenAPI**（已移除内置演示数据）：页面在浏览器加载时请求 `/api/models`，离线时列表为空；搜索失败返回 502 `{"detail": "..."}`。
- **搜索命中的模型可能非常大**：例如 `MiniMax/MiniMax-H3-Image` 仓库约 204 GB（Comfy-Org 重打包版约 142 GB），需要足够的磁盘空间；它的 text encoder 在另一个仓库 `MiniMax/MiniMax-H3`，`snapshot_download` 不会自动拉取。
- **受限模型需要登录**：启动时若 `MODELSCOPE_API_KEY` 不是占位符会调用 `HubApi.login()`，此时私有或受限仓库才能访问；否则请求是匿名的，受限仓库返回 401/403。登录失败只记录 warning，应用继续以匿名方式运行。
- **运行身份**：compose 以 `HOST_UID:HOST_GID`（默认 `1000:1000`）运行，下载文件归属当前用户；`HOME=/tmp` 是 modelscope 凭据目录所需，否则非 root 启动会报 `PermissionError`。
- **并发**：Redis 的字段写入是原子的，不再有进程内字典加锁问题；但同一模型重复提交时后写入的状态会覆盖前一个，多个 worker 需要自行约定（例如 `SETNX` 或队列消息）。

## 运行而不使用 Docker

```bash
pip install fastapi uvicorn jinja2 modelscope requests redis
export REDIS_URL=redis://localhost:6379/0   # 需要本地已有可用的 Redis
cd app && python main.py
```
