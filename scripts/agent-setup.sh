#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 米高远程研发 Agent 初始化脚本
#
# 在云服务器上运行一次即可。
# 前提：已安装 gh CLI + claude CLI + Node 20 + Python 3.11 + Java 21
# ═══════════════════════════════════════════════════════════════
set -e

echo "🔧 米高远程研发 Agent 初始化..."

# ── 配置（修改这里）──
AGENT_NAME="${AGENT_NAME:-migao-dev-agent}"
REPO="${REPO:-zhaokai-mgzn/migao}"
WORK_DIR="${WORK_DIR:-/opt/migao-agent}"
CRON_INTERVAL="${CRON_INTERVAL:-5}"  # 分钟

# ── 1. 克隆仓库 ──
if [ -d "$WORK_DIR" ]; then
    echo "📦 仓库已存在，git pull..."
    cd "$WORK_DIR" && git pull origin main
else
    echo "📦 克隆仓库..."
    git clone "https://github.com/${REPO}.git" "$WORK_DIR"
    cd "$WORK_DIR"
fi

# ── 2. 配置 git 用户 ──
git config user.name "$AGENT_NAME"
git config user.email "${AGENT_NAME}@migaozn.com"

# ── 3. 安装依赖 ──
echo "🐍 Python 依赖..."
cd "$WORK_DIR/backend/ai-agent-service"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

echo "☕ Java 依赖..."
cd "$WORK_DIR/backend/admin-api"
./mvnw dependency:resolve -q 2>/dev/null || echo "（跳过，需 Java 21）"

echo "📘 前端依赖..."
cd "$WORK_DIR/frontend/admin-web"
npm install

echo "🧪 E2E 依赖..."
cd "$WORK_DIR/tests"
npm install
npx playwright install chromium --with-deps 2>/dev/null || echo "（跳过，可能无头）"

# ── 4. 配置 .env ──
cd "$WORK_DIR"
if [ ! -f backend/ai-agent-service/.env ]; then
    echo "⚠️  请手动创建 backend/ai-agent-service/.env（含 DATABASE_URL、LLM key 等）"
fi
if [ ! -f backend/admin-api/.env ]; then
    echo "⚠️  请手动创建 backend/admin-api/.env"
fi

# ── 5. 配置 Claude Code agent ──
echo "🤖 配置 Claude Code agent..."
mkdir -p "$WORK_DIR/.claude"

# 复制 agent 指令（如果从本仓库初始化则已存在）
if [ ! -f "$WORK_DIR/.claude/agents/dev-agent.md" ]; then
    echo "⚠️  .claude/agents/dev-agent.md 不存在，请从项目仓库复制"
fi

# ── 6. 验证 gh 认证 ──
echo "🔐 验证 GitHub 认证..."
if ! gh auth status 2>/dev/null; then
    echo "请运行: gh auth login"
    exit 1
fi

# ── 7. 服务常驻（后台启动，Agent 随时可用）──
echo "🚀 启动本地服务（常驻后台）..."

# admin-api (Java, :8080)
cd "$WORK_DIR/backend/admin-api"
nohup ./mvnw spring-boot:run > /var/log/migao-admin-api.log 2>&1 &
echo "   admin-api → :8080 (pid $!)"

# ai-agent-service (Python, :8001)
cd "$WORK_DIR/backend/ai-agent-service"
nohup .venv/bin/python -m uvicorn app.main:app --port 8001 > /var/log/migao-ai-agent.log 2>&1 &
echo "   ai-agent-service → :8001 (pid $!)"

# admin-web (Next.js, :3001)
cd "$WORK_DIR/frontend/admin-web"
nohup npm run dev > /var/log/migao-admin-web.log 2>&1 &
echo "   admin-web → :3001 (pid $!)"

# 等 30 秒让服务启动
sleep 30

# 验证服务就绪
lsof -i :8080 -sTCP:LISTEN > /dev/null 2>&1 && echo "   ✅ admin-api 就绪" || echo "   ⚠️ admin-api 启动中..."
lsof -i :8001 -sTCP:LISTEN > /dev/null 2>&1 && echo "   ✅ ai-agent-service 就绪" || echo "   ⚠️ ai-agent-service 启动中..."
lsof -i :3001 -sTCP:LISTEN > /dev/null 2>&1 && echo "   ✅ admin-web 就绪" || echo "   ⚠️ admin-web 启动中..."

cd "$WORK_DIR"

# ── 8. 环境锁死 ──
echo "🔒 环境版本锁死..."
echo "   Java: $(java -version 2>&1 | head -1)"
echo "   Python: $(python3 --version)"
echo "   Node: $(node --version)"
echo "   npm: $(npm --version)"

# ── 9. 安装 cron 触发器 ──
chmod +x "$WORK_DIR/scripts/agent-poll.sh" 2>/dev/null || true

# 添加 cron job（每 5 分钟扫一次，并行处理 block + needs-verification）
(crontab -l 2>/dev/null | grep -v "agent-poll.sh"; echo "*/5 * * * * cd $WORK_DIR && bash scripts/agent-poll.sh >> /var/log/migao-agent.log 2>&1") | crontab -

echo ""
echo "✅ 初始化完成"
echo "  工作目录: $WORK_DIR"
echo "  cron: 每 ${CRON_INTERVAL} 分钟扫一次 GitHub"
echo "  日志: /var/log/migao-agent.log"
echo ""
echo "手动触发一次: cd $WORK_DIR && bash scripts/agent-poll.sh"
