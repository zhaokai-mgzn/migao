# case_ids: PG-065, PG-072, BM-006
"""「工人端页面（企业级）配置层」移除的**类级元守卫**（issue #6828）。

## 为什么要有它（修一个缺陷只修这一处 = 没修）

issue #6828 把「工人端出现哪些页面」从**两层**（企业级 `worker_page_configs` ∩ 工人档案级
`users.worker_pages`）收成**一层**（只有档案级），并整层删除了企业级那套载体：

| 被删对象 | 载体 |
|---|---|
| 表 | `backend/admin-api/src/main/resources/db/migration/V141__create_worker_page_configs.sql`（由 `V154__drop_worker_page_configs.sql` DROP） |
| 端点 | `GET/PUT /api/admin/worker-page-config` |
| 服务 / 实体 / mapper | `WorkerPageConfigService` / `WorkerPageConfig` / `WorkerPageConfigMapper` |
| 商家面 | 设置页「工人端页面」域 + `frontend/admin-web/src/components/settings/WorkerPageConfigPanel.tsx` |
| 逐人勾选的选项来源 | 改为只读目录端点 `GET /api/admin/worker-pages`（`WorkerPageCatalogController`） |

**只删这一遍 = 没修**：这个「层」会在下一次「顺手加个企业级开关」时**无声复活** ——
表被重新建出来、端点被重新挂上，而两层求交的空集 fail-open 语义（`effectiveForOrFallback`
那一族坑，#6805 记录过）会再踩一遍，且**没有任何东西会变红**。
⇒ 本文件把这些不变量钉成常驻判据（每条都带判别力自证）。

## 判据（1~6）

1. **符号与文件面**：已退场的类 / 组件 / API 客户端符号在受扫源码里**零命中**，且它们**自己的文件不存在**；
2. **端点面**：源码里不得再出现**带引号的** `/api/admin/worker-page-config`（注释里追述历史不算 —— 本判据只认字符串字面量）；
3. **DB 面**：`db/init/schema.sql` 基线不得再有 `worker_page_configs`；且**必须**有一条迁移 `DROP TABLE IF EXISTS worker_page_configs`（表回来了却没有 drop ⇒ 红）；
4. **商家面**：域目录 `config-center-domains.ts` 不得再有 `'worker-pages'` 域；设置页必须给出旧深链 `?tab=workerPages` 的确定性落点；
5. **替代面在场**：目录端点（`WorkerPageCatalogController` + `production:view`）与档案面板的消费点（`workerPageCatalogApi`）都必须真实存在（**否则「移除」会变成「工人菜单配不了」**）；
6. **判别力自证**：上述每条判据的坏形态在**内存语料**上各自判红，且一条**对照语料**（只改注释）不红。

## 边界（照实登记）

- 判的是**结构面**（符号 / 文件 / 字符串 / 迁移语句在不在），不是行为面
  —— 「`/api/worker/me` 下发的页集对不对」由 Java 单测承担（`WorkerPagesTest` / `WorkerProfileControllerTest`）；
- 扫描面只覆盖**源码与迁移**（`backend/admin-api/src`、`frontend/admin-web/src`、`frontend/worker-h5/src`、
  `db/init/schema.sql`、`db/migration/*.sql`）。`docs/` 与 `CHANGELOG.md` **不在射程**：
  它们是历史记载，本来就该写「曾经有过这一层」（否则后人读不懂改判）。
- **符号判据只看代码行**（整行注释 / 单行块注释被剥掉，见 `_code_only`）：注释里追述这段历史
  （「历史：曾用 X，issue #NNNN 移除」）**不算红** —— 否则判据会被自己的文档喂红。
- 不跑任何 Java / vitest（元守卫不嵌套跑别的套件，避免把「未登记即红」退化成全量重跑）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 受扫源码根（**只扫代码**；docs / CHANGELOG / acceptance 归档是历史记载，不在射程）。
SOURCE_ROOTS = (
    REPO_ROOT / "backend" / "admin-api" / "src",
    REPO_ROOT / "frontend" / "admin-web" / "src",
    REPO_ROOT / "frontend" / "worker-h5" / "src",
)

SCHEMA_SQL = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "db" / "init" / "schema.sql"
MIGRATION_DIR = REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources" / "db" / "migration"
DOMAINS_TS = REPO_ROOT / "frontend" / "admin-web" / "src" / "lib" / "config-center-domains.ts"
SETTINGS_PAGE = REPO_ROOT / "frontend" / "admin-web" / "src" / "app" / "(dashboard)" / "settings" / "page.tsx"
CATALOG_CONTROLLER = (REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao"
                      / "admin" / "controller" / "WorkerPageCatalogController.java")
PANEL_TSX = (REPO_ROOT / "frontend" / "admin-web" / "src" / "components" / "employees"
             / "WorkerProfilesPanel.tsx")

#: 已退场的**代码符号**（在**代码行**里出现即红）。注意：只收**符号**，不收端点路径 / 表名 ——
#: 后者在「追述这段历史的注释」里是合法的（本仓允许注释解释改判来由）。判据只看**非注释行**（见 `_code_only`）。
#:
#: ⚠️ `effectiveForOrFallback` 这**一条**不收在这里：它是「两层求交」的方法名，而
#: `backend/admin-api/src/test/java/com/migao/admin/worker/WorkerPagesTest.java` 的
#: `exposesNoTwoLayerEntryPoint` 正是**断言它不存在**的地方（把它列进本表会让那条判据自己踩自己）。
#: 那条的结构面判据更强：它检查 `WorkerPages` 的方法集合里没有该名、且 `effectiveFor` 恰一个参数。
RETIRED_SYMBOLS = (
    "WorkerPageConfigService",
    "WorkerPageConfigMapper",
    "WorkerPageConfigController",
    "WorkerPageConfigPanel",
    "WorkerPageConfigResponse",
    "WorkerPageConfigBody",
    "workerPageConfigApi",
    "DOMAIN_WORKER_PAGES",
)

#: 已退场的**文件**（存在即红）。
RETIRED_PATHS = (
    "backend/admin-api/src/main/java/com/migao/admin/controller/WorkerPageConfigController.java",
    "backend/admin-api/src/main/java/com/migao/admin/service/WorkerPageConfigService.java",
    "backend/admin-api/src/main/java/com/migao/admin/mapper/WorkerPageConfigMapper.java",
    "backend/admin-api/src/main/java/com/migao/admin/entity/WorkerPageConfig.java",
    "backend/admin-api/src/test/java/com/migao/admin/controller/WorkerPageConfigControllerTest.java",
    "backend/admin-api/src/test/java/com/migao/admin/service/WorkerPageConfigServiceTest.java",
    "backend/admin-api/src/test/java/com/migao/admin/mapper/WorkerPageConfigMapperTest.java",
    "frontend/admin-web/src/components/settings/WorkerPageConfigPanel.tsx",
    "frontend/admin-web/tests/unit/components/WorkerPageConfigPanel.test.tsx",
)

#: 已退场的**端点字面量**（带引号出现即红；注释里的追述不带引号）。
RETIRED_ENDPOINT = '"/api/admin/worker-page-config"'

#: 迁移里必须留下的 DROP（表回来了却没有 drop ⇒ 红）。
DROP_STATEMENT = "DROP TABLE IF EXISTS worker_page_configs"


# ══════════════════════════════════════════════════════════════════════════════
# 纯函数（注入式自证驱动**同一份**本体）
# ══════════════════════════════════════════════════════════════════════════════

def _code_only(text: str) -> str:
    """剥掉**整行注释**（`//` / `*` / `/*` 开头的行）与单行 `/* … */` 块，只留代码行。

    为什么需要它：本仓允许注释追述改判来由（「历史：曾用 X，issue #NNNN 移除」），
    若把注释里提到已删符号也算红，判据就会被自己的文档喂红（**假红**，且会逼后人删掉那段历史）。
    ⚠️ 覆盖边界：只处理**整行**注释与**单行**块注释；跨行块注释里的符号仍会被读到
    （宁严勿滥：跨行块注释里写已删符号，改写成 `{@code}` 之外的形态即可）。
    """
    kept = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        if "/*" in line and "*/" in line and line.index("/*") < line.index("*/"):
            line = line[: line.index("/*")] + line[line.index("*/") + 2:]
        kept.append(line)
    return "\n".join(kept)


def stale_symbols(sources: dict, symbols=RETIRED_SYMBOLS):
    """`{文件: [命中的符号, ...]}` —— 已退场符号在受扫源码**代码行**里的残留（空 = 干净）。"""
    out = {}
    for name, text in sources.items():
        code = _code_only(text)
        hits = [s for s in symbols if s in code]
        if hits:
            out[name] = hits
    return out


def schema_still_has_the_table(schema_sql: str) -> bool:
    """基线建库脚本里还有那张表 ⇒ True（应删不删）。"""
    return "worker_page_configs" in schema_sql


def migrations_drop_the_table(migration_texts: list) -> bool:
    """恰有一条迁移真的 DROP 掉那张表。"""
    return sum(1 for t in migration_texts if DROP_STATEMENT in t) == 1


def domain_is_gone(domains_ts: str) -> bool:
    """域目录里不再有 `worker-pages` 域（字符串字面量形态）。"""
    return "'worker-pages'" not in domains_ts


def legacy_link_has_a_landing(settings_page: str) -> bool:
    """旧深链 `?tab=workerPages` 有确定性落点（`LEGACY_TAB_REDIRECTS` 里有 workerPages）。"""
    return bool(re.search(r"LEGACY_TAB_REDIRECTS[^=]*=\s*\{[^}]*workerPages\s*:\s*'/[^']+'", settings_page, re.S))


def replacement_surface_is_wired(catalog_controller: str, panel_tsx: str) -> list:
    """替代面必须真实接线；返回问题清单（空 = 通过）。"""
    problems = []
    if "production:view" not in catalog_controller:
        problems.append("目录端点没挂 production:view（商家面读码缺失）")
    if '"/api/admin/worker-pages"' not in catalog_controller:
        problems.append("目录端点的路径不是 /api/admin/worker-pages")
    if "workerPageCatalogApi.get()" not in panel_tsx:
        problems.append("工人档案面板没消费目录端点（工人菜单会配不了）")
    return problems


# ══════════════════════════════════════════════════════════════════════════════
# 读真实语料
# ══════════════════════════════════════════════════════════════════════════════

def _source_texts(roots=SOURCE_ROOTS) -> dict:
    out = {}
    for root in roots:
        assert root.is_dir(), f"受扫源码根不存在：{root}（路径漂移 ⇒ 红，不得静默跳过）"
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix not in {".java", ".ts", ".tsx", ".mjs", ".js", ".sql", ".yml", ".yaml", ".json"}:
                continue
            out[str(p.relative_to(REPO_ROOT))] = p.read_text(encoding="utf-8", errors="replace")
    assert out, "受扫源码集为空 ⇒ 本判据空转（假绿）"
    return out


def _read(path: Path) -> str:
    assert path.is_file(), f"被判据引用的文件不存在：{path}（路径漂移 ⇒ 红）"
    return path.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1~5
# ══════════════════════════════════════════════════════════════════════════════

def test_retired_symbols_and_files_are_gone():
    """判据 1：已退场的符号在源码里零命中，且它们自己的文件不存在。"""
    hits = stale_symbols(_source_texts())
    assert not hits, (
        "已退场的企业级页面开关符号又出现在源码里（issue #6828 移除了那一层）：\n  "
        + "\n  ".join(f"{f}: {syms}" for f, syms in sorted(hits.items()))
        + "\n⇒ 要么删掉新引入的引用，要么在 issue 里说明为什么这一层要回来（两层求交的 fail-open 坑见 #6805）。"
    )
    alive = [p for p in RETIRED_PATHS if (REPO_ROOT / p).is_file()]
    assert not alive, f"已退场的文件又回来了：{alive}"


def test_retired_endpoint_literal_is_gone():
    """判据 2：源码里不得再有**带引号**的旧端点字面量（注释追述历史不算）。"""
    sources = _source_texts()
    hits = [name for name, text in sources.items() if RETIRED_ENDPOINT in text]
    assert not hits, (
        f"旧端点 {RETIRED_ENDPOINT} 又被挂上了：{hits}\n"
        "⇒ 企业级页面开关已整层移除（issue #6828）；商家面只需要只读目录端点 /api/admin/worker-pages。"
    )


def test_baseline_schema_has_no_tenant_table_and_a_migration_drops_it():
    """判据 3：基线不再建那张表，且有一条迁移真的 DROP 它。"""
    assert not schema_still_has_the_table(_read(SCHEMA_SQL)), (
        "`db/init/schema.sql` 基线里还有 worker_page_configs ⇒ 新建库会建出**已退场**的表"
        "（bootstrap 库与存量库两份真相，#3270 形态）。结构变更必须同步进基线。"
    )
    migs = [p.read_text(encoding="utf-8") for p in sorted(MIGRATION_DIR.glob("V*.sql"))]
    assert migrations_drop_the_table(migs), (
        f"没有任何**恰一条**迁移含 `{DROP_STATEMENT}` ⇒ 存量库里的那张表不会消失"
        "（而它承载的是已退场的配置层）。"
    )
    # 反向：档案级那一层**必须**还在（移除的是企业级，不是逐人收窄）
    schema = _read(SCHEMA_SQL)
    assert "worker_pages" in schema, "`users.worker_pages`（V152，唯一的页面集真值）不该被一起删掉"


def test_settings_domain_removed_and_legacy_link_lands_somewhere():
    """判据 4：设置页不再有那一域，且旧深链有确定落点（不落空白、不复活该域）。"""
    domains_ts = _read(DOMAINS_TS)
    assert domain_is_gone(domains_ts), (
        "`config-center-domains.ts` 里又出现了 `worker-pages` 域 ⇒ 设置页会重新长出那个配置面（issue #6828 已移除）"
    )
    settings = _read(SETTINGS_PAGE)
    assert legacy_link_has_a_landing(settings), (
        "旧深链 `?tab=workerPages` 没有确定性落点（`LEGACY_TAB_REDIRECTS` 缺条目）⇒ 收藏了这一页的商家会落到空白"
    )
    assert "'worker-pages'" not in settings, "设置页不得再渲染/引用已移除的 `worker-pages` 域"


def test_replacement_surface_is_present():
    """判据 5：移除之后，「逐人配菜单」仍配得动（目录端点 + 面板消费点都在）。"""
    problems = replacement_surface_is_wired(_read(CATALOG_CONTROLLER), _read(PANEL_TSX))
    assert not problems, "移除企业级层之后替代面不完整：\n  " + "\n  ".join(problems)


# ══════════════════════════════════════════════════════════════════════════════
# 判据 6：判别力自证（坏形态在内存语料上各自判红 + 对照语料不红）
# ══════════════════════════════════════════════════════════════════════════════

def test_guard_has_discriminating_power_on_mutated_corpus():
    """判据 6：每条判据的坏形态都**真的会红**（不是恒绿），且只改注释的对照语料不红。"""
    clean = {"a/X.java": "class X { }", "b/Y.tsx": "export const y = 1"}
    assert stale_symbols(clean) == {}
    assert stale_symbols({"a/X.java": "import com.migao.admin.service.WorkerPageConfigService;"}) != {}
    assert stale_symbols({"b/Y.tsx": "workerPageConfigApi.get()"}) != {}

    assert schema_still_has_the_table("CREATE TABLE worker_page_configs (id text);") is True
    assert schema_still_has_the_table("CREATE TABLE users (worker_pages JSONB);") is False

    assert migrations_drop_the_table(["DROP TABLE IF EXISTS worker_page_configs;"]) is True
    assert migrations_drop_the_table(["SELECT 1;"]) is False
    # 两条迁移各 DROP 一次（重复登记）也算异常形态
    assert migrations_drop_the_table(["DROP TABLE IF EXISTS worker_page_configs;"] * 2) is False

    assert domain_is_gone("export const CONFIG_DOMAINS = []") is True
    assert domain_is_gone("key: 'worker-pages',") is False

    assert legacy_link_has_a_landing("const LEGACY_TAB_REDIRECTS: Record<string,string> = { workerPages: '/employees' }") is True
    assert legacy_link_has_a_landing("const LEGACY_TAB_TO_DOMAIN = {}") is False

    assert replacement_surface_is_wired('production:view "/api/admin/worker-pages"', "workerPageCatalogApi.get()") == []
    assert replacement_surface_is_wired('"/api/admin/worker-pages"', "workerPageCatalogApi.get()") != []
    assert replacement_surface_is_wired('production:view "/api/admin/worker-pages"', "workerPageConfigApi.get()") != []

    # 对照语料：**只改注释**（追述历史）不红 —— 本仓允许注释解释改判来由
    comment_only = {"a/X.java": "/** 历史：曾用 WorkerPageConfigService 与 /api/admin/worker-page-config（issue #6828 移除） */"}
    assert stale_symbols(comment_only) == {}, "注释里追述历史也算红 ⇒ 判据会被自己的文档喂红（假红）"
