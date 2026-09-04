# AI Agent Service Dockerfile
# 构建: docker build -t ai-agent-service .

FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（含 ffmpeg 用于音频转码 + tzdata 保证容器时区可解析）
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev ffmpeg tzdata && \
    rm -rf /var/lib/apt/lists/*

# 统一时区 UTC+8（所有系统/agent 业务时间均为北京时间）
ENV TZ=Asia/Shanghai

# 复制并安装 Python 依赖
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i ${PIP_INDEX_URL} --trusted-host mirrors.aliyun.com --trusted-host pypi.org --trusted-host files.pythonhosted.org

# 复制应用代码
COPY . .

# 创建非 root 用户
RUN addgroup --system app && adduser --system --ingroup app app

# 创建日志目录并赋权
RUN mkdir -p logs && chown -R app:app logs

USER app:app

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-keep-alive", "65"]
