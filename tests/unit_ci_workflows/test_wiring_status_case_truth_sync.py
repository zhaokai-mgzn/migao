# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 test_yaml_light_scalar_fidelity.py / test_guard_parsing_is_comment_aware.py /
#   test_truth_retirement_guard.py 的同款声明与 `.github/cases/misc.yml` MC-012 的登记。
#   本 PR 不新建用例族。）
r"""用例面文本 × 主干事实的**接线状态同步**守卫（issue #5387；类级固化见 `migao-dev-flow` §23）。

## 实例（本单要治的那两句话）与它属于的**类**

#5348 / PR #5385 改了主干事实：`orders` 行**新增 `cost_amount`**（Σ 行成本；任一行不可判定 ⇒
整单 NULL，**不出部分和**）、引擎**新增第四态 `not_enabled`**（系统**有**、**该租户没开** ——
与 `not_wired` **并列、不可合并**，因为一个可行动一个不可行动）。而**用例面还写旧口径**：

| # | 陈旧文本 | 主干事实 |
|---|---|---|
| ① | `.github/cases/data.yml` 的 DA-016：「orders 行**没有** `cost_amount`（orders 表无成本列）」 | 装配层已给出 `cost_amount` 键（值可 NULL = **成本未知**，不是「缺字段」） |
| ② | 同文件 DA-017：「两条结构性不可达（**below_cost_price** 缺 cost_amount、price_change_over 缺 price_changes）为 **not_wired**」 | `below_cost_price` 的状态**随租户**三态（`wired` / `incomplete` / `not_enabled`）；只剩 `price_change_over` 是结构性不可达 |
| ③ | 真值 `.github/templates/dashboard-jump.yml` 的 `dashboard-jump.proactive-wiring-status`：「未接线 / 本次不完整 / 已接入且完整但当天无命中，**三者**可分」 | **四**态可分（第四态 `not_enabled` 未入真值） |

## 为什么没有任何东西会红（= 为什么它是一**类**，不是三处笔误）

用例面与真值面**只被校验引用完整性与生成物新鲜度**：
`.github/truths.py check` 只看 `truths_ref` 能否解析、`render_cases.py` 只看渲染是否同步
（见 `.github/workflows/pr-check.yml` 的 `Case Contract (truths_ref)` 两条 step）
—— **文本内容与主干事实之间一条机械联系都没有**。于是「主干加了字段 / 加了枚举态，文本照旧」
是**静默**的：改主干的人看不到用例面，改用例面的人不知道主干已经变了。
本文件就是那条联系（**类级**：不是只修 DA-016/DA-017 这两句话）。

## 判据（值一律**现取**；本文件只写「符号名 / 锚点」，不写死结论）

| # | 判据 | 单一源（只读） | 红证（怎么让它单独变红） |
|---|---|---|---|
| C0 | 引擎 `__all__` 里的**模块级字符串常量**必须恰好 = `STATUS_CONSTANTS` | `app/briefing/proactive.py`（AST） | 引擎新增第五态而不登记 ⇒ 红（逼同步真值面 + 本清单） |
| C1 | 真值文本必须**逐字点名**每个接线状态 | 同上（值从源码读） | 删掉文本里的 `not_enabled` ⇒ 红 |
| C1′ | **每一处**登记的真值/用例文本都必须点名全部态（登记处 = `STATUS_NAMING_TEXTS`） | 同上（面是显式登记的） | DA-018 或 `…unwired-disclosure` 真值漏一个态 ⇒ 红 |
| C2 | 真值文本里「**N 态可分**」的 N == 现取状态数 | 同上（`len`） | 写回「**三**者可分」⇒ 3≠4 红；引擎加第五态 ⇒ 4≠5 红 |
| C3 | 装配层声明的**每个行数组/行字段**必须逐字出现在 DA-016 的契约键清单里 | `DailyBriefingService.SNAPSHOT_ROW_FIELDS`（Java 原文） | 装配层加字段而不改 DA-016 ⇒ 红（**本单的历史形态**：`cost_amount`） |
| C4 | **每条规则**必须被 DA-017 点名，且在**同一条 `data_checks`** 里点名它**全部可达状态** | 引擎 `RULES`（AST）× 装配层数组集 | 去掉 below_cost_price 的 `not_enabled`/`incomplete` ⇒ 红；引擎新增一条规则 ⇒ 红 |

⇒ **燃尽锚点（现取，不是写死上限）**：状态 **N_STATES** / 点名面 **N_TEXTS** / 装配数组 **N_ARRAYS** /
行字段 **N_FIELDS** / 规则 **N_RULES** —— 任一面被收窄（少登记一个状态、少解析一个数组、少挂一处文本）
都会让 C0/C1′/C3/C4 的覆盖度判据变红（见 `test_coverage_anchor_is_live_and_printed`）。

## 容器核查（§23 G9）：同一类在容器里还有**第三处**

本单的两条判据只点名了真值 `…proactive-wiring-status` 与 DA-016 / DA-017。按「关单前核容器里还有没有剩余项」
把**同一类**（写死态数的陈旧枚举）在 `.github/` 全库扫了一遍，另有两处：
① DA-018 的「调用方自己可分『未接线 / 本次不完整 / 已接入且完整但无命中』」（**三态枚举**）；
② 它引用的真值 `dashboard-jump.proactive-unwired-disclosure` 只覆盖 `not_wired` 一态
（而 `not_enabled` 需要**可行动**的措辞、与「尚未接入」分开说 —— #5385 已落工具侧，真值/用例未跟）。
⇒ 两处**同批收口**并进 `STATUS_NAMING_TEXTS`（否则这是「修一处 = 没修」：第三、第四处照样静默腐烂）。

## 判据形态、自证与**残余**（照实登记，别把「登记了」读成「治住了」）

- **不 import 被测引擎**（`app` 包导入期需要完整 `.env` ⇒ 会红于环境而非红于口径）⇒ 照源读：
  Python 走 `ast`（语法单元）；Java 走「文本锚点 + 字面量切分」。**不按引号写取值正则** ——
  否则会落进 `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py`（issue #5325）的
  「原文口径」命中面（该文件要求「改走语法单元或先剥注释」）。
- 判据内核（`registry_mismatch` / `unattested_states` / `count_word_mismatch` /
  `missing_contract_entries` / `rules_without_named_states` / `parse_java_row_fields`）与
  **登记面的 fail-closed**（登记项不存在、锚点取不到 ⇒ 判红）**各有注入式自证**
  （`TestGuardSelfProof`）：在**构造的**缺陷载荷上必须报出问题，同一载荷不注入 ⇒ 必须干净
  —— 否则主测试的绿只是空跑（`migao-acceptance`「不会红的断言 = 空断言」）。
- **残余 ①**：C4 是**正向**判据（要求点名 + 点名全态）—— 它**不**机械禁止「再补一句矛盾的旧口径」，
  只要该条目仍同时点名了全部可达态；散文语义（否定/时序）不可机械判定，故此处**只做正向钉**。
- **残余 ②**：C3 只判「数组名 / 字段名逐字出现」，**不判** DA-016 里三个数组的**分组归属**是否写对
  （`orders` 的键写进 `skus` 那段照样过）—— 分组正确性属该用例自身的单测面（`traces.tests`）。
- **残余 ③**：真值文本里的可分数是**计数词**（「四态可分」）；`C2` 靠 `COUNT_WORDS` 认识十个词，
  超出范围的写法（如阿拉伯数字 `4态可分`）会被判「没有可分数声明」⇒ **红**（fail-closed，不是漏判）。
"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GITHUB = REPO / ".github"

ENGINE_PY = REPO / "backend" / "ai-agent-service" / "app" / "briefing" / "proactive.py"
ASSEMBLY_JAVA = (REPO / "backend" / "admin-api" / "src" / "main" / "java" / "com" / "migao"
                 / "admin" / "service" / "DailyBriefingService.java")
TRUTHS_PY = GITHUB / "truths.py"
TEMPLATES_DIR = GITHUB / "templates"
CASES_DIR = GITHUB / "cases"

#: 真值 ID（真值面）
WIRING_TRUTH_ID = "dashboard-jump.proactive-wiring-status"
DISCLOSURE_TRUTH_ID = "dashboard-jump.proactive-unwired-disclosure"
#: 用例 ID（用例面）：装配契约 / 逐规则接线状态 / 非 wired 的披露
SNAPSHOT_CASE_ID = "DA-016"
WIRING_CASE_ID = "DA-017"
DISCLOSURE_CASE_ID = "DA-018"

#: **必须逐字点名全部接线状态**的文本面（登记处；状态值一律现取）。
#: 本单的容器核查（§23 G9「关单前核容器里还有没有剩余项」）在**同一类**上又找到第三处陈旧口径
#: —— DA-018 的「未接线 / 本次不完整 / 已接入且完整但无命中」三态枚举（连它引用的真值
#: `proactive-unwired-disclosure` 也只覆盖 `not_wired` 一态）⇒ 一并收进本判据，别让它留在容器里。
#: ⚠️ **登记是显式的**：新增一个「枚举态数」的真值/用例**不会**被自动纳入；登记项改名/删除 ⇒ 红。
STATUS_NAMING_TEXTS = (
    ("truth", WIRING_TRUTH_ID),
    ("truth", DISCLOSURE_TRUTH_ID),
    ("case", WIRING_CASE_ID),
    ("case", DISCLOSURE_CASE_ID),
)

#: Java 侧锚点（**文本锚点，不写行号** —— 行号会随编辑腐烂；取不到 ⇒ 判红，不静默跳过）
JAVA_FIELDS_ANCHOR = "private static Map<String, List<String>> snapshotRowFields()"
JAVA_FIELDS_END = "record RowBatch"

#: 用例侧锚点：DA-016 里**契约键清单**那一段（C3 只认这一段，见 `contract_clause`）
CONTRACT_CLAUSE_ANCHOR = "行键逐字等于契约（"
CONTRACT_CLAUSE_END = "）"

#: 接线状态常量在引擎 `__all__` 里的**名字**（**值一律从源码读**）。C0 钉住「名字集 == 现取集合」
#: ⇒ 引擎新增/删除一个态 ⇒ 红，逼同步真值面与本清单（这就是燃尽靶，不是写死上限）。
STATUS_CONSTANTS = ("WIRED", "NOT_WIRED", "NOT_ENABLED", "INCOMPLETE")

#: 「N 态可分」的计数词（中文数字；阿拉伯数字写法按「没有可分数声明」判红 = fail-closed）
COUNT_WORDS = {"两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_COUNT_RE = re.compile(r"([两三四五六七八九十])\s*态可分")

sys.path.insert(0, str(GITHUB))

import render_cases  # noqa: E402  （`.github/render_cases.py`：用例字典的既有加载器，零第三方依赖）


# ── 单一源读取（只读、fail-closed；锚点取不到 ⇒ 判红）─────────────────────────

@lru_cache(maxsize=1)
def _engine_tree() -> ast.Module:
    return ast.parse(ENGINE_PY.read_text(encoding="utf-8"))


def _assigned(node: ast.stmt) -> tuple[str, ast.expr] | tuple[None, None]:
    """取「单目标赋值」的 (名字, 值表达式)；不是单目标赋值 ⇒ (None, None)。"""
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id, node.value
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
        return node.target.id, node.value
    return None, None


def _module_all(tree: ast.Module) -> set:
    for node in tree.body:
        name, value = _assigned(node)
        if name == "__all__" and isinstance(value, (ast.Tuple, ast.List)):
            return {e.value for e in value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    raise AssertionError(
        "引擎里找不到 `__all__`（状态常量的单一源锚点）—— 锚点漂移不得退化成静默通过："
        f"请同步本守卫（issue #5387）。文件：{ENGINE_PY.relative_to(REPO)}")


def _exported_string_constants(tree: ast.Module) -> dict:
    """`__all__` 里被赋成**字符串字面量**的模块级常量 —— 引擎自己导出的「状态取值」集合。"""
    exported = _module_all(tree)
    out: dict = {}
    for node in tree.body:
        name, value = _assigned(node)
        if name in exported and isinstance(value, ast.Constant) and isinstance(value.value, str):
            out[name] = value.value
    return out


@lru_cache(maxsize=1)
def status_values() -> dict:
    """{常量名: 状态取值}（值现取；缺一个 ⇒ C1 直接判红，不静默少判）。"""
    consts = _exported_string_constants(_engine_tree())
    missing = [name for name in STATUS_CONSTANTS if name not in consts]
    assert not missing, (
        f"引擎 `__all__` 里找不到接线状态常量 {missing} —— 状态集被改名/删除，"
        f"本守卫的清单已过期（issue #5387）：请同步 {ENGINE_PY.relative_to(REPO)} 与真值面")
    return {name: consts[name] for name in STATUS_CONSTANTS}


@lru_cache(maxsize=1)
def rules() -> tuple:
    """引擎 `RULES` 的逐条声明：{rule_id, requires_array, required_fields, has_enabled_by}（AST 读）。"""
    for node in _engine_tree().body:
        name, value = _assigned(node)
        if name != "RULES" or not isinstance(value, (ast.Tuple, ast.List)):
            continue
        out = []
        for element in value.elts:
            if not isinstance(element, ast.Call):
                continue
            kwargs = {kw.arg: kw.value for kw in element.keywords}
            rule_id = kwargs.get("rule_id")
            requires = kwargs.get("requires")
            assert isinstance(rule_id, ast.Constant) and isinstance(rule_id.value, str), (
                f"`RULES` 里有一条规则没有字符串字面量 `rule_id` —— 本守卫无法点名它"
                f"（issue #5387）：请显式写下 rule_id（{ENGINE_PY.relative_to(REPO)}）")
            assert isinstance(requires, ast.Tuple) and len(requires.elts) == 2, (
                f"规则 {rule_id.value} 的 `requires` 不是 (数组, 字段元组) 形态 —— "
                f"接线状态判据的输入契约变了，请同步本守卫（issue #5387）")
            array_key = requires.elts[0]
            field_tuple = requires.elts[1]
            out.append({
                "rule_id": rule_id.value,
                "requires_array": array_key.value,
                "required_fields": tuple(e.value for e in field_tuple.elts
                                         if isinstance(e, ast.Constant)),
                "has_enabled_by": "enabled_by" in kwargs,
            })
        assert out, (
            f"`RULES` 里一条 `RuleSpec(...)` 都没解析出来 —— 规则注册表被改名/换了形态，"
            f"不得退化成静默通过（issue #5387）：{ENGINE_PY.relative_to(REPO)}")
        return tuple(out)
    raise AssertionError(
        f"引擎里找不到 `RULES` 注册表锚点（issue #5387）：{ENGINE_PY.relative_to(REPO)}")


def parse_java_row_fields(text: str) -> dict:
    """`SNAPSHOT_ROW_FIELDS` 的**唯一**解析内核（锚点 + 字面量切分）—— 主判据与自证共用一份。

    折叠换行后再切：`fields.put("orders", List.of(...))` 在源码里**跨行**写，
    按行切会少读字段 ⇒ 那会让 C3 假绿（少读的字段「没出现在文本里」也不会被判红）。
    """
    start = text.find(JAVA_FIELDS_ANCHOR)
    assert start != -1, (
        f"Java 里找不到装配锚点「{JAVA_FIELDS_ANCHOR}」（issue #5387）—— 锚点漂移不得退化成静默通过："
        f"请同步本守卫。文件：{ASSEMBLY_JAVA.relative_to(REPO)}")
    end = text.find(JAVA_FIELDS_END, start)
    assert end != -1, (
        f"Java 里找不到装配锚点的结束标记「{JAVA_FIELDS_END}」（issue #5387）："
        f"文件 {ASSEMBLY_JAVA.relative_to(REPO)}")
    flat = " ".join(text[start:end].split())
    out: dict = {}
    for chunk in flat.split("fields.put(")[1:]:
        quoted = chunk.split('"')
        if len(quoted) < 4:
            continue
        out[quoted[1]] = [token for token in quoted[3::2]]
    return out


@lru_cache(maxsize=1)
def java_row_fields() -> dict:
    """装配层的行数组自描述 `SNAPSHOT_ROW_FIELDS`：{数组: [字段...]}（读真实文件）。"""
    out = parse_java_row_fields(ASSEMBLY_JAVA.read_text(encoding="utf-8"))
    assert out, (
        f"装配锚点里没解析出任何行数组（issue #5387）—— 判据面不得退化成「无输入即通过」："
        f"{ASSEMBLY_JAVA.relative_to(REPO)}")
    return out


@lru_cache(maxsize=1)
def truth_texts() -> dict:
    """全部真值 {ID: 文本}（复用 `.github/truths.py` 的既有加载器，不自己写一份）。"""
    spec = importlib.util.spec_from_file_location("migao_truths_for_5387", TRUTHS_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    index, conflicts, _unidentified = module.load_all_truths(str(TEMPLATES_DIR))
    assert not conflicts, f"真值 ID 冲突（同 ID 两处定义）：{conflicts} —— 真值面自身先要唯一"
    return index


@lru_cache(maxsize=1)
def cases_by_id() -> dict:
    """用例字典 {id: case}（复用 `.github/render_cases.py` 的既有加载器 = 生成物同一口径）。"""
    return {case.get("id"): case for case in render_cases.load_case_dicts(str(CASES_DIR))}


def _truth(truth_id: str) -> str:
    texts = truth_texts()
    assert truth_id in texts, (
        f"真值面找不到 `{truth_id}`（issue #5387）—— 真值 ID 被改名/删除，不得退化成静默通过："
        f"请同步 {TEMPLATES_DIR.relative_to(REPO)} 与本守卫")
    return texts[truth_id]


def _case_text(case_id: str) -> str:
    """用例的**全部文本面**（标题 + data_checks 逐条），用于「逐字出现」类判据。"""
    cases = cases_by_id()
    assert case_id in cases, (
        f"用例面找不到 `{case_id}`（issue #5387）—— 用例被改名/删除，不得退化成静默通过")
    case = cases[case_id]
    return "\n".join([str(case.get("title") or "")] + [str(x) for x in (case.get("data_checks") or [])])


def _case_items(case_id: str) -> tuple:
    """用例的 `data_checks` **逐条**文本（C4 的判定粒度 = 同一条目内点名规则与状态）。"""
    case = cases_by_id()[case_id]
    return tuple(str(x) for x in (case.get("data_checks") or []))


# ── 判据（纯函数；`""` = 无问题，便于注入式自证不写弱断言形态）────────────────

def registry_mismatch(consts: dict) -> str:
    """C0：引擎导出的字符串常量集与登记集是否一致。空串 = 一致（燃尽靶：不许把差异藏进豁免清单）。"""
    extra = sorted(set(consts) - set(STATUS_CONSTANTS))
    missing = sorted(set(STATUS_CONSTANTS) - set(consts))
    if not extra and not missing:
        return ""
    detail = []
    if extra:
        detail.append(f"引擎新增/改名而**未登记**：{extra}")
    if missing:
        detail.append(f"登记了但引擎里没有：{missing}")
    return ("；".join(detail)
            + " —— 接线状态集变了（新增/删除/改名）⇒ 必须同批同步："
              f"①{ENGINE_PY.relative_to(REPO)} 的语义注释 ②真值面 ③DA-017 / DA-018 的文本 "
              "④本守卫的 STATUS_CONSTANTS（issue #5387）")


def unattested_states(truth_text: str, values: dict) -> str:
    """C1：真值文本里**没逐字点名**的状态（名字 + 值）。空串 = 全部点名。"""
    missing = [f"{name}（`{value}`）" for name, value in values.items() if value not in truth_text]
    if not missing:
        return ""
    return ("该文本面没有逐字点名接线状态：" + "、".join(missing)
            + " —— 枚举态是**单一源**（引擎 `__all__` 的字符串常量），真值面必须点名每一个，"
              "否则「系统有、该租户没开」与「系统没实现」在真值层面不可分（issue #5387）")


def count_word_mismatch(truth_text: str, state_count: int) -> str:
    """C2：真值文本里「N 态可分」的 N 与现取状态数一致吗（写死数字 = 会腐烂的副本）。空串 = 一致。"""
    match = _COUNT_RE.search(truth_text)
    if not match:
        return (f"真值文本没有「N 态可分」的可分数声明（现取状态数 {state_count}）—— "
                "把可分数写出来才可能被判据钉住（issue #5387）；**不许**用阿拉伯数字偷懒，"
                "本守卫按中文计数词读，读不到即判红")
    got = COUNT_WORDS[match.group(1)]
    if got == state_count:
        return ""
    return (f"真值文本写「{match.group(0)}」（= {got}）而引擎现取状态数是 {state_count} —— "
            "散文里的数必须等于单一源（issue #5387 / 同族：issue #4819 的「散文抄常量」）")


def contract_clause(case_text: str) -> str:
    """DA-016 里**契约键清单**那一段（`行键逐字等于契约（…）` 的括号内）。

    🔴 为什么必须**定位到这一段**而不是全文找子串：本单的历史形态恰恰是
    「文本里**出现了** `cost_amount` —— 但那是『orders 行**没有** cost_amount』这句旧口径」
    ⇒ 全文子串判据会被**自己的文案**喂绿（`test_guard_parsing_is_comment_aware.py` 同族的
    「判据被文案喂绿」）。锚点取不到 ⇒ 判红（fail-closed），不静默退化。
    """
    start = case_text.find(CONTRACT_CLAUSE_ANCHOR)
    assert start != -1, (
        f"DA-016 里找不到契约键清单的锚点「{CONTRACT_CLAUSE_ANCHOR}」（issue #5387）—— "
        f"锚点漂移不得退化成静默通过：请同步本守卫（issue #5387）")
    end = case_text.find(CONTRACT_CLAUSE_END, start)
    assert end != -1, (
        f"DA-016 的契约键清单锚点没有配对的「{CONTRACT_CLAUSE_END}」（issue #5387）：请同步本守卫")
    return case_text[start + len(CONTRACT_CLAUSE_ANCHOR):end]


def missing_contract_entries(case_text: str, row_fields: dict) -> str:
    """C3：装配层声明的行数组/字段里，**没**出现在 DA-016 契约键清单里的（历史形态 = cost_amount）。

    数组名判在**全文**（数组名不会以「没有 X 数组」的反向口径出现在清单外），
    字段名判在**契约键清单那一段**（否则会被反向口径喂绿，见 `contract_clause`）。
    """
    clause = contract_clause(case_text)
    missing = [array for array in row_fields if array not in case_text]
    missing.extend(f"{array}.{field}" for array, fields in row_fields.items()
                   for field in fields if field not in clause)
    if not missing:
        return ""
    return ("装配层 `SNAPSHOT_ROW_FIELDS` 声明的行数组/字段没被 DA-016 的契约键清单覆盖："
            + "、".join(missing)
            + " —— 装配层加了行字段就必须同步用例文本，否则用例在描述一个**不存在**的契约"
              "（issue #5387；注意判据只认**契约键清单那一段**，别处提到该字段名不算）")


def reachable_states(rule: dict, declared: dict, values: dict) -> tuple:
    """某规则的**可达状态集**（由源推导，不写死结论）：

    · `requires` 的数组没装配、或要求的字段不在装配声明里 ⇒ 只有 `not_wired`（结构性接不通）；
    · 否则可达 `wired`（本次完整）与 `incomplete`（本次不完整：截断 / 维度缺值 / 有行未判定）；
    · 另有 `enabled_by`（租户级前置）⇒ 再加 `not_enabled`（系统**有**、该租户**没开**）。
    """
    array = rule["requires_array"]
    fields = declared.get(array)
    if fields is None or [f for f in rule["required_fields"] if f not in fields]:
        return (values["NOT_WIRED"],)
    out = [values["WIRED"], values["INCOMPLETE"]]
    if rule["has_enabled_by"]:
        out.append(values["NOT_ENABLED"])
    return tuple(out)


def rules_without_named_states(items, rules_, declared: dict, values: dict) -> str:
    """C4：每条规则必须被点名，且**同一条** `data_checks` 里点名它全部可达状态。空串 = 全部达标。"""
    problems = []
    for rule in rules_:
        rule_id = rule["rule_id"]
        reachable = reachable_states(rule, declared, values)
        naming = [item for item in items if rule_id in item]
        if not naming:
            problems.append(f"`{rule_id}`：没有任何 data_checks 条目点名它")
            continue
        if not any(all(value in item for value in reachable) for item in naming):
            problems.append(
                f"`{rule_id}`：点名它的条目里没有一条同时点名全部可达状态 "
                f"{'、'.join('`' + v + '`' for v in reachable)}（现取）")
    if not problems:
        return ""
    return ("DA-017 的逐规则接线状态描述与引擎 `RULES` × 装配声明不一致：\n  · "
            + "\n  · ".join(problems)
            + "\n  ⇒ 规则的可达状态集是**推导结果**（`requires` × `enabled_by` × 装配声明），"
              "主干改了规则/字段/租户前置就必须同步本用例（issue #5387）")


# ── 主判据（真值面 / 用例面；任一红 = 用例面文本与主干事实不一致）──────────────

def test_status_constants_are_fully_registered():
    """C0（覆盖度 + 燃尽靶）：引擎导出的字符串常量集必须**恰好** = 本守卫登记的状态集。"""
    problem = registry_mismatch(_exported_string_constants(_engine_tree()))
    assert problem == "", problem


def test_truth_names_every_wiring_state():
    """C1：真值必须逐字点名每个接线状态（第四态 `not_enabled` 未入真值 = 本单的第 ③ 条）。"""
    problem = unattested_states(_truth(WIRING_TRUTH_ID), status_values())
    assert problem == "", problem


def test_registered_texts_name_every_wiring_state():
    """C1′（类级、容器收口）：**每条登记的真值/用例文本**都必须逐字点名全部现取状态。

    登记处 = `STATUS_NAMING_TEXTS`（真值 2 条 + 用例 2 条）。本判据是 C1 的**面**，不是重复：
    它把「枚举态数的每一处文本」都挂上同一条机械联系 —— 主干加一个态，这里逐条变红。
    """
    values = status_values()
    problems = []
    for kind, ident in STATUS_NAMING_TEXTS:
        text = _truth(ident) if kind == "truth" else _case_text(ident)
        problem = unattested_states(text, values)
        if problem:
            problems.append(f"{kind} {ident}：{problem}")
    assert problems == [], (
        "登记的文本面没点名全部接线状态（主干加了态而文本没跟）：\n  · " + "\n  · ".join(problems))


def test_truth_state_count_matches_engine():
    """C2：真值文本的可分数必须是**四**（现取），写「三者可分」= 陈旧口径。"""
    problem = count_word_mismatch(_truth(WIRING_TRUTH_ID), len(status_values()))
    assert problem == "", problem


def test_snapshot_case_text_covers_assembly_row_fields():
    """C3：装配层声明的每个行数组/字段都要在 DA-016 的契约键清单里逐字出现。"""
    problem = missing_contract_entries(_case_text(SNAPSHOT_CASE_ID), java_row_fields())
    assert problem == "", problem


def test_wiring_case_names_every_rule_with_all_reachable_states():
    """C4：DA-017 要逐条点名规则，并在同一条目内点名它的全部可达状态。"""
    problem = rules_without_named_states(
        _case_items(WIRING_CASE_ID), rules(), java_row_fields(), status_values())
    assert problem == "", problem


def test_coverage_anchor_is_live_and_printed(capsys):
    """燃尽锚点（`-s` 可见）：四面覆盖度全部**现取**，任一面收窄都会让上面四条判据变红。

    覆盖面 = 真值 1 条 × 状态 N / 装配数组 N（字段 N）/ 规则 N —— **没有**豁免清单、**没有**
    「其余不判」的口子（本类当前**零豁免**：旧口径全部已按主干刷新，见 issue #5387）。
    """
    declared = java_row_fields()
    counts = {
        "truths": 1,
        "named_texts": len(STATUS_NAMING_TEXTS),
        "states": len(status_values()),
        "arrays": len(declared),
        "fields": sum(len(v) for v in declared.values()),
        "rules": len(rules()),
        "case_items": len(_case_items(WIRING_CASE_ID)),
    }
    anchor = "[issue #5387] 接线状态同步守卫的现取覆盖度：" + "，".join(
        f"{key}={value}" for key, value in counts.items())
    print(anchor)
    assert "issue #5387" in capsys.readouterr().out, "燃尽锚点没有真的打印出来（读数必须看得见）"
    assert counts["states"] >= 2, "接线状态少于 2 个（wired / 非 wired 不可分）—— 判据面已失真"
    assert counts["arrays"] >= 1, "装配层一个行数组都没解析出来 —— 判据面已失真"
    assert counts["rules"] >= 1, "引擎一条规则都没解析出来 —— 判据面已失真"
    assert counts["truths"] == 1 and counts["case_items"] >= 1, (
        "真值面或用例面的判据输入为空 —— 判据不得在「无输入」时静默通过（issue #5387）")
    assert counts["named_texts"] >= 4, (
        f"点名态集的文本面只剩 {counts['named_texts']} 处（< 4）—— 收窄覆盖面是**覆盖损失**，"
        "会让「主干加态而某处文本没跟」重新变成静默失效；确需收窄请在本判据里说明并逐条登记"
        "（issue #5387）")
    assert counts["fields"] >= counts["arrays"], "行字段数少于数组数 —— 解析器已失真"


# ── 注入式自证（证明上面四条判据真的会红，而不是「一起绿」）────────────────────

class TestGuardSelfProof:
    """在**构造的**缺陷载荷上必须报出问题；同一载荷不注入 ⇒ 必须干净。"""

    def test_registry_mismatch_detector_is_discriminating(self):
        """C0 的判据内核：**登记面**与现取集合的差集两个方向都要判红。"""
        real = _exported_string_constants(_engine_tree())
        assert registry_mismatch(real) == "", "登记集与现取集合本应一致 ⇒ 判据在乱红"
        grown = dict(real, FIFTH_STATE="fifth_state")
        assert "FIFTH_STATE" in registry_mismatch(grown), \
            "引擎新增一个态而没登记 ⇒ 必须判红且**点名**该常量（否则「加态」静默落地）"
        shrunk = {k: v for k, v in real.items() if k != "INCOMPLETE"}
        assert "INCOMPLETE" in registry_mismatch(shrunk), \
            "引擎删掉一个登记过的态 ⇒ 必须判红（登记面不得比现实宽）"

    def test_registered_entries_must_exist(self):
        """登记项改名/删除 ⇒ fail-closed 判红，**不得**静默跳过（否则判据面会自己缩水）。"""
        for kind, ident in (("truth", "dashboard-jump.no-such-truth-5387"),
                            ("case", "ZZ-999")):
            lookup = _truth if kind == "truth" else _case_text
            try:
                lookup(ident)
            except AssertionError as exc:
                assert ident in str(exc), f"{kind} {ident} 的不存在必须被点名报出，实测：{exc}"
            else:
                raise AssertionError(
                    f"{kind} {ident} 在仓里不存在却没判红 —— 判据会退化成「无输入即通过」")

    def test_state_naming_detector_is_discriminating(self):
        values = {"WIRED": "wired", "NOT_WIRED": "not_wired",
                  "NOT_ENABLED": "not_enabled", "INCOMPLETE": "incomplete"}
        clean = "`wired` / `incomplete` / `not_enabled` / `not_wired` 四态"
        assert unattested_states(clean, values) == "", "干净载荷被误判 ⇒ 判据在乱红"
        stale = "`wired` / `incomplete` / `not_wired` 三者"
        assert unattested_states(stale, values) != "", "漏掉 not_enabled 的载荷必须被判红"
        assert "NOT_ENABLED" in unattested_states(stale, values), "判红必须**可归因**到具体的态"

    def test_count_word_detector_is_discriminating(self):
        assert count_word_mismatch("四态可分", 4) == "", "一致的可分数被误判 ⇒ 判据在乱红"
        assert count_word_mismatch("三者可分", 4) != "", "三年者可分 vs 现取 4 ⇒ 必须判红"
        assert count_word_mismatch("四态可分", 5) != "", "引擎加第五态而文本仍写四 ⇒ 必须判红"
        assert count_word_mismatch("四个状态都可以分开", 4) != "", "没有可分数声明 ⇒ fail-closed 判红"

    def test_contract_field_detector_is_discriminating(self):
        declared = {"orders": ["order_no", "cost_amount"], "skus": ["sku_id"]}
        clean = ("快照带 orders/skus 两个行级数组，行键逐字等于契约"
                 "（order_no/cost_amount；skus 的 sku_id）")
        assert missing_contract_entries(clean, declared) == "", "干净载荷被误判 ⇒ 判据在乱红"
        stale = "快照带 orders/skus 两个行级数组，行键逐字等于契约（order_no；skus 的 sku_id）"
        problem = missing_contract_entries(stale, declared)
        assert "orders.cost_amount" in problem, "装配层新增字段而文本没同步 ⇒ 必须判红且点名该字段"
        # 反向口径**不得**把判据喂绿：只提到字段名而没进契约键清单 ⇒ 仍判红（本单的历史形态）
        negative = ("快照带 orders/skus 两个行级数组，行键逐字等于契约（order_no；skus 的 sku_id）；"
                    "orders 行**没有** cost_amount")
        assert "orders.cost_amount" in missing_contract_entries(negative, declared), \
            "「文本里出现了该字段名（但写的是『没有』）」把判据喂绿了 —— 判据必须只认契约键清单那一段"

    def test_rule_state_detector_is_discriminating(self):
        values = {"WIRED": "wired", "NOT_WIRED": "not_wired",
                  "NOT_ENABLED": "not_enabled", "INCOMPLETE": "incomplete"}
        declared = {"orders": ["order_no"]}
        tenant_rule = {"rule_id": "below_cost_price", "requires_array": "orders",
                       "required_fields": ("order_no",), "has_enabled_by": True}
        gap_rule = {"rule_id": "price_change_over", "requires_array": "price_changes",
                    "required_fields": ("change_no",), "has_enabled_by": False}
        assert reachable_states(tenant_rule, declared, values) == (
            "wired", "incomplete", "not_enabled"), "租户前置规则的态集推导错了（判据口径漂移）"
        assert reachable_states(gap_rule, declared, values) == ("not_wired",), "结构性缺口推导错了"
        clean = ("装配行级数组后 below_cost_price 随租户三态：`wired` / `incomplete` / `not_enabled`；"
                 "price_change_over 缺 price_changes ⇒ `not_wired`")
        assert rules_without_named_states([clean], [tenant_rule, gap_rule], declared, values) == "", \
            "干净载荷被误判 ⇒ 判据在乱红"
        stale = ("装配行级数组后 below_cost_price 与 price_change_over 两条结构性不可达为 `not_wired`")
        problem = rules_without_named_states([stale], [tenant_rule, gap_rule], declared, values)
        assert "below_cost_price" in problem, "把随租户三态的规则写死成 not_wired ⇒ 必须判红"
        unnamed = rules_without_named_states(["与规则名无关的一段话"], [tenant_rule], declared, values)
        assert "below_cost_price" in unnamed, "规则没被点名 ⇒ 必须判红（覆盖度不得静默收窄）"

    def test_java_row_field_parser_survives_line_wrapping(self):
        """解析器自身的判别力：跨行的 `fields.put(...)` 少读字段 ⇒ 判据会假绿。"""
        snippet = (
            '    private static Map<String, List<String>> snapshotRowFields() {\n'
            '        Map<String, List<String>> fields = new LinkedHashMap<>();\n'
            '        fields.put("orders", List.of("order_no", "cost_amount",\n'
            '                "sale_amount"));\n'
            '        fields.put("skus", List.of("sku_id"));\n'
            '    }\n'
            '    record RowBatch(List<Map<String, Object>> rows, boolean truncated) {\n'
        )
        parsed = parse_java_row_fields(snippet)
        assert parsed == {"orders": ["order_no", "cost_amount", "sale_amount"], "skus": ["sku_id"]}, \
            f"跨行 `fields.put` 解析失真：{parsed}"