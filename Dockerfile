# ============================================================
# 多阶段 Dockerfile — 教学仓库生产级容器
# ============================================================
# 设计目标:
#   1. 小 image (slim + multi-stage)
#   2. 安全: 非 root user, no .env bake in
#   3. 教学友好: 默认进 01 跑基础 demo, 用户可自定义 entry
#   4. 健康检查 (curl 看 Python 是否还能跑)
#
# 跑法:
#   # 默认 — 跑 01-langchain-basics 入口
#   docker build -t lumen-langchain .
#   docker run --rm -it lumen-langchain
#
#   # 跑 08-cli-assistant 端到端 CLI
#   docker run --rm -it -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
#     -v $(pwd)/08-cli-assistant/data:/app/08-cli-assistant/data \
#     lumen-langchain python 08-cli-assistant/main.py
#
#   # 跑 12-async-pipeline SSE server (expose port)
#   docker run --rm -p 8000:8000 -e OPENAI_API_KEY=$OPENAI_API_KEY \
#     lumen-langchain uvicorn 04_sse_server:app --host 0.0.0.0 --port 8000

# ============================================================
# Stage 1: builder — 装 build deps + 包
# ============================================================
FROM python:3.11-slim AS builder

# 不缓冲 Python 输出 (docker logs 实时)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential 装某些包需要 (e.g. cryptography / pymysql)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先 copy pyproject + requirements — 利用 Docker layer cache
# deps 没变就不重新 pip install
COPY pyproject.toml ./
COPY requirements.txt ./

# 装包到 /install prefix, 后面 copy到 final image
RUN pip install --prefix=/install --no-cache-dir -e .

# ============================================================
# Stage 2: runtime — slim image + 非 root user
# ============================================================
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl 用于 HEALTHCHECK
# tini 是 PID 1 init, 正确处理信号 (Ctrl+C, SIGTERM)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 拷已装的包
COPY --from=builder /install /usr/local

# 拷源码 (从 builder 已经装好 deps, runtime 只要 source code)
WORKDIR /app
COPY . /app

# 创建非 root user (安全: 容器逃逸风险降低)
RUN useradd --create-home --shell /bin/bash --uid 1001 lumen && \
    chown -R lumen:lumen /app
USER lumen

# 暴露 8000 (12-async-pipeline FastAPI SSE/WebSocket demo 用)
EXPOSE 8000

# 健康检查 — 每 30s 测 Python 能否跑 (检查 `--version` 不消耗资源)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/ || python --version || exit 1

# 用 tini 作 PID 1, 正确处理 SIGTERM / SIGINT (uvicorn / python 都受益)
ENTRYPOINT ["/usr/bin/tini", "--"]

# 默认 CMD — 跑 01-langchain-basics 第一个 demo (10 个问题讲解)
# 用户可覆盖: `docker run ... <command>`
CMD ["python", "01-langchain-basics/01_models.py"]