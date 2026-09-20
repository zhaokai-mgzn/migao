# case_ids: PP-011
"""「旧工序名 → 逻辑名」映射的**单一出处**守卫（issue #4637）。

## 背景（实测：三份并存 ⇒ 改一份不改另两份 = 静默分叉）

| # | 副本位置 | 角色 | 本单处置 |
|---|---|---|---|
| 1 | `backend/ai-agent-service/app/production/routing.py::_LOGICAL_NAME_PAIRS` | **真值源**（35 条有序对） | 不动（ai-agent 只读） |
| 2 | `backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationQueryService.java` 的 `logicalNamePairs()` | Java 侧**唯一**表（运行期归一 + 静态入口 `logicalOperationName`） | **保留（单一出处）** |
| 3 | `backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java` 的 `logicalNames()` | 播种路径副本（35 条，与 #2 逐条同值） | **退场**（改为引用 #2 的静态入口） |

第 3 份**当时未纳入任何守卫**：既有双向比对判据（`ProductionOperationQueryServiceTest` 的
`logicalNameTableMatchesTruthSource`）只读 #2 的**行为**（`normalizeOperationName` 的投影）
⇒ 改第 3 份那张表**不会让任何东西变红**，而它决定**新租户播种出来的**规则/主线锚点名字。

## 判据（两条，都按**真值源键集**判定，不按「哪个变量名」）

1. **生产 Java 里不得存在第二份「旧名 → 逻辑名」表** —— 扫 `backend/admin-api/src/main/java/**/*.java`，
   按真值源的 **35 个旧名键**找 `.<put>("<旧名>", "<逻辑名>")` 形态；命中集必须**恰好**是
   `ProductionOperationQueryService.java`（且该文件命中数 == 真值源条数）。
   ⇒ 谁把副本写回来（改个 map 变量名也一样）⇒ 红。
2. **单一出处的那一份与真值源逐条一致**（少一条/多一条/映射不同/顺序不同都红）。

## 为什么用「真值源键集」而不是正则匹配「带部位后缀的名字」

`旧名` 的形态**不规则**：`布三边`（无分隔符）/ `布帘车被`（前缀而非后缀）/ `帘头制作` / `质检`。
按 `-布` / `-纱` 正则找会**漏掉**这些 ⇒ 判据的覆盖面就不是「这张表」而是「长得像变体名的名字」
（`test_op_name_registry_guard.py` 已登记「白名单/正则是判据的覆盖面」这条教训）。
本文件改为：**键集 = 真值源里那 35 个键**，命中形态 = 键旁边就是值 ⇒ 覆盖面 = 这张映射本身。

## 与既有守卫的关系（**本文件不重写它们**）

- `backend/admin-api/src/test/java/com/migao/admin/service/ProductionOperationQueryServiceTest.java`
  的 `logicalNameTableMatchesTruthSource`：**行为级**双向比对（真值源 ↔ `normalizeOperationName`）—— 本文件不复制它；
- `backend/admin-api/src/test/java/com/migao/admin/service/ProductionSeedTemplateServiceTest.java`
  的 `seedNormalizationMatchesSingleSource`：**播种路径行为级**等价（播种规则里的工序名 == 静态入口的输出）—— 本文件不复制它；
- 测试夹具副本（`RoutingModelFixture.LOGICAL`）与 `variant_map` / 帘头条目同族的收敛**不在本单范围**
  （登记为遗留，见 issue #4637）。

## 反空跑锚点（三条 + 一条注入自证）

| 锚点 | 判据 |
|---|---|
| 真值源解析 | 解析出 **0** 条 ⇒ 红（解析正则/锚点漂了，不得静默变成「扫了个空集」） |
| 扫描根缺失 | `backend/admin-api/src/main/java` 不存在 ⇒ 红（不得静默跳过） |
| 单一出处命中 | 命中集为空 ⇒ 红（机制已死 ≠ 没问题） |
| 注入自证 | 把一份**带副本表**的合成 Java 塞进临时目录 ⇒ 判据必须命中它（见 `test_detector_flags_injected_duplicate_table`） |

## 边界（本单**不做**）

- **不碰 `.github/cases/**`**（行为用例 `PP-011` 已覆盖「web 面工序命名统一」这条行为；本单只**引用**它）；
- **不改模板数据**（`backend/admin-api/src/main/resources/production-templates/curtain/seed.json`
  的 37 条 `operations[].name` 本就是**库口径旧名**，与「映射表」是两件事 —— 逐条理由见 issue #4637）；
- **不改 ai-agent**（`routing.py` 是真值源，只读）。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 真值源（ai-agent，**只读**）
ROUTING_PY = "backend/ai-agent-service/app/production/routing.py"
#: 生产 Java 扫描面
JAVA_SRC = "backend/admin-api/src/main/java"
#: 唯一允许持有「旧名 → 逻辑名」表的文件（仓库相对路径）
SOLE_SOURCE = "backend/admin-api/src/main/java/com/migao/admin/service/ProductionOperationQueryService.java"

#: 真值源里这张表的定义处锚点（**文本锚点，不写行号**：行号会腐烂）
_PAIRS_ANCHOR = "_LOGICAL_NAME_PAIRS: List[tuple]"
#: 真值源的结束锚点（派生 dict 处）
_PAIRS_END_ANCHOR = "OPERATION_LOGICAL_NAMES: Dict"
#: 有序对行形态（真值源里逐行一条）
_PAIR_LINE_RE = re.compile(r'\n\s*\("([^"]+)",\s*"([^"]+)"\),')
#: 命中形态：任何 map 的 `.put("<旧名>", "<逻辑名>")`（变量名无关 —— 改名躲不过判据）
_PUT_RE = re.compile(r'\.put\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')


def _truth_pairs(root: Path = REPO_ROOT) -> list[tuple[str, str]]:
    """真值源里的有序对（**唯一** import 点：其余判据都从这里取键集）。"""
    text = (root / ROUTING_PY).read_text(encoding="utf-8")
    start = text.index(_PAIRS_ANCHOR)
    end = text.index(_PAIRS_END_ANCHOR, start)
    return _PAIR_LINE_RE.findall(text[start:end])


def _legacy_keys(root: Path = REPO_ROOT) -> set[str]:
    """真值源的**键集** = 35 个旧工序名（判据的覆盖面由此定义，不靠正则猜形态）。"""
    return {legacy for legacy, _ in _truth_pairs(root)}


def _duplicate_table_hits(root: Path = REPO_ROOT) -> dict[str, list[tuple[str, str]]]:
    """扫生产 Java，返回 `{仓库相对路径: [(旧名, 逻辑名), …]}`（只收**真值源键集**里的键）。"""
    keys = _legacy_keys(root)
    base = root / JAVA_SRC
    hits: dict[str, list[tuple[str, str]]] = {}
    for path in sorted(base.rglob("*.java")):
        found = [(k, v) for k, v in _PUT_RE.findall(path.read_text(encoding="utf-8")) if k in keys]
        if found:
            hits[path.relative_to(root).as_posix()] = found
    return hits


# ── 判据 1：生产 Java 里只有一份表 ────────────────────────────────────────────


def test_truth_source_parses_35_pairs() -> None:
    """反空跑锚点：真值源必须解析出 35 条（解析正则/锚点漂了 ⇒ 红，不是静默空集）。"""
    pairs = _truth_pairs()
    assert len(pairs) == 35, (
        f"{ROUTING_PY} 的 {_PAIRS_ANCHOR} 应解析出 35 条有序对，实测 {len(pairs)} 条 —— "
        "锚点或行形态变了，本守卫的覆盖面随之失效，请同步判据（不得放宽条数）"
    )


def test_java_src_root_exists() -> None:
    """反空跑锚点：扫描根必须存在（否则 `rglob` 空转 ⇒ 判据恒绿）。"""
    assert (REPO_ROOT / JAVA_SRC).is_dir(), f"扫描根不存在：{JAVA_SRC}（判据会静默变成空跑）"


def test_only_one_legacy_name_table_in_production_java() -> None:
    """判据 1：生产 Java 里「旧名 → 逻辑名」表**只此一份**（写回第二份 ⇒ 红）。"""
    hits = _duplicate_table_hits()
    assert hits, (
        "生产 Java 里找不到任何「旧名 → 逻辑名」表 —— 单一出处也不见了？"
        "（机制已死 ≠ 没问题；本判据的正面对象是 "
        f"{SOLE_SOURCE}）"
    )
    offenders = sorted(path for path in hits if path != SOLE_SOURCE)
    assert offenders == [], (
        "「旧名 → 逻辑名」映射又出现了第二份副本（issue #4637 已把它收敛为单一出处）："
        f"{offenders} —— 请改为引用 {SOLE_SOURCE}.logicalOperationName(...)，"
        "而不是另抄一份表（副本并存 ⇒ 改一份不改另一份 = 静默分叉，且播种出来的数据与运行期口径分叉）"
    )


def test_sole_source_has_exactly_the_truth_pairs() -> None:
    """判据 2：单一出处那一份与真值源**逐条一致**（含顺序；少/多/改值都红）。"""
    hits = _duplicate_table_hits()
    assert SOLE_SOURCE in hits, (
        f"{SOLE_SOURCE} 里没有「旧名 → 逻辑名」表 —— 表被搬走了？"
        "（若是**有意**迁移，请同步本文件的 SOLE_SOURCE 常量与判据，不要绕过）"
    )
    java_pairs = hits[SOLE_SOURCE]
    truth = _truth_pairs()
    assert len(java_pairs) == len(truth), (
        f"{SOLE_SOURCE} 的表有 {len(java_pairs)} 条，真值源 {ROUTING_PY} 有 {len(truth)} 条"
    )
    assert java_pairs == truth, (
        f"{SOLE_SOURCE} 的表与真值源 {ROUTING_PY} 不逐条一致"
        "（改一处不改另一处 ⇒ 本判据红；缺条/多条/映射不同/顺序不同都算不一致）"
    )


# ── 注入自证：判据真的会红（不是恒真） ────────────────────────────────────────


def _synthetic_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    """在临时目录里造一棵最小的 `backend/admin-api/src/main/java` 树（复制真值源）。"""
    (tmp_path / JAVA_SRC).mkdir(parents=True, exist_ok=True)
    (tmp_path / ROUTING_PY).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / ROUTING_PY).write_text((REPO_ROOT / ROUTING_PY).read_text(encoding="utf-8"),
                                       encoding="utf-8")
    for rel, body in files.items():
        target = tmp_path / JAVA_SRC / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return tmp_path


def test_detector_flags_injected_duplicate_table(tmp_path: Path) -> None:
    """注入自证：把副本表塞进**另一个**文件 ⇒ 判据 1 必须命中它（且只命中它）。"""
    root = _synthetic_tree(tmp_path, {
        "com/migao/admin/service/Sole.java": (
            "package com.migao.admin.service;\n"
            "class Sole { static void build(java.util.Map<String,String> names) {\n"
            '    names.put("精裁-布", "精裁");\n'
            "} }\n"
        ),
        "com/migao/admin/service/Duplicate.java": (
            "package com.migao.admin.service;\n"
            "class Duplicate { static void build(java.util.Map<String,String> names) {\n"
            '    names.put("布三边", "三边");\n'
            "} }\n"
        ),
    })
    hits = _duplicate_table_hits(root)
    assert "backend/admin-api/src/main/java/com/migao/admin/service/Sole.java" in hits
    assert "backend/admin-api/src/main/java/com/migao/admin/service/Duplicate.java" in hits, (
        "注入的副本表没被扫到 ⇒ 判据对「改名/换文件的副本」失效（覆盖面不足）"
    )


def test_detector_is_clean_on_a_tree_without_duplicates(tmp_path: Path) -> None:
    """注入自证（阴性对照）：只有一份表时，副本清单为空（判据不会恒红）。"""
    root = _synthetic_tree(tmp_path, {
        "com/migao/admin/service/Sole.java": (
            "package com.migao.admin.service;\n"
            "class Sole { static void build(java.util.Map<String,String> names) {\n"
            '    names.put("精裁-布", "精裁");\n'
            '    names.put("布三边", "三边");\n'
            "} }\n"
        ),
    })
    hits = _duplicate_table_hits(root)
    assert sorted(hits) == ["backend/admin-api/src/main/java/com/migao/admin/service/Sole.java"]
