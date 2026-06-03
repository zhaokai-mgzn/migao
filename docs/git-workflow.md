# Git 操作规范

> 根据网络状况选择最优工具，提升开发效率

## 问题背景

当前环境（2026-06-03 诊断）：
- ✅ GitHub API (`gh` CLI) 稳定快速
- ⚠️ Git HTTPS 可用但不稳定（19s 连接时间）
- ❌ SSH 未配置

## 工具选择指南

### 场景 1：创建分支

**推荐：`gh api`（绕过 Git 协议）**
```bash
# 从 main 创建新分支
BRANCH="feat/your-feature"
PARENT_SHA=$(gh api repos/zhaokai-mgzn/youke/git/refs/heads/main --jq '.object.sha')

gh api repos/zhaokai-mgzn/youke/git/refs \
  -f ref="refs/heads/$BRANCH" \
  -f sha="$PARENT_SHA" \
  --jq '.ref'
```

**备选：`git`（网络好时）**
```bash
git checkout main && git pull origin main
git checkout -b feat/your-feature
```

### 场景 2：提交代码

**推荐：`gh api`（绕过 Git 协议）**
```bash
# 单文件修改
BRANCH="feat/your-feature"
FILE_PATH="backend/ai-agent-service/app/config.py"
FILE_SHA=$(gh api "repos/zhaokai-mgzn/youke/contents/$FILE_PATH?ref=$BRANCH" --jq '.sha')

gh api "repos/zhaokai-mgzn/youke/contents/$FILE_PATH" \
  -X PUT \
  -f message="feat: your commit message" \
  -f content="$(cat $FILE_PATH)" \
  -f sha="$FILE_SHA" \
  -f branch="$BRANCH" \
  --jq '.commit.sha'
```

**多文件修改：使用 GitHub Actions**
```bash
# 1. 本地修改文件
git add .
git commit -m "feat: your changes"

# 2. 推送分支（重试机制）
for i in 1 2 3; do 
  git push origin feat/your-feature && break
  sleep 5
done
```

### 场景 3：创建 PR

**推荐：`gh pr create`（始终可用）**
```bash
gh pr create \
  --head feat/your-feature \
  --base main \
  --title "feat: your PR title" \
  --body "## Changes\n..."
```

### 场景 4：合并 PR

**推荐：`gh api`（绕过 Git 协议）**
```bash
PR_NUMBER=149
gh api repos/zhaokai-mgzn/youke/pulls/$PR_NUMBER/merge \
  -X PUT \
  -f merge_method="squash" \
  -f commit_title="feat: your PR title (#$PR_NUMBER)"
```

**备选：`gh pr merge`（网络好时）**
```bash
gh pr merge $PR_NUMBER --squash --delete-branch
```

### 场景 5：同步远程变更

**推荐：`git fetch + reset`（绕过 merge 冲突）**
```bash
# 强制同步到远程状态
git fetch origin main
git reset --hard origin/main
```

**备选：`git pull`（需要合并时）**
```bash
git pull --rebase origin main
```

## 网络优化配置

已应用（2026-06-03）：
```bash
# 增大缓冲区，避免大文件传输中断
git config --global http.postBuffer 524288000

# 禁用低速断连，避免网络波动时中断
git config --global http.lowSpeedLimit 0
git config --global http.lowSpeedTime 999999

# 禁用压缩，减少 CPU 开销
git config --global core.compression 0
```

## SSH 配置（可选，更稳定）

如果 HTTPS 持续不稳定，可配置 SSH：

```bash
# 1. 生成 SSH key
ssh-keygen -t ed25519 -C "your-email@example.com"

# 2. 添加到 GitHub
cat ~/.ssh/id_ed25519.pub
# 复制输出，到 https://github.com/settings/ssh/new 添加

# 3. 切换仓库到 SSH
git remote set-url origin git@github.com:zhaokai-mgzn/youke.git

# 4. 测试
ssh -T git@github.com
```

## 故障排查

### 问题 1：`git push` 超时

```bash
# 诊断
curl -I https://github.com

# 解决
gh api repos/zhaokai-mgzn/youke/contents/...  # 用 API 上传
```

### 问题 2：`git pull` 冲突

```bash
# 强制同步（丢弃本地未提交的修改）
git fetch origin main
git reset --hard origin/main
```

### 问题 3：`gh` 命令失败

```bash
# 检查认证
gh auth status

# 重新登录
gh auth login
```

## 监控部署状态

```bash
# 查看最新 workflow
gh workflow list --all

# 监控运行状态
gh run list --workflow=<workflow-id>

# 查看日志
gh run view <run-id> --log
```

## 最佳实践

1. **优先使用 `gh api`** — 绕过 Git 协议，网络要求低
2. **批量修改用 Git** — 多文件改动时 Git 更方便
3. **配置重试机制** — `for i in 1 2 3; do ... && break; done`
4. **及时 fetch** — 避免本地分支落后太多
5. **监控 CI/CD** — `gh run list` 确认部署状态

## 参考

- [GitHub REST API 文档](https://docs.github.com/rest)
- [Git 配置选项](https://git-scm.com/docs/git-config)
- [项目规范](./CLAUDE.md)
