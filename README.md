# ModelScope Web Downloader

基于 FastAPI 的 ModelScope 模型网页下载器：在浏览器中搜索/选择模型，提交下载任务，后台异步下载到本地目录，并可查看每个模型的任务状态。

## 目录结构

```
ms_web_downloader/
├── app/
│   ├── main.py              # FastAPI 应用与后台下载任务
│   └── templates/index.html # 前端页面（Tailwind + 原生 JS）
├── models/                  # 挂载到容器 /models 的下载目录
├── .env                     # 环境变量
├── docker-compose.yml
└── Dockerfile
```

## 快速开始

编辑 `.env`（填入 `MODELSCOPE_API_KEY`，可选），然后：

```bash
docker compose up -d --build
```

打开浏览器访问 http://localhost:8000 。

如果 Docker Hub 无法访问，可改用镜像源拉取基础镜像：

```bash
docker pull docker.m.daocloud.io/library/python:3.9-slim
docker tag docker.m.daocloud.io/library/python:3.9-slim python:3.9-slim
```

（当前 `Dockerfile` 已直接使用该镜像源地址，如网络可直连可改回 `python:3.9-slim`。）

## 环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `MODELSCOPE_API_KEY` | ModelScope 访问令牌，可在 https://modelscope.cn 获取。目前代码仅读取、尚未使用；需要下载受限模型时须显式调用 `HubApi.login()` | 空 |
| `DOWNLOAD_DIR` | 容器内下载目录，对应宿主机的 `./models` | `/models` |
| `PORT` | 仅作记录，当前未被程序读取，端口在 `Dockerfile` 与 `docker-compose.yml` 中固定为 8000 | `8000` |

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | 模型列表页面 |
| `GET` | `/api/models?query=<关键词>` | 调用 ModelScope OpenAPI 搜索（`https://modelscope.cn/openapi/v1/models`），返回 `id`/`name`/`description`/`license`/`downloads`/`file_size_gb`；空关键词返回 OpenAPI 的默认列表 |
| `POST` | `/api/download` | 提交下载任务，请求体 `{"model_id": "Qwen/Qwen2-7B-Instruct"}`，立即返回，后台异步执行 |
| `GET` | `/api/status` | 所有模型的任务状态（`Downloading...` / `Completed` / `Failed: <原因>`） |

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

- **状态存储为进程内字典**：容器重启后状态即丢失，生产环境应改用 Redis 或数据库。
- **模型列表完全来自 ModelScope OpenAPI**（已移除内置演示数据）：页面在浏览器加载时请求 `/api/models`，离线时列表为空；搜索失败返回 502 `{"detail": "..."}`。
- **搜索命中的模型可能非常大**：例如 `MiniMax/MiniMax-H3-Image` 仓库约 204 GB（Comfy-Org 重打包版约 142 GB），需要足够的磁盘空间；它的 text encoder 在另一个仓库 `MiniMax/MiniMax-H3`，`snapshot_download` 不会自动拉取。
- **受限模型需要登录**：`MODELSCOPE_API_KEY` 当前未参与任何请求，私有或受限仓库会返回 401/403。
- **下载目录权限**：容器以 root 写入 `./models`，宿主普通用户无法直接删除这些文件，可在 compose 中映射 `user:` 或改用命名卷。
- **并发与线程安全**：后台任务在线程池中读写共享字典，未加锁；大量并发任务时状态可能不一致。

## 运行而不使用 Docker

```bash
pip install fastapi uvicorn jinja2 modelscope
cd app && python main.py
```
