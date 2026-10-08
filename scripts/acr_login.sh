#!/usr/bin/env bash
# ACR 登录的**唯一一份**实现（issue #6526 A）。所有 ACR 登录都必须走这里。
#
# 用法（密码**只**经 stdin 喂给 docker，一个字节都不经过命令行 / argv / 日志）：
#   bash scripts/acr_login.sh <registry> <username> <password> [--fatal]
#
# ## 病（issue #6526，逐条锚点）
# 修前四处调用点都是**未重试的 fail-fast 前置**（`echo "${{ secrets.ACR_PASSWORD }}" | docker login …`，
# 或 ai-agent 那处的 `--password` 命令行形态）：网络 RST / TLS 抖动**一次**就把整条部署腿打死 ——
# 而 C′（issue #5814）之后 **CI 不构建、不推 ACR**（自证步 = `deploy-frontend.yml` 的
# `Assert server-side build (no ACR push)`）⇒ CI 侧登录**已不承重**，却仍握着一票否决。
# 让一个不承重的步骤否决整条腿，正是本单要治的病。
#
# ## 两态（唯一接口差异就是末位那个 `--fatal`）
# | 态 | 调用点 | 3 次仍失败时 |
# |---|---|---|
# | **不承重**（默认） | `deploy-admin-api.yml` / `deploy-frontend.yml` / `deploy-ai-agent-service.yml` / `deploy-reconcile.yml` | 具名 `::warning::` + 关键 stderr 行 ⇒ **`exit 0`** |
# | **承重**（`--fatal`） | `bmini-h5-publish.yml`（把产物装进传输镜像、**真的推到 ACR**，登录是必要步骤） | 具名 `::error::` + 关键 stderr 行 ⇒ **非零退出** |
#
# 🔴 **重启条件（写在实现里，因为忘记它的代价就是本单的病复发）**：
# 若将来**恢复「CI 侧推 ACR」**（例如镜像私有化 / 重新把构建搬回 CI）⇒ 上面那 4 处必须
# **从「不承重」升回「承重」**（调用点加 `--fatal`）。届时不改会被判据抓住：
# `tests/unit_ci_workflows/test_acr_login_not_load_bearing.py` 对「哪条腿该带 `--fatal`」
# 是**双向**判据（该带的没带 ⇒ 红；不该带的带了 ⇒ 也红）⇒ 恢复推 ACR 时它强迫你回来改这一处。
#
# 判据＝同目录测试文件；红证＝照它的注入锚改一处即可（见该文件 §红证）。
set -uo pipefail

# ⚠️ 只有**入参不齐**才跳过；**文件不在检出里不是脚本能判的事**（脚本在被调时才存在）。
# 「helper 不在检出里」的弃权在**调用点**：`bmini-h5-publish.yml` 的调用步带
# `if: ${{ hashFiles('scripts/acr_login.sh') != '' }}`。其余四条腿的检出**没有** 那条
# 弃权 —— 它们原本就有裸 `docker login`，helper 落地后**同时**替换（同批），不存在中间态。

FATAL="no"
if [ "${4:-}" = "--fatal" ]; then FATAL="yes"; fi
REGISTRY="${1:-}"; USERNAME="${2:-}"; PASSWORD="${3:-}"
#: 单次尝试的墙钟上界（秒）。60s 的出处：`docker login` 到 cn-hangzhou 的 ACR 在实测里
#: 正常 **<2s**（本机与 runner 都如此）；60s 已远超「一次 TCP+TLS 握手 + 一次 token 交换」
#: 的量级 ⇒ 到了这个数就是**挂住**，再等只是把整条腿的预算喂给一个不承重的步骤。
#: 可复算：`time docker login <registry> ...` 本地正常路径读数。
ATTEMPT_TIMEOUT="${ACR_LOGIN_ATTEMPT_TIMEOUT_SECONDS:-60}"
MAX_ATTEMPTS=3

# 单次尝试的墙钟包裹器（**可移植**）：GNU coreutils 的 `timeout` 在 ubuntu runner 上有
# （CI 是 Linux），但 **macOS 本机没有**（实测：`command -v timeout` 在本机 = 空，只有
# `gtimeout` 且**本机也没装**）⇒ 硬调 `timeout` 会让「本机执行式判据」全数退化（`command not
# found` 被误读成「docker login 失败」，也就是说**判据本身在 macOS 上假红**）。
# ⇒ 有 `timeout` 用 `timeout`，有 `gtimeout` 用 `gtimeout`，都没有就**直跑 + 具名 warning**
# （诚实降级：上界在这一台上不存在，而不是假装有）。CI（ubuntu）走第一条分支。
TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then TIMEOUT_BIN="timeout"
elif command -v gtimeout >/dev/null 2>&1; then TIMEOUT_BIN="gtimeout"
else echo "::warning::本机没有 timeout/gtimeout（macOS 默认如此）⇒ 单次 ACR 登录**无墙钟上界**（CI 的 ubuntu runner 有，生产不受影响）"; fi

if [ -z "$REGISTRY" ] || [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
  echo "::warning::ACR 登录跳过：入参不齐（registry/username/password 任一为空）——凭据可能没下发到本 run（如 bot 触发）"
  exit 0
fi

i=1
while [ "$i" -le "$MAX_ATTEMPTS" ]; do
  # 密码走 stdin（`--password-stdin`）⇒ **绝不**出现在 argv / ps / 日志里；
  # `timeout` 保证单次尝试有上界（挂住的 docker login 会等到 job 的 timeout-minutes）。
  if [ -n "$TIMEOUT_BIN" ]; then
    err="$(printf '%s\n' "$PASSWORD" | "$TIMEOUT_BIN" "$ATTEMPT_TIMEOUT" docker login "$REGISTRY" -u "$USERNAME" --password-stdin 2>&1 >/dev/null)"
  else
    err="$(printf '%s\n' "$PASSWORD" | docker login "$REGISTRY" -u "$USERNAME" --password-stdin 2>&1 >/dev/null)"
  fi
  # ⚠️ `$?` 必须**当场**存下：赋值是两个命令组成的列表，紧随其后的 `[` 会把它读成 0
  #（`local`/赋值语句永远返回 0）⇒ 「失败」会被静默读成「成功」（本文件首版的真缺陷）。
  rc=$?
  if [ "$rc" = "0" ]; then
    echo "✅ ACR 登录成功：${REGISTRY}（第 ${i}/${MAX_ATTEMPTS} 次尝试）"
    exit 0
  fi
  # 关键 stderr 行（最多 3 行）—— 不吞信息，但也不把整段刷进日志。
  echo "⚠️ ACR 登录第 ${i}/${MAX_ATTEMPTS} 次失败（registry=${REGISTRY}）："
  printf '%s\n' "$err" | tail -n 3 | sed 's/^/    /'
  if [ "$i" -lt "$MAX_ATTEMPTS" ]; then
    # 退避 5s / 10s：网络 RST / 短暂 5xx 的恢复窗口；总代价上界 = 3×60 + 15 = 195s。
    if [ "$i" = "1" ]; then sleep 5; else sleep 10; fi
  fi
  i=$((i + 1))
done

if [ "$FATAL" = "yes" ]; then
  # 承重态：这条腿**真的在用 ACR**（推传输镜像）⇒ 登录不上 = 这条腿必然做不成 ⇒ 必须判红。
  echo "::error::ACR 登录失败（承重调用点，已重试 $MAX_ATTEMPTS 次）：$REGISTRY —— 本步依赖 ACR，判红"
  exit 1
fi

# 不承重态（issue #6526 A 的承重判据）：C′（#5814）之后 CI **不构建、不推 ACR**
# （自证步 = `deploy-frontend.yml` 的 `Assert server-side build (no ACR push)`；构建在服务器侧
# `deploy/scripts/swas-deploy-ci.sh` 的 docker build）⇒ 这个登录的**唯一**用途是让下游
# `docker manifest inspect` 之类的只读探测不至于因未登录而失败，它**不能**决定这条腿的成败。
# ⇒ `exit 0`（非致命）：三条部署腿 + 对账腿继续跑，失败以具名 `::warning::` 留在日志里。
echo "::warning::ACR 登录失败（$MAX_ATTEMPTS 次尝试后仍失败，非致命）：$REGISTRY —— 本步不承重（C′ 后 CI 不推 ACR），已按 issue #6526 A 降级为告警、不判红；若将来恢复 CI 侧推 ACR 必须改回 --fatal"
exit 0
