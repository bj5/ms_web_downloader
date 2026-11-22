from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import os
import logging
import json
import requests
import redis
from modelscope.hub.api import HubApi
from modelscope.hub.file_download import model_file_download

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

# Status storage: Redis hash `download_status` (field = model_id, value = JSON progress)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
STATUS_KEY = "download_status"
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

hub_api = HubApi()
if MODELSCOPE_API_KEY and MODELSCOPE_API_KEY != "your_api_key_here":
    try:
        hub_api.login(MODELSCOPE_API_KEY)
    except Exception as e:
        logger.warning("ModelScope login failed, continuing anonymously: %s", e)

def save_status(model_id: str, info: dict) -> None:
    redis_client.hset(STATUS_KEY, model_id, json.dumps(info))

def read_status() -> dict:
    raw = redis_client.hgetall(STATUS_KEY)
    parsed = {}
    for model_id, value in raw.items():
        try:
            parsed[model_id] = json.loads(value)
        except ValueError:
            parsed[model_id] = {"model_id": model_id, "state": value}
    return parsed

class ModelItem(BaseModel):
    id: str
    name: str
    description: str
    license: str = ""
    downloads: int = 0
    file_size_gb: float = 0.0

class StatusItem(BaseModel):
    model_id: str
    state: str
    files_total: int = 0
    files_done: int = 0
    bytes_total: int = 0
    bytes_done: int = 0
    current_file: str = ""

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
    # Model grid and status list are both filled by the browser from the API
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/models", response_model=list[ModelItem])
def get_models(query: str = "", page_size: int = 20):
    try:
        return search_models(query, page_size)
    except Exception as e:
        logger.exception("Search failed: %s", query)
        raise HTTPException(status_code=502, detail=f"Search failed: {e}")

@app.get("/api/status", response_model=dict[str, StatusItem])
def get_status():
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
        save_status(model_id, {"model_id": model_id, "state": "Downloading"})
    except redis.RedisError as e:
        logger.exception("Redis unavailable")
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {e}")

    background_tasks.add_task(run_download, model_id)
    return {"message": f"Started downloading {model_id}"}

def run_download(model_id: str):
    # Progress is tracked per file, which is what ModelScope reports for each repo
    try:
        files = [f for f in hub_api.get_model_files(model_id, recursive=True) if f.get("Type") != "tree"]
    except Exception as e:
        logger.exception("Cannot list files for %s", model_id)
        safe_save_status(model_id, {"model_id": model_id, "state": f"Failed: {e}"})
        return

    progress = {
        "model_id": model_id,
        "state": "Downloading",
        "files_total": len(files),
        "files_done": 0,
        "bytes_total": sum(int(f.get("Size") or 0) for f in files),
        "bytes_done": 0,
        "current_file": "",
    }
    safe_save_status(model_id, progress)

    for f in files:
        # Path is the repo-relative path; Name is only the basename
        file_path = f.get("Path") or f.get("Name")
        try:
            model_file_download(model_id, file_path, cache_dir=DOWNLOAD_DIR)
        except Exception as e:
            logger.exception("Failed on file %s of %s", file_path, model_id)
            progress["state"] = f"Failed: {e}"
            safe_save_status(model_id, progress)
            return

        progress["files_done"] += 1
        progress["bytes_done"] += int(f.get("Size") or 0)
        progress["current_file"] = file_path
        safe_save_status(model_id, progress)

    progress["state"] = "Completed"
    safe_save_status(model_id, progress)
    logger.info("Download completed: %s (%s files, %s bytes)", model_id, progress["files_done"], progress["bytes_done"])

def safe_save_status(model_id: str, info: dict) -> None:
    try:
        save_status(model_id, info)
    except redis.RedisError as e:
        logger.error("Status for %s not persisted: %s", model_id, e)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
