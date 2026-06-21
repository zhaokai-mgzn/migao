# 12 — 部署指南

从零搭建军师服务器的完整步骤。

## 前提条件

- 云服务器: Linux (Alibaba Cloud Linux / CentOS / Ubuntu)
- 已安装: `git`, `java-21`, `python-3.11`, `node-20`, `gh` CLI
- GitHub: `zhaokai-mgzn` 账号有 repo 读写权限

## 步骤 1: 安装基础依赖

```bash
# Java 21
yum install -y java-21-alibaba-dragonwell  # Alibaba Cloud Linux
# 或: apt-get install openjdk-21-jdk       # Ubuntu

# Python 3.11 + pip
yum install -y python3.11 python3.11-pip
python3.11 -m ensurepip

# Node.js 20
curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
yum install -y nodejs

# gh CLI
yum install -y gh
# 或: https://github.com/cli/cli/blob/trunk/docs/install_linux.md

# Claude Code CLI (需要 API key)
# 按官方文档安装: https://docs.anthropic.com/en/docs/claude-code
```

## 步骤 2: 认证

```bash
# GitHub 认证 (需要 repo + workflow + project 权限)
gh auth login
# 选择 GitHub.com → HTTPS → Paste token
# Token scopes: delete_repo, gist, project, read:org, repo, workflow

# 验证
gh auth status
```

## 步骤 3: 运行 agent-setup.sh

```bash
cd /opt
git clone https://github.com/zhaokai-mgzn/migao.git youke
cd /opt/youke
bash scripts/agent-setup.sh
```

**agent-setup.sh 做什么**:
1. Clone 仓库到 `/opt/youke/`
2. 配置 git user: `junshi` / `junshi@youke.local`
3. 安装 Python venv + Java mvn + Node npm + Playwright
4. 复制 Agent 配置: `dev-agent.md` + `verify-agent.md` + `settings.json`
5. 安装 crontab: agent-poll + verify-poll (各每 5 分钟)

## 步骤 4: 配置环境变量

### `/opt/youke/backend/admin-api/.env`
```bash
RDS_HOST=pgm-xxx.pg.rds.aliyuncs.com
RDS_PORT=5432
RDS_DB=ai_customer_service
RDS_USER=migao_admin
RDS_PASSWORD=<password>
REDIS_HOST=r-xxx.redis.rds.aliyuncs.com
REDIS_PORT=6379
REDIS_PASSWORD=<password>
SERVICE_TOKEN=<service_token>
```

### `/opt/youke/backend/ai-agent-service/.env`
```bash
DATABASE_URL=postgresql+asyncpg://migao_admin:<password>@pgm-xxx.pg.rds.aliyuncs.com:5432/ai_customer_service
REDIS_URL=redis://:<password>@r-xxx.redis.rds.aliyuncs.com:6379/0
ADMIN_API_BASE_URL=http://localhost:8081
SERVICE_TOKEN=<service_token>
PRIMARY_API_KEY=<llm_api_key>
PRIMARY_MODEL=deepseek-v4-pro
```

## 步骤 5: 验证

```bash
# 查看 crontab
crontab -l | grep -E 'agent-poll|verify-poll'

# 查看最近日志
tail -20 /var/log/migao-agent.log
tail -20 /var/log/migao-verify.log

# 手动触发 agent-poll
cd /opt/youke && bash scripts/agent-poll.sh

# 手动触发 verify-poll
cd /opt/youke && bash scripts/verify-poll.sh

# 查看健康指标
cat /tmp/migao-agent-health.json
```

## 步骤 6: 配置 OpenClaw (可选)

OpenClaw 是军师 LLM 调度器，需要单独安装：

```bash
# 按 OpenClaw 官方文档安装
cd /opt
git clone <openclaw-repo> openclaw

# 复制二郎神 cron prompt
cp /opt/youke/ershen/prompts/*.md /opt/junshi/prompts/

# 配置 OpenClaw cron
# 7 个 job 的 schedule 和 prompt 见 05-cron-jobs.md
```

## 验证清单

| 检查项 | 命令 | 预期 |
|--------|------|------|
| crontab 运行 | `crontab -l` | 2 行 agent/verify-poll |
| agent 心跳 | `tail -1 /var/log/migao-agent.log` | 5 分钟内有输出 |
| git 认证 | `gh auth status` | Logged in |
| 服务可达 | `curl localhost:8081/api/admin/dashboard/stats` | 200 |
| 工作区干净 | `cd /opt/youke && git status` | clean, on main |
| 锁文件不存在 | `ls /tmp/migao-*.lock` | No such file |

## 安全注意事项

- `.env` 文件包含密码，确保 `chmod 600`
- Agent 使用 root 用户运行，git refs 权限可能漂移
- Token 过期 → `gh auth refresh`
- 日志包含敏感信息 (DB 密码等)，限制访问权限
