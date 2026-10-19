# ── Stage 1: Build frontend ───────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Production image ─────────────────────────────────────────────────
FROM python:3.11-slim

# 系统依赖（curl_cffi 需要 libcurl，akshare 需要 gcc）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libcurl4-openssl-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖（单独一层，利用 Docker 缓存）
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝后端代码
COPY backend/ ./backend/

# 拷贝前端构建产物
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist/

# 拷贝配置模板（运行时由 docker-compose volume 挂载真实 config.yaml 覆盖）
COPY config.example.yaml ./config.yaml

# 数据目录（挂载 volume 后持久化）
RUN mkdir -p data

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8802

# 生产模式：不用 --reload
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8802"]
