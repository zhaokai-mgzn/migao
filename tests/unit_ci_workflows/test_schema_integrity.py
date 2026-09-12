"""
SQL schema 完整性守卫（issue #3270）。

背景（2026-09-11 CI 实测根因，串联出同一 commit 的多处遗留）：
`xiaobu-acceptance` 自 2026-08-31 起 **9/9 全 failure**，真因是
`docs/sql/schema.sql` 无法初始化 —— `docker-entrypoint-initdb.d` 的 psql 带
`ON_ERROR_STOP=1`，任何一条语句报错都会中止建库 → postgres 容器 `exited (3)`
→ admin-api/ai-agent 起不来 → 整个评测栈不可用。

定位到 **5 类**缺陷（建表顺序 + 已删表遗留语句）：

| # | 位置 | 问题 |
|---|---|---|
| 1 | `product_processing_items` | 引用尚未创建的 `processing_items`（前向 FK） |
| 2 | `idx_knowledge_cards_*` 三个索引 | `ON knowledge_entries`（表实为 `knowledge_cards`） |
| 3 | `COMMENT ON COLUMN rag_chunks.*` | 表已随 LLM WIKI 迁移删除 |
| 4 | `rag_chunks` / `knowledge_sync_history` RLS + POLICY | 同上 |
| 5 | `POLICY ... ON knowledge_documents` | 同上 |

来源 commit：`f685b491`（issue #3051「LLM WIKI 完全替代旧知识库」）——
删了旧表却没清干净引用它的索引/注释/RLS/策略语句。

**验证方式（本地真库实测）**：`initdb` + `psql -v ON_ERROR_STOP=1 -f schema.sql`
→ 修复前 exit 3，修复后 **exit 0**，39 张表 + FK 全部建成。

本测试用静态分析等价覆盖上述 5 类，提交即可拦住，无需起库。
"""
# case_ids: MC-012, CH-010, OR-017, CH-024
import re
import sys
from pathlib import Path

SCHEMA = Path(__file__).parent.parent.parent / "docs" / "sql" / "schema.sql"

# 允许被引用但不由本文件创建的表（运行时扩展/外部扩展；当前为空）
EXTERNAL_TABLES = set()

# 非表名的 SQL 关键字（正则误伤的常见形态）
_NON_TABLE = {"select", "where", "set", "values", "only", "if", "exists", "table", "column"}


def _strip_comments(sql: str) -> str:
    return "\n".join(l for l in sql.split("\n") if not l.lstrip().startswith("--"))


def _created_tables(body: str):
    return [
        m.group(1).lower()
        for m in re.finditer(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.]+)", body, re.I)
    ]


def _stmt_targets(body: str):
    """{表名: {语句类型}} —— 所有指向某表的语句（ALTER/COMMENT/INDEX/POLICY/REFERENCES）"""
    patterns = [
        (r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?([A-Za-z0-9_.]+)", "ALTER TABLE"),
        (r"COMMENT\s+ON\s+(?:TABLE|COLUMN)\s+([A-Za-z0-9_.]+)", "COMMENT ON"),
        (r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?[A-Za-z0-9_]+\s+ON\s+([A-Za-z0-9_.]+)",
         "CREATE INDEX"),
        (r"CREATE\s+POLICY\s+[A-Za-z0-9_]+\s+ON\s+([A-Za-z0-9_.]+)", "CREATE POLICY"),
        (r"REFERENCES\s+([A-Za-z0-9_.]+)", "REFERENCES"),
    ]
    out = {}
    for pat, label in patterns:
        for m in re.finditer(pat, body, re.I):
            t = m.group(1).lower()
            if t in _NON_TABLE or "." in t:
                continue
            out.setdefault(t, set()).add(label)
    return out


def _forward_refs(body: str):
    """CREATE TABLE 块内的前向 REFERENCES（含列内联与表级约束两种语法）"""
    created = []
    seen = set()
    forward = []
    starts = [m.start() for m in re.finditer(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[A-Za-z0-9_.]+\s*\(", body, re.I)]
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(body)
        chunk = body[s:e]
        m = re.match(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.]+)", chunk, re.I)
        if not m:
            continue
        table = m.group(1).lower()
        for ref in re.findall(r"REFERENCES\s+([A-Za-z0-9_.]+)", chunk, re.I):
            ref_l = ref.lower()
            if ref_l == table or ref_l in EXTERNAL_TABLES or "." in ref_l:
                continue
            if ref_l not in seen:
                forward.append((table, ref_l))
        created.append(table)
        seen.add(table)
    return created, forward


class TestSchemaParses:
    def test_schema_has_expected_tables(self):
        body = _strip_comments(SCHEMA.read_text(encoding="utf-8"))
        created = _created_tables(body)
        assert len(created) >= 30, (
            f"仅解析出 {len(created)} 张表（预期 ≥30）—— schema 结构或本解析器已变更"
        )


class TestNoForwardReferences:
    def test_no_forward_foreign_key_references(self):
        """核心契约 1：REFERENCES 指向的表必须已在前文创建。

        先例：product_processing_items 引用 processing_items，后者定义在更后面
        → psql 报 relation does not exist → initdb 中止 → docker 栈不可用。
        """
        body = _strip_comments(SCHEMA.read_text(encoding="utf-8"))
        _, forward = _forward_refs(body)
        assert not forward, (
            "schema.sql 存在前向外键引用（建表顺序错误 → initdb 中止）：\n"
            + "\n".join(f"  - 表 {t} 引用了尚未创建的 {r}" for t, r in forward)
        )

    def test_processing_items_before_product_processing_items(self):
        """回归锚点：processing_items 必须早于 product_processing_items"""
        body = _strip_comments(SCHEMA.read_text(encoding="utf-8"))
        created, _ = _forward_refs(body)
        if "processing_items" not in created or "product_processing_items" not in created:
            return
        assert created.index("processing_items") < created.index("product_processing_items"), (
            "processing_items 必须早于 product_processing_items（后者 FK 引用前者）"
        )


class TestNoStrayStatementsOnDroppedTables:
    """核心契约 2：不得对**不存在的表**下 ALTER/COMMENT/INDEX/POLICY 语句。

    先例（同一 commit f685b491 遗留）：仅按「REFERENCES 顺序」检查不够 ——
    还有 `CREATE INDEX ... ON knowledge_entries`（表实为 knowledge_cards）、
    `COMMENT ON COLUMN rag_chunks.*`、`POLICY ON knowledge_documents` 等
    **孤儿语句**，同样会让 ON_ERROR_STOP 中止建库。
    """

    def test_no_statements_targeting_missing_tables(self):
        body = _strip_comments(SCHEMA.read_text(encoding="utf-8"))
        created = set(_created_tables(body))
        targets = _stmt_targets(body)
        missing = {t: v for t, v in targets.items()
                   if t not in created and t not in EXTERNAL_TABLES}
        assert not missing, (
            "schema.sql 存在指向**不存在表**的语句（建库会因 ON_ERROR_STOP 中止）：\n"
            + "\n".join(f"  - {t}  ← {', '.join(sorted(v))}" for t, v in sorted(missing.items()))
        )

    def test_known_dropped_tables_have_no_references(self):
        """回归锚点：LLM WIKI 迁移删除的表不得再被引用"""
        body = _strip_comments(SCHEMA.read_text(encoding="utf-8"))
        dropped = ["knowledge_entries", "rag_chunks", "knowledge_sync_history",
                   "knowledge_documents"]
        found = []
        for t in dropped:
            m = re.search(rf"\b{t}\b", body, re.I)
            if m:
                found.append(f"  - 第 ~{body[:m.start()].count(chr(10)) + 1} 行仍引用已删表 {t}")
        assert not found, (
            "已随 LLM WIKI 迁移（issue #3051）删除的表仍被引用 → 建库中止：\n"
            + "\n".join(found)
        )

    def test_knowledge_card_indexes_target_knowledge_cards(self):
        """回归锚点：idx_knowledge_cards_* 三个索引必须建在 knowledge_cards 上"""
        body = _strip_comments(SCHEMA.read_text(encoding="utf-8"))
        for idx in ["idx_knowledge_cards_tenant", "idx_knowledge_cards_status",
                    "idx_knowledge_cards_category"]:
            m = re.search(
                rf"CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?{idx}\s+ON\s+([A-Za-z0-9_.]+)",
                body, re.I)
            assert m, f"索引 {idx} 不存在（被误删？）"
            assert m.group(1).lower() == "knowledge_cards", (
                f"{idx} 建在 {m.group(1)} 上，应为 knowledge_cards"
            )


COMPOSE = Path(__file__).parent.parent.parent / "deploy" / "docker-compose.yml"
WORKFLOWS_DIR = Path(__file__).parent.parent.parent / ".github" / "workflows"


class TestPostgresHealthcheckMatchesDatabase:
    """postgres 健康检查必须连对库（issue #3270）。

    先例：健康检查写成 `pg_isready -U app_user` —— pg_isready 未给 `-d` 时以
    **用户名**为库名连接，而实例只有 `POSTGRES_DB=ai_customer_service` →
    `FATAL: database "app_user" does not exist` → 容器永远 unhealthy →
    `docker compose up --wait` 判定 postgres 未就绪 → 整个栈起不来。

    隐蔽点：**schema 初始化其实已成功**（日志有 "PostgreSQL init process complete;
    ready for start up"），失败发生在 init 之后的健康探测 —— 只看容器 exited(3)
    会误判成 schema 问题。
    """

    def _postgres(self):
        import yaml
        d = yaml.safe_load(COMPOSE.read_text(encoding="utf-8")) or {}
        return d["services"]["postgres"]

    def test_healthcheck_specifies_target_database(self):
        pg = self._postgres()
        test_cmd = " ".join(pg.get("healthcheck", {}).get("test") or [])
        assert "-d " in test_cmd, (
            f"postgres healthcheck 未指定 -d 目标库（实为 {test_cmd!r}）—— "
            "pg_isready 会以用户名当库名，永远 unhealthy"
        )

    def test_healthcheck_database_matches_postgres_db(self):
        pg = self._postgres()
        test_cmd = " ".join(pg.get("healthcheck", {}).get("test") or [])
        db = pg["environment"]["POSTGRES_DB"]
        m = re.search(r"-d\s+([A-Za-z0-9_]+)", test_cmd)
        assert m, f"healthcheck 里解析不到 -d 的库名：{test_cmd!r}"
        assert m.group(1) == db, (
            f"healthcheck 连的是 {m.group(1)}，而实例的 POSTGRES_DB 是 {db} —— 必然 FATAL"
        )

    def test_healthcheck_user_matches_postgres_user(self):
        pg = self._postgres()
        test_cmd = " ".join(pg.get("healthcheck", {}).get("test") or [])
        user = pg["environment"]["POSTGRES_USER"]
        m = re.search(r"-U\s+([A-Za-z0-9_]+)", test_cmd)
        assert m, f"healthcheck 里解析不到 -U 用户名：{test_cmd!r}"
        assert m.group(1) == user, (
            f"healthcheck 用的用户是 {m.group(1)}，实例的 POSTGRES_USER 是 {user}"
        )

    def test_compose_mounts_schema_sql_as_init_script(self):
        """bootstrap 脚本必须仍挂载为 initdb 脚本（本 issue 修复对象的入口）"""
        pg = self._postgres()
        mounts = " ".join(pg.get("volumes") or [])
        assert "schema.sql" in mounts and "docker-entrypoint-initdb.d" in mounts, (
            f"compose 未把 docs/sql/schema.sql 挂为 initdb 脚本：{mounts!r}"
        )


class TestAiAgentRequiredSettingsProvided:
    """compose 必须为 ai-agent 的**必填**配置项提供值（issue #3270）。

    先例：`app/config.py` 里以下 6 项声明为无默认值的必填字段
    （`JWT_PUBLIC_KEY: str` 等），而 compose 未提供 →
    `pydantic_core.ValidationError: 6 validation errors for Settings`
    → aikf-ai-agent 起不来 → 整个栈失败。

    实测：本地补齐这 6 项后 `from app.config import settings` 加载成功。
    """

    REQUIRED = ["JWT_PUBLIC_KEY", "LOGISTICS_API_URL", "LOGISTICS_APPCODE",
                "SSE_TIMEOUT", "SSE_PING_INTERVAL", "CORS_ALLOWED_ORIGINS"]

    def _ai_agent_env(self):
        import yaml
        d = yaml.safe_load(COMPOSE.read_text(encoding="utf-8")) or {}
        return d["services"]["ai-agent-service"]["environment"]

    def test_all_required_settings_present_in_compose(self):
        env = self._ai_agent_env()
        missing = [k for k in self.REQUIRED if k not in env]
        assert not missing, (
            f"compose 未为 ai-agent 必填配置提供值：{missing} —— "
            "app/config.py 中这些字段无默认值，缺任一则服务启动即 ValidationError"
        )

    def test_numeric_settings_have_usable_defaults(self):
        """SSE 两项必须给数值默认值（空串会让 int 校验失败）"""
        env = self._ai_agent_env()
        for k in ["SSE_TIMEOUT", "SSE_PING_INTERVAL"]:
            raw = str(env[k])
            m = re.search(r":-(\d+)\}", raw)
            assert m, f"{k} 未提供数值默认值（实为 {raw!r}）—— int 字段会校验失败"
            assert int(m.group(1)) > 0, f"{k} 默认值必须为正数，实为 {m.group(1)}"


class TestDevStackRS256Keys:
    """dev/CI 栈必须能拿到 RS256 密钥（issue #3270）。

    先例：`JwtTokenProvider.init()` 在密钥缺失时 **fail-fast**
    （禁止静默回退 HS256，否则 ai-agent 只接受 RS256 会报 TOKEN_INVALID），
    而生产私钥 `src/main/resources/rsa/private.pem` 被 `.gitignore:79` 刻意排除
    → CI clone 后镜像内无该文件 → admin-api 起不来。

    解法：用仓库**已入库的测试密钥对**（`src/test/resources/rsa/*.pem`，
    `.gitignore:81` 白名单）走 PEM 内容注入。本测试锁定该链路完整性。
    """

    REPO = Path(__file__).parent.parent.parent
    TEST_KEY_DIR = REPO / "backend" / "admin-api" / "src" / "test" / "resources" / "rsa"

    def test_test_keypair_is_committed(self):
        """测试密钥对必须在仓库里（gitignore 白名单），否则 CI 无从注入"""
        for name in ("private.pem", "public.pem"):
            f = self.TEST_KEY_DIR / name
            assert f.exists(), (
                f"缺少 {f} —— CI 无法注入 RS256 密钥；"
                "注意 .gitignore:79 **/rsa/private.pem 会误伤它，"
                ".gitignore:81 的 ! 白名单必须保留"
            )
            content = f.read_text(encoding="utf-8")
            assert "-----BEGIN" in content and "KEY-----" in content, (
                f"{f} 不是合法 PEM 内容"
            )

    def test_compose_accepts_pem_injection(self):
        """compose 必须把 PEM 透传给 admin-api（JwtTokenProvider 的 PEM 优先级更高）"""
        import yaml
        d = yaml.safe_load(COMPOSE.read_text(encoding="utf-8")) or {}
        env = d["services"]["admin-api"]["environment"]
        for k in ("JWT_PRIVATE_KEY_PEM", "JWT_PUBLIC_KEY_PEM"):
            assert k in env, (
                f"compose 未透传 {k} —— dev/CI 栈会因缺 RS256 密钥 fail-fast 起不来"
            )

    def test_workflow_exports_keys_before_stack_start(self):
        """workflow 必须在起栈**之前**导出 PEM 到 GITHUB_ENV"""
        import yaml
        wf = WORKFLOWS_DIR / "xiaobu-acceptance.yml"
        d = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        steps = d["jobs"]["xiaobu-acceptance"]["steps"]
        names = [s_.get("name") or "" for s_ in steps]
        # 用 -1 作「未找到」哨兵：只断言位置关系，避免触发门禁的弱断言模式
        i_export = next((i for i, n in enumerate(names) if "RS256" in n), -1)
        i_stack = next((i for i, n in enumerate(names) if "Start local stack" in n), -1)
        assert 0 <= i_export < i_stack, (
            f"workflow 步骤顺序有误（i_export={i_export}, i_stack={i_stack}）："
            "缺少 RS256 密钥导出步骤，或它没排在起栈之前（GITHUB_ENV 只对后续步骤生效）。"
            f"实际步骤名：{names}"
        )
        body = steps[i_export].get("run") or ""
        assert "GITHUB_ENV" in body, "导出步骤未写入 $GITHUB_ENV"
        assert "test/resources/rsa" in body, "导出步骤未读取测试密钥对"

    def test_workflow_also_exports_jwt_public_key(self):
        """ai-agent 需要 JWT_PUBLIC_KEY（config.py 必填）—— 导出步骤必须一并给

        先例：不给则 aikf-ai-agent 报
        「生产环境必须设置以下环境变量：JWT_PUBLIC_KEY」→ 服务起不来。
        """
        import yaml
        wf = WORKFLOWS_DIR / "xiaobu-acceptance.yml"
        d = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        steps = d["jobs"]["xiaobu-acceptance"]["steps"]
        body = next((s_.get("run") or "" for s_ in steps
                     if "RS256" in (s_.get("name") or "")), "")
        assert "JWT_PUBLIC_KEY=" in body, (
            "导出步骤未写入 JWT_PUBLIC_KEY —— ai-agent 会因必填校验失败起不来"
        )
        assert "public.pem" in body, "JWT_PUBLIC_KEY 应取自测试密钥对的公钥文件"


class TestBootstrapSeedData:
    """bootstrap schema 必须包含**关键种子数据**（issue #3270）。

    背景（2026-09-11 本地真库复现）：
    `schema.sql` 只建表不插种子，而 ai-agent 的 DEBUG customer 身份固定
    `tenant_id=1`（app/utils/auth.py）→ 全新库上 `INSERT INTO sessions` 违反
    `sessions_tenant_id_fkey`（tenant 1 不存在）→ 会话创建 HTTP 500 →
    C 端评测在本地/CI docker 栈**全部失败**（9/9，2026-08-31 起）。

    复现证据（本地 initdb + 起 ai-agent）：
    ```
    IntegrityError: insert or update on table "sessions" violates foreign key
    constraint "sessions_tenant_id_fkey"
    DETAIL:  Key (tenant_id)=(1) is not present in table "tenants".
    ```
    补种子后：`POST /api/chat/sessions` 从 500 → 200，小布知识问答端到端可用。

    `schema_full.sql` 一直有这段种子，`schema.sql` 缺失 —— 两份 schema 漂移
    （本测试就是防止再次漂移）。
    """

    def _sql(self):
        return SCHEMA.read_text(encoding="utf-8")

    def test_seeds_default_tenant_1(self):
        sql = self._sql()
        assert re.search(r"INSERT\s+INTO\s+tenants[\s\S]*?VALUES\s*\(1,", sql, re.I), (
            "bootstrap 必须种默认租户 id=1 —— ai-agent DEBUG customer 身份固定 tenant 1，"
            "缺它会话创建必 500（sessions_tenant_id_fkey）"
        )
        assert "ON CONFLICT" in sql, "种子必须幂等（ON CONFLICT DO NOTHING）"

    def test_seeds_default_roles(self):
        sql = self._sql()
        assert re.search(r"INSERT\s+INTO\s+roles[\s\S]*?role_admin", sql, re.I), (
            "bootstrap 必须种默认角色（含 role_admin）—— 商户员工登录/权限链依赖"
        )

    def test_seed_block_lives_at_end_of_schema(self):
        """种子在 END OF SCHEMA 之前（建表完成后才插数据）"""
        sql = self._sql()
        i_insert = sql.find("INSERT INTO tenants")
        i_end = sql.find("END OF SCHEMA")
        assert i_insert != -1 and i_end != -1
        assert i_insert < i_end, "种子必须在全部建表语句之后（FK 依赖）"


class TestDebugPassthroughForEval:
    """ai-agent 必须能收到 DEBUG=true（issue #3270：C 端评测的鉴权前提）。

    背景：`X-Debug-Role: customer` 调试身份注入只在 `DEBUG=true` 时生效
    （app/utils/auth.py fail-closed）。docker-compose 此前**未**透传 DEBUG →
    容器内 `DEBUG=False`、`Environment=production` → 评测请求被
    `401 AUTH_REQUIRED` 拒绝 → C 端评测 100% 失败。

    实测证据（CI 诊断）：
        aikf-ai-agent | Logging system initialized (debug=False)
        aikf-ai-agent | Environment: production
        ❌ 创建会话失败: HTTP 401 AUTH_REQUIRED
    """

    def test_compose_passes_debug_to_ai_agent(self):
        import yaml
        d = yaml.safe_load(COMPOSE.read_text(encoding="utf-8")) or {}
        env = d["services"]["ai-agent-service"]["environment"]
        assert "DEBUG" in env, (
            "compose 未向 ai-agent 透传 DEBUG —— 本地/CI 栈内 DEBUG=False，"
            "X-Debug-Role 调试身份被 fail-closed 拒绝（401），评测无法运行"
        )

    def test_debug_default_is_false(self):
        """默认必须是 false（生产安全 fail-closed），由工作流显式传 true"""
        import yaml
        d = yaml.safe_load(COMPOSE.read_text(encoding="utf-8")) or {}
        raw = str(d["services"]["ai-agent-service"]["environment"]["DEBUG"])
        assert ":-false}" in raw or raw in ("false", "${DEBUG}"), (
            f"DEBUG 默认值应安全（false / 显式外部传入），实为 {raw!r}"
        )

    def test_workflow_sets_debug_true_for_stack(self):
        """验收 workflow 必须显式把 DEBUG 传给起栈步骤"""
        import yaml
        wf = WORKFLOWS_DIR / "xiaobu-acceptance.yml"
        d = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        step = next((s_ for s_ in d["jobs"]["xiaobu-acceptance"]["steps"]
                     if "Start local stack" in (s_.get("name") or "")), {})
        env = step.get("env") or {}
        assert str(env.get("DEBUG", "")).lower() == "true", (
            "起栈步骤未设置 DEBUG=true —— ai-agent 会以 production 模式启动，"
            "X-Debug-Role 被拒绝导致评测 401"
        )

    def test_debug_true_actually_enables_debug_role(self):
        """语义核实：DEBUG=true 时 X-Debug-Role 才被接受（源码级契约）"""
        repo_root = Path(__file__).parent.parent.parent
        auth = (repo_root / "backend" / "ai-agent-service" / "app" / "utils" / "auth.py").read_text(encoding="utf-8")
        assert "settings.DEBUG and debug_role" in auth, (
            "auth.py 的调试身份注入条件已变更 —— 需同步本测试与 compose 契约"
        )


FIXTURE = (Path(__file__).parent.parent.parent
           / "tests" / "agent_eval" / "fixtures" / "xiaobu_eval_seed.sql")


def _strip_sql_comments(sql: str) -> str:
    """剥掉 SQL 注释，只留可执行代码。

    ⚠️ 为什么必须剥：fixture 的注释里**大量引用商品名/用例输入**（这正是文档价值所在），
    于是裸 `assert "夏日清风窗帘" in sql` 会被**注释**满足 —— 把商品改名后测试照样通过
    （变异测试 M2 实测假绿）。与「断言匹配到注释里的 pipefail」是同一类错误。
    """
    sql = re.sub(r"/\*[\s\S]*?\*/", "", sql)
    return "\n".join(re.sub(r"--.*$", "", line) for line in sql.splitlines())


class TestXiaobuEvalFixture:
    """C 端评测业务数据 fixture 契约（issue #3270）。

    背景：C 端验收栈是全新 bootstrap 空库。空库下 agent 搜不到商品 → 反复重试
    `product_search` → 从不进入 `product_detail` → PR-003 等依赖数据的用例必然失败
    （实测 CI：`tools=[product_search ×3]`，期望 `product_detail` → 0 分）。
    行为本身合理，缺的是**数据**。

    本测试锁定：fixture 存在、幂等、含关键实体、且 workflow 在评测**之前**注入。
    """

    def test_fixture_exists_with_seed_content(self):
        sql = FIXTURE.read_text(encoding="utf-8")
        assert "INSERT INTO products" in sql
        assert "INSERT INTO processing_items" in sql

    def test_fixture_provides_product_needed_by_pr003(self):
        """PR-003 断言 `product_detail`，需要「遮光窗帘」可被搜到"""
        sql = FIXTURE.read_text(encoding="utf-8")
        assert "遮光窗帘" in sql, "fixture 必须含「遮光窗帘」（PR-003 依赖）"

    def test_fixture_products_are_on_sale(self):
        """admin-api 未指定 status 时默认只返回 on_sale 商品 —— fixture 必须用 on_sale"""
        sql = FIXTURE.read_text(encoding="utf-8")
        assert "on_sale" in sql, "fixture 商品必须 status=on_sale（否则搜索查不到）"

    def test_fixture_is_idempotent(self):
        """每次 CI 起栈都会重放 —— 所有 INSERT 必须幂等（ON CONFLICT / WHERE NOT EXISTS）"""
        sql = FIXTURE.read_text(encoding="utf-8")
        # 按分号切 INSERT 语句，逐条确认带幂等保护
        inserts = re.findall(r"INSERT\s+INTO[\s\S]*?;", sql, re.I)
        assert len(inserts) >= 4, f"fixture INSERT 语句过少（{len(inserts)}），疑似解析失效"
        bad = []
        for stmt in inserts:
            if "ON CONFLICT" not in stmt.upper() and "NOT EXISTS" not in stmt.upper():
                first = " ".join(stmt.split())[:80]
                bad.append(first)
        assert not bad, (
            "以下 INSERT 缺少幂等保护（重复执行会报重复键）：\n  "
            + "\n  ".join(bad)
        )

    def test_fixture_links_processing_items(self):
        """下单加工项用例（OR-016/OR-017）需要商品绑定加工项"""
        sql = FIXTURE.read_text(encoding="utf-8")
        assert "product_processing_items" in sql, (
            "fixture 必须建立商品↔加工项关联 —— 否则加工项环节用例无数据可断言"
        )

    def test_workflow_seeds_before_eval(self):
        """workflow 必须在评测步骤**之前**注入 fixture"""
        import yaml
        wf = WORKFLOWS_DIR / "xiaobu-acceptance.yml"
        d = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        steps = d["jobs"]["xiaobu-acceptance"]["steps"]
        names = [s_.get("name") or "" for s_ in steps]
        i_seed = next((i for i, n in enumerate(names) if "Seed" in n and "评测业务数据" in n), -1)
        i_eval = next((i for i, n in enumerate(names) if "local_runner" in n), -1)
        assert 0 <= i_seed < i_eval, (
            f"fixture 注入必须早于评测（i_seed={i_seed}, i_eval={i_eval}）—— "
            "否则空库上依赖数据的用例仍会失败"
        )

    def test_workflow_references_fixture_path(self):
        import yaml
        wf = WORKFLOWS_DIR / "xiaobu-acceptance.yml"
        d = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        step = next((s_ for s_ in d["jobs"]["xiaobu-acceptance"]["steps"]
                     if "Seed" in (s_.get("name") or "")), {})
        body = step.get("run") or ""
        assert "tests/agent_eval/fixtures/xiaobu_eval_seed.sql" in body, (
            "workflow 未引用 fixture 文件路径"
        )
        assert "ON_ERROR_STOP=1" in body, "注入步骤应 fail-fast（ON_ERROR_STOP=1）"


class TestXiaobuFixtureCustomerOrders:
    """C 端顾客本人 + 历史订单（issue #3270 数据层，CH-010 / CH-012）。

    为什么必须有（不是"补点数据"）—— 这三个缺口都会让 agent 的**正确行为**也拿 0 分：
      ① `customer_address_query` 取"最近一笔有地址的订单"，空库永远未命中 →
         下单表单无法预填 → agent 只能反复追问（实测 `customer_address_query` ×3~4 空转），
         看着像模型循环，实为环境缺数据；
      ② `aftersale_create` 的订单归属校验（#518）先拉
         `GET /api/admin/agent/orders/mine` 再匹配 order_id → 空库必不匹配 →
         一律返回「该订单不属于您」→ **售后建单在该库里根本不可能成功**（CH-012 4 轮 0 建单）；
      ③ `customer_order_query` 列表为空 → 顾客说"第一笔订单"无从指代。
    修测量环境 ≠ 修模型 —— 不补齐就拿不到真实能力分。
    """

    AUTH_PY = (Path(__file__).parent.parent.parent / "backend" / "ai-agent-service"
               / "app" / "utils" / "auth.py")

    def _sql(self) -> str:
        """fixture 的**可执行代码**（剥注释）——注释里引用了商品名/用例，裸 in 会被注释满足"""
        return _strip_sql_comments(FIXTURE.read_text(encoding="utf-8"))

    def _auth_customer_user_id(self) -> str:
        """从 auth.py 读出 DEBUG customer 身份注入的 user_id（单一事实源）"""
        src = self.AUTH_PY.read_text(encoding="utf-8")
        # debug_role == "customer" 分支内的 user_id="..."
        m = re.search(
            r'debug_role\s*==\s*"customer"[\s\S]{0,400}?user_id\s*=\s*"([^"]+)"',
            src,
        )
        assert m, (
            "未能在 auth.py 中定位 DEBUG customer 的 user_id —— "
            "注入逻辑已变更，需同步本测试与 fixture"
        )
        return m.group(1)

    def test_fixture_customer_id_matches_auth_debug_identity(self):
        """fixture 的顾客 id 必须与 auth.py 注入的身份**逐字一致**

        这是跨源重复常量（auth.py ↔ fixture）：一旦 drift，订单不属于该顾客 →
        地址预填与售后建单同时失效，且失败信号是「该订单不属于您」（看起来像
        权限/能力问题），极难反查到 fixture。故用测试锁死。
        """
        expected = self._auth_customer_user_id()
        assert expected in self._sql(), (
            f"fixture 未使用 auth.py 的 DEBUG customer id {expected!r} —— "
            "订单将不属于评测身份的顾客"
        )

    def _orders_stmt(self) -> str:
        """取 `INSERT INTO orders ...;` 这一条语句的正文（截到第一个分号）

        ⚠️ 必须**先截语句再断言**：直接用 `INSERT INTO orders[\\s\\S]*?'id'` 会一路
        匹配到文件末尾的其它语句（如自检 DO 块里的 `user_id = 'debug_customer_1'`），
        于是删掉种子里的 user_id 测试照样通过 —— 假绿（本测试首版即踩此坑，
        用变异测试 M2 抓出）。
        """
        m = re.search(r"INSERT\s+INTO\s+orders\b[\s\S]*?;", self._sql(), re.I)
        assert m, "未找到 orders 种子语句"
        return m.group(0)

    def test_fixture_orders_belong_to_customer(self):
        """orders.user_id 必须显式赋为该顾客 —— C 端数据隔离的唯一依据"""
        uid = self._auth_customer_user_id()
        stmt = self._orders_stmt()
        assert "user_id" in stmt, "orders 种子 INSERT 未包含 user_id 列"
        assert f"'{uid}'" in stmt, (
            f"orders 种子未把 user_id 赋为 {uid!r} —— "
            "按 user_id 隔离的查询（我的订单/地址预填/售后归属校验）会全部查不到"
        )
        # 两笔订单都要归属该顾客（变异测试：只改一笔也必须被发现）
        assert stmt.count(f"'{uid}'") >= 2, (
            f"orders 种子中 {uid!r} 出现次数 < 2（两笔订单都应归属该顾客）"
        )

    def test_orders_self_check_uses_same_customer_id(self):
        """fixture 自检必须核对同一个顾客 id（否则自检形同虚设）"""
        uid = self._auth_customer_user_id()
        m = re.search(r"DO\s+\$\$[\s\S]*?\$\$", self._sql(), re.I)
        assert m, "fixture 缺少自检 DO 块"
        assert f"'{uid}'" in m.group(0), (
            "自检块未核对 auth.py 的 DEBUG customer id —— 注入了别人的订单也不会报错"
        )

    def test_fixture_orders_have_address_for_prefill(self):
        """地址预填依赖"最近一笔有地址的订单" —— 种子里必须有非空 customer_address"""
        stmt = self._orders_stmt()
        assert "customer_address" in stmt, "orders 种子缺少 customer_address 列"
        assert "文三路" in stmt, "orders 种子缺少可预填的收货地址"

    def test_fixture_orders_are_aftersale_eligible(self):
        """售后建单的状态门禁允许 confirmed/producing/shipped/completed"""
        stmt = self._orders_stmt()
        for st in ("completed", "shipped"):
            assert re.search(r"'" + st + r"'", stmt), (
                f"orders 种子缺少 status={st}（售后/物流用例依赖）"
            )

    def _order_value_tuples(self) -> list:
        """把 orders VALUES 列表切成一条订单一个元组（按每条订单元组的起始边界切）"""
        block = self._orders_stmt()
        values = block.split("VALUES", 1)[-1]
        # 订单主键是 UUID 形态（见 fixture：与生产一致，后端按 ^[0-9a-fA-F-]{20,}$ 判 UUID）
        parts = re.split(r"(?=\('a1b2c3d4-)", values)
        return [p for p in parts if p.strip().startswith("('a1b2c3d4-")]

    def test_fixture_orders_have_distinct_created_at(self):
        """created_at 必须显式给值且**每笔不同**

        `customer_order_query` 按 `ORDER BY created_at DESC` 排序，顾客说"最近那笔"
        取列表首条；若两笔同刻（`NOW()` 默认值）顺序不确定 → 用例随机命中 → 抖动。

        ⚠️ 断言按**每条订单自己的 created_at** 比对，不是拿全局时间戳列表比相邻两项
        —— 首版用 `stamps[0] != stamps[1]` 把 created_at 与 updated_at 混在一起比，
        两笔订单 created_at 改成同刻也能通过（变异测试 M1 抓出）。
        """
        tuples = self._order_value_tuples()
        assert len(tuples) >= 2, f"orders 种子解析出 {len(tuples)} 条订单（应 ≥2）"
        created = []
        for t in tuples:
            stamps = re.findall(r"TIMESTAMPTZ\s+'([^']+)'", t)
            assert stamps, "订单元组未显式指定时间戳（created_at 走 NOW() → 顺序不确定）"
            created.append(stamps[0])  # 每元组第一个时间戳 = created_at
        assert len(set(created)) == len(created), (
            f"订单 created_at 存在重复 {created} → 『最近一笔』命中不确定 → 用例抖动"
        )

    def test_fixture_has_logistics_for_shipped_order(self):
        """已发货订单要有物流轨迹，否则物流查询用例无数据"""
        assert "order_logistics" in self._sql()

    def test_fixture_self_checks_order_count(self):
        """fixture 末尾必须自检订单数 —— 防"注入了但没生效"静默通过"""
        sql = self._sql()
        assert "RAISE EXCEPTION" in sql, (
            "fixture 缺少注入自检（RAISE EXCEPTION）——注入静默失败会让整轮评测失真的"
        )


class TestEvalRunnerDepsInstalled:
    """评测 workflow 必须装齐 runner + E2E 依赖（issue #3270）。
    先例：安装步骤只有 `pip install httpx`，而 real E2E 步骤用
    `python -m pytest ... --timeout=120 --reruns 1` →
    `No module named pytest` → 步骤 exit 1（此时 C 端评测步骤其实已绿）。
    """

    REQUIRED = ["httpx", "pytest", "pytest-timeout", "pytest-rerunfailures"]
    # real E2E 跑 ai-agent 自己的测试套件（conftest 依赖 jwt/fastapi 等）
    REQUIREMENTS_REF = "backend/ai-agent-service/requirements.txt"

    def _install_step_run(self):
        import yaml
        wf = WORKFLOWS_DIR / "xiaobu-acceptance.yml"
        d = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        step = next((s_ for s_ in d["jobs"]["xiaobu-acceptance"]["steps"]
                     if "Install eval runner" in (s_.get("name") or "")), {})
        return step.get("run") or ""

    def test_all_required_deps_declared(self):
        run = self._install_step_run()
        missing = [d for d in self.REQUIRED if d not in run]
        assert not missing, (
            f"安装步骤缺依赖 {missing} —— real E2E 步骤会因缺 module 直接失败"
        )

    def test_installs_ai_agent_requirements_for_e2e(self):
        """real E2E 跑 ai-agent 测试套件 → 必须装其 requirements（否则缺 jwt 等）"""
        run = self._install_step_run()
        assert self.REQUIREMENTS_REF in run, (
            "安装步骤未装 ai-agent requirements —— real E2E 的 tests/conftest.py 依赖 "
            "jwt/fastapi 等，会报 ModuleNotFoundError（实测踩到 jwt）"
        )

    def test_pytest_plugins_match_e2e_flags(self):
        """E2E 步骤用到 --timeout / --reruns，对应插件必须已安装"""
        import yaml
        wf = WORKFLOWS_DIR / "xiaobu-acceptance.yml"
        d = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        e2e = next((s_ for s_ in d["jobs"]["xiaobu-acceptance"]["steps"]
                    if "real E2E" in (s_.get("name") or "")), {})
        body = e2e.get("run") or ""
        install = self._install_step_run()
        if "--timeout" in body:
            assert "pytest-timeout" in install, "--timeout 需要 pytest-timeout"
        if "--reruns" in body:
            assert "pytest-rerunfailures" in install, "--reruns 需要 pytest-rerunfailures"


class TestEvalTierDispatch:
    """C 端评测档位可切换（issue #3270 第 2 步：取缺陷分布）。

    只跑 smoke（5 条）等于体检只量身高。要拿「C 端能力缺陷分布」必须能跑
    normal 档（C 端全量 ~40 条）。档位由 workflow_dispatch 输入控制，
    默认 smoke 保持门禁快速。
    """

    def _wf(self):
        import yaml
        return yaml.safe_load((WORKFLOWS_DIR / "xiaobu-acceptance.yml").read_text(encoding="utf-8")) or {}

    def test_dispatch_exposes_tier_choice(self):
        wf = self._wf()
        # yaml 会把裸 on: 解析成 True 键
        triggers = wf.get("on") or wf.get(True) or {}
        dispatch = triggers.get("workflow_dispatch") or {}
        inputs = dispatch.get("inputs") or {}
        assert "tier" in inputs, "workflow_dispatch 必须暴露 tier 输入（否则只能跑 smoke）"
        opts = inputs["tier"].get("options") or []
        assert "smoke" in opts and "normal" in opts, f"tier 选项须含 smoke/normal，实为 {opts}"
        assert inputs["tier"].get("default", "") == "smoke", "默认应为 smoke（门禁保持快速）"

    def test_eval_step_uses_tier_variable(self):
        wf = self._wf()
        step = next((s_ for s_ in wf["jobs"]["xiaobu-acceptance"]["steps"]
                     if "local_runner" in (s_.get("name") or "")), {})
        body = step.get("run") or ""
        assert "github.event.inputs.tier" in body, "评测步骤未读取 tier 输入"
        assert 'local_runner.py "$TIER"' in body, "评测步骤未把 tier 作为档位参数传给 runner"
        # 不得再硬编码 smoke（否则档位切换失效）
        assert "local_runner.py smoke" not in body, "评测步骤仍硬编码 smoke 档"


class TestRouteTraceDumpStep:
    """CI 必须 dump 逐轮**路由/意图**轨迹（issue #3270 归因层）。

    为什么是 CI 的事而不是 runner 的事：runner 只跟 HTTP API 对话，
    意图分类与路由决策不经过 API 响应，只写在 ai-agent 进程日志里
    （`intent_router` / `route_by_intent`）。没有这一步，「退货被路由到了 order」
    与「aftersales 没绑定这个工具」在 CI 报告里永远同形，五层归因做不下去
    —— CH-012 就是这么卡住的。
    """

    def _wf(self) -> dict:
        import yaml
        wf = WORKFLOWS_DIR / "xiaobu-acceptance.yml"
        return yaml.safe_load(wf.read_text(encoding="utf-8")) or {}

    def _step(self):
        steps = self._wf()["jobs"]["xiaobu-acceptance"]["steps"]
        for s_ in steps:
            if "路由" in (s_.get("name") or ""):
                return s_
        return None

    def test_step_exists(self):
        assert self._step() is not None, (
            "workflow 缺少「Dump C 端逐轮路由轨迹」步骤 —— 路由层归因无证据"
        )

    def test_step_is_always_run(self):
        step = self._step()
        assert step.get("if") == "always()", (
            "路由轨迹步骤必须 if: always() —— 基线/改进的**成功**run 同样需要留痕对比"
        )

    def test_step_comes_after_eval(self):
        steps = self._wf()["jobs"]["xiaobu-acceptance"]["steps"]
        names = [s_.get("name") or "" for s_ in steps]
        i_dump = next((i for i, n in enumerate(names) if "路由" in n), -1)
        i_eval = next((i for i, n in enumerate(names) if "local_runner" in n), -1)
        assert 0 <= i_eval < i_dump, (
            f"路由 dump 必须在评测之后（i_eval={i_eval}, i_dump={i_dump}）"
        )

    def test_step_greps_routing_markers(self):
        step = self._step()
        body = step.get("run") or ""
        for kw in ("route_by_intent", "ai-agent-service"):
            assert kw in body, f"路由 dump 未包含关键标记 {kw!r}"
        # 必须给 DEV_SERVICE_TOKEN（否则 compose 插值失败，拿不到任何日志）
        assert (step.get("env") or {}).get("DEV_SERVICE_TOKEN"), (
            "缺 DEV_SERVICE_TOKEN → docker compose logs 插值失败 → dump 为空"
        )


class TestNamedProductsAreSeeded:
    """用例**点名**的商品必须在 fixture 里（否则该用例恒 0 分，且看着像能力缺陷）。

    先例（OR-017，issue #3316）：输入是「我想买夏日清风窗帘，米白色，3米…」，
    而 fixture 只有「遮光窗帘/北欧风窗帘」→ `product_search` 搜不到 → agent 无从下单 →
    CI 报告 `tools=[customer_address_query ×3]`、0 建单。**报告的长相是「agent 不会
    下单」，真因是「库里没这个东西」** —— 数据层缺口被误读成能力缺陷，
    正是 `migao-acceptance` 五层归因要防的事。

    本测试把「用例点名商品 → fixture 必须有」变成可执行约束：新增用例若点名了
    新商品，这里会失败并强迫你二选一 —— 注入 fixture，或声明为泛指（GENERIC）。
    """

    # 泛指 / 非商品库查询的候选（token → 理由）。不在 fixture 里也无需注入。
    GENERIC = {
        "你们窗帘": "口语泛指质量投诉，不指向具体商品（CH-013）",
        "有什么窗帘": "泛指求推荐，靠 fixture 里的推荐位/列表回答（CH-017）",
        "推荐几款热销窗帘": "泛指求推荐，靠 recommended=TRUE 商品回答（CH-010）",
        "雪尼尔面料": "知识问答走 knowledge_search，非商品库查询（KN-001/KN-008）",
        "几款窗帘": "泛指求推荐（未点名任何商品），靠 fixture 推荐位/列表回答（CH-024）",
    }
    # 候选提取：≥2 个中/英/数字字符 + 窗帘/面料/布艺 结尾
    CANDIDATE_RE = r"[\u4e00-\u9fa5A-Za-z0-9]{2,10}(?:窗帘|面料|布艺)"
    # 候选里的动词前缀（"搜一下遮光窗帘" → "遮光窗帘"）：否则提取出的是整句而非商品名
    # ⚠️ 长词必须排在短词前（正则择先匹配）：`搜索` 要在 `搜` 前，`我想买` 要在 `我想` 前
    VERB_PREFIX_RE = (
        r"^(?:帮我|给我|我想买|我想|我要|搜索|搜一下|搜下|查一下|查下|搜|查|看看|看|推荐|要|买|选了?)+"
    )

    def _candidates_by_case(self) -> dict:
        import glob
        import yaml
        root = Path(__file__).parent.parent.parent
        cases = []
        for f in glob.glob(str(root / ".github" / "cases" / "*.yml")):
            d = yaml.safe_load(Path(f).read_text(encoding="utf-8")) or {}
            cases.extend(d.get("cases") or [])

        # 复用生产过滤逻辑（与评测跑的是同一套选择口径），避免测试自造口径漂移
        sys.path.insert(0, str(root / ".github"))
        sys.path.insert(0, str(root / "tests" / "agent_eval"))
        try:
            from eval_case_filter import select_cases_for_persona
        finally:
            pass
        selected = select_cases_for_persona(cases, "xiaobu")

        out = {}
        for c in selected:
            names = set()
            for ui in (c.get("user_inputs") or []):
                text = ui if isinstance(ui, str) else str(ui)
                for raw in re.findall(self.CANDIDATE_RE, text):
                    names.add(re.sub(self.VERB_PREFIX_RE, "", raw))
            names.discard("")
            if names:
                out[c["id"]] = sorted(names)
        return out

    def test_selected_case_set_is_non_trivial(self):
        """自检：过滤逻辑真的选出了用例（否则本类测试空转 = 假绿）"""
        cands = self._candidates_by_case()
        assert len(cands) >= 5, (
            f"仅解析出 {len(cands)} 条带商品候选的 C 端用例 —— 过滤/解析疑似失效"
        )

    def _is_generic(self, token: str) -> bool:
        """token 是否属泛指/非商品库查询。

        用**双向包含**匹配：动词剥离后 token 可能变成 GENERIC 键的子串
        （"推荐几款热销窗帘" → "几款热销窗帘"），裸相等会漏判而误报。
        """
        return any(g in token or token in g for g in self.GENERIC)

    def test_named_products_exist_in_fixture(self):
        sql = _strip_sql_comments(FIXTURE.read_text(encoding="utf-8"))
        missing = []
        for cid, names in self._candidates_by_case().items():
            for n in names:
                if self._is_generic(n):
                    continue
                if n not in sql:
                    missing.append(f"{cid} 点名商品 {n!r} 不在 fixture")
        assert not missing, (
            "以下用例点名的商品未注入 fixture → 该用例必然 0 分（且会被误读为能力缺陷）：\n  "
            + "\n  ".join(missing)
            + "\n修复：在 tests/agent_eval/fixtures/xiaobu_eval_seed.sql 注入该商品"
              "（含颜色/SKU/加工项关联），或确认属泛指后加入 GENERIC。"
        )

    def test_OR017_product_is_seeded_with_processing(self):
        """OR-017 专项：夏日清风窗帘 + 米白色 + 散剪 2.8 + 加工项关联都要有

        （该用例断言 `product_detail` → `interact(choice, multiSelect)` → `order_create`，
          缺任一环都跑不通。）
        """
        sql = _strip_sql_comments(FIXTURE.read_text(encoding="utf-8"))
        assert "夏日清风窗帘" in sql
        assert "米白色" in sql
        assert "prod_eval_summer" in sql
        # 加工项关联必须带上该商品（否则 product_detail 里没有加工项可问）
        link = re.search(r"INSERT\s+INTO\s+product_processing_items[\s\S]*?;", sql, re.I)
        assert link and "prod_eval_summer" in link.group(0), (
            "product_processing_items 未关联夏日清风窗帘 → 加工项环节无数据"
        )

    def test_only_one_recommended_product(self):
        """推荐位只能有一个商品：CH-010「推荐几款热销窗帘」→「第一款」依赖列表顺序，
        多个推荐商品会让"第一款"不确定 → 用例抖动。

        解析方式：products 的最后一个字段是 `recommended`（紧跟 `has_processing`），
        故取每条 VALUES 元组末尾的 `, <bool>, <bool>)`，后一个即 recommended。
        """
        sql = _strip_sql_comments(FIXTURE.read_text(encoding="utf-8"))
        block = re.search(r"INSERT\s+INTO\s+products[\s\S]*?;", sql, re.I)
        assert block, "未找到 products 种子语句"
        flags = re.findall(r",\s*(TRUE|FALSE)\s*,\s*(TRUE|FALSE)\s*\)", block.group(0))
        assert len(flags) >= 3, (
            f"仅解析出 {len(flags)} 条商品元组 —— 解析疑似失效（本测试会空转假绿）"
        )
        recommended = [rec for _, rec in flags if rec == "TRUE"]
        assert len(recommended) == 1, (
            f"fixture 中 recommended=TRUE 的商品有 {len(recommended)} 个（应恰好 1 个）—— "
            "多个会让 CH-010 的『第一款』不确定"
        )


class TestSchemaFullDeprecation:
    """`docs/sql/schema_full.sql` 必须保持「已废弃」标注，直到它真正与迁移链对齐。

    背景（2026-09-11 实测逐表比对）：该文件是 2026-05-30 的快照，此后未跟进，
    **两个方向都失真** —— 缺 6 张新表，且仍会创建 4 张已被 V36 等迁移 DROP 的表
    （`knowledge_documents` / `knowledge_sync_history` / `rag_chunks` /
    `quick_reply_templates`）。拿它建库不是"旧一点"，是**错的**。

    风险面：外部 runbook / 审计仍可能引用这个路径（故未直接删除），
    若头部没有显著废弃标注，读者会以为它是权威全量脚本。
    """

    FULL = Path(__file__).parent.parent.parent / "docs" / "sql" / "schema_full.sql"
    CANONICAL = Path(__file__).parent.parent.parent / "docs" / "sql" / "schema.sql"

    @staticmethod
    def _tables(p: Path) -> set:
        src = _strip_sql_comments(p.read_text(encoding="utf-8"))
        return {m.lower() for m in
                re.findall(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`]?(\w+)", src, re.I)}

    def test_deprecation_banner_present_while_drift_persists(self):
        """有漂移 → 必须有废弃标注；无漂移 → 标注必须撤掉（防标注本身过期）"""
        full_sql = self.FULL.read_text(encoding="utf-8")
        drift = self._tables(self.CANONICAL) ^ self._tables(self.FULL)
        has_banner = "已废弃" in full_sql and "DEPRECATED" in full_sql

        if drift:
            assert has_banner, (
                f"schema_full.sql 与 schema.sql 仍有 {len(drift)} 张表漂移 "
                f"{sorted(drift)[:6]}，但文件头部没有废弃标注 —— "
                "读者会把它当成权威全量脚本。"
            )
            assert "docs/sql/schema.sql" in full_sql, (
                "废弃标注必须明确指向正确入口 docs/sql/schema.sql"
            )
        else:
            assert not has_banner, (
                "schema_full.sql 已与 schema.sql 对齐（无漂移），"
                "请撤掉废弃标注（否则标注本身变成错误信息）"
            )

    def test_drift_is_documented_in_banner(self):
        """标注里点名的缺失表必须与实际漂移一致（防写了但写错）"""
        full_sql = self.FULL.read_text(encoding="utf-8")
        missing = self._tables(self.CANONICAL) - self._tables(self.FULL)
        if not missing:
            return  # 已对齐情形由上一条用例负责
        header = full_sql[:2000]
        undocumented = [t for t in sorted(missing) if t not in header]
        assert not undocumented, (
            f"以下缺失表未在废弃标注里列出：{undocumented} —— 标注与事实不符"
        )


def _column_name_of_ddl_line(line: str):
    """从 `CREATE TABLE` 体内的一行解析列名；非列定义返回 None。

    ⚠️ 不能用"首词是关键字就跳过"的写法：`key` 既是 SQL 关键字又是合法列名
    （`user_memories.key VARCHAR(128)`）。首版即因此把该列判为"不存在"，
    产生假缺口。判据改为：**第二个词必须是类型名**，而 `PRIMARY KEY (...)` /
    `UNIQUE (...)` / `CONSTRAINT ...` 的第二个词是 `KEY`/`(` 这类，自然被排除。
    """
    m = re.match(r'\s*"?(\w+)"?\s+(\w+)', line)
    if not m:
        return None
    name, second = m.group(1).lower(), m.group(2).upper()
    if second in {"KEY", "CONSTRAINT", "INDEX", "CHECK", "UNIQUE", "PRIMARY",
                  "FOREIGN", "EXCLUDE", "LIKE", "AS"}:
        return None
    return name


class TestSchemaCoversMigrationChainColumns:
    """`schema.sql` 必须覆盖**迁移链**的全部表与列（issue #3270 实测根因）

    CI 实证（run 34617597854，postgres 日志原文）：C 端验收栈的库由
    `docs/sql/schema.sql` 经 docker-entrypoint-initdb.d 建立，而 **Flyway 不在该栈运行**
    → 只存在于迁移链的列**建库后并不存在** →

        column "actual_amount" does not exist      (orders，来自 V5/V14)
        column "position" does not exist           (users，来自 docs/sql/migrations)
        ... → admin-api 查询 500 → ai-agent 工具拿到 "服务暂时不可用"(CIRCUIT_OPEN)
        → 熔断器打开 → 后续同类工具调用**全部失败** → 整轮评测被污染

    现象是「agent 不会下单/不会建售后单」，真因是**后端 500 + 熔断**（基础设施层）。
    本测试把「bootstrap 必须与迁移链终态一致」变成可执行约束。
    """

    MIGRATION_DIRS = [
        Path(__file__).parent.parent.parent / "backend" / "admin-api" / "src" / "main" / "resources" / "db" / "migration",
        Path(__file__).parent.parent.parent / "docs" / "sql" / "migrations",
    ]

    # schema.sql 里以 `key` 这类 SQL 关键字命名的列，解析时需特判（否则被当约束跳过）
    _NON_COLUMN = {"primary", "unique", "constraint", "foreign", "check", "key", "exclude"}

    @classmethod
    def _schema_columns(cls) -> dict:
        src = _strip_sql_comments(SCHEMA.read_text(encoding="utf-8"))
        tables: dict = {}
        for m in re.finditer(
                r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)\"?\s*\(([\s\S]*?)\n\)\s*;",
                src, re.I):
            name, body = m.group(1).lower(), m.group(2)
            cols = set()
            for line in body.splitlines():
                col = _column_name_of_ddl_line(line)
                if col:
                    cols.add(col)
            tables[name] = cols
        for m in re.finditer(
                r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?\"?(\w+)\"?[\s\S]*?;", src, re.I):
            t = m.group(1).lower()
            for cm in re.finditer(
                    r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)\"?", m.group(0), re.I):
                tables.setdefault(t, set()).add(cm.group(1).lower())
        return tables

    @classmethod
    def _migration_requirements(cls) -> tuple:
        """从两条迁移链提取 (表 -> 列) 要求"""
        need: dict = {}
        superseded: set = set()  # 被后续迁移改名/删除的表（非终态要求）
        for d in cls.MIGRATION_DIRS:
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.sql")):
                src = _strip_sql_comments(f.read_text(encoding="utf-8"))
                for m in re.finditer(
                        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)\"?\s*\(([\s\S]*?)\n\)\s*;",
                        src, re.I):
                    t, body = m.group(1).lower(), m.group(2)
                    need.setdefault(t, set())
                    for line in body.splitlines():
                        col = _column_name_of_ddl_line(line)
                        if col:
                            need[t].add(col)
                for m in re.finditer(
                        r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?\"?(\w+)\"?([\s\S]*?);", src, re.I):
                    t = m.group(1).lower()
                    for cm in re.finditer(
                            r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)\"?", m.group(2), re.I):
                        need.setdefault(t, set()).add(cm.group(1).lower())
                    # 重命名（如 V37 把 knowledge_entries 改名为 knowledge_cards）：
                    # 旧表名不是"终态要求"，必须剔除，否则产生假缺口。
                    if re.search(r"RENAME\s+TO\s+", m.group(2), re.I):
                        superseded.add(t)
                for m in re.finditer(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?\"?(\w+)\"?", src, re.I):
                    superseded.add(m.group(1).lower())
        for t in superseded:
            need.pop(t, None)
        return need

    def test_requirements_are_non_trivial(self):
        """自检：确实解析出要求（否则本类测试空转 = 假绿）"""
        need = self._migration_requirements()
        total = sum(len(v) for v in need.values())
        # 阈值只为"解析没坏"兜底：实测两条链约 23 表 / 130+ 列（已剔除被改名/删除的表）。
        # 取宽松下界，避免正常增删迁移就误报。
        assert len(need) >= 15 and total >= 100, (
            f"迁移链解析结果过少（表 {len(need)} / 列 {total}）—— 解析疑似失效"
        )

    def test_schema_covers_migration_chain(self):
        schema = self._schema_columns()
        missing_tables, missing_cols = [], []
        for table, cols in self._migration_requirements().items():
            if table not in schema:
                missing_tables.append(table)
                continue
            for c in sorted(cols - schema[table]):
                missing_cols.append(f"{table}.{c}")
        assert not missing_tables, (
            "schema.sql 缺少迁移链已建的表（bootstrap 不完整 → 建库后 admin-api 查询 500）：\n  "
            + "\n  ".join(sorted(missing_tables))
        )
        assert not missing_cols, (
            "schema.sql 缺少迁移链已加的列（bootstrap 不完整 → 建库后 admin-api 查询 500 "
            "→ 工具返回「服务暂时不可用」→ 熔断 → 评测被污染）：\n  "
            + "\n  ".join(missing_cols)
            + "\n修复：在 schema.sql 的「bootstrap 对齐」段补 ALTER TABLE ... ADD COLUMN IF NOT EXISTS，"
              "并同步新增迁移（迁移链是结构变更事实源）。"
        )


class TestSchemaCoversEntityColumns:
    """`schema.sql` 必须覆盖 **Java 实体声明**的表与列（迁移链守卫的互补项）

    为什么还需要这一层：有些列**两条 SQL 链都没有**，只在 Java 实体里声明 ——
    生产库里存在（否则线上同类查询也 500），但 bootstrap 建出来的库没有：

        product_skus.color_name   ← ProductSku.colorName（admin-api 拉 SKU 列表 SELECT 它）
        orders.close_reason       ← Order.closeReason（docs/sql/013 有，迁移链没有）
        tenant_ai_configs.bot_name← TenantAiConfig.botName（docs/sql/009 有）
        user_memories（整表）      ← UserMemory 实体

    CI 实证：`column "color_name" does not exist` → 商品详情接口 500 → 工具返回
    「服务暂时不可用」→ 熔断 → **整轮 C 端评测被污染**。
    迁移链守卫查不到这类列（它们不在任何迁移里），故必须按实体再查一遍。
    """

    ENTITY_DIR = (Path(__file__).parent.parent.parent / "backend" / "admin-api"
                  / "src" / "main" / "java" / "com" / "migao" / "admin" / "entity")

    # 非列字段（MyBatis-Plus 约定 / Java 常量）
    _SKIP_FIELDS = {"serialVersionUID"}

    @staticmethod
    def _snake(name: str) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()

    @classmethod
    def _entities(cls) -> dict:
        """{表名: {列名: 'Entity.java#field'}}"""
        out: dict = {}
        for f in sorted(cls.ENTITY_DIR.glob("*.java")):
            src = f.read_text(encoding="utf-8")
            tm = re.search(r'@TableName\(\s*(?:value\s*=\s*)?"(\w+)"', src)
            if not tm:
                continue
            table = tm.group(1).lower()
            # 去掉 @TableField(exist = false) 标注的字段（非表列）
            cleaned = re.sub(
                r"@TableField\([^)]*exist\s*=\s*false[^)]*\)[\s\S]{0,120}?;", "", src)
            cols = out.setdefault(table, {})
            for fm in re.finditer(
                    r'(?:@TableField\(\s*(?:value\s*=\s*)?"(\w+)"[^)]*\)\s*)?'
                    r"private\s+[\w<>,\[\]\. ]+\s+(\w+)\s*;", cleaned):
                explicit, field = fm.group(1), fm.group(2)
                if field in cls._SKIP_FIELDS:
                    continue
                col = explicit.lower() if explicit else cls._snake(field)
                cols.setdefault(col, f"{f.name}#{field}")
        return out

    def test_entity_parse_is_non_trivial(self):
        """自检：确实解析出实体与列（否则本类测试空转 = 假绿）"""
        ents = self._entities()
        total = sum(len(v) for v in ents.values())
        assert len(ents) >= 20 and total >= 200, (
            f"实体解析结果过少（表 {len(ents)} / 列 {total}）—— 解析疑似失效"
        )

    def test_schema_covers_entity_columns(self):
        schema = TestSchemaCoversMigrationChainColumns._schema_columns()
        missing_tables, missing_cols = [], []
        for table, cols in self._entities().items():
            if table not in schema:
                missing_tables.append(table)
                continue
            for c, origin in sorted(cols.items()):
                if c not in schema[table]:
                    missing_cols.append(f"{table}.{c}  ({origin})")
        assert not missing_tables, (
            "schema.sql 缺少 Java 实体声明的表（建库后相关接口必然 500）：\n  "
            + "\n  ".join(sorted(missing_tables))
        )
        assert not missing_cols, (
            "schema.sql 缺少 Java 实体声明的列 —— 建库后该接口 500 → ai-agent 工具返回"
            "「服务暂时不可用」→ 熔断 → 评测被污染：\n  "
            + "\n  ".join(missing_cols)
            + "\n修复：在 schema.sql 的「bootstrap 对齐」段补 ALTER TABLE ... ADD COLUMN "
              "IF NOT EXISTS，**并新增迁移**（迁移链是结构变更事实源）。"
        )


class TestEvalArtifactAuditStep:
    """workflow 必须审计 Eval 期间 agent **实际落库**的产物（acceptance-protocol §2.2）

    为什么：round_trace 证明「工具被调用了」，但不证明「数据真的落库了」。
    §2.2（2026-09-08 复盘）要求复核 AI 留下的会话/工单/订单 —— 报告说"创建成功"、
    库里没有（或相反）都是翻车样本。CI 评测的库是**每次销毁的临时库**，所以
    复核必须在销毁前以 workflow 步骤自动化：dump agent_sessions / orders /
    after_sales_tickets / user_memories，与报告的 tool_calls 对得上才算闭环。
    """

    def _wf(self) -> dict:
        import yaml
        return yaml.safe_load((WORKFLOWS_DIR / "xiaobu-acceptance.yml").read_text(encoding="utf-8")) or {}

    def _step(self):
        steps = self._wf()["jobs"]["xiaobu-acceptance"]["steps"]
        return next((s_ for s_ in steps if "DB 审计" in (s_.get("name") or "")), None)

    def test_step_exists_after_eval_with_always(self):
        steps = self._wf()["jobs"]["xiaobu-acceptance"]["steps"]
        names = [s_.get("name") or "" for s_ in steps]
        i_audit = next((i for i, n in enumerate(names) if "DB 审计" in n), -1)
        i_eval = next((i for i, n in enumerate(names) if "local_runner" in n), -1)
        assert 0 <= i_eval < i_audit, (
            f"审计步骤必须在评测之后（i_eval={i_eval}, i_audit={i_audit}）"
        )
        assert self._step().get("if") == "always()", (
            "审计必须 if: always() —— 失败轮次更要看（失败≠没创建；成功≠真创建）"
        )

    def test_step_covers_all_write_artifacts(self):
        body = self._step().get("run") or ""
        for table in ("agent_sessions", "orders", "after_sales_tickets", "user_memories"):
            assert table in body, f"审计未覆盖表 {table}"
        # C 端评测会话在 ai-agent 的 sessions 表（`agent_sessions` 是人工会话表，
        # 只有 human_handoff 会写）——旧审计把两张表混为一谈，会话残留看不见（#3357）
        assert "FROM sessions" in body, "审计未统计 ai-agent 会话表 sessions"
        assert "status='active'" in body, "审计未统计未关闭残留会话（清理失效无人发现）"
        assert "ticket_type='complaint'" in body, "未单独统计转人工工单（CH-008/013/015 对账）"
        assert (self._step().get("env") or {}).get("DEV_SERVICE_TOKEN"), (
            "缺 DEV_SERVICE_TOKEN → compose 插值失败 → 审计为空"
        )

    def test_audit_prints_order_amounts(self):
        """审计必须带订单金额（issue #3361）：金额是 C 端最硬的正确性证据。

        只有金额能回答「下单成了，且钱算对了吗」。实测 OR-014 在没查商品详情的情况下
        发出的确认卡写着「遮光窗帘3米+打孔加工，合计¥95.4」（该商品真实单价 ¥168/米），
        无金额审计时这种「钱算错但工具调用成功」在报告里看着一切正常。
        """
        body = self._step().get("run") or ""
        assert "total_amount" in body, "审计未输出订单金额（金额错误无法发现）"

    def test_eval_creates_and_closes_ai_agent_sessions(self):
        """对照：评测每用例在 ai-agent 建会话，且收尾必须**关闭它**（issue #3357）。

        旧断言只查 `api/chat/sessions`（创建），于是"关闭打到了另一张表的接口、
        会话从未关闭、记忆候选从未 flush"这一整条链路断了却无人发现。现在把
        关闭接口也锁进契约：必须是 ai-agent 的 close（记忆 flush 的唯一入口）。
        """
        src = (Path(__file__).parent.parent.parent / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        assert "api/chat/sessions" in src, "runner 未创建会话（审计目标落空）"
        assert "/api/chat/sessions/{session_id}/close" in src, (
            "runner 未通过 ai-agent 关闭接口收尾 —— 记忆候选不会 flush，会话残留"
        )


class TestFalseGreenGuardInAudit:
    """审计必须把「写用例通过但 DB 无产物」显式标成假绿风险（调了 ≠ 成了）

    run 34678939564 实证：17/17 全绿但 orders 无新增 —— order_create 被确认门禁拦
    （confirmValue >24 字）或被 API 拒，用例却因「工具被调用」判通过。审计若只
    dump 数据、不对账，人还是要逐行自己看才能发现 —— 本测试要求审计里带对账告警。
    """

    def _wf(self) -> dict:
        import yaml
        return yaml.safe_load((WORKFLOWS_DIR / "xiaobu-acceptance.yml").read_text(encoding="utf-8")) or {}

    def _audit_body(self) -> str:
        steps = self._wf()["jobs"]["xiaobu-acceptance"]["steps"]
        step = next((s_ for s_ in steps if "DB 审计" in (s_.get("name") or "")), {})
        return step.get("run") or ""

    def test_audit_warns_when_orders_not_landed(self):
        body = self._audit_body()
        assert "假绿风险" in body, "审计缺少假绿告警文案"
        assert "orders=" in body and "ORDERS" in body, "未统计订单数并据此告警"
        assert "CH-010" in body, "告警未点名下单写用例"

    def test_audit_warns_when_memories_not_landed(self):
        """CH-024 通过但 user_memories 为空 = 记忆链断（或断言失效）→ 必须告警。"""
        body = self._audit_body()
        assert "memories=" in body and "MEMORIES" in body, "未统计记忆条数并据此告警"
        assert "CH-024" in body, "记忆告警未点名跨会话记忆用例"

    def test_eval_emits_all_traces(self):
        """写用例成败必须可见：通过用例的轨迹也要打（否则写工具结果藏在暗处）"""
        steps = self._wf()["jobs"]["xiaobu-acceptance"]["steps"]
        step = next((s_ for s_ in steps if "local_runner" in (s_.get("name") or "")), {})
        assert (step.get("env") or {}).get("AGENT_EVAL_TRACE_ALL") == "1", (
            "未开启全量轨迹 —— 通过的写用例的工具结果（如 order_create 被拒）看不见"
        )


class TestFixtureOrderIdsAreUuidShaped:
    """fixture 的订单主键必须是 **UUID 形态**（与生产一致）

    实证（run 34684474262，CH-012）：`aftersale_create` 报
    「无法找到订单：ord_eval_0002。请确认订单号正确后重试。」—— 用例判通过（工具被调用）
    但工单没落库，DB 审计里 8 张工单全是 complaint、无 refund。

    根因（admin-api `AfterSalesTicketService.createTicketForAgent`）：
    orderId 的解析是二分启发式 —— 形如 `^[0-9a-fA-F-]{20,}$` 当 **UUID** 直查主键，
    否则当 **订单号** 查 order_no。fixture 此前用 `ord_eval_0002` 这种短 id：
    既非 UUID 形态（且含非 hex 字符），于是被当成订单号 → 查不到 → 404。
    **生产订单主键是 UUID**，故 fixture 必须同形，否则评测链路与生产不一致（假失败）。
    """

    # 与 admin-api 的判据保持一致（单一事实源：AfterSalesTicketService.createTicketForAgent）
    UUID_HEURISTIC = re.compile(r"^[0-9a-fA-F-]{20,}$")

    def _order_ids(self) -> list:
        sql = _strip_sql_comments(FIXTURE.read_text(encoding="utf-8"))
        stmt = re.search(r"INSERT\s+INTO\s+orders\b[\s\S]*?;", sql, re.I)
        assert stmt, "未找到 orders 种子语句"
        return re.findall(r"\(\s*'([0-9a-zA-Z_\-]+)'\s*,\s*1\s*,\s*'EVAL-ORD-", stmt.group(0))

    def test_order_ids_satisfy_backend_uuid_heuristic(self):
        ids = self._order_ids()
        assert len(ids) >= 2, f"仅解析出 {len(ids)} 个订单主键 —— 解析疑似失效"
        bad = [i for i in ids if not self.UUID_HEURISTIC.match(i)]
        assert not bad, (
            f"以下订单主键不满足后端 UUID 判据 {self.UUID_HEURISTIC.pattern}：{bad}\n"
            "后果：agent 传该 id 时被当成订单号去查 order_no → 404「无法找到订单」→ "
            "售后工单不落库（而用例因『工具被调用』假绿）。"
        )

    def test_item_and_logistics_reference_the_same_ids(self):
        """订单明细/物流的 order_id 外键必须指向同一批 UUID 主键"""
        sql = _strip_sql_comments(FIXTURE.read_text(encoding="utf-8"))
        ids = set(self._order_ids())
        referenced = set(re.findall(r"'(a1b2c3d4-[0-9a-f\-]+)'", sql)) - ids
        assert not referenced, f"明细/物流引用了不属于订单主键集合的 id：{referenced}"
