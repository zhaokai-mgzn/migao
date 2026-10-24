#!/usr/bin/env bash
# ============================================================================
# 生产环境「建站脚本」：一次跑完 = 建库 + 建表 + 索引 + RLS + 初始化数据 + 活迁移 + 自检
# ----------------------------------------------------------------------------
# 唯一真值源仍是 `backend/admin-api/src/main/resources/db/init/schema.sql`
# （表 + 索引 + RLS + 终态种子）与 `db/migration/V*.sql`（切点之后的增量）。
# 本脚本**不复制任何 DDL**：它只负责「顺序 + 前置检查 + 失败即停 + 跑完自证」。
# 这与 `docs/wiki/Database.md` 的「唯一建库脚本」口径一致（两份真相是本仓最忌讳的形态）。
#
# 用法：
#   PGHOST=... PGPORT=5432 PGDATABASE=migao PGPASSWORD=... \
#     ./deploy/init/prod-bootstrap.sh --yes
#
# 选项：
#   --yes             非交互确认（CI / 运维脚本里必须显式给）
#   --allow-existing  目标库已初始化过（`tenants` 表存在）时，**只补跑活迁移**，不重建
#   --dry-run         只打印将要执行的动作与目标库状态，不写任何东西
#
# 环境变量（都可省，省略则用 psql 默认/本地 socket）：
#   PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD
#
# 🔴 安全性（为什么这么设计）：
#   1. **不 drop 任何东西**：库/表已存在 ⇒ 默认**拒绝**（不做「静默重建」）；
#   2. **失败即停**：每一步 `ON_ERROR_STOP=1`，与 `MigrationRunner` 的「内容类失败只跳过」
#      不同 —— 建站是一次性动作，半成品站点比「明确报错」危险得多；
#   3. **跑完自证**：表数 / 关键索引 / 种子租户三项**现取**，不写死行数也不假设成功；
#   4. **不清理**：不删历史数据、不删旧索引（那些是迁移的职责）。
# ============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCHEMA="$REPO_ROOT/backend/admin-api/src/main/resources/db/init/schema.sql"
MIGRATION_DIR="$REPO_ROOT/backend/admin-api/src/main/resources/db/migration"

ASSUME_YES=0
ALLOW_EXISTING=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --yes) ASSUME_YES=1 ;;
    --allow-existing) ALLOW_EXISTING=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "未知参数：${arg}（--help 看用法）" >&2; exit 2 ;;
  esac
done

log()  { printf '[bootstrap] %s\n' "$*"; }
fail() { printf '[bootstrap] ❌ %s\n' "$*" >&2; exit 1; }

command -v psql >/dev/null 2>&1 || fail "找不到 psql（PostgreSQL 客户端）"
[ -f "$SCHEMA" ] || fail "找不到建库脚本：$SCHEMA"
[ -d "$MIGRATION_DIR" ] || fail "找不到活迁移目录：$MIGRATION_DIR"

PSQL_TARGET=(psql -v ON_ERROR_STOP=1 -X -q)
Q() { "${PSQL_TARGET[@]}" -tAc "$1"; }

# ── 迁移台账（与 MigrationRunner 同一张表、同一形态，见 MigrationRunner#ensureHistoryTable）──
# 为什么要共用：`--allow-existing` 必须知道「哪些迁移已经跑过」，否则数据迁移（如 V129）重跑会
# 自己判红并回滚。两套台账 = 两份真相 ⇒ 直接复用 `schema_migrations`。
ledger_init() {
  PGDATABASE="$DB_NAME" "${PSQL_TARGET[@]}" -c "
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version VARCHAR(255) PRIMARY KEY,
        applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW())" >/dev/null
}
# 文件名来自本仓 `db/migration/`（受控、不含单引号）⇒ 直接内联，不做转义
ledger_has() {
  [ -n "$(PGDATABASE="$DB_NAME" Q "SELECT 1 FROM schema_migrations WHERE version = '$1'")" ]
}
ledger_record() {
  PGDATABASE="$DB_NAME" "${PSQL_TARGET[@]}" -c \
    "INSERT INTO schema_migrations (version) VALUES ('$1') ON CONFLICT DO NOTHING" >/dev/null
}

DB_NAME="${PGDATABASE:-ai_customer_service}"

# ── 0. 前置读取（只读）──────────────────────────────────────────────────────
log "目标：host=${PGHOST:-<socket>} port=${PGPORT:-5432} db=${DB_NAME} user=${PGUSER:-<default>}"
PGDATABASE=postgres Q "SELECT 1" >/dev/null 2>&1 || fail "连不上 PostgreSQL（先确认 PGHOST/PGPORT/PGUSER/PGPASSWORD）"

DB_EXISTS="$(PGDATABASE=postgres Q "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'")"
TABLES_EXIST=""
if [ -n "$DB_EXISTS" ]; then
  TABLES_EXIST="$(PGDATABASE="$DB_NAME" Q "SELECT to_regclass('public.tenants') IS NOT NULL")"
fi

log "库存在=${DB_EXISTS:-0}｜已建过表=${TABLES_EXIST:-f}"

if [ "$TABLES_EXIST" = "t" ] && [ "$ALLOW_EXISTING" -eq 0 ]; then
  fail "目标库已经初始化过（tenants 表存在）。本脚本**不重建**任何东西。
        · 只想补跑活迁移 ⇒ 加 --allow-existing
        · 想确认状态     ⇒ 加 --dry-run
        · 想重建         ⇒ 由人显式 drop 库/表后再跑（本脚本不替你做破坏性动作）"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  log "dry-run：将执行 ——"
  log "  1) $([ -n "$DB_EXISTS" ] && echo '库已存在（跳过 CREATE DATABASE）' || echo "CREATE DATABASE $DB_NAME")"
  log "  2) $([ "$TABLES_EXIST" = "t" ] && echo '建库脚本（跳过：已初始化）' || echo "psql -f $SCHEMA")"
  log "  3) 依次执行活迁移 $(ls "$MIGRATION_DIR"/V*.sql 2>/dev/null | wc -l | tr -d ' ') 条"
  log "  4) 自检（表数 / 关键索引 / 种子租户）"
  exit 0
fi

if [ "$ASSUME_YES" -eq 0 ]; then
  if [ ! -t 0 ]; then
    fail "非交互环境必须显式给 --yes（避免在 CI/管道里误建库）"
  fi
  printf '[bootstrap] 即将在 %s 上建站（库=%s）。继续？[y/N] ' "${PGHOST:-socket}" "$DB_NAME"
  read -r answer
  [ "$answer" = "y" ] || [ "$answer" = "Y" ] || fail "已取消"
fi

# ── 1. 建库（仅当不存在）────────────────────────────────────────────────────
if [ -z "$DB_EXISTS" ]; then
  log "创建数据库 $DB_NAME"
  PGDATABASE=postgres "${PSQL_TARGET[@]}" -c "CREATE DATABASE \"${DB_NAME}\"" >/dev/null
else
  log "库已存在，跳过 CREATE DATABASE"
fi

ledger_init
ledger_rows="$(PGDATABASE="$DB_NAME" Q "SELECT COUNT(*) FROM schema_migrations")"
if [ "$TABLES_EXIST" = "t" ] && [ "${ledger_rows:-0}" -eq 0 ]; then
  fail "库已初始化，但迁移台账（schema_migrations）是空的 ⇒ **无法判定**哪些迁移已经跑过。
        · 先让 admin-api 启动一次（MigrationRunner 会把已应用的迁移记进台账），再回来跑 --allow-existing
        · 或在确认可以重放的前提下，由人显式给库做快照后手动处理（本脚本不替你猜）"
fi

# ── 2. 建库脚本（表 + 索引 + RLS + 终态种子）───────────────────────────────
if [ "$TABLES_EXIST" = "t" ]; then
  log "已初始化过 ⇒ 只补跑活迁移（--allow-existing）"
else
  log "执行建库脚本（${SCHEMA}）"
  PGDATABASE="$DB_NAME" "${PSQL_TARGET[@]}" -f "$SCHEMA"
  # 与 MigrationRunner 的基线语义一致：台账键 = 建库脚本的文件名（schema.sql）
  ledger_record "schema.sql"
fi

# ── 3. 活迁移（按**数值**版本号排序，不是字典序）───────────────────────────
log "执行活迁移"
# ⚠️ 路径里可能有空格（本仓工作区叫 `ai native`）⇒ 必须按行读，不能 `for f in $list` 词分割
count=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  name="$(basename "$f")"
  if ledger_has "$name"; then
    printf '[bootstrap]   · %s（台账已有，跳过）\n' "$name"
    continue
  fi
  printf '[bootstrap]   · %s\n' "$name"
  PGDATABASE="$DB_NAME" "${PSQL_TARGET[@]}" -f "$f"
  ledger_record "$name"
  count=$((count + 1))
done < <(ls "$MIGRATION_DIR"/V*.sql | sed 's|.*/V\([0-9]*\)__.*|\1 &|' | sort -n | cut -d' ' -f2-)
log "活迁移完成：$count 条"

# ── 4. 自检（**从 schema.sql 现取期望集合**，不写死数字/名字）────────────────
# 为什么现取：写死「表数 ≥ 80」会在表数变化时误报/漏报；写死索引清单会在 cut 之外的分支上
# 误报（如本脚本与 V170 索引不在同一条分支时）。这里只问一个问题：
# 「建库脚本声明的每一个表/索引，在库里**真的**存在吗？」
log "自检"

# 剥掉 SQL 注释再抽名字（schema.sql 里有「已删除的索引」这类说明性注释）
strip_comments() { sed -E 's/--.*$//' "$SCHEMA"; }

expected_tables="$(strip_comments | grep -oE 'CREATE TABLE (IF NOT EXISTS )?[a-z0-9_]+' \
  | sed -E 's/CREATE TABLE (IF NOT EXISTS )?//' | sort -u)"
expected_indexes="$(strip_comments | grep -oE 'CREATE (UNIQUE )?INDEX (IF NOT EXISTS )?[a-z0-9_]+' \
  | sed -E 's/CREATE (UNIQUE )?INDEX (IF NOT EXISTS )?//' | sort -u)"

[ -n "$expected_tables" ] || fail "自检失败：没能从 $SCHEMA 抽出任何表名（脚本/文件漂移了）"
[ -n "$expected_indexes" ] || fail "自检失败：没能从 $SCHEMA 抽出任何索引名（脚本/文件漂移了）"

sql_array() { printf "'%s'," $1 | sed 's/,$//'; }

missing_tables="$(PGDATABASE="$DB_NAME" "${PSQL_TARGET[@]}" -tAc "
  SELECT string_agg(x, ', ') FROM unnest(ARRAY[$(sql_array "$expected_tables")]) AS x
   WHERE to_regclass('public.' || x) IS NULL")"
missing_indexes="$(PGDATABASE="$DB_NAME" "${PSQL_TARGET[@]}" -tAc "
  SELECT string_agg(x, ', ') FROM unnest(ARRAY[$(sql_array "$expected_indexes")]) AS x
   WHERE to_regclass('public.' || x) IS NULL")"

table_count="$(PGDATABASE="$DB_NAME" Q "SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r'")"
index_count="$(PGDATABASE="$DB_NAME" Q "SELECT COUNT(*) FROM pg_indexes WHERE schemaname='public'")"
tenant_count="$(PGDATABASE="$DB_NAME" Q "SELECT COUNT(*) FROM tenants")"

[ -z "$missing_tables" ]  || fail "自检失败：建库脚本声明的表在库里缺失 → $missing_tables"
[ -z "$missing_indexes" ] || fail "自检失败：建库脚本声明的索引在库里缺失 → $missing_indexes"
[ "$tenant_count" -ge 1 ] || fail "自检失败：租户种子没落库（tenants=0）"

log "✅ 建站完成：表=${table_count}（声明 $(printf '%s\n' "$expected_tables" | wc -l | tr -d ' ') 张）｜索引=${index_count}｜租户=$tenant_count"
log "下一步（都要显式做，脚本不替你做）："
log "  · 改首个租户信息：UPDATE tenants SET name='<企业名>', code='<企业编码>' WHERE id=1;"
log "  · 建管理员：由后台初始化/入驻流程完成（不要手工塞 password_hash）"
log "  · 保留期：按 ops 手册人工执行 deploy/ops/db-retention.sql（默认只读 count）"
