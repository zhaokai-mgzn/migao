#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# prod-inspect.sh — 生产实例的**只读盘点**，一条命令（云助手通道；GitHub 不参与）
#
# ## 治什么（2026-11-23 用户裁定逐字「生产环境需要和 github 的能力解耦」）
#
# 生产现状是「发成半截」：2026-11-23 11:32–11:39 有一次**只更新 admin-api 的手工发布**
# （`admin-api=sha-26ff9f7` 起于 11-23 11:39，而 `admin-web=sha-caf01e4` 停在 11-21 22:52、
# `ai-agent=sha-0dced39` 停在 11-22 18:25）⇒ 三服务身份不自洽，**而当时没有任何东西会报**。
# 盘点的第一步因此不是「查日志」，而是**把现场固定成一段可复算的读数**。
#
# 这段读数此前是**手搓的**：每次要点开阿里云控制台 / 手打一串 `docker ps`、`df`、`nginx -T`。
# 手搓 = 每次口径都不一样 = 读数没法对比 ⇒ 本脚本把它固化成**固定只读命令集**。
#
# ## 通道（为什么不是 ssh、不是 GitHub）
#
#   部署机（`ssh migao-deploy`，Apple Silicon 那台）到生产实例的 **22 端口不通**（只对办公出口开放）、
#   **443 通** ⇒ 运维通道 = OpenAPI 云助手 `swas-open run-command`，凭证是**部署机本地**
#   `~/.aliyun/config.json` 的 `prod` profile（2026-11-23 裁定的「解耦钥匙」，不走 GitHub secret）。
#   通道实现只有一份：`scripts/lib/prod-swas-run.sh`（本脚本不自己拼 CLI）。
#
# ## 只读（结构性保证，不是纪律）
#
#   远端载荷**全部**落在 `# READONLY-PAYLOAD-BEGIN` / `# READONLY-PAYLOAD-END` 之间，
#   每条以 `sec <名字> '<命令>'` 给出；判据逐条拆开校验**首词必须在只读白名单内**
#   （`hostname/date/uptime/df/free/docker/cat/ls/du/nginx/crontab/systemctl` + 只读过滤器
#   `grep/sort/tail/head/awk/sed/cut/wc`），且**不许出现**任何写动词。
#   判据 = `tests/unit_ci_workflows/test_prod_release_decoupled.py::test_inspect_payload_is_readonly_whitelisted`
#
# ## 容量读数只作信息（2026-11-23 用户裁定「磁盘先不用管……可以依赖阿里云的能力」）
#
#   `df` / `free` / `docker system df` / `uptime` 是**给人看的现场**，**不参与**退出码：
#   资源面告警（磁盘 / 内存 / 连接数）未来走**阿里云云监控**，本脚本不自建阈值判据。
#
# ## 三态退出码（`3` 不当 `0` 读）
#
#   `0` 全部段都跑通 / `1` 有段失败（具名是哪一段）/ `3` **判不了**（CLI 缺、凭证缺、实例拿不到）
#
# ## 用法
#
#   bash scripts/prod-inspect.sh          # 全量只读盘点（打印 + 结尾 READONLY-INSPECT=…）
#   bash scripts/prod-inspect.sh --help
#
#   结尾行：`READONLY-INSPECT=OK` 或 `READONLY-INSPECT=INCOMPLETE failed=[…] missing=[…]`
#
# ## 注入点（判据用；沿用 `SERVED_VERSION_*` / `BMINI_GOLIVE_*` 先例）
#
#   MIGAO_PROD_ALIYUN_BIN / MIGAO_PROD_PYTHON_BIN / MIGAO_PROD_REGION / MIGAO_PROD_BIZ_REGION /
#   MIGAO_PROD_INSTANCE_ID / MIGAO_PROD_CRED_FILE / MIGAO_PROD_POLL_ATTEMPTS / MIGAO_PROD_POLL_INTERVAL
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

SELF_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$SELF_DIR/.." && pwd)

# shellcheck source=lib/prod-swas-run.sh
. "$ROOT/scripts/lib/prod-swas-run.sh"

# 盘点段名（与远端载荷一一对应；缺任何一段 ⇒ INCOMPLETE）
READONLY_SECTIONS="host disk_root disk_opt memory containers docker_df env_site deploy_dir deploy_usage nginx cron timers"

usage() {
  cat <<'USAGE'
用法：bash scripts/prod-inspect.sh [--help]

只读盘点生产实例（云助手通道；GitHub 不参与）。零写面：远端只跑只读命令集。
退出码：0 全成功 / 1 有段失败（具名）/ 3 判不了（CLI 缺、凭证缺、实例拿不到）
注入点（判据 / 排障）：MIGAO_PROD_ALIYUN_BIN / MIGAO_PROD_PYTHON_BIN / MIGAO_PROD_REGION /
  MIGAO_PROD_BIZ_REGION / MIGAO_PROD_INSTANCE_ID / MIGAO_PROD_CRED_FILE / MIGAO_PROD_POLL_ATTEMPTS
USAGE
}

# 远端脚本：**固定只读命令集**。每段用 sec 包一层，输出 @@SEC:名字@@ / @@END:名字@@ rc=N 标记，
# 段内失败**不**中断后面的段（盘点要一次看全，不要因为 nginx 抖一下就看不到 docker ps）。
build_remote_script() {
  cat <<'REMOTE'
set -u
sec() { printf '@@SEC:%s@@\n' "$1"; eval "$2" 2>&1; printf '@@END:%s@@ rc=%s\n' "$1" "$?"; }
# READONLY-PAYLOAD-BEGIN
sec host 'hostname; date -u +%FT%TZ; uptime'
sec disk_root 'df -h /'
sec disk_opt 'df -h /opt'
sec memory 'free -h'
sec containers "docker ps --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.CreatedAt}}'"
sec docker_df 'docker system df'
sec env_site 'cat /opt/migao-deploy/.env.site'
sec deploy_dir 'ls -l /opt/migao-deploy/ | head -30'
sec deploy_usage 'du -sh /opt/migao-deploy/* 2>/dev/null | sort -h | tail -10'
sec nginx "nginx -T 2>/dev/null | grep -E 'server_name|proxy_pass'"
sec cron 'crontab -l 2>&1; ls -l /etc/cron.d/ 2>&1'
sec timers 'systemctl list-timers --all --no-pager 2>&1 | head -40'
# READONLY-PAYLOAD-END
REMOTE
}

main() {
  case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    "") ;;
    *) echo "用法错误：未知参数 $1（--help 看用法）" >&2; exit 2 ;;
  esac

  prod_swas_init || exit 3

  echo "== 生产只读盘点（云助手 run-command；不经 GitHub / 不走 22 端口）=="
  echo "   实例 = ${PROD_INSTANCE_ID} · region = ${PROD_REGION} · CLI = ${PROD_ALIYUN_BIN}"
  echo "   口径 = 容量读数（df / free / docker system df / uptime）**只作信息**，不参与退出码"
  echo ""

  local decoded rc report summary failed missing ok_count
  decoded=$(prod_swas_run "$(build_remote_script)" "$PROD_REMOTE_TIMEOUT" migao-prod-inspect)
  rc=$?
  if [ "$rc" -eq 3 ]; then
    echo "READONLY-INSPECT=INCOMPLETE reason=通道判不了（见上面的不可判定文案）"
    exit 3
  fi

  # 渲染 + 统计（统计只看段标记，不看命令输出内容 ⇒ 输出里出现 "rc=" 也不会被误读）
  report=$(printf '%s' "$decoded" | "$PROD_PYTHON_BIN" -c '
import sys
want = sys.argv[1].split()   # 段名是空格分隔的一句话（与 READONLY_SECTIONS 同一份口径）
lines = sys.stdin.read().splitlines()
seen = {}
section = None
for line in lines:
    if line.startswith("@@SEC:"):
        section = line[len("@@SEC:"):].rstrip("@")
        print("\u2500\u2500 %s \u2500\u2500" % section)
    elif line.startswith("@@END:") and "@@ rc=" in line:
        name = line[len("@@END:"):line.index("@@ rc=")]
        seen[name] = line.rsplit("@@ rc=", 1)[1].strip()
        print("   [%s] rc=%s" % (name, seen[name]))
        section = None
    else:
        print(line)
failed = [n for n in want if n in seen and seen[n] != "0"]
missing = [n for n in want if n not in seen]
print("@@SUMMARY@@ failed=%s missing=%s ok=%d" % (",".join(failed), ",".join(missing), len(want) - len(failed)))
' "$READONLY_SECTIONS")
  summary=$(printf '%s\n' "$report" | grep '^@@SUMMARY@@' | tail -1)
  printf '%s\n' "$report" | grep -v '^@@SUMMARY@@'
  echo ""
  failed=$(printf '%s' "$summary" | sed -n 's/.*failed=\([^ ]*\) .*/\1/p')
  missing=$(printf '%s' "$summary" | sed -n 's/.*missing=\([^ ]*\) .*/\1/p')
  ok_count=$(printf '%s' "$summary" | sed -n 's/.*ok=\([0-9]*\)$/\1/p')

  # 远端整体退出码也是读数的一部分：段全绿但远端 rc≠0（例如 `InvocationStatus=Failed` 却没给 ExitCode）
  # ⇒ **不许**宣布 `OK`（实测形态：状态 Failed 时 `prod_swas_run` 退 1，段标记却可能都在）。
  if [ "$rc" -ne 0 ]; then
    echo "READONLY-INSPECT=INCOMPLETE remote_rc=${rc} failed=[${failed}] missing=[${missing}] —— 远端执行没干净收尾，不当通过" >&2
    exit 1
  fi
  if [ -z "$failed" ] && [ -z "$missing" ]; then
    echo "READONLY-INSPECT=OK sections=${ok_count} instance=${PROD_INSTANCE_ID}"
    exit 0
  fi
  echo "READONLY-INSPECT=INCOMPLETE failed=[${failed}] missing=[${missing}] —— 缺的段就是没看到的现场，不当通过" >&2
  exit 1
}

main "$@"
