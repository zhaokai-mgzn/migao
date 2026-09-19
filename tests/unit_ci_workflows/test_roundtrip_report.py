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

## 边界（照实登记）

- CI 的 `ci workflow helper unit tests` job 只装 `pytest` + `pyyaml`（**无 `zstandard`**，`zstd` CLI 不保证），
  故 zstd **等价性**那条用 `skipif` 显式跳过（跳过长得像跳过）；**无解压器必须报原因**那条在 CI 真跑。
- 本文件不测「模型时间」的绝对值：它是**上界**（后台 job 与生成重叠），只断言其**算术关系**。
"""

from __future__ import annotations

import importlib.util
import json
import os
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


def _persona_blocks(path: Path) -> dict:
    """取 persona 的 `text` / `prefix` 两个块标量（逐字，含空行）。"""
    out: dict = {}
    key = None
    buf: list = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.startswith("    text: >-") or line.startswith("    prefix: >-"):
            if key:
                out[key] = "\n".join(buf)
            key, buf = line.split(":")[0].strip(), []
        elif key and (line.startswith("      ") or not line.strip()):
            buf.append(line[6:] if line.startswith("      ") else "")
        elif key:
            out[key] = "\n".join(buf)
            key = None
    if key:
        out[key] = "\n".join(buf)
    return out


def test_persona_text_and_prefix_are_byte_identical():
    """两处副本一旦漂移，加载到的研发模式就取决于 DSH 读哪个键 —— 而没有任何东西会红。"""
    blocks = _persona_blocks(PRESET)
    assert blocks["text"] == blocks["prefix"]


def test_persona_carries_the_roundtrip_budget_rule():
    """#4428 的落点判据：规则名 + 指向的章节号必须两处都在（措辞可变，身份不可丢）。"""
    blocks = _persona_blocks(PRESET)
    for key in ("text", "prefix"):
        assert "往返预算" in blocks[key]
        assert "§21" in blocks[key]


def test_the_section_the_persona_points_at_really_exists():
    """悬空指针 = 读的人找不到判据 ⇒ persona 说「全文见 §21」时技能里必须有 §21。"""
    assert "## 21. " in SKILL.read_text(encoding="utf-8")
