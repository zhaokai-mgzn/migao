#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# 线上「实际在跑什么」—— **只读**读取体（issue #4858）
#
# 为什么需要它：`deploy-reconcile.yml` 只看「main HEAD 的镜像在不在 + 该服务自上次成功部署
# 以来有没有改动」，**从不看运行中的容器实际是哪个 tag** ⇒ 两种形态无声无息：
#   ② 静默跳过：某服务镜像拉取失败 ⇒ 远端 `⚠️ 跳过该服务`，而整次部署仍报成功
#      （若某模块改了、镜像却没建 ⇒ 跳过 = **静默不交付**）；
#   ① 静默回退的事后对账（#4854 已拦住「发生」，但**事后**仍无人核对线上到底是哪个 commit）。
# 本文件只做一件事：把「线上真身」读出来，交给 `deploy/scripts/post-deploy-reconcile.sh` 判定。
#
# 🔴 只读红线（由 `tests/unit_ci_workflows/test_post_deploy_reconcile.py` 逐词钉住）：
#   本文件**只允许**出现查询类动词（compose 的 `ps`、`inspect`、`cat`、`command -v`）。
#   任何会改变线上状态的动词（容器启停/删除/拉取、镜像删除/清理、仓库登录/推送）一律禁止 ——
#   对账腿写的是**生产环境**，一次误写就是把「发现问题」变成「制造问题」。
#   这也是本文件独立成文（而不是内联进 workflow）的理由：同一份代码在 CI 侧拼成远端命令、
#   在本地沙箱复跑（守卫测试的行为级红证）、人工排障时手动执行 —— 内联会立刻造出
#   「测试测的是另一份实现」这个形态（同 `deploy/swas/h5-publish-remote.sh` 的理由）。
#
# 输出契约（**机器可读，逐行；CI 侧按前缀解析**）：
#   RECONCILE_HOST=<hostname>            RECONCILE_DATE=<utc>
#   RECONCILE_COMPOSE_DIR=<dir>          RECONCILE_DOCKER=<docker 路径 或 (absent)>
#   RECONCILE_LAST_GOOD_TAG=<tag 或空>
#   RUNNING_TAG=<compose 服务名>:<tag>   RUNNING_IMAGE=<svc>:<完整镜像引用>
#   RUNNING_STATE=<svc>:<running|exited|not-found|unknown>
# ⚠️ `RUNNING_TAG=<svc>:`（冒号后为空）= **读到了但读不出 tag**；整行缺失 = **没读到**。
#    两者在 CI 侧都判「判不出」+ `::warning::`（fail-open），**绝不**当作一致。
#
# 用法（远端由 CI 拼成命令内容；本地沙箱复跑直接 bash 本文件）：
#   bash deploy/swas/reconcile-read-remote.sh
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

COMPOSE_DIR=${RECONCILE_COMPOSE_DIR:-/opt/migao-deploy}
SERVICES=${RECONCILE_SERVICES:-admin-api ai-agent admin-web}

echo "RECONCILE_HOST=$(hostname 2>/dev/null || echo unknown)"
echo "RECONCILE_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)"
echo "RECONCILE_COMPOSE_DIR=$COMPOSE_DIR"
echo "RECONCILE_DOCKER=$(command -v docker 2>/dev/null || echo '(absent)')"

LAST_GOOD=""
if [ -f "$COMPOSE_DIR/.last-good-tag" ]; then
  LAST_GOOD=$(cat "$COMPOSE_DIR/.last-good-tag" 2>/dev/null || true)
fi
echo "RECONCILE_LAST_GOOD_TAG=${LAST_GOOD}"

# compose 文件在 $COMPOSE_DIR 下（`docker compose ps` 需要它）⇒ 读之前先定位；
# 定位不到也**不报错退出**：照常逐服务输出（CI 侧据此判「判不出」+ 告警，而不是静默无声）。
cd "$COMPOSE_DIR" 2>/dev/null || echo "RECONCILE_CD_FAIL=1"

for svc in $SERVICES; do
  cid=""
  if command -v docker >/dev/null 2>&1; then
    # `ps -q` 是**查询**（不带 -a ⇒ 只列在跑的容器）；取首行不用 `head`（pipefail 下 head 早退
    # 会让上游吃 SIGPIPE ⇒ 整条管道非零）
    cid=$(docker compose ps -q "$svc" 2>/dev/null || true)
  fi
  cid=${cid%%$'\n'*}
  if [ -z "$cid" ]; then
    echo "RUNNING_TAG=${svc}:"
    echo "RUNNING_IMAGE=${svc}:"
    echo "RUNNING_STATE=${svc}:not-found"
    continue
  fi
  img=$(docker inspect --format '{{.Config.Image}}' "$cid" 2>/dev/null || true)
  state=$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || true)
  echo "RUNNING_TAG=${svc}:${img##*:}"
  echo "RUNNING_IMAGE=${svc}:${img}"
  echo "RUNNING_STATE=${svc}:${state:-unknown}"
done

echo "RECONCILE_READ_DONE=1"
