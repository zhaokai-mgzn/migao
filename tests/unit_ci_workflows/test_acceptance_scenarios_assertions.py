# case_ids: MC-012
"""验收剧本必须有**可执行断言**（issue #9217）。

## 病

`tests/agent_eval/scenarios_b.json` / `scenarios_c.json` 原先每条只有
`id/title/domain/rounds`，**一条 `checks` 都没有** ⇒ `acceptance_runner.py` 的
`evaluate_checks(sc.get("checks") or [], ...)` 永远返回 0 违规，跑完打印
「L1/L2 违规 0 条」—— 这是 `migao-acceptance` 铁律 2 点名禁止的**空断言**。

## 本文件锁什么

1. 每个 `scenarios_*.json` 里的每条场景必须有**非空 `checks`**；
2. 每条场景至少含 1 条 `no_error`（链路/工具错误必须红）+ 1 条**非 UA 的行为断言**
   （不允许只用 `no_error` 充当「测过了」）；
3. 断言类型必须在 `acceptance_runner.SUPPORTED_CHECK_TYPES` 里（从源码静态反解，
   不 import：CI 的 helper job 只装 pytest + pyyaml，不装 httpx）；
4. `ref` 只能写 `*` 或 `R<n>`，且 `n` 不超出该场景实际轮数（锚点写错 = 断言永不成立）；
5. 需要 `expect` 的类型不得为空（静默空断言的另一种形态）。

## 红证（注入式）

给任一场景删掉 `checks`（或把 `type` 改成 `not_supported`、把 `ref` 写成 `R99`）
⇒ 本文件对应用例必红；本条不依赖任何 LLM / 网络。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCENARIO_DIR = REPO / "tests" / "agent_eval"
RUNNER = SCENARIO_DIR / "acceptance_runner.py"

#: 与 `acceptance_runner.SUPPORTED_CHECK_TYPES` 的一致性由 `test_supported_types_match_runner_source` 锁。
SUPPORTED_TYPES = {
    "tool_called", "tool_not_called", "no_error", "card_shown",
    "ai_text_contains", "ai_text_not_contains",
}

#: 需要非空 `expect` 的类型（`no_error` 不需要）。
EXPECT_REQUIRED = SUPPORTED_TYPES - {"no_error"}


def _scenario_files() -> list[Path]:
    files = sorted(SCENARIO_DIR.glob("scenarios_*.json"))
    assert files, f"{SCENARIO_DIR} 下没有 scenarios_*.json —— 判据会空转（fail-closed）"
    return files


def _scenarios() -> list[tuple[str, dict]]:
    out = []
    for path in _scenario_files():
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, list) and data, f"{path.name}: 不是非空列表"
        for sc in data:
            out.append((path.name, sc))
    return out


def test_every_scenario_has_executable_checks():
    """每条场景：非空 checks + no_error + 至少 1 条非 UA 行为断言。"""
    for name, sc in _scenarios():
        checks = sc.get("checks") or []
        assert checks, f"{name}:{sc.get('id')} 没有 checks —— 验收会打印「0 违规」的假绿"
        types = [str(c.get("type") or "") for c in checks if isinstance(c, dict)]
        assert "no_error" in types, f"{name}:{sc.get('id')} 缺 no_error（链路错误必须红）"
        behavioral = [
            t for t, c in zip(types, [c for c in checks if isinstance(c, dict)])
            if t != "no_error" and str(c.get("level") or "L1").upper() != "UA"
        ]
        assert behavioral, (
            f"{name}:{sc.get('id')} 只有 no_error / UA 条目 —— 没有行为断言，仍是空断言")


def test_check_types_and_anchors_are_valid():
    """类型必须在支持集里；ref 只能 `*`/`R<n>` 且不得越界；expect 不得为空。"""
    for name, sc in _scenarios():
        rounds = sc.get("rounds") or []
        for chk in sc.get("checks") or []:
            assert isinstance(chk, dict), f"{name}:{sc.get('id')} check 不是字典: {chk!r}"
            ctype = str(chk.get("type") or "")
            assert ctype in SUPPORTED_TYPES, (
                f"{name}:{sc.get('id')} 不支持的断言类型 {ctype!r}（不得静默跳过）")
            if ctype in EXPECT_REQUIRED:
                assert str(chk.get("expect") or "").strip(), (
                    f"{name}:{sc.get('id')} {ctype} 缺 expect —— 断言永不成立")
            ref = str(chk.get("ref") or "*")
            if ref == "*":
                continue
            m = re.fullmatch(r"R(\d+)", ref)
            assert m, f"{name}:{sc.get('id')} ref 形态非法：{ref!r}（只允许 * 或 R<n>）"
            assert 1 <= int(m.group(1)) <= len(rounds), (
                f"{name}:{sc.get('id')} ref={ref} 超出实际轮数 {len(rounds)}")


def test_scenario_ids_are_unique_across_files():
    """两端剧本 id 不得重复（同一 id 出现在两个文件 ⇒ 报告无法定位）。"""
    ids = [str(sc.get("id") or "") for _, sc in _scenarios()]
    assert all(ids), "存在空 id"
    dup = sorted({i for i in ids if ids.count(i) > 1})
    assert not dup, f"场景 id 重复：{dup}"


def test_supported_types_match_runner_source():
    """本文件的类型集必须与 `acceptance_runner.SUPPORTED_CHECK_TYPES` 逐字一致。

    ⚠️ 静态反解而非 import：helper job 只装 pytest + pyyaml，import runner 会 ImportError。
    """
    src = RUNNER.read_text(encoding="utf-8")
    m = re.search(r"SUPPORTED_CHECK_TYPES\s*=\s*\{(.*?)\}", src, re.S)
    assert m, "acceptance_runner.py 里找不到 SUPPORTED_CHECK_TYPES（判据真相源消失，fail-closed）"
    runner_types = set(re.findall(r'"([a-z_]+)"', m.group(1)))
    assert runner_types == SUPPORTED_TYPES, (
        f"断言类型集与 runner 不一致：runner={sorted(runner_types)} / 本文件={sorted(SUPPORTED_TYPES)}")
