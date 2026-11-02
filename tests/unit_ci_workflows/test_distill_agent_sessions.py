# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""离线候选蒸馏脚本（`scripts/distill_agent_sessions.py`）的 L0 守卫 —— issue #8175 P1a。

## 这个脚本承诺了什么（本文件逐条钉住）

P1a 的定位是**零运行时风险**：只读、纯标准库、不连库、不调 LLM、不接触发器。
这类「离线小工具」的失效形态都不是崩溃，而是**安静地给出看起来合理的读数**：

1. **抽错口径**（闲聊也产出候选 / C 端会话被当 B 端抽）；
2. **串租户**（候选的 `tenant_id` 不来自来源会话 —— 落库后是跨租户污染）；
3. **漏 PII**（把手机号 / 邮箱 / 地址写进候选文件）；
4. **不幂等**（同一输入两次跑出不同字节 ⇒ 人工复核无法对账）；
5. **偷偷写盘**（不给 `--out` 也落文件 ⇒ 「只读」只是口头承诺）；
6. **假装能落库**（`--write` 静默通过 ⇒ 有人以为 P1a 已经写库）。

## 判据 ↔ 反例（每条都会红）

| 用例 | 反例输入 / 反向改法 |
|---|---|
| `test_three_constructed_sessions_yield_exactly_one_correction` | 禁用抽取（`hits = []`）⇒ 0 条 ⇒ 必红 |
| `test_chitchat_only_yields_no_candidates` | 给闲聊词加一条规则（如把「你好」当口径）⇒ 候选冒出 ⇒ 必红 |
| `test_non_mibao_sessions_are_skipped` | 去掉 `agent_type != "mibao"` 过滤 ⇒ C 端候选冒出 ⇒ 必红 |
| `test_cross_tenant_candidates_keep_their_source_tenant` | 把 `tenant_id` 写成常量（如 1）⇒ 租户 2 的候选被改写 ⇒ 必红 |
| `test_pii_phone_blocks_candidate_and_counts_one` | 摘掉 PII 扫描（`pii = None`）⇒ 候选冒出且计数为 0 ⇒ 必红 |
| `test_output_is_byte_identical_across_runs` | 往 payload 里塞时间戳 / 随机数 ⇒ 两次字节不同 ⇒ 必红 |
| `test_default_run_writes_no_files` | 不给 `--out` 也写文件 ⇒ 目录树新增 ⇒ 必红 |
| `test_write_flag_is_rejected_with_p1b_message` | 把 `_reject_write()` 改成 `pass` ⇒ 退出码 0 ⇒ 必红 |

## 边界（照实登记，§19.1）

- 本文件**不测**真实 DB 导出样本（那是一次性人工复核，见 PR body 的实测统计）；合成语料的期望值全部手算得出。
- 本文件**不测**「抽出来的候选质量好不好」—— P1a 的目的就是先拿给人看；本文件只保证**形态**（分类 / 租户 / PII / 幂等 / 只读）。
- 不测 `--write` 的文案措辞是否优雅，只测「非零退出 + 指向 P1b + 不产生输出文件」。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "distill_agent_sessions.py"


def _messages(*pairs: "tuple[str, str]") -> "list[dict]":
    return [{"role": role, "content": content} for role, content in pairs]


def _session(
    tenant_id: object = 1,
    session_id: str = "s1",
    agent_type: str = "mibao",
    messages: "list[dict] | None" = None,
) -> dict:
    return {
        "tenant_id": tenant_id,
        "session_id": session_id,
        "agent_type": agent_type,
        "messages": messages if messages is not None else _messages(("user", "你好")),
    }


def _write_jsonl(directory: Path, sessions: "list[dict]", name: str = "export.jsonl") -> Path:
    path = directory / name
    path.write_text(
        "\n".join(json.dumps(session, ensure_ascii=False) for session in sessions) + "\n",
        encoding="utf-8",
    )
    return path


def _run(*args: str, cwd: "Path | None" = None, env: "dict[str, str] | None" = None):
    merged = dict(os.environ)
    merged.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        env=merged,
    )


def _distill(tmp_path: Path, sessions: "list[dict]") -> dict:
    """跑一次 `--out`，返回解析后的 payload；失败时把 stdout/stderr 带进断言消息。"""
    input_path = _write_jsonl(tmp_path, sessions)
    out_path = tmp_path / "candidates.json"
    result = _run("--in", str(input_path), "--out", str(out_path))
    assert result.returncode == 0, result.stderr
    assert out_path.is_file()
    return json.loads(out_path.read_text(encoding="utf-8"))


def _tree_files(root: Path) -> "set[str]":
    """目录树里的文件集合（排除 `__pycache__`：并行 worker 里的 import 会写字节码，与只读无关）。"""
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.relative_to(root).parts
    }


def test_three_constructed_sessions_yield_exactly_one_correction(tmp_path: Path) -> None:
    sessions = [
        _session(
            session_id="s1",
            messages=_messages(
                ("user", "你好"),
                ("assistant", "您好，请问这单怎么算？"),
                ("user", "不对，我们按整卷算"),
                ("assistant", "好的，整卷算。"),
            ),
        ),
        _session(
            session_id="s2",
            messages=_messages(("user", "今天天气怎么样"), ("assistant", "今天晴。")),
        ),
        _session(
            session_id="s3",
            messages=_messages(("user", "谢谢"), ("assistant", "不客气。")),
        ),
    ]

    payload = _distill(tmp_path, sessions)

    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert candidate["category"] == "纠正"
    assert candidate["session_id"] == "s1"
    assert candidate["turn"] == 2
    assert "不对" in candidate["trigger_text"]
    assert candidate["context_before"] == "您好，请问这单怎么算？"
    assert "同时命中口径「我们按」" in candidate["reason"]
    assert payload["stats"]["candidates"] == 1
    assert payload["stats"]["sessions_read"] == 3
    assert payload["stats"]["sessions_distilled"] == 3


def test_chitchat_only_yields_no_candidates(tmp_path: Path) -> None:
    sessions = [
        _session(
            session_id="s1",
            messages=_messages(("user", "你好，今天天气怎么样"), ("assistant", "今天晴。")),
        ),
        _session(
            session_id="s2",
            messages=_messages(("user", "是不是这样？"), ("assistant", "嗯。")),
        ),
        _session(
            session_id="s3",
            messages=_messages(("user", "对不起，我没听清"), ("assistant", "没关系。")),
        ),
    ]

    payload = _distill(tmp_path, sessions)

    assert payload["candidates"] == []
    assert payload["stats"]["candidates"] == 0
    assert sum(payload["stats"]["sessions_skipped"].values()) == 0


def test_non_mibao_sessions_are_skipped(tmp_path: Path) -> None:
    sessions = [
        _session(
            session_id="c-end",
            agent_type="xiaobu",
            messages=_messages(("user", "不对，我们按整卷算")),
        ),
        _session(
            session_id="b-end",
            agent_type="mibao",
            messages=_messages(("user", "不对，我们按整卷算")),
        ),
    ]

    payload = _distill(tmp_path, sessions)

    assert [candidate["session_id"] for candidate in payload["candidates"]] == ["b-end"]
    assert payload["stats"]["sessions_skipped"]["agent_type_not_mibao"] == 1
    assert payload["stats"]["sessions_distilled"] == 1


def test_cross_tenant_candidates_keep_their_source_tenant(tmp_path: Path) -> None:
    sessions = [
        _session(
            tenant_id=1,
            session_id="t1",
            messages=_messages(("user", "以后都按整卷算")),
        ),
        _session(
            tenant_id=2,
            session_id="t2",
            messages=_messages(("user", "不对，按延米算")),
        ),
    ]

    payload = _distill(tmp_path, sessions)

    pairs = {(candidate["tenant_id"], candidate["session_id"]) for candidate in payload["candidates"]}
    assert pairs == {(1, "t1"), (2, "t2")}
    assert len(payload["candidates"]) == 2


def test_pii_phone_blocks_candidate_and_counts_one(tmp_path: Path) -> None:
    sessions = [
        _session(
            session_id="pii",
            messages=_messages(("user", "不对，以后都打我手机 13800138000")),
        ),
        _session(
            session_id="clean",
            messages=_messages(("user", "以后都按整卷算")),
        ),
    ]

    payload = _distill(tmp_path, sessions)

    assert [candidate["session_id"] for candidate in payload["candidates"]] == ["clean"]
    assert payload["stats"]["pii_skipped"] == 1
    assert payload["stats"]["candidates"] == 1


def test_pii_covers_id_card_email_and_address(tmp_path: Path) -> None:
    sessions = [
        _session(
            session_id="phone",
            messages=_messages(("user", "不对，以后都打我手机 13800138000")),
        ),
        _session(
            session_id="id-card",
            messages=_messages(("user", "不对，以后都按身份证 110101199003071234 记")),
        ),
        _session(
            session_id="email",
            messages=_messages(("user", "不对，以后都发到 a.b@example.com")),
        ),
        _session(
            session_id="address",
            messages=_messages(("user", "不对，以后都寄到杭州市余杭区文一西路969号")),
        ),
        _session(
            session_id="clean",
            messages=_messages(("user", "以后都按整卷算")),
        ),
    ]

    payload = _distill(tmp_path, sessions)

    assert [candidate["session_id"] for candidate in payload["candidates"]] == ["clean"]
    assert payload["stats"]["pii_skipped"] == 4


def test_long_message_is_truncated_and_context_is_bounded(tmp_path: Path) -> None:
    sessions = [
        _session(
            session_id="long",
            messages=_messages(
                ("assistant", "长" * 300),
                ("user", "不对，" + "啊" * 600),
            ),
        ),
    ]

    payload = _distill(tmp_path, sessions)

    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert candidate["context_before"] == "长" * 120
    assert len(candidate["context_before"]) == 120
    assert len(candidate["trigger_text"]) <= 120
    assert payload["stats"]["truncated_messages"] == 1


def test_output_is_byte_identical_across_runs(tmp_path: Path) -> None:
    sessions = [
        _session(
            session_id="s1",
            messages=_messages(("user", "不对，我们按整卷算")),
        ),
        _session(
            session_id="s2",
            messages=_messages(("user", "以后都发到 a.b@example.com")),
        ),
        _session(
            session_id="c-end",
            agent_type="xiaobu",
            messages=_messages(("user", "不对，按延米算")),
        ),
        _session(
            session_id="s3",
            messages=_messages(("user", "谢谢"), ("assistant", "不客气。")),
        ),
    ]
    input_path = _write_jsonl(tmp_path, sessions)
    out_a = tmp_path / "run-a.json"
    out_b = tmp_path / "run-b.json"

    first = _run("--in", str(input_path), "--out", str(out_a), env={"PYTHONHASHSEED": "1"})
    second = _run("--in", str(input_path), "--out", str(out_b), env={"PYTHONHASHSEED": "424242"})

    assert (first.returncode, second.returncode) == (0, 0)
    assert out_a.read_bytes() == out_b.read_bytes()
    assert json.loads(out_a.read_text(encoding="utf-8"))["stats"]["candidates"] == 1


def test_default_run_writes_no_files(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    _write_jsonl(work, [_session(messages=_messages(("user", "不对，我们按整卷算")))])
    before_work = _tree_files(work)
    before_scripts = _tree_files(REPO_ROOT / "scripts")

    result = _run("--in", str(work), cwd=work)

    assert result.returncode == 0
    assert _tree_files(work) == before_work
    assert _tree_files(REPO_ROOT / "scripts") == before_scripts
    assert "未写文件" in result.stdout
    assert "候选: 1" in result.stdout


def test_write_flag_is_rejected_with_p1b_message(tmp_path: Path) -> None:
    input_path = _write_jsonl(tmp_path, [_session(messages=_messages(("user", "不对，我们按整卷算")))])
    out_path = tmp_path / "should-not-exist.json"

    result = _run("--in", str(input_path), "--out", str(out_path), "--write")

    assert result.returncode != 0
    assert "--write" in result.stderr
    assert "P1b" in result.stderr
    assert not out_path.exists()


def test_directory_and_json_session_list_input_are_supported(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    payload = {
        "sessions": [
            _session(
                tenant_id=7,
                session_id="j1",
                messages=_messages(("user", "以后都按整卷算")),
            )
        ]
    }
    (nested / "export.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    out_path = tmp_path / "candidates.json"
    result = _run("--in", str(tmp_path), "--out", str(out_path))

    assert result.returncode == 0, result.stderr
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert [(candidate["tenant_id"], candidate["session_id"]) for candidate in data["candidates"]] == [(7, "j1")]
