from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import os
import logging
import requests
import redis
from modelscope import snapshot_download as ms_download

app = FastAPI()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger("modelscope_downloader")

# ModelScope OpenAPI（搜索与默认模型列表都来自它，不再有内置演示数据）
MODELSCOPE_OPENAPI = "https://modelscope.cn/openapi/v1/models"

# Configuration from environment
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/models")
MODELSCOPE_API_KEY = os.getenv("MODELSCOPE_API_KEY", "")

# Ensure download directory exists
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Status storage: Redis hash `download_status` (field = model_id, value = state)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
STATUS_KEY = "download_status"
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

def set_status(model_id: str, state: str) -> None:
    redis_client.hset(STATUS_KEY, model_id, state)

def read_status() -> dict:
    return redis_client.hgetall(STATUS_KEY)

class ModelItem(BaseModel):
    id: str
    name: str
    description: str
    license: str = ""
    downloads: int = 0
    file_size_gb: float = 0.0

def search_models(query: str, page_size: int = 20) -> list:
    # ModelScope OpenAPI: keyword search over model names and authors.
    # An empty query returns the API's default (hot) listing.
    params = {"page_number": 1, "page_size": page_size}
    if query:
        params["search"] = query
    resp = requests.get(MODELSCOPE_OPENAPI, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    return [
        {
            "id": m["id"],
            "name": m.get("display_name") or m["id"],
            "description": m.get("description") or "",
            "license": m.get("license") or "",
            "downloads": m.get("downloads") or 0,
            "file_size_gb": round((m.get("file_size") or 0) / 1e9, 1),
        }
        for m in data.get("models", [])
    ]

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # The model grid is filled by the browser from /api/models
    try:
        status = read_status()
    except redis.RedisError as e:
        logger.warning("Redis unavailable, status not rendered: %s", e)
        status = {}
    return templates.TemplateResponse("index.html", {"request": request, "status": status})

@app.get("/api/models", response_model=list[ModelItem])
def get_models(query: str = "", page_size: int = 20):
    try:
        return search_models(query, page_size)
    except Exception as e:
        logger.exception("Search failed: %s", query)
        raise HTTPException(status_code=502, detail=f"Search failed: {e}")

@app.get("/api/status")
async def get_status():
    try:
        return read_status()
    except redis.RedisError as e:
        logger.exception("Redis unavailable")
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {e}")

@app.post("/api/download")
async def start_download(data: dict, background_tasks: BackgroundTasks):
    model_id = data.get("model_id")
    if not model_id:
        return {"error": "No model_id provided"}

    try:
        set_status(model_id, "Downloading...")
    except redis.RedisError as e:
        logger.exception("Redis unavailable")
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {e}")

    background_tasks.add_task(run_download, model_id)
    return {"message": f"Started downloading {model_id}"}

def run_download(model_id: str):
    try:
        # The actual ModelScope download call
        ms_download(model_id, cache_dir=DOWNLOAD_DIR)
        state = "Completed"
    except Exception as e:
        state = f"Failed: {e}"
        logger.exception("Download failed: %s", model_id)

    try:
        set_status(model_id, state)
        logger.info("Status persisted: %s -> %s", model_id, state)
    except redis.RedisError as e:
        logger.error("Download %s finished as %s, but status could not be persisted: %s", model_id, state, e)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
