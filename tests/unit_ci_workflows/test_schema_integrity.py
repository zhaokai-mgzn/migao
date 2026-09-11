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
# case_ids: MC-012, CH-010
import re
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
