# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""会话往返账（`scripts/roundtrip_report.py`）的 L0 守卫 —— issue #4428。

## 为什么给一个「报告型脚本」写 L0 测试

报告型脚本最典型的失效形态是**静默空转**：解析悄悄命中 0 步 ⇒ 报告打印得像一份正常账单
⇒ 读者读成「**本次会话往返很少**」。而真相可能是「解析器坏了 / 格式漂移了」。
两种结论在控制台上**长得一模一样**，这正是 `migao-acceptance` 的「空跑」形态。

第二个形态是**把报告悄悄变成门禁**：加一条阈值 `exit 1` ⇒ 从此没人敢跑它，
而 §21 要的是「把分母摆到台面上」而不是「再拦一道」。

故本文件锁五件事：

1. **计数判据**：步 = `assistant/message`、调用 = `tool/call`、往返比 = 调用/步（精确值断言）；
2. **配对判据**：工具执行按 `callId` 配对，**不按出现顺序**（结果乱序回来是最常见的形态）；
3. **不许静默丢弃**：未配对的 `tool/call` 与非 JSON 行都要**计数上报**；
4. **不可判定 ≠ 通过**：0 步 ⇒ 打印「不可判定」且 `exit 3`，**不得**退化成正常报告；
5. **报告型语义**：指标再差也 `exit 0`；报告必须含**处置要求原文**（否则被读成「仅供参考的统计」）。

## 红证（每条都能指出反例输入）

| 用例 | 反例输入 / 反向改法 |
|---|---|
| `test_counts_steps_calls_and_ratio` | 把 `tool/result` 也算成步（或漏算 `tool/call`）⇒ 步数/比值必错 |
| `test_tool_exec_pairs_by_call_id_not_order` | 改成「按出现顺序 zip 调用与结果」⇒ edit/bash 的耗时互换 ⇒ 必红 |
| `test_unpaired_call_is_reported_not_dropped` | 配对失败时静默 `continue` ⇒ `unpaired_calls` 为 0 ⇒ 必红 |
| `test_zero_steps_is_undecidable_and_exits_3` | 解析不出步时返回 0 / 照打正常报告 ⇒ 必红 |
| `test_bad_metrics_still_exit_0` | 加一条「比值低于 N 就 exit 1」的阈值 ⇒ 必红 |
| `test_malformed_lines_are_counted` | 坏行静默 `continue` 不计数 ⇒ 必红 |
| `test_report_contains_required_action_text` | 删掉「处置要求」段 ⇒ 报告退化成统计表 ⇒ 必红 |
| `test_zstd_frame_without_decompressor_is_not_silent` | 无解压器时返回空串（而非显式原因）⇒ 必红 |
| `test_directory_input_picks_the_latest_session` | 取第一个匹配（或不过滤 `session*`）⇒ 必红 |
| `TestPersonaJudgmentIsNotVacuous::test_anchor_form_is_a_single_source_and_passes` | 锚点/别名接错（如 `prefix: *nope`）⇒ `KeyError`（fail-closed），不是静默通过 |
| `TestPersonaJudgmentIsNotVacuous::test_literal_form_drift_is_still_caught` | 两份字面副本漂移 ⇒ 必红（**真断言差异**，不是 `KeyError`） |
| `TestPersonaJudgmentIsNotVacuous::test_anchor_form_rule_change_is_caught` | 锚点形态下改「往返预算」⇒ 必红（规则名判据没被锚点架空） |
| `TestPersonaJudgmentIsNotVacuous::test_undefined_anchor_is_fail_closed` | 未定义锚点静默返回空块 ⇒ 必红（空块 = `text == prefix` 与规则名两条同时变成空断言） |

## 边界（照实登记）

- CI 的 `ci workflow helper unit tests` job 只装 `pytest` + `pyyaml`（**无 `zstandard`**，`zstd` CLI 不保证），
  故 zstd **等价性**那条用 `skipif` 显式跳过（跳过长得像跳过）；**无解压器必须报原因**那条在 CI 真跑。
- 本文件不测「模型时间」的绝对值：它是**上界**（后台 job 与生成重叠），只断言其**算术关系**。
- `text` / `prefix` 自 issue #5081 起用 YAML 锚点**合流为单一源**（`&migao_persona` / `*migao_persona`）：
  「两处必相同」由 YAML 语义**结构性保证**（不可能漂移）⇒ 本判据是**守卫改判**（支持 `&anchor` / `*anchor`），
  **不是放宽**：字面副本形态的漂移检测**原样保留**（见 `test_literal_form_drift_is_still_caught`）。
  有意**不**加「禁止退回逐字副本」的判据：退回后漂移仍被本判据抓住，无需再加一条。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "roundtrip_report.py"


def _load_module():
    """按路径加载脚本模块（`scripts/` 不是包，不能 import）。"""
    spec = importlib.util.spec_from_file_location("roundtrip_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["roundtrip_report"] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


# ── 合成会话（时间单位 ms，全部为手算得出的精确期望值）──────────────────────
def _assistant(ts: int, step: int) -> str:
    return json.dumps({"type": "assistant/message", "time": ts, "data": {"turn": 1, "step": step}})


def _call(ts: int, call_id: str, name: str) -> str:
    return json.dumps({"type": "tool/call", "time": ts, "data": {"callId": call_id, "name": name}})


def _result(ts: int, call_id: str) -> str:
    return json.dumps(
        {"type": "tool/result", "time": ts, "data": {"message": {"source": {"callId": call_id}}}}
    )


def _write(tmp_path: Path, lines: list[str], name: str = "session.v3.jsonl") -> Path:
    target = tmp_path / name
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _session_lines() -> list[str]:
    """3 步 / 4 调用；**结果乱序**（c3 的结果先于 c2 回来）；c4 无结果。

    期望：exec read=0.5s、edit=0.1s、bash=2.0s（合计 2.6s）；span=4.1s；model_upper=1.5s。
    """
    return [
        _assistant(0, 1),
        _call(100, "c1", "read"),
        _result(600, "c1"),
        _assistant(1000, 2),
        _call(1100, "c2", "edit"),
        _call(1100, "c3", "bash"),
        _result(3100, "c3"),
        _result(1200, "c2"),
        _assistant(4000, 3),
        _call(4100, "c4", "read"),
    ]


# ── 1. 计数判据 ─────────────────────────────────────────────────────────────
def test_counts_steps_calls_and_ratio(tmp_path):
    report = mod.analyze(_write(tmp_path, _session_lines()).read_text(encoding="utf-8"))
    assert report["steps"] == 3
    assert report["calls"] == 4
    assert report["ratio"] == pytest.approx(4 / 3)


def test_span_and_model_time_are_arithmetic_not_guesses(tmp_path):
    report = mod.analyze(_write(tmp_path, _session_lines()).read_text(encoding="utf-8"))
    assert report["span_s"] == pytest.approx(4.1)
    assert report["exec_total_s"] == pytest.approx(2.6)
    assert report["model_upper_s"] == pytest.approx(report["span_s"] - report["exec_total_s"])


# ── 2. 配对判据（结果乱序）──────────────────────────────────────────────────
def test_tool_exec_pairs_by_call_id_not_order(tmp_path):
    report = mod.analyze(_write(tmp_path, _session_lines()).read_text(encoding="utf-8"))
    assert report["tools"]["edit"]["exec_s"] == pytest.approx(0.1)
    assert report["tools"]["bash"]["exec_s"] == pytest.approx(2.0)
    assert report["tools"]["read"]["exec_s"] == pytest.approx(0.5)


# ── 3. 不许静默丢弃 ─────────────────────────────────────────────────────────
def test_unpaired_call_is_reported_not_dropped(tmp_path, capsys):
    target = _write(tmp_path, _session_lines())
    assert mod.main([str(target)]) == mod.EXIT_OK
    assert mod.analyze(target.read_text(encoding="utf-8"))["unpaired_calls"] == 1
    assert "未配对的 tool/call" in capsys.readouterr().out


def test_malformed_lines_are_counted(tmp_path):
    lines = _session_lines() + ["{ 这不是 JSON", "也不是 JSON"]
    report = mod.analyze("\n".join(lines) + "\n")
    assert report["malformed_lines"] == 2
    assert report["steps"] == 3  # 坏行不得改变步数


# ── 4. 不可判定 ≠ 通过 ──────────────────────────────────────────────────────
def test_zero_steps_is_undecidable_and_exits_3(tmp_path, capsys):
    target = _write(tmp_path, ['{"type": "session", "version": 3}', "hello"], name="not-a-session.jsonl")
    assert mod.main([str(target)]) == mod.EXIT_UNDECIDABLE
    out = capsys.readouterr().out
    assert "不可判定" in out
    assert "往返比" not in out  # 不得打出一份看起来正常的账单


def test_undecidable_json_form_still_reports_zero_steps(tmp_path, capsys):
    target = _write(tmp_path, ['{"type": "session"}'], name="empty.jsonl")
    assert mod.main([str(target), "--json"]) == mod.EXIT_UNDECIDABLE
    assert json.loads(capsys.readouterr().out)["steps"] == 0


# ── 5. 报告型语义 ───────────────────────────────────────────────────────────
def test_bad_metrics_still_exit_0(tmp_path, capsys):
    """往返比再差也不许变成门禁：40 次 read / 40 步 ⇒ 仍 exit 0。"""
    lines: list[str] = []
    for i in range(40):
        lines.append(_assistant(i * 1000, i + 1))
        lines.append(_call(i * 1000 + 10, f"c{i}", "read"))
        lines.append(_result(i * 1000 + 20, f"c{i}"))
    target = _write(tmp_path, lines)
    assert mod.main([str(target)]) == mod.EXIT_OK
    out = capsys.readouterr().out
    assert "100.0%" in out  # 40/40 调用全给了 read
    assert mod.analyze(target.read_text(encoding="utf-8"))["ratio"] == pytest.approx(1.0)


def test_report_contains_required_action_text(tmp_path, capsys):
    target = _write(tmp_path, _session_lines())
    assert mod.main([str(target)]) == mod.EXIT_OK
    assert "处置要求（原文" in capsys.readouterr().out


def test_report_names_the_upper_bound_caveat(tmp_path, capsys):
    """模型时间是**上界** —— 这个口径必须出现在报告里，否则会被当成绝对数引用。"""
    target = _write(tmp_path, _session_lines())
    assert mod.main([str(target)]) == mod.EXIT_OK
    assert "上界" in capsys.readouterr().out


# ── 6. 解压路径 ─────────────────────────────────────────────────────────────
def test_zstd_frame_without_decompressor_is_not_silent(tmp_path, monkeypatch):
    """无解压器 ⇒ 必须给**显式原因**（而不是返回空串 ⇒ 静默退化成「0 步」）。"""
    if importlib.util.find_spec("zstandard") is not None:
        pytest.skip("本机有 zstandard 模块 ⇒ 走不到「无解压器」分支（CI 无该模块，那里真跑）")

    def _no_zstd_cli(*_args, **_kwargs):
        raise FileNotFoundError("zstd")

    target = tmp_path / "x.jsonl.zst"
    target.write_bytes(mod.ZSTD_MAGIC + b"\x00" * 16)
    monkeypatch.setattr(mod.subprocess, "run", _no_zstd_cli)
    text, why = mod.read_session_text(target)
    assert not text
    assert "无法解压" in why


@pytest.mark.skipif(shutil.which("zstd") is None, reason="本机无 zstd CLI ⇒ 压缩等价性无法真跑")
def test_zstd_and_plain_inputs_agree(tmp_path):
    plain = _write(tmp_path, _session_lines())
    compressed = tmp_path / "session.v3.jsonl.zst"
    subprocess.run(["zstd", "-q", "-f", str(plain), "-o", str(compressed)], check=True)
    assert mod.read_session_text(compressed)[0] == mod.read_session_text(plain)[0]


# ── 7. 目录输入 ─────────────────────────────────────────────────────────────
def test_directory_input_picks_the_latest_session(tmp_path):
    older = tmp_path / "a" / "session-old.jsonl"
    newer = tmp_path / "b" / "session-new.jsonl"
    for path in (older, newer):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(_session_lines()) + "\n", encoding="utf-8")
        os.utime(path, (time.time() - 1000, time.time() - 1000))
    os.utime(newer, None)
    picked, why = mod.resolve_input(tmp_path)
    assert picked == newer
    assert not why


def test_usage_error_is_2_not_a_silent_pass(tmp_path):
    assert mod.main([str(tmp_path / "nope.jsonl")]) == mod.EXIT_USAGE


# ── 8. 研发模式落点判据（本单改的是 persona + 技能，两处必须对得上）──────────
PRESET = ROOT / ".agent-presets" / "migao" / "agent.cordis.yml"
SKILL = ROOT / ".agent-presets" / "migao" / "skills" / "migao-dev-flow" / "SKILL.md"

# `text` / `prefix` 的合法形态（issue #5081 起允许锚点合流为单一源）：
#   ① `key: >-`             字面块标量（两份独立副本）
#   ② `key: &anchor >-`     锚点（正文只存这一份）
#   ③ `key: *anchor`        别名（解析到锚点正文）
_BLOCK_LINE = re.compile(r"^    (text|prefix): (?:&([\w.-]+) )?>-$")
_ALIAS_LINE = re.compile(r"^    (text|prefix): \*([\w.-]+)$")


def _persona_blocks(path: Path) -> dict:
    """取 persona 的 `text` / `prefix` 正文（逐字，含空行）—— 支持上面三种形态。

    ① 两份字面副本各自独立 ⇒「两处必相同」只能靠本判据**事后比对**；
    ②③ 锚点 + 别名 ⇒ 两个键拿到**同一份**正文，「必相同」成了 YAML 语义的
    **结构性保证**（不可能漂移，比事后比对更强）—— 这正是 issue #5081 的合流修法。

    别名指向**未定义的锚点** ⇒ `KeyError`（**fail-closed**）：不得退化成「少一个键 / 空块」——
    空块会让 `text == prefix` 与「规则名两处都在」两条断言**同时**变成空断言。
    """
    out: dict = {}
    anchors: dict = {}
    key = None
    buf: list = []
    pending = None

    def flush() -> None:
        nonlocal key, buf, pending
        if key:
            body = "\n".join(buf)
            out[key] = body
            if pending:
                anchors[pending] = body
        key, buf, pending = None, [], None

    for line in path.read_text(encoding="utf-8").split("\n"):
        m_alias = _ALIAS_LINE.match(line)
        if m_alias:
            flush()
            out[m_alias.group(1)] = anchors[m_alias.group(2)]
            continue
        m_block = _BLOCK_LINE.match(line)
        if m_block:
            flush()
            key, pending = m_block.group(1), m_block.group(2)
            continue
        if key and (line.startswith("      ") or not line.strip()):
            buf.append(line[6:] if line.startswith("      ") else "")
        elif key:
            flush()
    flush()
    return out


def _persona_violations(path: Path) -> list:
    """persona 落点判据的**唯一实现**（空表 = 通过）—— 真用例与红证夹具共用，避免两套口径。"""
    blocks = _persona_blocks(path)
    problems = []
    if blocks["text"] != blocks["prefix"]:
        problems.append("text 与 prefix 的正文不同（副本漂移 ⇒ 加载到哪份取决于 DSH 读哪个键）")
    for name in ("text", "prefix"):
        if "往返预算" not in blocks[name]:
            problems.append(f"{name} 缺「往返预算」规则名（#4428 的落点判据）")
        if "§21" not in blocks[name]:
            problems.append(f"{name} 缺章节号 §21（读的人找不到判据 = 悬空指针）")
    return problems


def test_persona_text_and_prefix_are_byte_identical():
    """两处正文必须逐字相同：锚点形态由 YAML 保证，字面形态由本判据盯着。"""
    blocks = _persona_blocks(PRESET)
    assert set(blocks) == {"text", "prefix"}, (
        f"persona 的 text/prefix 没解析出来（实测键 = {sorted(blocks)}）—— 判据会退化成空断言，宁可红"
    )
    assert blocks["text"] == blocks["prefix"]


def test_persona_carries_the_roundtrip_budget_rule():
    """#4428 的落点判据：规则名 + 指向的章节号必须两处都在（措辞可变，身份不可丢）。"""
    problems = [p for p in _persona_violations(PRESET) if "往返预算" in p or "§21" in p]
    assert problems == []


def test_the_section_the_persona_points_at_really_exists():
    """悬空指针 = 读的人找不到判据 ⇒ persona 说「全文见 §21」时技能里必须有 §21。"""
    assert "## 21. " in SKILL.read_text(encoding="utf-8")


_PERSONA_BODY = """\
      You are the MIGAO AI 智能客服系统研发 Agent（夹具 persona）。

      开发节奏遵循「往返预算」…全文见 `migao-dev-flow` §21。
"""


def _write_preset(tmp_path: Path, text_line: str, prefix_line: str,
                  text_body: str = _PERSONA_BODY, prefix_body=None) -> Path:
    """写一个最小 preset 夹具（**真文件**，不是 mock —— 本判据的本体就是这份 YAML）。"""
    body2 = _PERSONA_BODY if prefix_body is None else prefix_body
    fixture = ("- id: persona\n"
               "  name: '@deepseek-ai/dsh-persona'\n"
               "  config:\n"
               f"    {text_line}\n{text_body}\n"
               f"    {prefix_line}\n{body2}\n"
               "    suffix: Your working directory is {{cwd}}.\n")
    path = tmp_path / "agent.cordis.yml"
    path.write_text(fixture, encoding="utf-8")
    return path


class TestPersonaJudgmentIsNotVacuous:
    """:red_circle: 红证（注入式，issue #5081）：合流的**每种形态**各有一条，逐条都能单独判红。"""

    def test_anchor_form_is_a_single_source_and_passes(self, tmp_path):
        """形态①（本 PR 的形态）：一处锚点 + 一处别名 ⇒ 两键同一份正文 ⇒ 通过。"""
        path = _write_preset(tmp_path, "text: &persona >-", "prefix: *persona")
        assert _persona_violations(path) == []

    def test_literal_form_drift_is_still_caught(self, tmp_path):
        """形态②（反例）：两份字面副本漂移 ⇒ **必须判红**，且是**真断言差异**（不是 KeyError）。"""
        path = _write_preset(tmp_path, "text: >-", "prefix: >-",
                             prefix_body=_PERSONA_BODY + "      （漂移注入）\n")
        problems = _persona_violations(path)      # 能返回值本身 = 两个块都解析出来了（不是 KeyError）
        assert problems, "副本漂移没有被判红 —— 判据是空的"
        assert any("不同" in p for p in problems), f"漂移该报「正文不同」，实测 = {problems}"

    def test_anchor_form_rule_change_is_caught(self, tmp_path):
        """形态③（反例）：锚点形态下改「往返预算」⇒ 仍必须判红（规则名判据没被锚点架空）。"""
        path = _write_preset(tmp_path, "text: &persona >-", "prefix: *persona",
                             _PERSONA_BODY.replace("往返预算", "往返统计"))
        problems = _persona_violations(path)
        assert problems, "锚点形态下规则名消失没有被判红 —— 判据被架空"
        assert any("往返预算" in p for p in problems), f"该报缺规则名，实测 = {problems}"

    def test_undefined_anchor_is_fail_closed(self, tmp_path):
        """别名指向**不存在的锚点** ⇒ `KeyError`（fail-closed）：不许退化成空块 / 少一个键。"""
        path = _write_preset(tmp_path, "text: >-", "prefix: *nope")
        with pytest.raises(KeyError):
            _persona_blocks(path)


# ── 9. 等待型调用（`sleep N` 轮询）判据（issue #4455）──────────────────────
# 实测（会话 session-cf73f497，即 #4443 那一单）：7 次 `sleep N` = 684s = 11.4 min，
# 占 bash 执行 **42%**。P1~P4 把「逐点小步编辑」治住之后，瓶颈转移到了「等 CI」
# —— 故单列一条可判据（`migao-dev-flow` §21 的 P7）。


def _bash_call(ts: int, call_id: str, command: str) -> str:
    return json.dumps(
        {
            "type": "tool/call",
            "time": ts,
            "data": {"callId": call_id, "name": "bash", "arguments": json.dumps({"command": command})},
        }
    )


def test_sleep_polling_calls_are_reported(tmp_path):
    lines = _session_lines() + [
        _bash_call(5000, "b1", "gh pr checks 1 --json state; sleep 120; gh pr checks 1"),
        _bash_call(6000, "b2", "sleep 60 && gh pr checks 1"),
        _result(100000, "b1"),  # 95s
        _result(106000, "b2"),  # 100s
    ]
    report = mod.analyze("\n".join(lines) + "\n")
    assert report["wait_calls"] == 2
    assert report["wait_s"] == pytest.approx(195.0)


def test_non_sleep_bash_is_not_counted_as_waiting(tmp_path):
    """防误伤：真实工作（vitest / mvnw / pytest）不得被算成「等待」。"""
    lines = _session_lines() + [
        _bash_call(5000, "b1", "npx vitest run tests/unit/pages/customer-detail.test.tsx"),
        _bash_call(6000, "b2", "./mvnw -q -o test -Dtest=Foo"),
    ] + [_result(40000, "b1"), _result(90000, "b2")]
    report = mod.analyze("\n".join(lines) + "\n")
    assert report["wait_calls"] == 0
    assert report["wait_s"] == 0.0


def test_sleep_like_text_is_not_a_wait_call(tmp_path):
    """判据的边界：`sleepy 5` / `xsleep 5` 不是 sleep 调用。"""
    lines = _session_lines() + [
        _bash_call(5000, "b1", 'echo "sleepy 5"; echo xsleep 5'),
    ] + [_result(9000, "b1")]
    assert mod.analyze("\n".join(lines) + "\n")["wait_calls"] == 0


def test_non_bash_tool_with_sleep_in_arguments_is_not_a_wait_call(tmp_path):
    """判据只看 bash 的 `command` —— 别的工具参数里出现 sleep 不算。"""
    lines = _session_lines() + [
        json.dumps(
            {
                "type": "tool/call",
                "time": 5000,
                "data": {"callId": "e1", "name": "edit", "arguments": json.dumps({"new_string": "sleep 300"})},
            }
        ),
    ] + [_result(9000, "e1")]
    assert mod.analyze("\n".join(lines) + "\n")["wait_calls"] == 0


def test_report_surfaces_the_waiting_section_with_actionable_fix(tmp_path, capsys):
    """报告必须给出**处置**（改 `--watch`），否则会被读成「仅供参考的统计」。"""
    lines = _session_lines() + [_bash_call(5000, "b1", "sleep 90; gh pr checks 1")] + [_result(95000, "b1")]
    target = _write(tmp_path, lines)
    assert mod.main([str(target)]) == mod.EXIT_OK
    out = capsys.readouterr().out
    assert "等待型调用" in out
    assert "--watch" in out


def test_section_11_no_longer_offers_the_polling_escape_hatch():
    """§11.1 的「`--watch` 或轮询」是实测踩过的逃生口（#4455）⇒ 必须消失，否则规则形同虚设。

    ⚠️ 判据盯的是**那个许可式措辞**（`--watch` 与轮询**并列可选**），不是「或轮询」这四个字 ——
    本节现在**引述**被删掉的措辞来解释为什么删它，**引述 ≠ 许可**（判据若只看字面会误伤这条引述）。
    """
    section = SKILL.read_text(encoding="utf-8").split("## 11. ")[1].split("## 12. ")[0]
    assert "或轮询 `gh pr checks" not in section  # 旧的许可式措辞：--watch 与轮询并列
    assert "禁止 `sleep N` 轮询" in section  # 替代它的禁令必须在场
    assert "--watch" in section
