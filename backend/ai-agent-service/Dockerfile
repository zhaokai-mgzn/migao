# AI Agent Service Dockerfile
# 构建: docker build -t ai-agent-service .

FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（含 ffmpeg 用于音频转码 + tzdata 保证容器时区可解析）
#
# ── APT_MIRROR 参数化（issue #5814：C′ 服务器侧构建）──────────────────────────
# 默认值 = **不改写 sources.list** ⇒ GitHub 托管 runner 上的行为**逐字不变**（双架构安全）。
# 只有服务器侧构建显式传 `--build-arg APT_MIRROR=mirrors.aliyun.com` 才换源。
#
# 为什么非参数化不可（**实测**，issue #5814 的施工单）：
# | 源 | 实测 |
# |---|---|
# | `deb.debian.org`（默认，从国内） | **4009 s（67 min）仍未下完 189 MB** —— 只下到第 164/≈240 个包 |
# | `mirrors.aliyun.com` | 吞吐 **855.6 KB/s**（vs 94.9 KB/s，≈9×；连接延迟 0.014s vs 0.346s）⇒ apt 步 **1100 s** |
# ⇒ 不换源时「服务器侧构建」光是 apt 就 >1 小时，比现状 40 分钟卡死更差 ⇒ 该方案不成立。
#
# ⚠️ 这一层**不打印** `sources.list` 内容：BuildKit 会把 apt 源写进层缓存元数据，
#    但那是 apt 自身行为，与本 ARG 无关；此处刻意不新增任何 `echo`/`cat`。
ARG APT_MIRROR=deb.debian.org
RUN if [ "$APT_MIRROR" != "deb.debian.org" ]; then \
      sed -i -e "s|deb.debian.org|${APT_MIRROR}|g" -e "s|security.debian.org|${APT_MIRROR}|g" \
          /etc/apt/sources.list.d/debian.sources 2>/dev/null \
       || sed -i -e "s|deb.debian.org|${APT_MIRROR}|g" -e "s|security.debian.org|${APT_MIRROR}|g" \
          /etc/apt/sources.list 2>/dev/null \
       || { echo "❌ APT_MIRROR=${APT_MIRROR} 换源失败：找不到可改写的 apt sources 文件（拒绝静默继续用默认源）" >&2; exit 1; }; \
    fi && \
    apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev ffmpeg tzdata && \
    rm -rf /var/lib/apt/lists/*

# 统一时区 UTC+8（所有系统/agent 业务时间均为北京时间）
ENV TZ=Asia/Shanghai

# 复制并安装 Python 依赖
#
# ⚠️ 同一族的口径（issue #5814 §四.2）：CI 现在传 `--build-arg PIP_INDEX_URL=https://pypi.org/simple/`
#    = **境外源**（在 GitHub 托管 runner 上是对的）；**服务器侧构建必须改传国内 PyPI 镜像**
#    （实测 pip 步 675 s @国内镜像），否则 pip 会成为下一个瓶颈。
#    本 Dockerfile 的默认值**保持原样**（阿里云镜像）⇒ 不改 CI 行为，只把选择权交给调用方。
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
