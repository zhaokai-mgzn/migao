# case_ids: MC-246
"""代码判据类用例必须声明契约标记（`[backend-contract]` / `[frontend-contract]`）。

## 病（实证 run 42127246100，2026-11-06）

```
gh workflow run post-deploy-eval.yml --ref main -f tier=normal -f persona=both \\
  -f case_ids='' -f purpose=determination
```

⇒ run **42127246100** = failure：`mibao 行为回归` + `xiaobu 行为回归` **两条腿都红**
（`部署后回归结论` 腿 success —— 它只汇总，不判分）。失败形态**全部**是
`unmatched expectation`，命中的 12 条**全部**是代码判据类用例：

`MC-202` / `MC-209` / `MC-210` / `MC-216` / `MC-217` / `MC-218` / `MC-219` /
`MC-220` / `MC-227` / `MC-234` / `MC-235` / `MC-240`

它们断言的原文是「扫 `frontend/bmini-app/src/**/*.scss` 的每一条 `@use` / `@import` …目标不存在
⇒ 判红并具名」「扫 `git ls-files` 的全部入库文件 …行首七字符冲突标记 ⇒ 判红并具名」
「暂存目录**不在**仓库目录树里」这类**代码判据**，真值在 `traces.tests` 指向的 pytest / node 里。

## 根因

`tests/agent_eval/eval_case_filter.py` 的选择函数里有一行
`cases = [c for c in cases if not case_skip_reason(c)]` —— **机制是有的：`skip_reason` 非空即被过滤**。
而现取这 12 条的 `skip_reason` **全是空串** ⇒ 被 `tier=normal` 全量选中 ⇒ agent 跑不动
⇒ **每一轮判定档评测都全红**。修法是给它们补 `skip_reason`（判据在 `traces.tests`，
`skip_reason` 只说明「不进 LLM 评测」），本文件是防复发的**类级元守卫**。

## 判据（两个**独立**信号，各自 fail-closed）

| 信号 | 内容 |
|---|---|
| **B（结构）** | `expectations` **非空**，且 `assertion_taxonomy.expectation_tools()` **一条工具名都取不到** ⇒ 该用例没有任何可被 runner 计分的 agent 行为断言 ⇒ 必须声明契约标记 |
| **A（词面）** | `expectations` 命中 `CODE_CRITERION_ANCHORS` 里的任一**代码判据形态锚点** ⇒ 必须声明契约标记 |

信号 B **复用仓库既有的单一判据源**（`assertion_taxonomy.expectation_tools`），不新写一套工具名解析
（两套口径必然漂移）。现取实测：全库 1067 条里「no-skip + 非空 `expectations` + 零工具名」= **12** 条，
**恰是**上面那 12 条，误伤 **0**。

信号 A 的锚点集合是**现取统计**出来的，不是拍脑袋选的：每一个锚点在「160 条真 LLM 行为用例」上的
命中数都是 **0**（`0` = 误伤），而在那 12 条上至少命中 1 条。刻意**不用**单个「不」这类宽词
（它会把全库判红）。复算命令见 `test_anchor_set_has_no_false_positives` 的 docstring。

**为什么两个信号都要**（都不完备，各自的洞实测存在）：
- 只靠 B：把断言写成 `{tool: "<中文散文>"}` 的用例会漏 —— `expectation_tools` 对 dict 形态
  **不校验**工具名形状，任何字符串都算一条「工具」（见其实现）；
- 只靠 A：词表**完不完备**无法自证（新形态的代码判据可以不带任何既有锚点）。
⇒ 取并集；两者现取**都无误伤**，并集覆盖 12/12。

## 扫描面自证（fail-closed，两条下界）

1. 全库用例数 ≥ `MIN_LIBRARY_CASES` —— 读不到用例时「零违规」是假绿；
2. 锚点命中面 ≥ `MIN_ANCHOR_HITS` —— 锚点全失效时「零违规」同样是假绿（判据失明）。
   ⚠️ 这一条**不许**实现成「扫到 0 条 ⇒ 通过」：那是本仓被点名过多次的空断言形态。

## 正控 / 负控（逐条实跑）

| 控制 | 语料 | 期望 |
|---|---|---|
| 正控 A | 「扫 `frontend/**/*.scss` 的每一条 `@use` ⇒ 目标不存在判红并具名」，`skip_reason` 空 | **红并具名** |
| 正控 B | `expectations` 非空但一条工具名都没有（纯散文），`skip_reason` 空 | **红并具名** |
| 负控 1 | 「用户问订单状态 ⇒ agent 调 `order_query`」 | **不许红** |
| 负控 2 | `{tool: direct_reply}`（合法行为期望 = 断言「不调工具」，实测 7 条是这形态） | **不许红** |
| 负控 3 | `expectations` 为空、走 `forbidden_text` / `forbidden_tools` 通道（`CH-049` / `PR-073`） | **不许红** |
| 负控 4 | 已声明契约标记的同形态用例 | **不许红** |

## 未覆盖（照实登记，不写成恒真判断）

- `expectations` **完全为空**、且既无 `forbidden_*` 也无 `want_text` 的用例 —— 本判据**不表态**
  （现取 0 条；那属于「空断言」的另一族，与本文判据面不同）；
- 本判据判的是「**该标而未标**」，不判 `skip_reason` 的文案质量，也不判 `traces.tests`
  里那条测试**是否真的会红**（后者由 `case_trust_gate` 的规则族负责）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))

from assertion_taxonomy import (  # noqa: E402
    CONTRACT_MARKERS,
    expectation_tools,
    is_backend_contract_case,
)

CASES_DIR = REPO_ROOT / ".github" / "cases"

#: 全库用例数下界（现取 1067；下界只防"读不到用例 ⇒ 零违规 ⇒ 假绿"）。
MIN_LIBRARY_CASES = 900

#: 锚点命中面下界（现取 12；锚点整体失效 ⇒ 判据失明 ⇒ 必须红，不许静默通过）。
MIN_ANCHOR_HITS = 12

#: 代码判据形态锚点 —— **每个锚点在 160 条真 LLM 行为用例上误伤 = 0**（现取实测）。
#: 判据口径 = 命中任一即视为「这条 expectations 断言的不是 agent 行为」。
CODE_CRITERION_ANCHORS: tuple = (
    "扫",          # 「扫 xx 文件 / 扫 git ls-files」—— 扫描面判据的开头
    "扫描面",      # 「扫描面非空（> 100 个源文件）」
    "零残留",      # 「旧工具名在 5 个调用面的可执行位置零残留」
    "不入库",      # 「生成物 … 不入库」
    "不出现",      # 「源码形态：… 不出现任何承运商名字面量」
    "不许",        # 「任何入库文件都不许含合并冲突标记」
    "白名单",      # 「能力取值不是白名单」
    "结构上没有",  # 「ManualWaybillProvider 结构上没有 HTTP 客户端」
    "剥注释",      # 「Java 侧结构判据：… 的代码（剥注释后）不出现 …」
    "源码形态",    # 「源码形态：取号链路…」
    "git ls-files",
    "暂存目录",    # 「生成腿的暂存区必须在仓库外」
    "文件数",      # 「每个扫描面文件数 > 0（空扫描 = 空断言）」
    "rglob",       # 「REPO_ROOT.rglob 的整仓扫描面」
    "行首",        # 「文件出现行首七字符冲突标记」
    "行号",        # 「判红并具名「文件:行号」」
    "具名",        # 「判红并具名」—— 代码判据的报错形态
    "尾部顺延",    # 「取号默认 = 尾部顺延」（纯 CI 工具链行为）
)


def load_cases() -> list:
    """全库用例（`.github/cases/*.yml` 是行为用例的单一真值源）。"""
    cases: list = []
    for path in sorted(CASES_DIR.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for case in doc.get("cases") or []:
            if isinstance(case, dict):
                cases.append(case)
    return cases


def _expectation_texts(case: dict) -> list:
    return [str(e) for e in (case.get("expectations") or [])]


def signal_b_no_behavior_assertion(case: dict) -> bool:
    """信号 B：`expectations` 非空，却取不到任何工具名（= 没有可计分的 agent 行为断言）。

    ⚠️ `expectations` **为空**时返回 False（不表态）——`CH-049` / `PR-073` 走
    `forbidden_text` / `forbidden_tools` 通道，是合法的非 expectations 断言形态。
    """
    if not case.get("expectations"):
        return False
    return not expectation_tools(case)


def signal_a_code_criterion_wording(case: dict) -> bool:
    """信号 A：`expectations` 出现代码判据形态锚点。"""
    return any(anchor in text
               for text in _expectation_texts(case)
               for anchor in CODE_CRITERION_ANCHORS)


def undeclared_code_criteria(cases: list) -> list:
    """该标契约标记却没标的用例 id（判据的纯函数内核；排序后返回便于具名）。"""
    out = []
    for case in cases:
        if is_backend_contract_case(case):
            continue
        if signal_a_code_criterion_wording(case) or signal_b_no_behavior_assertion(case):
            out.append(str(case.get("id")))
    return sorted(out)


def anchor_hit_count(cases: list) -> int:
    """锚点在**全库**（含已豁免的）上的命中数 —— 判据失明自证用。"""
    return sum(1 for case in cases if signal_a_code_criterion_wording(case))


# ══════════════════════════════════════════════════════════════════════════════
# 判据
# ══════════════════════════════════════════════════════════════════════════════


def test_library_is_not_empty() -> None:
    """扫描面非空自证 ①：读不到用例时下面的「零违规」是假绿。"""
    cases = load_cases()
    assert len(cases) >= MIN_LIBRARY_CASES, (
        f"只读到 {len(cases)} 条用例（下界 {MIN_LIBRARY_CASES}）—— 扫描面失效，"
        "本文判据会假绿；先查 .github/cases/*.yml 是否还能解析"
    )


def test_anchor_scan_surface_is_not_blind() -> None:
    """扫描面非空自证 ②：锚点整体失效（命中 0 条）⇒ 判据失明 ⇒ 红，不许静默通过。"""
    hits = anchor_hit_count(load_cases())
    assert hits >= MIN_ANCHOR_HITS, (
        f"代码判据形态锚点在全库只命中 {hits} 条（下界 {MIN_ANCHOR_HITS}）—— "
        f"说明锚点集合与真实语料脱节（判据失明），不是「没有代码判据用例」。"
        f"现取锚点表：{list(CODE_CRITERION_ANCHORS)}"
    )


def test_code_criteria_cases_declare_contract_marker() -> None:
    """主判据：断言代码判据的用例必须声明契约标记（否则会被 normal 全量评测当 LLM 用例跑）。"""
    bad = undeclared_code_criteria(load_cases())
    assert bad == [], (
        f"这些用例断言的是**代码判据**、却没声明契约标记 {CONTRACT_MARKERS}：{bad}\n"
        "后果（实证 run 42127246100）：它们被 `tier=normal` 全量选中、当 LLM 行为用例执行 ⇒ "
        "`mibao 行为回归` + `xiaobu 行为回归` 两条腿全红、失败形态全是 `unmatched expectation`。\n"
        "修法：`skip_reason` 以 `[backend-contract]` / `[frontend-contract]` 开头，写清"
        "「为什么它不是 LLM 用例 + 判据在哪（`traces.tests`）」；**不要**删用例、"
        "**不要**改 `expectations` / `traces`。"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 判别力（正控 / 负控，逐条实跑）
# ══════════════════════════════════════════════════════════════════════════════


def test_positive_control_scan_wording_is_red() -> None:
    """正控 A：「扫 xx 文件 ⇒ 判红」但 `skip_reason` 为空 ⇒ 必须红并具名。"""
    fake = [{
        "id": "FX-901",
        "user_inputs": ["N/A（静态判据，无对话轮次）"],
        "expectations": ["扫 frontend/bmini-app/src/**/*.scss 的每一条 @use，"
                         "目标不存在 ⇒ 判红并具名给出文件与目标。"],
        "skip_reason": "",
    }]
    assert undeclared_code_criteria(fake) == ["FX-901"]


def test_positive_control_no_behavior_assertion_is_red() -> None:
    """正控 B：`expectations` 非空但一条工具名都没有（纯散文）⇒ 必须红并具名。"""
    fake = [{
        "id": "FX-902",
        "expectations": ["暂存目录必须在仓库目录树之外，否则整仓遍历会扫到生成过程的临时物。"],
        "skip_reason": "",
    }]
    assert undeclared_code_criteria(fake) == ["FX-902"]


def test_negative_control_behavior_case_is_green() -> None:
    """负控 1：真正的 LLM 行为用例（用户问一句 ⇒ agent 调工具）⇒ 不许红。"""
    fake = [{
        "id": "FX-903",
        "user_inputs": ["帮我查一下最近订单到哪了"],
        "expectations": [{"tool": "order_query"}],
        "skip_reason": "",
    }]
    assert undeclared_code_criteria(fake) == []


def test_negative_control_direct_reply_is_green() -> None:
    """负控 2：`direct_reply` 是**合法行为期望**（断言「不调工具」）⇒ 不许红。

    这是最容易误伤的形态：现取全库有 7 条 no-skip 用例的期望只有 `direct_reply`
    （`CH-015` / `CH-051` / `CH-052` / `DF-001` / `DF-004` / `OR-074` / `ST-003`）。
    """
    fake = [{
        "id": "FX-904",
        "user_inputs": ["我要转人工"],
        "expectations": [{"tool": "direct_reply"}],
        "skip_reason": "",
    }]
    assert undeclared_code_criteria(fake) == []


def test_negative_control_forbidden_channel_is_green() -> None:
    """负控 3：`expectations` 为空、走 `forbidden_text` / `forbidden_tools` 通道 ⇒ 不许红。

    语料现取真实形态 = `CH-049`（`expectations: null` + `forbidden_text`）与
    `PR-073`（`expectations: []` + `forbidden_tools`）。
    """
    fake = [
        {"id": "FX-905", "user_inputs": ["帮我开个客服账号"],
         "expectations": None, "forbidden_text": ["已帮你建好"]},
        {"id": "FX-906", "user_inputs": ["帮我写张海报文案"],
         "expectations": [], "forbidden_tools": ["marketing_poster"]},
    ]
    assert undeclared_code_criteria(fake) == []


def test_negative_control_declared_case_is_green() -> None:
    """负控 4：已声明契约标记的同形态用例 ⇒ 不许红（判据只看「该标而未标」）。"""
    fake = [{
        "id": "FX-907",
        "expectations": ["扫 git ls-files 的全部入库文件，出现冲突标记 ⇒ 判红并具名。"],
        "skip_reason": "[backend-contract] 判据在 tests/unit_ci_workflows/test_no_conflict_markers_in_tree.py",
    }]
    assert undeclared_code_criteria(fake) == []


def test_anchor_set_has_no_false_positives() -> None:
    """锚点表在**真实 LLM 行为用例**上必须零误伤（误伤 = 把真用例逼去 skip）。

    复算命令（现取，零成本）：

        python3 - <<'PY'
        import sys, yaml, pathlib
        sys.path.insert(0, '.github')
        from assertion_taxonomy import expectation_tools, is_backend_contract_case
        # 真行为用例 = 没标契约标记 且 expectation_tools 非空
        ...
        PY
    """
    false_positives = []
    for case in load_cases():
        if is_backend_contract_case(case):
            continue
        if not expectation_tools(case):
            continue                      # 本来就没有行为断言 ⇒ 不在误伤面内
        if signal_a_code_criterion_wording(case):
            false_positives.append(str(case.get("id")))
    assert false_positives == [], (
        f"这些用例**有** agent 行为断言（`expectation_tools` 非空）、却被代码判据锚点命中："
        f"{false_positives}\n锚点过宽 ⇒ 会把真 LLM 用例误判成代码判据。"
        f"修法 = 收窄锚点（去掉命中的那个词），**不是**给这些用例加 `skip_reason`。"
    )
