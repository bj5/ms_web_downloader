FROM python:3.9-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    jinja2 \
    modelscope \
    requests \
    redis \
    python-multipart

WORKDIR /app

# 设置环境变量
ENV DOWNLOAD_DIR=/models
ENV PORT=8000
# modelscope 需要一个可写的 HOME（非 root 运行时 ~ 可能指向不可写目录）
ENV HOME=/tmp

# 复制项目文件
COPY ./app /app/app
WORKDIR /app/app

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]