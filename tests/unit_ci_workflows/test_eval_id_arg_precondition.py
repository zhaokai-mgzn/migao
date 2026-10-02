# case_ids: MC-049
"""类级固化 B：**把「名称」塞进 id 型参数 ⇒ 必须声明对应前置**（issue #6041；PR-003 的形状）。

## 病灶（真实实例 = PR-003，2026-10-02 活栈实测假红）

`.github/cases/**` 的期望里出现 `product_detail(product_id=遮光窗帘)` 这种形态时，那条期望真正
依赖的是**「该名称能被解析成唯一一件商品」**这条**只读前置**。此前 PR-003 **没有声明任何前置** ⇒
名字不唯一（活栈实测 tenant 1 名字含「遮光窗帘」的商品 **7 件**）时，agent 会**正确地**反问
「要查看哪一件」（发 choice 交互卡），而报告上表现为 `unmatched expectation`
⇒ 被判 `🔬 确定性回归·禁止 rerun`（**假红**，归因指向「agent 不会查商品详情」= 全错）。

**形状**：`<id 型参数名>: <人读名称>` —— 此时「名称能解析成谁」是**运行期数据事实**，
不是用例能假定的常量。⇒ 必须把该事实写成可判定的 `precondition`（成立则跑、不成立则落
「前置不成立」而**不落行为失败**）。

## 判据（纯静态、可解释、不许宽到误伤）

`_PARAM_PRECONDITION_TYPES` 逐条给出「哪个工具的哪个参数 = 哪一种前置」，规则是**判据自己声明
的唯一真相源**（并由判据 4 反向核对：每条映射指向的 type 必须在 runner 的实现集里，否则红）。
对真语料逐条期望核：

- **判据 1**：值不是 id 形态、且**不是**指向上轮产物的占位（`复用上轮 UUID` / `<case-id>` 这类
  上轮接续），且**不落**在任一已声明前置的 `source` 里 ⇒ 该 id 型参数**必须有**对应前置 ⇒ 否则红；
- **判据 2**：规则表里每个 `<tool, arg>` 的 `(type, source)` 必须在 `_PARAM_PRECONDITION_TYPES`
  声明的 `allowed_types` 内、且真语料里存在 `type == 必需 type` 的前置 ⇒ 否则红（挂到不存在的前置上）；
- **判据 3**：判别力自证 —— 未实现的 type / 没有声明前置的用例副本 / 规则指向未登记 type
  ⇒ **各自判红**；只改注释 ⇒ **不红**。

## 边界（照实登记，**不要把本判据读成覆盖面更大的东西**）

- 判的是**声明层形态**，判不了「那条前置本身对不对」（值/下界是 `test_precondition_target_present.py`
  与 `test_eval_precondition_types_implemented.py` 的面），也判不了「该名称在某个栈上到底唯一与否」
  —— 那是运行期 `precondition[...]` 的读数（本判据只保证**它被声明**）。
- 「占位 = 上轮产物」的判定是**词法**的：照 `PROSE_PLACEHOLDER` 的两种形态（含「上轮」或尖括号占位）。
  值里含 `<用例号>` 的形态由「值不落在任一 source 里」一并放行（那是名义上的跨用例引用，不是共享夹具名）。
- 本判据**不跑**评测、**不联网**、**不 import** ai-agent 依赖（CI 的 `ci workflow helper unit tests`
  只装 `pytest` + `pyyaml`），也**禁**「跑不了就跳」；**不改**任何门禁的通过条件、不新增豁免。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_REL = "tests/agent_eval/local_runner.py"
CASES_DIR = REPO_ROOT / ".github" / "cases"

sys.path.insert(0, str(REPO_ROOT / ".github"))
from render_cases import load_case_dicts  # noqa: E402  —— 用例书解析的仓内单一实现（纯 stdlib + pyyaml）

#: 规则表（本判据的射程**显式声明**，不靠想象；`allowed_types` 由判据 4 反向核对）。
#: `allowed_types[0]` = **必需**的前置 type；其余是等价可接受形态（指向同一批共享夹具的其它类型）。
_PARAM_PRECONDITION_TYPES: dict = {
    ("product_detail", "product_id"): {
        "allowed_types": ("product_count_for_keyword", "processing_item_count_for_keyword"),
        "why": "商品详情按名称定位 ⇒ 该名称唯一性是只读前置（PR-003 的形状）",
    },
    ("product_update", "product_id"): {
        "allowed_types": ("product_count_for_keyword", "processing_item_count_for_keyword"),
        "why": "商品改价按名称定位 ⇒ 同名副本会让 agent 反问要改哪一件",
    },
}

#: id 形态（UUID / 纯数字 / 种子短 id / 星座号/MC 号这类登记键）—— 这些是**真 id**，不在本判据射程。
_ID_SHAPED = re.compile(r"\A(?:[0-9a-f]{16,}|[0-9]{3,}|[A-Z]{2,6}-[0-9]{2,}|[a-z]{2,10}_[a-z0-9_]+)\Z")
#: 「上轮产物 / 跨用例引用」的**词法**占位形态（不是共享夹具的固有名；与仓内既有判据
#: `tests/unit_ci_workflows/test_eval_idsynced_reuse_case.py` 的 `^<[^<>]*>$` 同口径，
#: **不用 `\A<.*>\Z`** —— 真实语料里存在「…含 `<MC-067>` 的那条用例」这类**句子里带尖括号**的值，
#: 贪婪形态会把它们一并放行 ⇒ 判据退化成永绿，本包实测踩过）。
_PROSE_PLACEHOLDER = re.compile(r"上轮|\A<[^<>]*>\Z")
#: 用例号形态（值里出现它 ⇒ 这条期望是**跨用例引用**而不是按共享夹具名定位）。
_CASE_ID_IN_VALUE = re.compile(r"\b[A-Z]{2,6}-[0-9]{2,}\b")


def _registered_types() -> set:
    """runner 的 `_PRECONDITION_TYPES` 键集（AST 反解，纯静态）。"""
    tree = ast.parse((REPO_ROOT / RUNNER_REL).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "_PRECONDITION_TYPES":
            return {k.value for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    raise RuntimeError(f"找不到 {RUNNER_REL} 的 _PRECONDITION_TYPES（判据 fail-closed）")


def _cases() -> list:
    return load_case_dicts(CASES_DIR)


def _declared_preconditions(case: dict) -> list:
    pc = case.get("precondition")
    return [s for s in pc if isinstance(s, dict)] if isinstance(pc, list) else []


def _id_like_keys() -> set:
    """规则射程用到的 id 型参数名（`_PARAM_PRECONDITION_TYPES` 的第二个分量）。"""
    return {arg for _tool, arg in _PARAM_PRECONDITION_TYPES}


def _issues(cases: list) -> list:
    """判据 1~2 的判定体（纯函数，便于注入式自证）。"""
    out: list = []
    ids_in_corpus = _CASE_ID_IN_VALUE
    for c in cases:
        cid = str(c.get("id") or "?")
        declared = _declared_preconditions(c)
        sources = {str(s.get("source") or "") for s in declared}
        for e in (c.get("expectations") or []):
            if not isinstance(e, dict):
                continue
            tool = str(e.get("tool") or "")
            args = e.get("args") or {}
            if not isinstance(args, dict):
                continue
            for arg, value in args.items():
                if arg not in _id_like_keys() or not isinstance(value, str) or not value:
                    continue
                rule = _PARAM_PRECONDITION_TYPES.get((tool, arg))
                if rule is None:                      # 规则越界 ⇒ 见判据 2（另一条腿现取核对）
                    out.append(f"{cid}: 期望的 id 型参数 {tool}.{arg} 的形态触及规矩但规则表里没有它")
                    continue
                if _ID_SHAPED.match(value):           # 真 id ⇒ 本判据射程之外
                    continue
                if _PROSE_PLACEHOLDER.search(value):  # 上轮产物占位 ⇒ 不是共享夹具名
                    continue
                if ids_in_corpus.search(value):       # 跨用例引用（值里含 MC-067 这类用例号）
                    continue
                if value in sources:                  # 已按同一名称声明了前置 ⇒ 合规
                    continue
                need = rule["allowed_types"][0]
                out.append(
                    f"{cid}: 期望 {tool}.{arg}={value!r} 是**人读名称**、且没有前置声明 "
                    f"[{need}, source={value!r}] —— 名称唯一性未被核过：名字不唯一时 agent 会合理地"
                    f"反问要哪一件，期望落空却伪装成「agent 不干活」（{rule['why']}）")
        # 判据 2：挂在不存在的前置上（声明了 type 但没实现 / 规则指向未登记 type）
        for s in declared:
            t = str(s.get("type") or "")
            if t and t not in _registered_types():
                out.append(f"{cid}: precondition.type {t!r} 不在 runner 实现集里（该前置不会被求值）")
    for (tool, arg), rule in _PARAM_PRECONDITION_TYPES.items():
        for t in rule["allowed_types"]:
            if t not in _registered_types():
                out.append(f"规则表 ({tool}.{arg}) 指向未登记的 precondition type {t!r}（判据自身失效）")
    return out


def test_id_typed_arguments_with_names_declare_matching_preconditions():
    """判据 1+2：真语料上没有任何「名称塞进 id 型参数却不声明前置」的用例。"""
    issues = _issues(_cases())
    assert not issues, (
        "以下用例把**人读名称**塞进 id 型参数、却没有声明对应前置（名称唯一性无处可判）：\n  "
        + "\n  ".join(issues)
        + "\n出口：给该用例补 `precondition[<type>, source=<该名称>, expect: 1]`"
          "（并配 `pre_clean[product_dedupe]` 同类收敛动作），或在规则表里说明为什么它不需要。")


def test_rule_table_points_at_implemented_types():
    """判据 4：规则表的每条 `allowed_types` 都必须指向 runner 已登记的类型（判据自身不许悬空）。"""
    registered = _registered_types()
    dangling = sorted({t for rule in _PARAM_PRECONDITION_TYPES.values()
                       for t in rule["allowed_types"] if t not in registered})
    assert not dangling, f"规则表指向未登记的前置类型：{dangling}"


def test_red_proof_injections_are_named():
    """判据 3（注入式红证 + 反向对照）：三种坏形态在内存里各自判红，真实语料不报，注释改动不报。"""
    real = _cases()
    clean = _issues(real)
    assert not clean, f"**真实语料**上已有违规（判据 1/2 的核心缺口）：{clean}"

    # ① 摘掉**真语料里那条「按名称定位 + 已声明该前置」用例**的声明（不写死用例 id ⇒ 判据搬走后仍成立）
    def _name_like_product_id(case: dict) -> str:
        for e in (case.get("expectations") or []):
            if not isinstance(e, dict) or e.get("tool") != "product_detail":
                continue
            v = (e.get("args") or {}).get("product_id")
            if isinstance(v, str) and v and not _ID_SHAPED.match(v) \
                    and not _PROSE_PLACEHOLDER.search(v) and not _CASE_ID_IN_VALUE.search(v):
                return v
        return ""

    hit = next(((str(c.get("id")), _name_like_product_id(c)) for c in real
                if _name_like_product_id(c)
                and _name_like_product_id(c)
                in {str(s.get("source") or "") for s in _declared_preconditions(c)}), None)
    assert hit, "真语料里找不到「按名称定位商品且已声明对应前置」的用例（判据射程漂了）"
    hit_id, hit_name = hit
    no_pre = [({k: v for k, v in c.items() if k != "precondition"} if str(c.get("id")) == hit_id
               else c) for c in real]
    got = _issues(no_pre)
    assert any(hit_id in g and "product_id" in g for g in got), \
        f"摘掉 {hit_id}（{hit_name}）的前置声明后未被判红（判据退化成永绿）：{got}"

    # ② 声明一个未实现的 type ⇒ 必须判红
    bad_type = [dict(c) for c in real]
    bad_type[0] = dict(bad_type[0])
    bad_type[0]["precondition"] = [{"type": "redproof_unimplemented", "source": "x"}]
    assert any("redproof_unimplemented" in g for g in _issues(bad_type)), \
        "未实现的前置 type 未被判红"

    # ③ 规则表指向未登记 type ⇒ 必须判红（判据自身失效的形态）
    saved = _PARAM_PRECONDITION_TYPES[("product_update", "product_id")]
    _PARAM_PRECONDITION_TYPES[("product_update", "product_id")] = {
        "allowed_types": ("redproof_not_registered",), "why": "注入"}
    try:
        assert any("redproof_not_registered" in g for g in _issues(real)), \
            "规则表指向未登记类型时未被判红"
    finally:
        _PARAM_PRECONDITION_TYPES[("product_update", "product_id")] = saved

    # ④ 反向对照：只改注释 ⇒ 不红
    commented = [dict(c) for c in real]
    commented[0] = dict(commented[0])
    commented[0]["merge_log"] = str(commented[0].get("merge_log") or "") + " # 只加一条注释"
    assert not _issues(commented)


def test_the_rule_really_matches_a_real_case():
    """判据 5（射程自证）：规则表必须**真的**在真语料上命中 ≥1 条 —— 否则「没报红」只是「没扫到」。

    为什么必须有：把这条判据的射程改成空集（改错工具名 / 参数名）时，
    「真语料零违规」会**恒成立** ⇒ 判据退化成永绿。本包实测踩过同族形态：
    目标的 `expectations` 被误删后，`_issues` 对一切都返回空表（**绿得毫无根据**）。
    """
    hits = []
    for c in _cases():
        sources = {str(s.get("source") or "") for s in _declared_preconditions(c)}
        for e in (c.get("expectations") or []):
            if not isinstance(e, dict):
                continue
            arg_val = (e.get("args") or {}).get("product_id")
            if (str(e.get("tool") or ""), "product_id") in _PARAM_PRECONDITION_TYPES \
                    and isinstance(arg_val, str) and arg_val in sources:
                hits.append(str(c.get("id")))
    assert hits, ("规则表（product_detail/product_update 的 product_id）在真语料上**零命中** —— "
                  "射程已漂（工具名 / 参数名改了？），「真语料无违规」这一句因此没有根据；"
                  "出口：把 _PARAM_PRECONDITION_TYPES 的键改成现取真语料里真实存在的 <工具, 参数>。")


def test_the_instance_case_still_declares_its_expectation():
    """判据 6（实例面防误删）：PR-003 的 `expectations` 必须仍在 YAML 原文里（issue #6041 的实例）。"""
    text = (CASES_DIR / "product.yml").read_text(encoding="utf-8")
    i = text.index("  - id: PR-003")
    j = text.index("  - id: PR-004")
    assert "product_id: 遮光窗帘" in text[i:j], (
        "PR-003 的期望 `product_detail(product_id=遮光窗帘)` 不在块里了 —— 断言面被误删/改判"
        "（这类丢失不会让任何行为判据变红：期望为空时报绿得毫无根据）")


def test_this_judgement_is_pure_static_and_never_skips():
    """纯静态自证：零 ai-agent 依赖 + 禁「跑不了就跳」（跳 = 绿了但没跑）。"""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = imported & {"pydantic", "langchain_core", "langchain", "fastapi", "app"}
    assert not forbidden, f"本判据不得依赖 ai-agent 运行时依赖（CI 里没装）：{sorted(forbidden)}"
