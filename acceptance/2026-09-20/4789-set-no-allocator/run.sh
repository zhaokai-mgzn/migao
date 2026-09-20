#!/usr/bin/env bash
# #4789 端到端真库判据（**本地 PG 16**，因为云 dev RDS 对本机间歇不可达 —— 见 recon.sh 的 8 次重试读数）。
#
# 做三件事，全部对着**真库**（不是 mock）：
#   ① 用 V92 / schema.sql 的**逐字 DDL** 建 processing_order_sets / processing_set_part_tokens；
#   ② 跑 `ProcessingOrderSetMapper` / `ProcessingSetPartTokenMapper` 的**逐字 SQL**（含 ON CONFLICT 谓词）；
#   ③ 跑「生产明细页二维码按钮 → 工人 H5 扫一扫」那条链路的**服务端读面 SQL**：
#      `ProductionScanService.selectionView` 的套清单查询 + `listSetOperations` 的实例行查询。
#
# 用法：
#   ./run.sh              # 分配器已落码（绿）
#   ./run.sh --no-alloc   # 不跑分配器（= 改前状态：新单无套行）⇒ 用于取红证
set -uo pipefail

SOCK=/tmp/pg4789sock
PORT=55440
DB=mig4789_e2e
ROOT="/Users/guangzhen.zk/ai native/migao-wt/set-no-allocator-4789"
SCHEMA="$ROOT/docs/sql/schema.sql"
ALLOC=1
[[ "${1:-}" == "--no-alloc" ]] && ALLOC=0

export PGHOST="$SOCK" PGPORT="$PORT" PGUSER=postgres
psql -q -d postgres -c "DROP DATABASE IF EXISTS $DB;" -c "CREATE DATABASE $DB;" >/dev/null

# ── 前置表：逐字取自 docs/sql/schema.sql（只保留本判据用到的列；去掉 FK/RLS 以免引入无关噪声）──
psql -q -v ON_ERROR_STOP=1 -d "$DB" <<'SQL' >/dev/null
CREATE TABLE tenants (
    id BIGINT PRIMARY KEY, name VARCHAR(128), deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE processing_orders (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL, processing_order_no VARCHAR(32) NOT NULL,
    items_snapshot JSONB, qr_token VARCHAR(64), deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE order_items (
    id VARCHAR(36) PRIMARY KEY, tenant_id BIGINT NOT NULL, order_id VARCHAR(64) NOT NULL,
    processing_info JSONB, deleted INTEGER NOT NULL DEFAULT 0);
SQL

# ── ①② 逐字取自 schema.sql（= V92 终态）：套号载体 + 部位码载体 ──
# ⚠️ 必须带 `-v ON_ERROR_STOP=1` 且**校验 DDL 真的建成**：本单已踩过「DDL 没建成 ⇒ 后面 INSERT 全失败
# ⇒ 查询返回 0 行」被读成「判据红」的坑（**红得对不上原因**）。fail-fast 让「表不存在」长得像它自己。
sed -n '1105,1146p' "$SCHEMA" > /tmp/e2e4789_ddl.sql
echo "DDL 抽取自检：processing_order_sets=$(grep -c 'CREATE TABLE IF NOT EXISTS processing_order_sets' /tmp/e2e4789_ddl.sql) uk_set_part_tokens_part=$(grep -c 'CREATE UNIQUE INDEX IF NOT EXISTS uk_set_part_tokens_part' /tmp/e2e4789_ddl.sql)"
psql -q -v ON_ERROR_STOP=1 -d "$DB" -f /tmp/e2e4789_ddl.sql >/dev/null || {
  echo "❌ DDL 未建成（判据前置失败，不是业务红）"; exit 3; }

# ── 工序实例表（只保留本判据的列：V92 加的 set_id / set_no + 既有定位列）──
psql -q -v ON_ERROR_STOP=1 -d "$DB" <<'SQL' >/dev/null
CREATE TABLE processing_position_operations (
    id VARCHAR(64) PRIMARY KEY, tenant_id BIGINT NOT NULL, processing_order_id VARCHAR(64) NOT NULL,
    position_name VARCHAR(128), order_item_id VARCHAR(36), position_kind VARCHAR(16),
    seq INT, operation_name VARCHAR(128), status VARCHAR(16) DEFAULT 'pending',
    set_id VARCHAR(64), set_no VARCHAR(64), deleted INTEGER NOT NULL DEFAULT 0);
SQL

# ── 造一樘「布 + 纱 + 帘头」（同 craftLineId=cl-A，3 条 order_items 行 = 3 个部位 = **1 套**）──
psql -q -v ON_ERROR_STOP=1 -d "$DB" <<'SQL' >/dev/null
INSERT INTO tenants (id, name) VALUES (1, '词元通达');
INSERT INTO processing_orders (id, tenant_id, processing_order_no, items_snapshot, qr_token)
VALUES ('po-4789', 1, 'JG-20260920-0001',
        '[{"itemId":"i-1","craftLineId":"cl-A","processingItems":[{"name":"韩褶"}]},
          {"itemId":"i-2","craftLineId":"cl-A","componentRole":"纱","processingItems":[{"name":"韩褶"}]},
          {"itemId":"i-3","craftLineId":"cl-A","processingItems":[{"name":"韩褶"}]},
          {"itemId":"i-9","processingItems":[{"name":"韩褶"}]}]'::jsonb,
        'tok-old-4789');
INSERT INTO order_items (id, tenant_id, order_id, processing_info) VALUES
  ('i-1', 1, 'order-4789', '{"craftLineId":"cl-A"}'::jsonb),
  ('i-2', 1, 'order-4789', '{"craftLineId":"cl-A"}'::jsonb),
  ('i-3', 1, 'order-4789', '{"craftLineId":"cl-A"}'::jsonb),
  ('i-9', 1, 'order-4789', '{}'::jsonb);
SQL

if [[ $ALLOC -eq 1 ]]; then
  echo "════ ① 分配器（ProcessingOrderSetMapper 的逐字 SQL；2 樘窗 ⇒ 2 行套）════"
  psql -v ON_ERROR_STOP=1 -d "$DB" <<'SQL'
INSERT INTO processing_order_sets
    (id, tenant_id, processing_order_id, set_index, set_no, craft_line_id,
     position_item_ids, created_at, updated_at, deleted)
VALUES ('set-1', 1, 'po-4789', 1, 'JG-20260920-0001-001', 'cl-A',
        CAST('["i-1","i-2","i-3"]' AS jsonb), NOW(), NOW(), 0)
ON CONFLICT (tenant_id, processing_order_id, set_index) WHERE deleted = 0 DO NOTHING;
INSERT INTO processing_order_sets
    (id, tenant_id, processing_order_id, set_index, set_no, craft_line_id,
     position_item_ids, created_at, updated_at, deleted)
VALUES ('set-2', 1, 'po-4789', 2, 'JG-20260920-0001-002', 'i-9',
        CAST('["i-9"]' AS jsonb), NOW(), NOW(), 0)
ON CONFLICT (tenant_id, processing_order_id, set_index) WHERE deleted = 0 DO NOTHING;
SELECT set_index, set_no, craft_line_id, position_item_ids FROM processing_order_sets
 WHERE processing_order_id = 'po-4789' AND deleted = 0 ORDER BY set_index;

\echo '--- 幂等：同一条再插一次（必须仍 2 行）---'
INSERT INTO processing_order_sets
    (id, tenant_id, processing_order_id, set_index, set_no, craft_line_id,
     position_item_ids, created_at, updated_at, deleted)
VALUES ('set-1-again', 1, 'po-4789', 1, 'JG-20260920-0001-001', 'cl-A',
        CAST('["i-1","i-2","i-3"]' AS jsonb), NOW(), NOW(), 0)
ON CONFLICT (tenant_id, processing_order_id, set_index) WHERE deleted = 0 DO NOTHING;
SELECT count(*) AS live_sets_after_repeat FROM processing_order_sets
 WHERE processing_order_id = 'po-4789' AND deleted = 0;

\echo '--- 实例行落 set_id / set_no（按 position_item_ids 归属；V92 的回填 UPDATE 同形）---'
INSERT INTO processing_position_operations
    (id, tenant_id, processing_order_id, position_name, order_item_id, position_kind, seq, operation_name)
VALUES ('op-1', 1, 'po-4789', '布艺遮光帘A', 'i-1', '布帘', 1, '精裁-布'),
       ('op-2', 1, 'po-4789', '纱帘A',       'i-2', '纱帘', 1, '精裁-纱'),
       ('op-3', 1, 'po-4789', '帘头A',       'i-3', '帘头', 1, '精裁-帘头'),
       ('op-9', 1, 'po-4789', '独立窗',      'i-9', '布帘', 1, '精裁-布');
UPDATE processing_position_operations o
   SET set_id = s.id, set_no = s.set_no
  FROM processing_order_sets s
 WHERE s.processing_order_id = o.processing_order_id
   AND s.tenant_id = o.tenant_id AND s.deleted = 0 AND o.deleted = 0
   AND o.order_item_id IS NOT NULL AND o.set_id IS DISTINCT FROM s.id
   AND s.position_item_ids @> to_jsonb(o.order_item_id);
SELECT order_item_id, set_id, set_no FROM processing_position_operations
 WHERE processing_order_id = 'po-4789' ORDER BY order_item_id;

\echo '--- 部位码（ProcessingSetPartTokenMapper 的逐字 SQL；一部位一码 + 复用不换码）---'
INSERT INTO processing_set_part_tokens
    (id, tenant_id, processing_order_id, set_id, order_item_id, position_kind,
     token, print_count, created_at, updated_at, deleted)
VALUES ('pt-1', 1, 'po-4789', 'set-1', 'i-1', '布帘', 'tok-i1', 0, NOW(), NOW(), 0),
       ('pt-2', 1, 'po-4789', 'set-1', 'i-2', '纱帘', 'tok-i2', 0, NOW(), NOW(), 0),
       ('pt-3', 1, 'po-4789', 'set-1', 'i-3', '帘头', 'tok-i3', 0, NOW(), NOW(), 0),
       ('pt-9', 1, 'po-4789', 'set-2', 'i-9', '布帘', 'tok-i9', 0, NOW(), NOW(), 0)
ON CONFLICT (tenant_id, set_id, order_item_id) WHERE deleted = 0 DO NOTHING;
INSERT INTO processing_set_part_tokens
    (id, tenant_id, processing_order_id, set_id, order_item_id, position_kind,
     token, print_count, created_at, updated_at, deleted)
VALUES ('pt-1-again', 1, 'po-4789', 'set-1', 'i-1', '布帘', 'tok-DIFFERENT', 0, NOW(), NOW(), 0)
ON CONFLICT (tenant_id, set_id, order_item_id) WHERE deleted = 0 DO NOTHING;
SELECT set_id, order_item_id, token FROM processing_set_part_tokens
 WHERE processing_order_id = 'po-4789' AND deleted = 0 ORDER BY set_id, order_item_id;
SQL
fi

echo
echo "════ ② 工人 H5 扫一扫：服务端读面 SQL（ProductionScanService 的逐字查询）════"
psql -v ON_ERROR_STOP=1 -d "$DB" <<'SQL'
\echo '--- 扫码解析入口：既有四形态之一（qr_token）解析到加工单 ---'
SELECT id, processing_order_no FROM processing_orders
 WHERE tenant_id = 1 AND qr_token = 'tok-old-4789' AND deleted = 0;

\echo '--- selectionView：该单的「套 × 部位」可选清单（**新单此前这里是空的**）---'
SELECT s.set_no, s.set_index, o.order_item_id, o.position_kind
  FROM processing_order_sets s
  LEFT JOIN processing_position_operations o
         ON o.set_id = s.id AND o.deleted = 0
 WHERE s.processing_order_id = 'po-4789' AND s.tenant_id = 1 AND s.deleted = 0
 ORDER BY s.set_index, o.order_item_id;

\echo '--- 套数（1 樘「布+纱+帘头」= 1 套；另一樘独立窗 = 1 套 ⇒ 共 2）---'
SELECT count(*) AS live_sets FROM processing_order_sets
 WHERE processing_order_id = 'po-4789' AND deleted = 0;

\echo '--- 新码（部位码）直扫：token → 套 × 部位（第一优先形态）---'
SELECT t.token, s.set_no, t.order_item_id, t.position_kind
  FROM processing_set_part_tokens t JOIN processing_order_sets s ON s.id = t.set_id
 WHERE t.token = 'tok-i2' AND t.deleted = 0;

\echo '--- 反例（不许恒真）：不存在/已撤销的 token 必须 0 行 ---'
SELECT count(*) AS rows_for_revoked_token FROM processing_set_part_tokens
 WHERE token = 'tok-NOT-EXIST' AND deleted = 0;
SQL
echo "exit=$?"
