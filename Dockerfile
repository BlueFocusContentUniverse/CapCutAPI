# syntax=docker/dockerfile:1.7

FROM python:3.14-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONIOENCODING=UTF-8 \
    UVICORN_WORKERS=2

WORKDIR /app

# 安装系统依赖（ffmpeg）
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# 复制代码
COPY . .

# 安装 Python 依赖
RUN pip install --upgrade pip --trusted-host pypi.org --trusted-host files.pythonhosted.org \
    && pip install .

# 使用 secret 挂载方式读取 .env.prod（不会留在镜像层中）
RUN --mount=type=secret,id=env_file cat /run/secrets/env_file > /app/.env

# 创建日志目录和非 root 用户
RUN mkdir -p logs && \
    useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# 切换到非 root 用户
USER appuser

# 默认端口
EXPOSE 9000

# 启动命令（默认单核配置2个worker，可通过UVICORN_WORKERS覆盖）
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-9000} --workers ${UVICORN_WORKERS:-2}"]
