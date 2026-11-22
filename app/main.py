from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import os
import logging
import requests
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

# In-memory status for demo purposes (In production, use Redis/DB)
download_status = {}

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
    return templates.TemplateResponse("index.html", {"request": request, "status": download_status})

@app.get("/api/models", response_model=list[ModelItem])
def get_models(query: str = "", page_size: int = 20):
    try:
        return search_models(query, page_size)
    except Exception as e:
        logger.exception("Search failed: %s", query)
        raise HTTPException(status_code=502, detail=f"Search failed: {e}")

@app.get("/api/status")
async def get_status():
    return download_status

@app.post("/api/download")
async def start_download(data: dict, background_tasks: BackgroundTasks):
    model_id = data.get("model_id")
    if not model_id:
        return {"error": "No model_id provided"}
    
    download_status[model_id] = "Downloading..."
    background_tasks.add_task(run_download, model_id)
    return {"message": f"Started downloading {model_id}"}

def run_download(model_id: str):
    try:
        # The actual ModelScope download call
        ms_download(model_id, cache_dir=DOWNLOAD_DIR)
        download_status[model_id] = "Completed"
        logger.info("Download completed: %s", model_id)
    except Exception as e:
        download_status[model_id] = f"Failed: {str(e)}"
        logger.exception("Download failed: %s", model_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
