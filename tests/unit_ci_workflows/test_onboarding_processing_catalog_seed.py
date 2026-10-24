# case_ids: MC-114
"""开租默认加工项目录的**三源收敛**守卫（issue #7148）。

## 病（本文件要挡的形态）

加工项目录的种子有**两条历史路径**，都是「对当时的租户循环」：

| 载体 | 覆盖谁 |
|---|---|
| `backend/admin-api/src/main/resources/db/migration-archive/V83__seed_processing_item_catalog.sql` | 迁移时**已存在**的租户 |
| `backend/admin-api/src/main/resources/db/init/schema.sql` 的 V83 终态块（同一口径的 bootstrap 副本） | 建库时**已存在**的租户 |

⇒ 迁移之后新入驻的租户目录是 **0 行**（形态同 #4316 的工序库、#6295 的商品分类）。
#7148 的修法 = 入驻链路里用 **Java 常量目录**（`ProcessingItemSeedService.CATALOG`）播种。

**新增第三份目录副本 = 新增一个会漂移的真值源**：以后谁改了库里的目录（或新加一条撤出迁移），
Java 那份**不会跟着变，也不会有任何东西变红** —— 新租户拿到的目录与老租户静默分叉。
本守卫把这条漂移变成**当场红**。

## 判据（每条都能单独变红）

1. **Java 目录 ⇄（bootstrap 目录 − 活迁移的撤出项 + 改名映射）逐条同值**（名字 + `craftHint`）——
   这是本守卫的主判据。撤出项从**迁移本身**读（V123 撤 `接高`），改名从
   `_migration_renames.processing_item_renames()` 读（V139 `韩折`→`韩褶`）—— **判据里不另抄一份名单**；
2. **分类名单一来源**：种子用的分类名 = `OnboardingInitialData.DEFAULT_PROCESSING_CATEGORY_NAME`，
   该字面量在 admin-api 主源码里**恰出现一次**（定义处），且其值 = bootstrap 种的那个分类名；
3. **种子服务引用常量而不是再抄一份字面量**（`OnboardingInitialData.DEFAULT_PROCESSING_CATEGORY_NAME` 在代码里）；
4. **判别力自证**（注入式，内存语料）：删一行 / 改一个字 / 改 `craftHint` / 把目录清空 /
   把「接高」的撤出迁移从语料里去掉 —— 主判据各自判红；**只改注释 ⇒ 不红**（判据不被自己的文案喂红）。

## 边界（照实登记，`migao-dev-flow` §19.1）

- 判的是**数据面**（目录内容同不同值），不是「播种那段代码真的跑在真入驻链路里」——
  后者由 `backend/admin-api/src/test/java/com/migao/admin/service/NewTenantOnboardingCategoryRealDbTest.java`
  与 `ProcessingItemSeedServiceTest.java` 承担；
- 「清单里登记了这条必需初始数据、且入驻链路真的调了它」由既有元守卫
  `tests/unit_ci_workflows/test_onboarding_required_seed_guard.py` 承担（本文件**不重复**判它）；
- 只裁**目录（名字 + 工艺声明）**；`description` / `unit` / 排位不在此面（文案改动不该红在这里）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_processing_catalog_seed as catalog_guard  # noqa: E402
from unit_ci_workflows._migration_paths import INIT_SCRIPT, migration_files  # noqa: E402
from unit_ci_workflows._migration_renames import processing_item_renames  # noqa: E402

SERVICE_DIR = REPO / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao" / "admin"
SEED_SERVICE = SERVICE_DIR / "service" / "ProcessingItemSeedService.java"
CHECKLIST = SERVICE_DIR / "service" / "OnboardingInitialData.java"

#: 目录项形态：`new CatalogItem("名字", null|"工艺声明", "描述")`（**不写行号**；换行无关）
_CATALOG_ITEM_RE = re.compile(
    r'new\s+CatalogItem\(\s*"([^"]+)"\s*,\s*(null|"([^"]*)")\s*,\s*"([^"]*)"\s*\)')
#: 分类名常量（单一来源在清单类里）
_CATEGORY_CONST_RE = re.compile(r'DEFAULT_PROCESSING_CATEGORY_NAME\s*=\s*"([^"]*)"')
#: 撤出迁移里 `name = '<项名>'` 的谓词
_RETIRE_NAME_RE = re.compile(r"name\s*=\s*'([^']+)'")
#: `UPDATE processing_items … SET … deleted = 1 …`（撤出 = 软删）
_RETIRE_STMT_RE = re.compile(r"UPDATE\s+processing_items\b", re.I)


# ────────────────────────────────────── 解析工具（纯函数：真语料与变异语料共用）

def _strip_java_comments(text: str) -> str:
    """去掉 Java 的 `//` 与 `/* … */` 注释，**保留字符串字面量**（目录数据就在字符串里）。"""
    out: list[str] = []
    i, n = 0, len(text)
    in_line = in_block = in_str = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if ch == "\n":
                in_line = False
                out.append(ch)
            i += 1
            continue
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if ch == '"':
            in_str = True
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_sql_comments(sql: str) -> str:
    """去掉 SQL 的 `--` 行注释与 `/* */` 块注释（判据读**可执行**语句，不读解释性示例）。"""
    without_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return "\n".join(re.sub(r"--.*$", "", line) for line in without_block.splitlines())


def java_catalog(text: str) -> dict:
    """`ProcessingItemSeedService` 源码 → `{名字: craftHint}`（注释不算；读不出 ⇒ fail-closed）。"""
    code = _strip_java_comments(text)
    items = _CATALOG_ITEM_RE.findall(code)
    assert items, (
        f"`{SEED_SERVICE.name}` 里读不出 `new CatalogItem(\"名字\", null|\"工艺\", \"描述\")` 形态的目录项 —— "
        "种子目录被删 / 形态变了？本判据 fail-closed（读不到 ≠ 没问题）")
    return {name: (hint or None) for name, _raw, hint, _desc in items}


def java_category_constant(checklist_text: str) -> str:
    """从清单类（单一真值源）读默认加工分类名。"""
    m = _CATEGORY_CONST_RE.search(checklist_text)
    assert m, (
        f"`{CHECKLIST.name}` 里找不到 `DEFAULT_PROCESSING_CATEGORY_NAME = \"…\";` —— "
        "默认分类名的单一来源被删/改名了？")
    return m.group(1)


def retired_processing_item_names(sql: str) -> set:
    """撤出迁移 → 被软删的目录项名集合（只认 `UPDATE processing_items … deleted = 1` 的语句）。"""
    names: set[str] = set()
    for statement in _strip_sql_comments(sql).split(";"):
        if not _RETIRE_STMT_RE.search(statement):
            continue
        if not re.search(r"deleted\s*=\s*1", statement, re.I):
            continue
        names.update(_RETIRE_NAME_RE.findall(statement))
    return names


def all_retired_names() -> set:
    """归档 ∪ 活目录里**所有**撤出迁移的并集（新撤一条 ⇒ 本集合变大 ⇒ 主判据当场红）。"""
    names: set[str] = set()
    for path in migration_files("*.sql"):
        names |= retired_processing_item_names(path.read_text(encoding="utf-8"))
    return names


def bootstrap_catalog() -> dict:
    """建库脚本（基线）里的目录 → `{名字: craftHint}`（复用既有解析器，不另写一份 SQL 解析）。"""
    return catalog_guard.migration_catalog(INIT_SCRIPT.read_text(encoding="utf-8"))


def expected_catalog(bootstrap: dict, renames: dict, retired: set) -> dict:
    """（基线目录 − 撤出项）+ 改名映射 = 今天**存活**目录（与 Java 种子应对齐的期望值）。"""
    expected = {}
    for name, hint in bootstrap.items():
        current = renames.get(name, name)
        if current in retired:
            continue
        expected[current] = hint
    return expected


def category_name_in_bootstrap(sql: str) -> str:
    """建库脚本里 `INSERT INTO processing_categories …` 那句种的分类名。"""
    m = re.search(r"INSERT\s+INTO\s+processing_categories\b.*?;", sql, re.S | re.I)
    assert m, "建库脚本里找不到 `INSERT INTO processing_categories …` 段 —— 目录分类的基线种子被删了？"
    name = re.search(r"'([^']+)'\s*,\s*10\s*,", m.group(0))
    assert name, f"读不出基线种下的加工分类名（形态变了）：{m.group(0)[:200]}"
    return name.group(1)


def category_literal_sites(name: str, main_java_texts: dict) -> list:
    """默认加工分类名**带引号的字面量**在 admin-api 主源码里的出现位置（单一来源判据）。"""
    return sorted(rel for rel, text in main_java_texts.items()
                  if re.search(r'"' + re.escape(name) + r'"', text))


# ────────────────────────────────────── 真语料夹具

def _main_java_texts() -> dict:
    return {str(p.relative_to(REPO)): p.read_text(encoding="utf-8")
            for p in sorted(SERVICE_DIR.rglob("*.java"))}


def _load() -> tuple[str, str, dict, str]:
    service_text = SEED_SERVICE.read_text(encoding="utf-8")
    checklist_text = CHECKLIST.read_text(encoding="utf-8")
    expected = expected_catalog(bootstrap_catalog(), processing_item_renames(), all_retired_names())
    bootstrap_sql = INIT_SCRIPT.read_text(encoding="utf-8")
    return service_text, checklist_text, expected, bootstrap_sql


# ────────────────────────────────────── 判据 1~3（真语料）

EVAL_SEED = REPO / "tests" / "agent_eval" / "fixtures" / "mibao_eval_seed.sql"
#: eval seed 自检里的目录项阈值形态：`... OR v_pi < N THEN`
_SEED_PI_RE = re.compile(r"v_pi\s*<\s*(\d+)")


def eval_seed_catalog_threshold(sql: str) -> int:
    """eval seed 自检声明的「目录项数」下限（读不出 ⇒ fail-closed）。"""
    m = _SEED_PI_RE.search(sql)
    assert m, "读不出 eval seed 的 v_pi 阈值 —— 形态变了，本判据 fail-closed"
    return int(m.group(1))


def test_eval_seed_catalog_threshold_converges_with_live_migrations():
    """**类级守卫**：eval seed 的目录项阈值必须等于今天存活的目录项数（建库脚本 − 撤出项）。

    为什么值得守（issue #7027 实证）：V123（#5230）撤出「接高」后阈值仍写 16 ⇒
    B 端评测腿在 **seed 阶段**就 `RAISE EXCEPTION`（rc=3），一行 LLM 都没跑到，
    而日志只显示「fixture 注入失败」—— 极易被读成环境抖动。新撤一项而漏改这里 ⇒ 本判据当场红。
    """
    expected = expected_catalog(bootstrap_catalog(), processing_item_renames(), all_retired_names())
    actual = eval_seed_catalog_threshold(EVAL_SEED.read_text(encoding="utf-8"))
    assert actual == len(expected), (
        f"eval seed 的目录阈值 {actual} ≠ 今天存活目录 {len(expected)} 项"
        f"（建库脚本 {len(bootstrap_catalog())} 项 − 撤出 {sorted(all_retired_names())}）—— "
        "撤项迁移落地后必须同步 mibao_eval_seed.sql，否则评测腿在 seed 阶段 rc=3"
    )


def test_red_proof_seed_threshold_drift_is_detectable():
    """判别力自证：阈值写回 16（漂移形态）⇒ 解析出 16 ≠ 今天存活目录 ⇒ 上面的断言必红。"""
    assert eval_seed_catalog_threshold("IF v_prod < 1 OR v_colors < 1 OR v_pi < 16 THEN") == 16


def test_java_catalog_converges_with_the_live_database_catalog():
    """判据 1：Java 种子目录 == （基线目录 − 撤出项 + 改名映射）逐条同值。"""
    service_text, _checklist, expected, _sql = _load()
    actual = java_catalog(service_text)

    assert expected, "基线目录 − 撤出项 后为空 ⇒ 本判据空转（fail-closed）"
    assert actual == expected, (
        "开租默认加工项目录与库里（基线 − 撤出 + 改名）的存活目录**分叉** ——\n"
        f"  只在 Java 种子里有（库里已没有）：{sorted(set(actual) - set(expected))}\n"
        f"  只在库里有（新租户拿不到）：{sorted(set(expected) - set(actual))}\n"
        f"  craftHint 不同：{sorted(k for k in set(actual) & set(expected) if actual[k] != expected[k])}\n"
        "  改 Java 种子（ProcessingItemSeedService.CATALOG）或改基线/迁移，**两边必须同批对齐**")


def test_java_catalog_has_no_duplicates_and_the_retired_item_is_gone():
    """判据 1b：目录里名字不许重复；被撤出的项不许出现（否则 = 复活一个商家不该勾到的项）。"""
    service_text, _checklist, expected, _sql = _load()
    code = _strip_java_comments(service_text)
    names = [m[0] for m in _CATALOG_ITEM_RE.findall(code)]

    assert len(names) == len(set(names)), f"目录里出现了重复的名字：{names}"
    retired = all_retired_names()
    assert retired, "读不出任何撤出项 —— V123 那条「接高」撤出迁移丢了？（注册表 fail-closed）"
    assert not (set(names) & retired), (
        f"目录里出现了**已撤出**的项：{sorted(set(names) & retired)} —— 撤出项不种（种了 = 复活），"
        "见 V123 的终态口径")
    assert set(names) == set(expected), "目录项集合与期望不一致（细节见主判据的输出）"


def test_category_name_is_single_sourced():
    """判据 2+3：分类名取自单一来源常量、字面量恰一处、值 = 基线种的那个分类名，且种子服务引用常量。"""
    service_text, checklist_text, _expected, bootstrap_sql = _load()
    name = java_category_constant(checklist_text)

    assert name == category_name_in_bootstrap(bootstrap_sql), (
        f"Java 默认加工分类名「{name}」与建库脚本种下的分类名"
        f"「{category_name_in_bootstrap(bootstrap_sql)}」不一致 ⇒ 新租户与老租户的分类分叉")

    sites = category_literal_sites(name, _main_java_texts())
    assert sites == [str(CHECKLIST.relative_to(REPO))], (
        f"默认加工分类名的字面量必须**恰出现一次**（定义处 {CHECKLIST.name}），实际 {sites} —— "
        "别处请引用 `OnboardingInitialData.DEFAULT_PROCESSING_CATEGORY_NAME`")

    assert "OnboardingInitialData.DEFAULT_PROCESSING_CATEGORY_NAME" in _strip_java_comments(service_text), (
        "种子服务必须引用 OnboardingInitialData.DEFAULT_PROCESSING_CATEGORY_NAME（不许再抄一份字面量）")


# ────────────────────────────────────── 判据 4：判别力自证（内存变异，不改盘上文件）

def test_guard_has_discriminating_power_on_mutated_corpus():
    """判据 4：五种坏形态各自判红 + 「只改注释」不红（守卫自身不许退化成恒绿）。"""
    service_text, _checklist, expected, bootstrap_sql = _load()
    renames = processing_item_renames()
    retired = all_retired_names()

    # ① 删掉目录里的一行 ⇒ 主判据红（新租户少一项）
    dropped = re.sub(r'\s*new\s+CatalogItem\(\s*"打孔".*?\),', "", service_text, count=1, flags=re.S)
    assert dropped != service_text, "注入未生效（删行正则没命中）—— 红证无效"
    assert java_catalog(dropped) != expected, "删掉目录里的一项必须判红"

    # ② 改一个字（名字是取价组合键）⇒ 红
    renamed = service_text.replace('new CatalogItem("韩褶"', 'new CatalogItem("韩折"', 1)
    assert renamed != service_text, "注入未生效（改名没命中）—— 红证无效"
    assert java_catalog(renamed) != expected, "名字改一个字必须判红"

    # ③ 改 craftHint ⇒ 红（工艺维的受控来源）
    hint_changed = service_text.replace('new CatalogItem("打孔", "打孔"',
                                        'new CatalogItem("打孔", "韩褶"', 1)
    assert hint_changed != service_text, "注入未生效（改 craftHint 没命中）—— 红证无效"
    assert java_catalog(hint_changed) != expected, "craftHint 漂移必须判红"

    # ④ 目录清空 ⇒ 解析器 fail-closed（读不到 ≠ 没问题）
    emptied = re.sub(r'new\s+CatalogItem\([^;]*?\)\s*,?\s*', "", service_text, flags=re.S)
    assert "new CatalogItem(" not in _strip_java_comments(emptied), "注入未生效（清空没命中）"
    with pytest.raises(AssertionError):
        java_catalog(emptied)

    # ⑤ 撤出迁移从语料里去掉 ⇒ 期望里多出「接高」⇒ 红（证明「撤出项从迁移读」是承重的）
    without_retirement = expected_catalog(bootstrap_catalog(), renames, set())
    assert without_retirement != expected, "撤出项没进入期望集 —— 解析退化成空断言"
    assert java_catalog(service_text) != without_retirement, "漏读撤出迁移必须判红"
    assert retired, "撤出项集合为空（V123 没被读到）"

    # ⑥ 反向对照：只改注释 ⇒ 目录与分类名解析**一字不变**
    comment_only = service_text + (
        '\n// new CatalogItem("假项", null, "注释里的示例不算目录")'
        '\n/* new CatalogItem("另一个假项", null, "块注释也不算") */\n')
    assert java_catalog(comment_only) == java_catalog(service_text), "只改注释被误判成目录变更"
