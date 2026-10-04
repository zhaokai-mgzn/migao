# case_ids: MC-081
"""**唯一键 / 幂等键写入点的类级元守卫**（issue #6301，铁律 8）。

## 这一类缺陷长什么样（本单的形态）

`#6301` 的缺陷**不在数据正确性**（防双记本身有效：分录 1 行、库存 Δ 正确），而在
**「唯一冲突未被处理」**：服务层「先查是否已记 → 再插入」是**非原子读**（TOCTOU），
并发时多个同 run id 的请求同时判定「未记」，随后争抢部分唯一索引
`uk_batch_consumption_stocktake`，落库抛 `DuplicateKeyException` ⇒ 直接冒泡成 **HTTP 500**
（探针 W5 读数 `[200,500,500,500,500,500]`，两个构建点都红）。

⇒ 修一个写入点**只修这一处 = 没修**：全仓还有 **17 处**「写唯一约束表、且代码里没有任何
冲突处理」的写入点（本文件末尾的冻结台账逐条列出）。它们不会被任何实例判据覆盖
（每个写入点自带的测试都只测自己的路径、且大多**成功路径**），而缺陷一旦触发就是 500。

## 判据（三条，全部可归因）

| # | 判什么 | 会怎么红 |
|---|---|---|
| 1 | **未登记即红**：语料里每一对「服务文件 × 写唯一约束表的 mapper 字段」都必须在冻结台账里 | 新增一处这样的写入点而没登记 ⇒ 具名报出该文件 / 字段 / 表 |
| 2 | **登记即须属实（双向）**：台账说 `handling: none`（未处理）而语料里现在**有**处理 ⇒ 红（陈旧登记）；台账说某文件在处理而该文件**没有**处理 ⇒ 红（台账给不存在的处理盖章） | 两种方向都判红，且报出是哪一条 |
| 3 | **fail-closed**：台账为空 / 扫描零命中 / 一条唯一约束表都解析不出来 ⇒ 红（判据自己失效必须自曝，不许静默绿） | 有人清空台账或改坏 schema 解析「消红」⇒ 当场红 |

## 台账只许缩短（§19.1）

`unique_write_ledger.json` 里 `handling: none` 的每条都是**已登记的缺口**（观测面）：
**只许减少**（补上原子写 / 冲突映射后销账）。本判据**不为存量缺口的安全性背书** —— 它只保证
「新的同类写入点进不来、缺口从台账里静默消失也进不来」。缺口的**修复**是各自独立的包。

## 判据是**纯函数**（输入 = 语料字典 → 具名问题清单）

于是注入式红证可以在**内存里**做完（不碰工作树）：构造坏语料 ⇒ 判据必须报出**具名**问题。
`test_injected_bad_corpora_are_named` 就是这些红证，随判据常驻。

## 边界（照实登记，§19.1）

- 判据只认**仓内文本形态**：`<mapper 字段>.insert(` 与「该字段类型（`XxxMapper`）的 mapper 接口
  经 `extends BaseMapper<实体>` → 实体的 `@TableName` → 唯一约束表」这条**静态链**。
  用**裸 SQL / JdbcTemplate / 反射**写这些表、或 mapper 不经 `BaseMapper` 泛型声明的代码
  **不在射程内**（本仓没有这种写法，出现时也不会有东西提醒）；
- 「处理」的判定是**形态学**的：服务文件里出现 `DuplicateKeyException`，或该 mapper 接口里
  出现一条 `ON CONFLICT` 的 `@Insert`。它**判不了**「那条处理真的被调用 / 真的在并发下有效」
  —— 行为面由实例判据承担（`BatchStocktakeConcurrentRealDbTest` / 各写入点自己的判据）；
- 它**不**判「某个写入点该不该用幂等键」（那是业务口径），也不为 `handling: none` 的存量缺口背书。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import java_code as _java_code  # noqa: E402

MAIN_JAVA = REPO_ROOT / "backend/admin-api/src/main/java"
MAPPER_DIR = MAIN_JAVA / "com/migao/admin/mapper"
ENTITY_DIR = MAIN_JAVA / "com/migao/admin/entity"
SCHEMA = REPO_ROOT / "backend/admin-api/src/main/resources/db/init/schema.sql"
LEDGER = REPO_ROOT / "tests/unit_ci_workflows/unique_write_ledger.json"

#: 唯一约束的建法（bootstrap 终态 schema = 唯一真值源；与迁移的终态由既有判据核过）
_UNIQUE_INDEX = re.compile(r"CREATE UNIQUE INDEX IF NOT EXISTS (\w+)\s+ON\s+(\w+)")
_TABLE_NAME = re.compile(r'@TableName\(\s*(?:value\s*=\s*)?"([^"]+)"')
_BASE_MAPPER = re.compile(r"extends\s+\w*BaseMapper\s*<\s*(\w+)\s*>")
#: 服务类里的 mapper 字段声明（`StockBatchConsumptionMapper consumptionMapper;`）
_MAPPER_FIELD = re.compile(r"\b([A-Za-z_]\w*Mapper)\s+([A-Za-z_]\w*)\s*[;,)=]")
#: mapper 的插入调用：`field.insert(` 与 `field.insertIgnoreConflict(` 这类**带前后缀的插入**都算
#: （「写入点」是行为面的事实，不因方法名里有 IgnoreConflict 就变成不是写入点）
_INSERT_CALL = r"\b{field}\s*\.\s*(insert\w*)\s*\("

#: 冲突处理的**形态学**标记（服务侧 / mapper 侧各一条）
_SERVICE_HANDLING = "DuplicateKeyException"
_MAPPER_HANDLING = "ON CONFLICT"   # 形态学标记：mapper 里的原子写（逐方法判，见 _mapper_handles_conflict）

#: 台账里表示「未处理」的取值（= 已登记的缺口）
NONE = "none"


def java_code(text: str) -> str:
    """剥掉 Java 注释（复用判据面的**唯一一份**实现，见 `tests/unit_ci_workflows/_source_parsing.py`）。"""
    return _java_code(text)


# ══════════════════════════════════════════════════════════════════════════════
# 一、判据本体（纯函数：输入语料 ⇒ 具名问题清单）
# ══════════════════════════════════════════════════════════════════════════════


def unique_tables_by_index(schema_text: str) -> dict[str, str]:
    """`表名 → 唯一索引名`（同一表多条时取第一条；只用于「这张表有没有唯一约束」）。"""
    out: dict[str, str] = {}
    for match in _UNIQUE_INDEX.finditer(schema_text):
        out.setdefault(match.group(2), match.group(1))
    return out


def mapper_tables(mapper_sources: dict[str, str], entity_sources: dict[str, str]) -> dict[str, str]:
    """`XxxMapper`（**接口类名**）→ 表名（经 `BaseMapper<实体>` + 实体的 `@TableName`）。"""
    entity_table: dict[str, str] = {}
    for name, text in entity_sources.items():
        found = _TABLE_NAME.search(text)
        if found:
            entity_table[name] = found.group(1)
    out: dict[str, str] = {}
    for path, text in mapper_sources.items():
        found = _BASE_MAPPER.search(text)
        if found:
            out[Path(path).stem] = entity_table.get(found.group(1))
    return out


def _mapper_handles_conflict(mapper_text: str, method_names: set[str]) -> bool:
    """该 mapper 里**被调用的那些插入方法**是否带 `ON CONFLICT`（逐方法判，不是「文件里有就行」）。

    逐方法判是必须的：`StockBatchConsumptionMapper` 里同时有「原子闸」与「朴素插入」两条路径，
    按文件判「有没有 ON CONFLICT」⇒ **把原子闸摘掉之后判据照样绿**（实测：删掉
    `ON CONFLICT … DO NOTHING` 后本判据仍绿 —— 假绿）。逐方法判之后，摘掉原子闸 ⇒ 具名判红。
    """
    code = java_code(mapper_text)
    for name in method_names:
        # 取「方法声明行 → 到分号」这一段（注解 + SQL 都在里面），判它有没有 ON CONFLICT
        match = re.search(
            rf"(?:@Insert\([^;]*?\)\s*(?:@\w+\([^)]*\)\s*)*)?\bint\s+{re.escape(name)}\s*\(",
            code, re.S)
        if match and re.search(r"ON\s*CONFLICT", match.group(0), re.I):
            return True
    return False


def unique_write_sites(sources: dict[str, str], mappers: dict[str, str],
                       mapper_sources: dict[str, str],
                       unique_tables: dict[str, str]) -> dict[str, dict[str, str]]:
    """语料里**写唯一约束表**的（文件 × mapper 字段）现取清单。

    @return `{"<仓库相对路径>::<字段>": {"table":…, "handling": <处理所在文件> | "none"}}`
    """
    sites: dict[str, dict[str, str]] = {}
    for path, raw in sorted(sources.items()):
        code = java_code(raw)
        fields = {m.group(2): m.group(1) for m in _MAPPER_FIELD.finditer(code)}
        if not fields:
            continue
        for field, mapper in fields.items():
            table = mappers.get(mapper)
            if table not in unique_tables:
                continue
            calls = set(m.group(1) for m in
                        re.finditer(_INSERT_CALL.format(field=re.escape(field)), code))
            if not calls:
                continue
            mapper_file = f"backend/admin-api/src/main/java/com/migao/admin/mapper/{mapper}.java"
            mapper_text = mapper_sources.get(mapper_file, "")
            if _SERVICE_HANDLING in code:
                handling = path
            elif _mapper_handles_conflict(mapper_text, calls):
                handling = mapper_file
            else:
                handling = NONE
            sites[f"{path}::{field}"] = {"table": table, "handling": handling}
    return sites


def ledger_problems(sites: dict[str, dict[str, str]], ledger: dict[str, dict[str, str]]) -> list[str]:
    """三条判据合成的问题清单（空 = 绿）。"""
    problems: list[str] = []
    if not ledger:
        problems.append(
            f"冻结台账 `{LEDGER.relative_to(REPO_ROOT).as_posix()}` 为空 ⇒ 判据 fail-closed"
            "（零登记不许当绿）")
    if not sites:
        problems.append(
            "扫描零命中：一个「写唯一约束表」的写入点都没找到 ⇒ 判据本身失效（fail-closed）")

    for key in sorted(set(sites) - set(ledger)):
        info = sites[key]
        problems.append(
            f"**未登记**的唯一键写入点：`{key}`（表 `{info['table']}`，处理 = `{info['handling']}`）"
            " —— 新增这样的写入点必须登记进 unique_write_ledger.json：要么补上原子写"
            "（`ON CONFLICT DO NOTHING` 按影响行数判首次）/ 冲突映射（`DuplicateKeyException`），"
            f"要么按登记为缺口（`handling: \"{NONE}\"`）")
    for key in sorted(set(ledger) - set(sites)):
        problems.append(
            f"台账指向的写入点 `{key}` 已不再写唯一约束表（或文件/mapper 字段改名）⇒ 陈旧登记，须销账")

    for key in sorted(set(sites) & set(ledger)):
        now, claimed = sites[key]["handling"], ledger[key].get("handling")
        if claimed == NONE and now != NONE:
            problems.append(
                f"`{key}` 已经**有**冲突处理（`{now}`）而台账仍登记为缺口 ⇒ 陈旧登记，须销账"
                "（台账只许缩短）")
        elif claimed != NONE and now == NONE:
            problems.append(
                f"`{key}` 的冲突处理**不见了**（台账说在 `{claimed}`，语料里没有）"
                " ⇒ 唯一冲突会重新冒泡成 5xx，须补回处理或改登记为缺口")
        elif claimed not in (NONE, now):
            problems.append(
                f"`{key}` 的登记处理位置与现取不一致（台账 `{claimed}` / 现取 `{now}`）⇒ 须同步")
        if sites[key]["table"] != ledger[key].get("table"):
            problems.append(
                f"`{key}` 的表漂移（台账 `{ledger[key].get('table')}` / 现取 `{sites[key]['table']}`）")
    return problems


# ══════════════════════════════════════════════════════════════════════════════
# 二、读真语料
# ══════════════════════════════════════════════════════════════════════════════


def read_sources(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*.java")):
        if path.parent == MAPPER_DIR:      # mapper 接口单独成面（它们不是「写入点」的宿主）
            continue
        out[path.relative_to(REPO_ROOT).as_posix()] = path.read_text(encoding="utf8")
    return out

def read_mappers() -> dict[str, str]:
    return {p.relative_to(REPO_ROOT).as_posix(): p.read_text(encoding="utf8")
            for p in sorted(MAPPER_DIR.rglob("*.java"))}


def read_entities() -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf8") for p in sorted(ENTITY_DIR.rglob("*.java"))}


def read_ledger() -> dict[str, dict[str, str]]:
    return dict(json.loads(LEDGER.read_text(encoding="utf8"))["sites"])


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据（真语料）
# ══════════════════════════════════════════════════════════════════════════════


def test_every_unique_write_site_is_registered() -> None:
    """未登记即红 + 登记即须属实（双向）+ fail-closed。"""
    unique = unique_tables_by_index(SCHEMA.read_text(encoding="utf8"))
    assert len(unique) >= 20, (
        f"schema 里解析到 {len(unique)} 张带唯一约束的表 —— 解析口径坏了（fail-closed）")
    mappers = mapper_tables(read_mappers(), read_entities())
    assert mappers, "一个 mapper→表 都没解析出来 ⇒ 判据失效（fail-closed）"
    sites = unique_write_sites(read_sources(MAIN_JAVA), mappers, read_mappers(), unique)
    ledger = read_ledger()
    gaps = sorted(k for k, v in ledger.items() if v.get("handling") == NONE)
    print(f"[MC-081] 唯一约束表现取 = {len(unique)} 张；写入点现取 = {len(sites)} 处")
    print(f"[MC-081] 台账缺口（handling=none）现取 = {len(gaps)} 条：{gaps}")
    problems = ledger_problems(sites, ledger)
    assert problems == [], "\n".join(problems)


def test_the_stocktake_write_point_uses_an_atomic_conflict_handler() -> None:
    """本单的实例写入点（#6301）：盘点落账必须**有**处理，且处理是 `ON CONFLICT` 的原子写。

    这条**不与**上面的类级判据重复：类级判据只保证「登记属实」，本判据钉住**本单这一处**
    的具体形态（原子闸）—— 有人把它改回 `try/catch` 或删掉处理时，这里会**具名**报出来。
    """
    sites = unique_write_sites(read_sources(MAIN_JAVA), mapper_tables(read_mappers(), read_entities()),
                              read_mappers(), unique_tables_by_index(SCHEMA.read_text(encoding="utf8")))
    key = "backend/admin-api/src/main/java/com/migao/admin/service/StockBatchConsumptionService.java::consumptionMapper"
    assert key in sites, f"盘点落账的写入点不见了（改名？）：现取 = {sorted(sites)}"
    assert sites[key]["handling"] != NONE, "盘点落账的唯一冲突**没有**处理 ⇒ 并发同 run id 会 500（#6301 复发）"
    mapper_text = read_mappers()[
        "backend/admin-api/src/main/java/com/migao/admin/mapper/StockBatchConsumptionMapper.java"]
    assert "insertStocktakeIfAbsent" in mapper_text, "原子闸方法不见了（#6301 的修复承载体）"
    assert _MAPPER_HANDLING in mapper_text.upper(), (
        "盘点落账的原子闸必须用 `ON CONFLICT … DO NOTHING`（在语句内部消解冲突）；"
        "删掉它 ⇒ 并发同 run id 会重新撞唯一索引并抛异常")


# ══════════════════════════════════════════════════════════════════════════════
# 四、判别力自证（注入式红证，**内存语料**，不碰工作树）
# ══════════════════════════════════════════════════════════════════════════════


def _good_sources() -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    """最小合规语料：一张唯一约束表 + 一个 mapper + 一个**有**处理的写入点。

    键的形态与**真语料**逐字相同（mapper 面用**文件路径**、实体面用**类名**）——
    形态不一致会让注入式自证在假语料上退化成「恒零命中」，那是**假绿**（本判据第一版正是这样红了一次）。
    """
    schema = ("CREATE UNIQUE INDEX IF NOT EXISTS uk_widgets_code ON widgets (tenant_id, code);\n")
    entities = {"Widget": '@TableName("widgets")\npublic class Widget {}\n'}
    mappers = {
        "backend/admin-api/src/main/java/com/migao/admin/mapper/WidgetMapper.java":
            "public interface WidgetMapper extends BaseMapper<Widget> {\n"
            "  @Insert(\"INSERT INTO widgets (code) VALUES (#{c}) ON CONFLICT (tenant_id, code) DO NOTHING\")\n"
            "  int insertIgnoreConflict(String c);\n}\n",
    }
    sources = {
        "backend/admin-api/src/main/java/com/migao/admin/service/WidgetService.java":
            "class WidgetService {\n"
            "  private final WidgetMapper widgetMapper;\n"
            "  int write() { return widgetMapper.insertIgnoreConflict(\"a\"); }\n"
            "  int read() { return widgetMapper.selectCount(null); }\n}\n",
    }
    return schema, entities, mappers, sources


def _sites(schema: str, entities: dict[str, str], mappers: dict[str, str],
           sources: dict[str, str]) -> dict[str, dict[str, str]]:
    return unique_write_sites(sources, mapper_tables(mappers, entities), mappers,
                              unique_tables_by_index(schema))


def test_injected_bad_corpora_are_named() -> None:
    """六条坏形态各自**判红**，且红得具名；两条对照读数**不红**。"""
    schema, entities, mappers, sources = _good_sources()
    good = _sites(schema, entities, mappers, sources)
    assert len(good) == 1, f"合规语料该恰好 1 个写入点，现取 {sorted(good)}"
    key = next(iter(good))
    ledger_ok = {key: {"table": "widgets", "handling": good[key]["handling"]}}
    assert ledger_problems(good, ledger_ok) == [], "合规语料 + 属实台账不该报红"

    # ① 新增一个**未登记**的写入点（新服务直接写同一张唯一表）⇒ 必红且点名
    forked = dict(sources)
    forked["backend/admin-api/src/main/java/com/migao/admin/service/RogueWidgetService.java"] = (
        "class RogueWidgetService {\n"
        "  private final WidgetMapper widgetMapper;\n"
        "  int write() { return widgetMapper.insert(null); }\n}\n")
    rogue_sites = _sites(schema, entities, mappers, forked)
    problems = ledger_problems(rogue_sites, ledger_ok)
    assert any("RogueWidgetService.java" in p and "未登记" in p for p in problems), problems

    # ② 台账为空 ⇒ fail-closed 红
    assert ledger_problems(good, {}), "台账清空必须红（fail-closed）"

    # ③ 扫描零命中（语料里根本没有写入点）⇒ 红，不许当绿
    silent = _sites(schema, entities, mappers, {
        "backend/admin-api/src/main/java/com/migao/admin/service/WidgetService.java":
            "class WidgetService { private final WidgetMapper widgetMapper; }\n"})
    assert ledger_problems(silent, ledger_ok), "零命中必须红（判据失效自曝）"

    # ④ 台账说「有处理」而语料里处理**没了**（把 ON CONFLICT 摘掉、服务也不 catch）⇒ 必红
    stripped_mappers = dict(mappers)
    stripped_mappers["backend/admin-api/src/main/java/com/migao/admin/mapper/WidgetMapper.java"] = (
        "public interface WidgetMapper extends BaseMapper<Widget> {\n"
        "  int insertIgnoreConflict(String c);\n}\n")
    stripped = _sites(schema, entities, stripped_mappers, sources)
    problems = ledger_problems(stripped, ledger_ok)
    assert any("不见了" in p for p in problems), problems

    # ⑤ 台账**陈旧**：已经补上了处理却还登记为缺口 ⇒ 必红（台账只许缩短）
    ledger_stale = {key: {"table": "widgets", "handling": NONE}}
    problems = ledger_problems(good, ledger_stale)
    assert any("已经**有**冲突处理" in p for p in problems), problems

    # ⑥ 表漂移 ⇒ 必红
    ledger_drift = {key: {"table": "other_table", "handling": good[key]["handling"]}}
    assert any("表漂移" in p for p in ledger_problems(good, ledger_drift)), "表漂移必须红"

    # ⑦ 对照：**只把 `.insert(` 写进注释 / 字符串** ⇒ 不红（判据不许被自己的文案喂红）
    commented = dict(sources)
    commented["backend/admin-api/src/main/java/com/migao/admin/service/RogueWidgetService.java"] = (
        "class RogueWidgetService {\n"
        "  // 这里**不**允许出现 widgetMapper.insert(...) 这种写法\n"
        "  String doc = \"widgetMapper.insert(x)\";\n}\n")
    assert ledger_problems(_sites(schema, entities, mappers, commented), ledger_ok) == [], \
        "注释 / 字符串里的 insert 不得被读成写入点"

    # ⑧ 对照：**写的是没有唯一约束的表** ⇒ 不在射程内（不红）
    no_unique = _sites("", entities, mappers, sources)
    assert no_unique == {}, "唯一约束表解析为空时不得凭空造出写入点"
