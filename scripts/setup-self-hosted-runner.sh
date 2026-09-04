#!/usr/bin/env bash
# =============================================================================
# setup-self-hosted-runner.sh — 注册 GitHub Actions 自托管 runner（migao 仓库）
#
# 背景（issue #2786）：GitHub 托管 runner 高峰时慢/排队，E2E 门禁等 job 反复
# 因 timeout 误报。自托管 runner 作为缓解手段：跑在本机/内网机器上，
# 减少对 GitHub 托管队列的依赖。
#
# 用法：
#   ./scripts/setup-self-hosted-runner.sh                # 交互式（前台运行，Ctrl+C 停止）
#   RUNNER_SERVICE=1 ./scripts/setup-self-hosted-runner.sh   # 安装为 launchd 服务（后台常驻）
#
# 前置：
#   - gh CLI 已登录且有仓库 admin 权限（用于拉取 registration token）
#   - 目标机器已装运行 CI 所需工具（Java 21 / Node 20 / Python 3.11，按需）
#
# 注意：
#   - registration token 1 小时内有效，本脚本每次运行时动态获取，勿硬编码
#   - 自托管 runner 与 GitHub 托管 runner 共享同一份 workflow（runs-on: ubuntu-latest
#     需在仓库 Settings → Actions → Runners 将该 runner 加 label: ubuntu-latest）
#   - 机器长时间挂机/休眠会导致 runner 掉线；建议用 RUNNER_SERVICE=1 常驻
# =============================================================================
set -uo pipefail

REPO="zhaokai-mgzn/migao"
RUNNER_DIR="${RUNNER_DIR:-$HOME/actions-runner}"
RUNNER_VERSION="2.337.0"   # 2026-08 最新稳定版，按需升级（查：gh api repos/actions/runner/releases/latest）
ARCH="$(uname -m)"; [ "$ARCH" = "arm64" ] && RUNNER_ARCH="arm64" || RUNNER_ARCH="x64"
OS="$(uname -s | tr 'A-Z' 'a-z')"   # darwin / linux

echo "▸ 仓库: $REPO | 目录: $RUNNER_DIR | 平台: ${OS}-${RUNNER_ARCH}"

if ! command -v gh >/dev/null 2>&1; then
  echo "❌ 需要 gh CLI（brew install gh / 官方安装脚本）"; exit 1
fi

# 1. 获取 registration token（每次运行动态生成）
TOKEN_JSON="$(gh api -X POST "repos/${REPO}/actions/runners/registration-token" 2>/dev/null)"
if [ -z "$TOKEN_JSON" ]; then
  echo "❌ 无法获取 registration token（gh 需仓库 admin 权限）"; exit 1
fi
TOKEN="$(echo "$TOKEN_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')"
echo "✓ registration token 已获取（有效期 1 小时）"

# 2. 下载并解压 runner
if [ ! -x "$RUNNER_DIR/config.sh" ]; then
  mkdir -p "$RUNNER_DIR"
  PKG="actions-runner-${OS}-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"
  URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${PKG}"
  echo "▸ 下载 $PKG ..."
  curl -sL -o "/tmp/${PKG}" "$URL" || { echo "❌ 下载失败"; exit 1; }
  tar xzf "/tmp/${PKG}" -C "$RUNNER_DIR"
  echo "✓ runner 已解压"
fi

# 3. 配置（幂等：已配置则跳过）
if [ ! -f "$RUNNER_DIR/.runner" ]; then
  (cd "$RUNNER_DIR" && ./config.sh --url "https://github.com/${REPO}" --token "$TOKEN" --unattended --replace --labels "ubuntu-latest,self-hosted,${OS}-${RUNNER_ARCH}" --work "_work")
  echo "✓ runner 已配置（label: ubuntu-latest,self-hosted）"
fi

# 4. 运行（前台或 launchd 服务）
if [ "${RUNNER_SERVICE:-0}" = "1" ]; then
  PLIST="$HOME/Library/LaunchAgents/actions.runner.zhaokai-mgzn.migao.plist"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>actions.runner.zhaokai-mgzn.migao</string>
  <key>ProgramArguments</key>
  <array><string>${RUNNER_DIR}/run.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>${RUNNER_DIR}</string>
</dict></plist>
EOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  echo "✓ 已注册为 launchd 服务并启动（后台常驻）。停止：launchctl unload $PLIST"
else
  echo "▸ 前台运行（Ctrl+C 停止）；常驻请用 RUNNER_SERVICE=1"
  cd "$RUNNER_DIR" && ./run.sh
fi
