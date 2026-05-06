"""
PostgreSQL Row Level Security (RLS) 策略验证测试

验证目标:
  - 所有业务表的 RLS 策略是否正确启用
  - 设置 app.current_tenant_id 后查询仅返回对应租户数据
  - 未设置 tenant_id 时查询返回空结果
  - 跨租户 INSERT / UPDATE / DELETE 被 RLS 阻止
  - 同一连接切换 tenant_id 后数据隔离仍然有效

依赖:
  - 需要实际运行的 PostgreSQL 15 实例
  - 数据库已执行 001_init.sql, 002_complete_tables.sql, 003_orders.sql
  - 连接用户（app_user）不是超级用户且不是表 owner（否则 RLS 不生效）
"""

import os
import re
from typing import List, Union

import pytest
import asyncpg

# ---------------------------------------------------------------------------
# Helper: 从 .env 或环境变量获取 asyncpg 可用的数据库 URL
# ---------------------------------------------------------------------------

def _get_asyncpg_dsn() -> str:
    """
    读取 DATABASE_URL 并转换为 asyncpg 可用的 DSN。
    SQLAlchemy 格式: postgresql+asyncpg://...  → asyncpg 格式: postgresql://...
    """
    dsn = os.environ.get("DATABASE_URL", "")

    # 如果环境变量未设置，尝试从 .env 文件读取
    if not dsn:
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DATABASE_URL="):
                        dsn = line.split("=", 1)[1].strip()
                        break

    if not dsn:
        return ""

    # 去掉 SQLAlchemy 驱动后缀 "+asyncpg"
    dsn = re.sub(r"^postgresql\+asyncpg://", "postgresql://", dsn)
    return dsn


DATABASE_DSN = _get_asyncpg_dsn()

# 如果无法获取数据库 URL，则跳过整个模块
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_DSN, reason="DATABASE_URL 未配置，跳过 RLS 集成测试"),
]


# ---------------------------------------------------------------------------
# 所有启用了 RLS 且带 tenant_id 列的业务表（不含 tenants 自身，其策略特殊）
# ---------------------------------------------------------------------------

RLS_TABLES: List[str] = [
    # 001_init.sql
    "users",
    "roles",
    "permissions",
    "user_roles",
    "user_identities",
    "categories",
    "products",
    "processing_categories",
    "processing_items",
    "knowledge_documents",
    "rag_chunks",
    "tenant_apps",
    "agent_employees",
    "sessions",
    "session_messages",
    "after_sales_tickets",
    "tenant_ai_configs",
    # 002_complete_tables.sql
    "processing_rules",
    "customer_profiles",
    "ticket_timeline",
    "ticket_notes",
    "audit_logs",
    "notification_templates",
    "notification_rules",
    "notifications",
    "customer_tags",
    "customer_segments",
    "customer_segment_members",
    "knowledge_sync_history",
    # 003_orders.sql
    "orders",
    "order_items",
    "order_logistics",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def conn():
    """
    获取一个 asyncpg 数据库连接。
    每个测试用例使用独立连接，测试结束后关闭。
    """
    connection = await asyncpg.connect(DATABASE_DSN)
    try:
        yield connection
    finally:
        await connection.close()


async def _set_tenant(conn: asyncpg.Connection, tenant_id: Union[int, str]) -> None:
    """在连接上设置当前租户 ID（模拟应用层行为）"""
    await conn.execute(f"SET app.current_tenant_id = '{tenant_id}'")


async def _check_rls_effective(conn: asyncpg.Connection, table_name: str) -> bool:
    """
    检测 RLS 策略是否对当前连接生效。
    RLS 不对表 owner 和 superuser 生效（除非启用 FORCE ROW LEVEL SECURITY）。
    """
    row = await conn.fetchrow(
        "SELECT relrowsecurity, relforcerowsecurity, relowner "
        "FROM pg_class WHERE relname = $1",
        table_name,
    )
    if not row or not row['relrowsecurity']:
        return False
    # FORCE RLS 启用时，所有角色都受 RLS 约束
    if row['relforcerowsecurity']:
        return True
    # 检查 superuser
    is_superuser = await conn.fetchval("SELECT current_setting('is_superuser')")
    if is_superuser == 'on':
        return False
    # 检查是否为表 owner
    current_role_oid = await conn.fetchval(
        "SELECT oid FROM pg_roles WHERE rolname = current_user"
    )
    if current_role_oid == row['relowner']:
        return False
    return True


async def _reset_tenant(conn: asyncpg.Connection) -> None:
    """重置当前租户 ID 为空字符串"""
    await conn.execute("RESET app.current_tenant_id")


async def _get_existing_tenant_ids(conn: asyncpg.Connection) -> List[int]:
    """
    查询数据库中已有的租户 ID 列表。
    tenants 表的 RLS 策略允许 current_tenant_id 为空时读取，所以先设为空。
    """
    # tenants 表策略: id::text = current_setting(...) OR current_setting(...) = ''
    await _set_tenant(conn, "")
    rows = await conn.fetch("SELECT id FROM tenants ORDER BY id LIMIT 10")
    return [row["id"] for row in rows]


# ---------------------------------------------------------------------------
# 1. 基础 RLS 验证
# ---------------------------------------------------------------------------

class TestRLSBasicIsolation:
    """基础租户隔离验证"""

    async def test_rls_query_with_tenant_1_returns_only_tenant_1_data(self, conn):
        """
        验证: 设置 tenant_id=1 后，查询任意业务表仅返回 tenant_id=1 的数据。
        使用 products 表作为代表进行验证。
        """
        tenant_ids = await _get_existing_tenant_ids(conn)
        if 1 not in tenant_ids:
            pytest.skip("数据库中不存在 tenant_id=1，跳过测试")

        await _set_tenant(conn, 1)
        # 查询 products 表，验证所有返回行的 tenant_id 均为 1
        rows = await conn.fetch("SELECT tenant_id FROM products")
        if not rows:
            pytest.skip("products 表中 tenant_id=1 无数据，跳过验证")
        for row in rows:
            assert row["tenant_id"] == 1, (
                f"RLS 泄漏: 期望 tenant_id=1，实际返回 tenant_id={row['tenant_id']}"
            )

    async def test_rls_query_with_tenant_2_returns_only_tenant_2_data(self, conn):
        """
        验证: 设置 tenant_id=2 后，查询仅返回 tenant_id=2 的数据。
        如果租户 2 不存在则跳过。
        """
        tenant_ids = await _get_existing_tenant_ids(conn)
        if 2 not in tenant_ids:
            pytest.skip("数据库中不存在 tenant_id=2，跳过测试")

        await _set_tenant(conn, 2)
        rows = await conn.fetch("SELECT tenant_id FROM products")
        if not rows:
            pytest.skip("products 表中 tenant_id=2 无数据，跳过验证")
        for row in rows:
            assert row["tenant_id"] == 2, (
                f"RLS 泄漏: 期望 tenant_id=2，实际返回 tenant_id={row['tenant_id']}"
            )

    async def test_rls_query_without_tenant_setting_returns_empty(self, conn):
        """
        验证: 未设置 app.current_tenant_id（或 RESET 后），
        current_setting 默认抛出错误或返回空，导致查询结果为空。

        注意: PostgreSQL 中如果 GUC 变量未设置，current_setting() 会抛错，
        除非设置了 missing_ok 参数。RLS USING 表达式直接调用 current_setting()
        未传 missing_ok，因此可能抛异常。此测试验证两种情况:
        - 返回空结果（如果数据库有默认值配置）
        - 抛出异常（标准行为）

        需要数据库启用 RLS 策略才能通过，本地开发环境通常未启用。
        """
        # 检测 RLS 是否启用且对当前用户生效
        rls_effective = await _check_rls_effective(conn, 'products')
        if not rls_effective:
            pytest.skip("RLS 策略对当前连接不生效（未启用/superuser/表 owner），跳过此测试")

        # 确保 GUC 变量未设置
        await _reset_tenant(conn)

        try:
            rows = await conn.fetch("SELECT tenant_id FROM products LIMIT 5")
            # 如果没抛异常，验证返回为空
            assert len(rows) == 0, (
                f"未设置 tenant_id 时应返回空，实际返回 {len(rows)} 行"
            )
        except asyncpg.exceptions.UndefinedObjectError:
            # current_setting('app.current_tenant_id') 未定义时会抛此异常
            # 这是预期行为，说明 RLS 正确阻止了无租户访问
            pass
        except asyncpg.exceptions.InternalServerError as e:
            # 某些 PostgreSQL 配置下可能包装为 InternalServerError
            if "unrecognized configuration parameter" in str(e):
                pass  # 预期行为
            else:
                raise

    async def test_rls_insert_mismatched_tenant_rejected(self, conn):
        """
        验证: 设置 tenant_id=1 后，INSERT 不匹配的 tenant_id (如 999)
        应被 RLS WITH CHECK 策略拒绝。

        RLS 策略的 USING 子句在未显式指定 WITH CHECK 时，会同时作为
        INSERT/UPDATE 的 CHECK 条件。

        需要数据库启用 RLS 策略才能通过，本地开发环境通常未启用。
        """
        # 检测 RLS 是否启用且对当前用户生效
        rls_effective = await _check_rls_effective(conn, 'categories')
        if not rls_effective:
            pytest.skip("RLS 策略对当前连接不生效（未启用/superuser/表 owner），跳过此测试")

        tenant_ids = await _get_existing_tenant_ids(conn)
        if 1 not in tenant_ids:
            pytest.skip("数据库中不存在 tenant_id=1，跳过测试")

        await _set_tenant(conn, 1)

        # 尝试向 categories 表插入 tenant_id=999 的数据（与当前设置的 1 不匹配）
        with pytest.raises(
            (asyncpg.exceptions.InsufficientPrivilegeError,
             asyncpg.exceptions.ForeignKeyViolationError),
        ):
            await conn.execute(
                """
                INSERT INTO categories (id, tenant_id, name, status)
                VALUES ($1, $2, $3, $4)
                """,
                "rls_test_cat_mismatch",
                999,
                "RLS 测试分类（不应成功）",
                "active",
            )


# ---------------------------------------------------------------------------
# 2. 核心业务表 RLS 批量验证
# ---------------------------------------------------------------------------

class TestRLSPerTable:
    """
    逐表验证 RLS 策略有效性。
    对每张启用 RLS 的业务表:
      1. 设置 tenant_id 为数据库中已有的某个租户
      2. 查询该表，确认返回的所有行 tenant_id 都匹配
      3. 如果表中无数据，优雅跳过
    """

    @pytest.mark.parametrize("table_name", RLS_TABLES)
    async def test_rls_isolation_per_table(self, conn, table_name: str):
        """
        验证: 设置租户后，查询 {table_name} 表仅返回当前租户数据。
        """
        tenant_ids = await _get_existing_tenant_ids(conn)
        if not tenant_ids:
            pytest.skip("数据库中无任何租户，跳过测试")

        # 使用第一个已有租户
        target_tenant = tenant_ids[0]
        await _set_tenant(conn, target_tenant)

        # 查询该表的 tenant_id 列（限制行数避免大表慢查询）
        rows = await conn.fetch(
            f"SELECT tenant_id FROM {table_name} LIMIT 100"  # noqa: S608
        )

        if not rows:
            pytest.skip(f"表 {table_name} 中 tenant_id={target_tenant} 无数据，跳过")

        # 验证: 所有返回行的 tenant_id 必须等于目标租户
        mismatched = [r["tenant_id"] for r in rows if r["tenant_id"] != target_tenant]
        assert not mismatched, (
            f"RLS 策略失效! 表 {table_name}: 设置 tenant_id={target_tenant} 后，"
            f"查询返回了其他租户数据: {set(mismatched)}"
        )

    @pytest.mark.parametrize("table_name", RLS_TABLES)
    async def test_rls_enabled_on_table(self, conn, table_name: str):
        """
        验证: 表 {table_name} 已启用 RLS（通过 pg_class.relrowsecurity 检查）。
        即使表中无数据，也可验证 RLS 是否正确启用。
        """
        row = await conn.fetchrow(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = $1 AND relnamespace = (
                SELECT oid FROM pg_namespace WHERE nspname = 'public'
            )
            """,
            table_name,
        )
        if row is None:
            pytest.skip(f"表 {table_name} 不存在，跳过")

        assert row["relrowsecurity"] is True, (
            f"表 {table_name} 未启用 RLS (relrowsecurity=False)"
        )


# ---------------------------------------------------------------------------
# 3. RLS 边界场景
# ---------------------------------------------------------------------------

class TestRLSEdgeCases:
    """RLS 边界场景验证"""

    async def test_rls_update_cross_tenant_blocked(self, conn):
        """
        验证: 跨租户 UPDATE 被 RLS 阻止。
        设置 tenant_id=1 后，尝试 UPDATE 其他租户的数据，受影响行数应为 0。
        """
        tenant_ids = await _get_existing_tenant_ids(conn)
        if len(tenant_ids) < 2:
            pytest.skip("数据库中租户数不足 2 个，无法验证跨租户 UPDATE")

        tenant_a, tenant_b = tenant_ids[0], tenant_ids[1]
        await _set_tenant(conn, tenant_a)

        # 尝试将 tenant_b 的 products 数据名称修改
        # 由于 RLS，当前连接只能看到 tenant_a 的行，UPDATE tenant_b 的行不会匹配
        result = await conn.execute(
            """
            UPDATE products
            SET name = 'RLS_CROSS_TENANT_ATTACK'
            WHERE tenant_id = $1
            """,
            tenant_b,
        )
        # asyncpg 返回命令标签如 "UPDATE 0"
        affected = int(result.split()[-1])
        assert affected == 0, (
            f"跨租户 UPDATE 应影响 0 行，实际影响 {affected} 行！RLS 策略可能存在漏洞"
        )

    async def test_rls_delete_cross_tenant_blocked(self, conn):
        """
        验证: 跨租户 DELETE 被 RLS 阻止。
        设置 tenant_id=1 后，尝试 DELETE 其他租户数据，受影响行数应为 0。
        """
        tenant_ids = await _get_existing_tenant_ids(conn)
        if len(tenant_ids) < 2:
            pytest.skip("数据库中租户数不足 2 个，无法验证跨租户 DELETE")

        tenant_a, tenant_b = tenant_ids[0], tenant_ids[1]
        await _set_tenant(conn, tenant_a)

        # 注意: 使用事务回滚保护，防止意外删除数据
        tr = conn.transaction()
        await tr.start()
        try:
            result = await conn.execute(
                """
                DELETE FROM products
                WHERE tenant_id = $1
                """,
                tenant_b,
            )
            affected = int(result.split()[-1])
            assert affected == 0, (
                f"跨租户 DELETE 应影响 0 行，实际影响 {affected} 行！RLS 策略可能存在漏洞"
            )
        finally:
            # 无论如何都回滚，避免真正删除数据
            await tr.rollback()

    async def test_rls_tenant_switch_in_same_connection(self, conn):
        """
        验证: 在同一连接中切换 tenant_id 后，查询结果正确切换。
        先设置 tenant_1 查询，再切换到 tenant_2 查询，
        两次结果应分别只包含对应租户数据。
        """
        tenant_ids = await _get_existing_tenant_ids(conn)
        if len(tenant_ids) < 2:
            pytest.skip("数据库中租户数不足 2 个，无法验证租户切换")

        tenant_a, tenant_b = tenant_ids[0], tenant_ids[1]

        # --- 阶段 1: 设置 tenant_a ---
        await _set_tenant(conn, tenant_a)
        rows_a = await conn.fetch("SELECT tenant_id FROM products LIMIT 50")
        tenant_ids_a = {r["tenant_id"] for r in rows_a}
        if tenant_ids_a:
            assert tenant_ids_a == {tenant_a}, (
                f"切换前: 期望仅包含 tenant={tenant_a}，实际: {tenant_ids_a}"
            )

        # --- 阶段 2: 切换到 tenant_b ---
        await _set_tenant(conn, tenant_b)
        rows_b = await conn.fetch("SELECT tenant_id FROM products LIMIT 50")
        tenant_ids_b = {r["tenant_id"] for r in rows_b}
        if tenant_ids_b:
            assert tenant_ids_b == {tenant_b}, (
                f"切换后: 期望仅包含 tenant={tenant_b}，实际: {tenant_ids_b}"
            )

        # 两次查询不应返回对方的数据
        if rows_a and rows_b:
            assert tenant_ids_a.isdisjoint(tenant_ids_b), (
                "两次查询返回了相同租户的数据，隔离失效"
            )

    async def test_rls_insert_matching_tenant_succeeds_then_rollback(self, conn):
        """
        验证: INSERT 匹配当前 tenant_id 的数据应成功（随后回滚以保持幂等）。
        """
        tenant_ids = await _get_existing_tenant_ids(conn)
        if not tenant_ids:
            pytest.skip("数据库中无租户，跳过")

        target_tenant = tenant_ids[0]
        await _set_tenant(conn, target_tenant)

        tr = conn.transaction()
        await tr.start()
        try:
            # 向 categories 表插入匹配 tenant_id 的数据
            await conn.execute(
                """
                INSERT INTO categories (id, tenant_id, name, status)
                VALUES ($1, $2, $3, $4)
                """,
                "rls_test_cat_ok",
                target_tenant,
                "RLS 测试分类（应成功）",
                "active",
            )

            # 验证插入成功：查询到刚插入的行
            row = await conn.fetchrow(
                "SELECT id, tenant_id FROM categories WHERE id = $1",
                "rls_test_cat_ok",
            )
            assert row is not None, "匹配 tenant_id 的 INSERT 应成功"
            assert row["tenant_id"] == target_tenant
        finally:
            # 回滚，保持测试幂等
            await tr.rollback()

    async def test_tenants_table_special_rls(self, conn):
        """
        验证: tenants 表有特殊 RLS 策略，当 current_tenant_id 为空字符串时
        允许访问所有租户（用于系统级查询）。

        策略: USING (id::text = current_setting(...) OR current_setting(...) = '')
        """
        # 设置空字符串，应能查看所有租户
        await _set_tenant(conn, "")
        rows = await conn.fetch("SELECT id, name FROM tenants LIMIT 10")
        # 应该能查到数据（至少有默认租户）
        assert len(rows) >= 1, "tenants 表在空 tenant_id 下应返回所有租户"

        # 设置具体 tenant_id，应只返回该租户
        first_tenant_id = rows[0]["id"]
        await _set_tenant(conn, first_tenant_id)
        rows_filtered = await conn.fetch("SELECT id FROM tenants")
        assert len(rows_filtered) == 1, (
            f"设置 tenant_id={first_tenant_id} 后 tenants 表应只返回 1 行，"
            f"实际返回 {len(rows_filtered)} 行"
        )
        assert rows_filtered[0]["id"] == first_tenant_id


# ---------------------------------------------------------------------------
# 4. RLS 策略配置完整性验证
# ---------------------------------------------------------------------------

class TestRLSPolicyCompleteness:
    """验证所有预期的 RLS 策略均已创建"""

    async def test_all_rls_tables_have_policy(self, conn):
        """
        验证: RLS_TABLES 中的每张表都至少有一条 RLS 策略。
        通过查询 pg_policies 系统视图来验证。
        """
        all_tables_with_rls = RLS_TABLES + ["tenants"]

        rows = await conn.fetch(
            """
            SELECT tablename, policyname, cmd, qual
            FROM pg_policies
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        )

        tables_with_policies = {r["tablename"] for r in rows}

        missing = []
        for table in all_tables_with_rls:
            if table not in tables_with_policies:
                missing.append(table)

        assert not missing, (
            f"以下表缺少 RLS 策略定义: {missing}"
        )

    async def test_rls_policy_uses_tenant_id_condition(self, conn):
        """
        验证: 所有业务表的 RLS 策略条件中包含 tenant_id 和 app.current_tenant_id。
        确保策略表达式不是空壳。
        """
        rows = await conn.fetch(
            """
            SELECT tablename, policyname, qual
            FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = ANY($1::text[])
            """,
            RLS_TABLES,
        )

        for row in rows:
            qual = row["qual"] or ""
            # 策略表达式应包含 tenant_id 和 app.current_tenant_id
            assert "tenant_id" in qual.lower(), (
                f"表 {row['tablename']} 策略 {row['policyname']} "
                f"的 USING 条件未包含 tenant_id: {qual}"
            )
            assert "app.current_tenant_id" in qual.lower(), (
                f"表 {row['tablename']} 策略 {row['policyname']} "
                f"的 USING 条件未包含 app.current_tenant_id: {qual}"
            )
