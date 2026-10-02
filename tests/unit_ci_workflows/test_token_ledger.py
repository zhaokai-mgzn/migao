# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""会话 token 账（`scripts/token_ledger.py`）的 L0 守卫 —— issue #5920。

## 为什么给一个「报告型脚本」写 L0 测试

报告型脚本有三种典型失效形态，且**在控制台上都长得像一份正常账单**：

1. **静默空转**：解析悄悄命中 0 步 ⇒ 读成「本期消耗很小」。真相可能是**解析器坏了**；
2. **口径漂移**：把 `totalTokens` 当账、把「上下文」算成 `totalTokens`、把停顿桶写成左闭右闭
   ⇒ 数字还在，**含义变了**（§25：读数与它声称的对象）；
3. **悄悄变成门禁**：加一条阈值 `exit 1` ⇒ 从此没人敢跑它，而 §29 要的是「把分母摆到台面上」。

故本文件锁十一件事（每条都能指出反例输入）：
精确计数 / 恒等式不符**计数上报** / 停顿桶**边界**（半开区间）/ 上下文口径 / 阈值投影的**单调与精确** /
子代理归属 / 不可判定 ⇒ `exit 3` / 报告型语义（指标再差也 `exit 0`，且必须含处置要求原文） /
`--until` 窗口上界的**半开边界**（冻结时钟钉死，不靠「大概在窗口里」）/ 折叠·prune 精确计数 /
**折叠后返工**的同会话前后对照（分子分母都精确 —— 分母错 = 判不出返工）。

## 红证（每条都能指出反例输入）

| 用例 | 反例输入 / 反向改法 |
|---|---|
| `test_totals_are_exact` | 少算 `cacheReadTokens`（或用 `totalTokens` 累加）⇒ 期望值必错 |
| `test_identity_violation_is_counted_not_swallowed` | 恒等式不符时静默 `continue` / 直接丢该条 ⇒ 计数为 0 ⇒ 必红 |
| `test_gap_buckets_are_half_open` | 把桶写成闭区间（`<=`）⇒ 30s / 120s 落进两个桶 ⇒ 必红 |
| `test_context_is_input_plus_cache_read` | 上下文用 `totalTokens`（含输出）⇒ 均值偏大 ⇒ 必红 |
| `test_cap_projection_is_exact_and_monotone` | 投影用「一次性截断」（`min(max,…)`）⇒ 期望值必错；不单调 ⇒ 必红 |
| `test_depth_attribution_is_by_delegation_depth` | 不读 `delegationDepth`（全归主会话）⇒ 子代理占比恒 0 ⇒ 必红 |
| `test_zero_steps_is_undecidable_and_exits_3` | 解析不出步时返回 0 / 照打正常报告 ⇒ 必红 |
| `test_missing_workspace_exits_3_with_candidates` | 推导不出目录时扫 0 个文件却报「消耗为 0」⇒ 必红 |
| `test_report_contains_required_action_text` | 删掉「处置要求」段 ⇒ 报告退化成统计表 ⇒ 必红 |
| `test_bad_metrics_still_exit_0` | 加一条「超过 N 就 exit 1」的阈值 ⇒ 必红 |
| `test_run_is_read_only_and_json_is_the_only_write` | 顺手落盘 / 改了会话文件 ⇒ 必红 |
| `test_workspace_key_matches_real_dsh_dir_names` | 编码器改口径（如空格写成 `_`）⇒ 与真实目录名不再相符 ⇒ 必红 |
| `test_unreadable_file_is_reported_not_silently_skipped` | 读不出来时静默跳过 ⇒ `errors` 为空 ⇒ 必红 |

## 边界（照实登记，§19.1）

- CI 的 workflow 单测 job 只装 `pytest`（**无 `zstandard`**、`zstd` CLI 不保证）⇒ 本文件一律用**未压缩**
  的 `.jsonl` 语料（`read_session_text` 按魔数识别，非 zstd 直接按文本读）。
- 本文件**不测**单价假设（`--price-cache` / `--price-output` 是人为系数）：只断言**份额算术**自洽；
  「套餐单价」不在本判据射程内 —— 报告里已把该口径与读数一起打印。
- 本文件**不测**真实会话语料（那是 `--all` 的手工复核，见 PR body）；合成语料的期望值全部手算得出。
- 判据**不判**「阈值投影的收益是否会发生」：它是**反事实**（折叠后步数会变），报告里已按上界标注。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "token_ledger.py"


def _load_module():
    """按路径加载脚本模块（`scripts/` 不是包，不能 import）。"""
    spec = importlib.util.spec_from_file_location("token_ledger", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["token_ledger"] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


# ── 合成语料：全部为手算得出的精确期望值 ─────────────────────────────────────
def _step(ts: int, *, i: int, c: int, o: int, r: int = 0, total: int | None = None) -> str:
    """一条 `assistant/message`（默认 `totalTokens` 与三者和相等 —— 恒等式自证）。"""
    usage = {"inputTokens": i, "cacheReadTokens": c, "outputTokens": o, "reasoningTokens": r}
    usage["totalTokens"] = i + c + o if total is None else total
    return json.dumps({"type": "assistant/message", "time": ts, "data": {"turn": 1, "step": 1, "usage": usage}})


def _session_header(depth: int) -> str:
    """DSH 会话日志**首行**的逐字形态（出处 = 本机真日志 `session-c24d616d-72ab-4fc1-808b-0028b306ca60`，2026-10-01 取证）。

    ⚠️ **口径：`delegationDepth` 在顶层**（与 `type/version/id/createdAt/cwd/isSeeded/agentPreset` 同级），
    **不在 `data` 里**。本夹具曾经"自己发明"成 `data.delegationDepth` ⇒ 判据与实现**共用同一个错误假设**
    ⇒ **本地绿、真机 100% 归因成「未知」**（#5927，合并后当场发现）。
    ⇒ 纪律：**合成语料逐字取自真对象，不许凭印象编形态**（同 §25「读数与它声称的对象」）。
    """
    return json.dumps({
        "type": "session",
        "version": 3,
        "id": "session-c24d616d-72ab-4fc1-808b-0028b306ca60",
        "createdAt": 1789383813968,
        "cwd": "/Users/guangzhen.zk/ai native",
        "isSeeded": False,
        "delegationDepth": depth,
        "agentPreset": "migao",
    })


def _write(root: Path, cwd: str, lines: list[str], name: str = "s1") -> Path:
    """在 `<root>/--<key>--/<name>/session.v3.jsonl` 落一份语料，返回文件路径。

    ⚠️ `cwd` 必须与 `main()` 同口径地 `resolve()`（macOS 上 `/tmp` 是 `/private/tmp` 的软链）——
    否则语料落在 `--tmp-fake--` 下、而被扫的是 `--private-tmp-fake--`，测试会以「不可判定」静默变红。
    """
    directory = root / f"--{mod.workspace_key(Path(cwd).resolve())}--" / name
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "session.v3.jsonl"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _run(capsys, root: Path, cwd: str, *extra: str) -> tuple[int, str, str]:
    """跑一次 `main()`；返回 `(退出码, stdout, stderr)`。"""
    code = mod.main(["--sessions", str(root), "--cwd", cwd, *extra])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ── 判据 1：精确计数 ────────────────────────────────────────────────────────
def test_totals_are_exact(tmp_path: Path, capsys) -> None:
    """3 步：上下文 100k/200k/400k ⇒ 计费 = input+cache+output；均值 = Σcontext/3。"""
    root = tmp_path / "sessions"
    _write(root, "/tmp/fake", [
        _session_header(0),
        '{"type":"session/title","data":{"title":"合成会话"}}',
        _step(1_000_000, i=10_000, c=90_000, o=500),          # 上下文 100_000
        _step(1_030_000, i=20_000, c=180_000, o=600),         # 上下文 200_000
        _step(1_090_000, i=40_000, c=360_000, o=700),         # 上下文 400_000
        '{"type":"user/message","data":{}}',
        '{"type":"tool/call","data":{"callId":"c1","name":"bash"}}',
    ])
    code, out, _ = _run(capsys, root, "/tmp/fake")
    assert code == mod.EXIT_OK
    assert "模型往返（步）      3" in out
    assert "计费 token 合计     701,800" in out            # 700_000 input+cache + 1_800 output
    assert "├ 未命中输入（全价） 70,000" in out
    assert "├ 缓存命中读取      630,000" in out
    assert "└ 输出              1,800" in out
    assert "平均上下文/步        233,333" in out            # (100k+200k+400k)/3
    assert "每条用户消息         701,800 计费 token（1 条用户消息）" in out


# ── 判据 2：恒等式不符必须**计数上报**（不静默丢弃）────────────────────────
def test_identity_violation_is_counted_not_swallowed(tmp_path: Path, capsys) -> None:
    """`totalTokens != i+c+o` ⇒ 计数上报；**该条仍按分量入账**（不整条丢弃）。"""
    root = tmp_path / "sessions"
    _write(root, "/tmp/fake", [
        _step(1_000_000, i=1_000, c=9_000, o=100),
        _step(1_010_000, i=2_000, c=8_000, o=200, total=999_999),  # 故意不符
    ])
    code, out, _ = _run(capsys, root, "/tmp/fake")
    assert code == mod.EXIT_OK
    assert "恒等式不符 1 条" in out
    assert "计费 token 合计     20,300" in out               # 两条分量之和，证明没被丢


# ── 判据 3：停顿桶是**半开区间**（边界值必须只落一个桶）─────────────────────
def test_gap_buckets_are_half_open(tmp_path: Path, capsys) -> None:
    """29s/<30s、30s/30s-2m、119s/30s-2m、120s/2-10m、599s/2-10m、600s/10-60m、3600s/>60m。"""
    root = tmp_path / "sessions"
    base = 1_000_000_000
    gaps_ms = [0, 29_000, 30_000, 119_000, 120_000, 599_000, 600_000, 3_600_000]
    lines = [_step(base + sum(gaps_ms[: idx + 1]), i=1_000, c=9_000, o=10) for idx in range(len(gaps_ms))]
    _write(root, "/tmp/fake", lines)
    code, out, _ = _run(capsys, root, "/tmp/fake", "--all")
    assert code == mod.EXIT_OK
    # 首步没有「上一步」⇒ 不计入任何桶 ⇒ 7 个间隔：29s 落 <30s=1；30s/119s 落 30s-2m=2；
    # 120s/599s 落 2-10m=2；600s 落 10-60m=1；3600s 落 >60m=1
    # （列宽用 `\s+` 匹配：断言的是**归属**，不是排版）
    for name, expected in (("<30s", 1), ("30s-2m", 2), ("2-10m", 2), ("10-60m", 1), (">60m", 1)):
        assert re.search(rf"{re.escape(name)}\s+{expected}\s", out), (name, expected)
    assert sum(b[0] for b in mod.parse_session("\n".join(lines))["gaps"].values()) == len(gaps_ms) - 1


# ── 判据 4：上下文 = input + cacheRead（**不含**输出）───────────────────────
def test_context_is_input_plus_cache_read(tmp_path: Path, capsys) -> None:
    """输出再大也不进「上下文」——把口径改成 `totalTokens` 会改变这条读数。"""
    root = tmp_path / "sessions"
    _write(root, "/tmp/fake", [_step(1_000_000, i=1_000, c=9_000, o=990_000)])
    _, out, _ = _run(capsys, root, "/tmp/fake")
    assert "平均上下文/步        10,000" in out
    assert "计费 token 合计     1,000,000" in out


# ── 判据 5：阈值投影 —— 精确值 + 单调 + 首档 = 现状 ─────────────────────────
def test_cap_projection_is_exact_and_monotone(tmp_path: Path, capsys) -> None:
    """prompt = 100k / 500k / 900k；cap 300k ⇒ Σmin = 100k+300k+300k = 700k。"""
    root = tmp_path / "sessions"
    _write(root, "/tmp/fake", [
        _step(1_000_000, i=0, c=100_000, o=0),
        _step(1_010_000, i=0, c=500_000, o=0),
        _step(1_020_000, i=0, c=900_000, o=0),
    ])
    _, out, _ = _run(capsys, root, "/tmp/fake")
    assert "     300,000            700,000            800,000   53.3%" in out
    rows = mod.parse_session(
        "\n".join([
            _step(1_000_000, i=0, c=100_000, o=0),
            _step(1_010_000, i=0, c=500_000, o=0),
            _step(1_020_000, i=0, c=900_000, o=0),
        ])
    )["cap_sums"]
    values = [rows[cap] for cap in mod.CAP_LADDER]      # 档位由大到小（1M → 100k）
    assert values == sorted(values, reverse=True)        # 单调：cap 越大，能保留的越多
    assert rows[1_000_000] == 1_500_000                  # 最大档 = 现状


# ── 判据 6：子代理归属按 `delegationDepth`（不是按目录名 / 标题猜）──────────
def test_depth_attribution_is_by_delegation_depth(tmp_path: Path, capsys) -> None:
    """depth 0 = 主会话；depth 1 = 子代理 ⇒ 份额按计费 token 各自归集。"""
    root = tmp_path / "sessions"
    _write(root, "/tmp/fake", [
        _session_header(0),
        _step(1_000_000, i=0, c=100_000, o=0),
    ], name="main")
    _write(root, "/tmp/fake", [
        _session_header(1),
        _step(1_000_000, i=0, c=300_000, o=0),
    ], name="child")
    _, out, _ = _run(capsys, root, "/tmp/fake")
    assert re.search(r"主会话\s+会话\s+1\s+计费\s+100,000\s+25\.0%", out)
    assert re.search(r"子代理 depth=1\s+会话\s+1\s+计费\s+300,000\s+75\.0%", out)


# ── 判据 7：不可判定 ⇒ exit 3（两种形态）───────────────────────────────────
def test_zero_steps_is_undecidable_and_exits_3(tmp_path: Path, capsys) -> None:
    """语料里没有任何 `usage` ⇒ **不是**「消耗为 0」，是解析不到 ⇒ exit 3。"""
    root = tmp_path / "sessions"
    _write(root, "/tmp/fake", ['{"type":"session","data":{"delegationDepth":0}}'])
    code, out, err = _run(capsys, root, "/tmp/fake")
    assert code == mod.EXIT_UNDECIDABLE
    assert "不可判定" in err
    assert "会话 token 账" not in out                     # 不得退化成一份「正常报告」


def test_missing_workspace_exits_3_with_candidates(tmp_path: Path, capsys) -> None:
    """推导不出工作区目录 ⇒ 打印**候选**再 exit 3（不许静默扫 0 个）。"""
    root = tmp_path / "sessions"
    (root / "--tmp-somewhere-else--" / "s1").mkdir(parents=True)
    code, _, err = _run(capsys, root, "/tmp/fake")
    assert code == mod.EXIT_UNDECIDABLE
    assert "候选" in err
    assert "--tmp-somewhere-else--" in err


def test_unreadable_file_is_reported_not_silently_skipped(tmp_path: Path, capsys) -> None:
    """损坏 / 读不出来的会话文件必须**具名计数上报**；唯一文件读不出来 ⇒ 不可判定（不是「0 消耗」）。

    ⚠️ **三种环境形态的失败原因各不相同，判据只咬三者共有的契约**（读失败 + 具名 + 计入 errors）：

    | 环境 | 走的路径 | 原因文案 |
    |---|---|---|
    | 本机（有 `zstandard`） | 模块 `stream_reader` | 「解压得到空内容」（该 API **不抛错、只回空串**）|
    | GitHub runner（有 `zstd` CLI） | `zstd -dc` | 「`zstd -dc` 退出 N：… Read error (39) : premature end」|
    | CI 单测 job（两者皆无） | 无解压器 | 「既无 `zstandard` 模块也无 `zstd` CLI」|

    ⇒ **咬具体文案 = 本地绿、CI 红**：本 PR 现场踩了**两次**（第二次是 GitHub runner 有 `zstd` CLI 那条路径，
    本地用 `PYTHONPATH` 屏蔽 `zstandard` 即可复现）。

    红证（本机形态下可判）：让 `read_session_text` 对损坏帧返回 `("", None)`（= 去掉「空内容」检查）
    ⇒ `main` 把它算成「扫过一份、0 步」，`err` 里不再有「读不出来」⇒ 本判据红。
    ⚠️ 覆盖随环境而变（CI 走 CLI 时该分支不可达）——**这是如实登记的边界，不是「已覆盖」**。
    """
    root = tmp_path / "sessions"
    target = _write(root, "/tmp/fake", [_step(1_000_000, i=1, c=1, o=1)])
    target.write_bytes(mod.ZSTD_MAGIC + b"\x00" * 32)     # 伪造 zstd 帧 ⇒ 一定读不出来
    code, out, err = _run(capsys, root, "/tmp/fake")
    assert code == mod.EXIT_UNDECIDABLE                   # 唯一文件读不出来 ⇒ 不可判定
    assert "读不出来（已计入 errors，未静默丢弃）" in err     # 契约：读失败必须被**计数上报**（三条路径都走它）
    assert target.name in err                             # 具名：哪一份文件
    assert "会话 token 账" not in out                      # 不得退化成一份「正常报告」


# ── 判据 8：报告型语义 + 只读 ───────────────────────────────────────────────
def test_report_contains_required_action_text(tmp_path: Path, capsys) -> None:
    """报告必须含处置要求原文（否则会被读成「仅供参考的统计」）。"""
    root = tmp_path / "sessions"
    _write(root, "/tmp/fake", [_step(1_000_000, i=1_000, c=9_000, o=10)])
    _, out, _ = _run(capsys, root, "/tmp/fake")
    for fragment in ("处置要求", "§29", "一个任务一个会话", "thresholdRatio", "停顿 >30s", "子代理"):
        assert fragment in out
    assert mod.REQUIRED_ACTION in out


def test_bad_metrics_still_exit_0(tmp_path: Path, capsys) -> None:
    """指标再差也 exit 0 —— 报告型，**不是门禁**（加阈值即红）。"""
    root = tmp_path / "sessions"
    _write(root, "/tmp/fake", [_step(1_000_000, i=0, c=900_000, o=0)])
    code, out, _ = _run(capsys, root, "/tmp/fake")
    assert code == mod.EXIT_OK
    assert "计费 token 合计     900,000" in out


def test_run_is_read_only_and_json_is_the_only_write(tmp_path: Path, capsys) -> None:
    """不带 `--json` ⇒ 会话目录**一个字节都不动**（也不新增文件）；带了 ⇒ 只多那一个文件。"""
    root = tmp_path / "sessions"
    target = _write(root, "/tmp/fake", [_step(1_000_000, i=1_000, c=9_000, o=10)])
    before = target.read_bytes()
    session_dir = target.parent
    code, _, _ = _run(capsys, root, "/tmp/fake")
    assert code == mod.EXIT_OK
    assert target.read_bytes() == before
    assert sorted(p.name for p in session_dir.iterdir()) == ["session.v3.jsonl"]

    payload = tmp_path / "out.json"
    code, _, _ = _run(capsys, root, "/tmp/fake", "--json", str(payload))
    assert code == mod.EXIT_OK
    assert target.read_bytes() == before                  # 仍然没动会话文件
    data = json.loads(payload.read_text(encoding="utf-8"))
    assert data["totals"]["steps"] == 1
    assert data["totals"]["fresh"] == 1_000
    assert data["totals"]["billed"] == 10_010
    assert sorted(p.name for p in session_dir.iterdir()) == ["session.v3.jsonl"]


# ── 判据 9：工作区推导必须与 DSH 真实目录名逐字相符 ─────────────────────────
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/Users/guangzhen.zk/ai native", "Users-guangzhen.zk-ai~0020native"),
        ("/Users/guangzhen.zk/deepseek-harness", "Users-guangzhen.zk-deepseek-harness"),
        ("/tmp/private/tmp/dsh/readme", "tmp-private-tmp-dsh-readme"),
    ],
)
def test_workspace_key_matches_real_dsh_dir_names(path: str, expected: str) -> None:
    """三条真值取自本机 `~/.dsh/sessions/` 的真实目录名（空格 ⇒ `~0020`）。"""
    assert mod.workspace_key(Path(path)) == expected


# ── 判据 10：多帧 zstd（同批修复的**真缺陷**，issue #5920）───────────────────
def _zstd_available() -> bool:
    """本机能否造多帧 zstd 语料（CI 只装 pytest ⇒ 那条行为判据会 skip；skip 长得像 skip）。"""
    if shutil.which("zstd"):
        return True
    try:
        import zstandard  # noqa: F401
    except ImportError:
        return False
    return True


def _frame(text: str) -> bytes:
    """把一段文本压成**一帧**（优先模块，退 CLI）—— 只为造多帧语料。"""
    data = text.encode("utf-8")
    try:
        import zstandard  # type: ignore

        return zstandard.ZstdCompressor().compress(data)
    except ImportError:
        proc = subprocess.run(["zstd", "-c", "-q"], input=data, capture_output=True)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout


@pytest.mark.skipif(
    not _zstd_available(),
    reason="无 zstandard / zstd ⇒ 「多帧文件真能读全」在本环境**不可判定**（故意 skip，不是通过）",
)
def test_multiframe_log_is_not_truncated_to_first_frame(tmp_path: Path, capsys) -> None:
    """DSH 会话日志是**逐条追加**写成的 zstd **多帧**文件（本机实测单份 15,841 帧）。

    `ZstdDecompressor().decompress()` **只解第一帧** ⇒ 步数恒为 0（实测：24.5MB 的日志只得到
    206 字符）⇒ 在装了 `zstandard` 的机器上，工具对**每一份**真实会话都报「不可判定」= 形同不可用。
    红证：把 `read_session_text` 的模块分支改回 `decompress(raw, max_output_size=…)` ⇒ 本判据红
    （`text.count(...)` 变 1、`steps` 变 0）。
    """
    root = tmp_path / "sessions"
    target = _write(root, "/tmp/fake", [])
    target.write_bytes(
        _frame(_step(1_000_000, i=1_000, c=9_000, o=10) + "\n")
        + _frame(_step(1_030_000, i=2_000, c=8_000, o=20) + "\n")
    )
    text, reason = mod.read_session_text(target)
    assert (text or "").count("assistant/message") == 2, (
        f"多帧日志被截断（只解了第一帧？）：只读到 {len(text or '')} 字符，原因 {reason}"
    )
    code, out, _ = _run(capsys, root, "/tmp/fake")
    assert code == mod.EXIT_OK
    assert "模型往返（步）      2" in out
    assert "计费 token 合计     20,030" in out


@pytest.mark.parametrize("script", ["scripts/token_ledger.py", "scripts/roundtrip_report.py"])
def test_zstd_module_path_uses_a_multiframe_capable_reader(script: str) -> None:
    """**类级元守卫**：报告型会话工具的 zstd 模块分支，不得用只解单帧的 `decompress()`。

    两个工具读的是**同一种**日志（DSH 逐条追加的多帧 zstd）⇒ 这个缺陷是**类**，不是一处。
    本条在 CI（无 zstandard / zstd）也能跑 —— 它判的是**形态**；**行为**由上面那条 skipif 判据承担。
    读法用 `ast`（**结构**）：注释与字符串都**不是** AST 节点 ⇒ 判据不可能吃到自己的说明文字，
    也不需要「先清空字符串再剥 `#`」那套（`tests/unit_ci_workflows/_source_parsing.py` 的口径）。
    边界（照实登记）：判不了「两套 API 都写了、先跑单帧那套」，也判不了别的解压实现。
    """
    tree = ast.parse((ROOT / script).read_text(encoding="utf-8"))
    funcs = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "read_session_text"]
    assert len(funcs) == 1, f"{script}: `read_session_text` 必须唯一存在（找不到 ⇒ 判据认错对象）"
    attrs = {node.attr for node in ast.walk(funcs[0]) if isinstance(node, ast.Attribute)}
    assert "stream_reader" in attrs                       # 跨帧读法在场
    assert "decompress" not in attrs                      # 只解单帧的 API 不得出现


# ── 判据 11：**真语料核对**（#5927 的类级出口：合成夹具不许自己发明形态）──────
def _smallest_real_session_log() -> Path | None:
    """本机 DSH 会话根下**最小**的一份真日志（没有 ⇒ None）。

    取最小而非最大：判据只需覆盖**首行的记录形态**，用最大那份 = 白解码 86M 字符。
    """
    root = Path(os.environ.get("DSH_SESSIONS_ROOT", "~/.dsh/sessions")).expanduser()
    if not root.is_dir():
        return None
    candidates = [p for p in root.glob("*/*/session*.jsonl*") if p.is_file() and p.stat().st_size > 0]
    return min(candidates, key=lambda p: p.stat().st_size) if candidates else None


def test_real_session_log_shape_is_read() -> None:
    """**拿真日志核对形态**：`delegationDepth` 必须从真记录里读得出来（本机可跑；CI 显式 skip）。

    这条判据才是 #5927 的类级出口：上一版用**我自己发明的** `data.delegationDepth` 做夹具
    ⇒ 判据与实现**共用同一个错误假设** ⇒ 两边一起绿、真机 100% 归因成「未知」。
    **合成语料必须逐字取自真对象**；本判据把这个纪律变成一台会红的机器。
    """
    log = _smallest_real_session_log()
    if log is None:
        pytest.skip("本机没有 DSH 会话日志 ⇒ 真语料形态核对在本环境不可判定（故意 skip，不是通过）")
    text, reason = mod.read_session_text(log)
    assert text, f"读不出真日志 {log}：原因 {reason}"
    header = text.splitlines()[0]
    assert '"type":"session"' in header, f"真日志首行不是会话头：{header[:120]}"
    depth = mod.parse_session(header)["depth"]
    assert isinstance(depth, int), (
        f"真日志首行的 `delegationDepth` 没被读出来（实际 {depth!r}，形态漂移？）"
        f"—— 取证：zstd -dc {log} | head -1"
    )


# ── 判据 9：窗口叠加 ────────────────────────────────────────────────────────
class _FrozenClock:
    """只替换 `token_ledger` 模块内的 `time`（不碰全局 `time` 模块）—— 边界判据要的是确定性。"""

    def __init__(self, now: float) -> None:
        self._now = now

    def time(self) -> float:
        return self._now


def _run_json(root: Path, cwd: str, out_path: Path, *extra: str) -> dict:
    """跑一次 `main()`，返回 `--json` 机读形态（判据不依赖控制台排版）。"""
    code = mod.main(["--sessions", str(root), "--cwd", cwd, "--json", str(out_path), *extra])
    assert code == 0, f"main() 退出码 {code}（期望 0）"
    return json.loads(out_path.read_text(encoding="utf-8"))


def _fold(seq: int) -> str:
    """一条 `compaction/start`（折叠点；返工对照靠它的 `seq` 划窗口）。"""
    return json.dumps({"type": "compaction/start", "seq": seq, "time": 1_700_000_000_000 + seq,
                       "data": {"compactionId": f"c{seq}", "turn": 1}})


def _tool(seq: int, name: str, **args) -> str:
    """一条 `tool/call`（真形态：`data.name` + `data.arguments` 是 **JSON 字符串**）。"""
    return json.dumps({"type": "tool/call", "seq": seq, "time": 1_700_000_000_000 + seq,
                       "data": {"name": name, "arguments": json.dumps(args), "callId": f"c{seq}"}})


def test_until_window_is_half_open(tmp_path: Path, monkeypatch) -> None:
    """`--days D` = `[T-D, ∞)`；`--days D --until U` = `[T-D, T-U)` —— 上界**不含**、下界**含**。

    冻结时钟才能判「恰好压在边界上」那一格：真时钟下 mtime 与边界永远差几毫秒 ⇒
    判据退化成「大概在窗口里」（= §25 的**空断言**形态）。
    """
    now = 5_000_000.0
    monkeypatch.setattr(mod, "time", _FrozenClock(now))
    root, cwd = tmp_path / "sessions", str(tmp_path / "repo")
    for name, age_days in (("a", 1.0), ("b", 4.0), ("c", 3.0)):
        p = _write(root, cwd, [_session_header(0), _step(1_700_000_000_000, i=10, c=90, o=1)], name=name)
        stamp = now - age_days * 86400
        os.utime(p, (stamp, stamp))

    # 下界**含**：c 恰好 3 天前仍在「最近 3 天」里；b（4 天前）在外。
    data = _run_json(root, cwd, tmp_path / "a.json", "--days", "3")
    assert data["totals"]["steps"] == 2, data["scope"]["window"]
    # 上界**不含**：`--days 6 --until 3` 只剩 b（c 恰好压在上界 ⇒ 排除；a 太新 ⇒ 排除）。
    data = _run_json(root, cwd, tmp_path / "b.json", "--days", "6", "--until", "3")
    assert data["totals"]["steps"] == 1, data["scope"]["window"]
    assert "前 3 天" in data["scope"]["window"], data["scope"]["window"]


# ── 判据 10：折叠 / prune 计数（分臂判据，单向） ────────────────────────────
def test_fold_and_prune_counts(tmp_path: Path, capsys) -> None:
    lines = [
        _session_header(0),
        _fold(100),
        json.dumps({"type": "compaction/end", "seq": 101, "time": 1_700_000_000_101, "data": {}}),
        json.dumps({"type": "compaction/prune", "seq": 102, "time": 1_700_000_000_102, "data": {}}),
        _step(1_700_000_000_103, i=10, c=90, o=1),
    ]
    root, cwd = tmp_path / "sessions", str(tmp_path / "repo")
    _write(root, cwd, lines)
    data = _run_json(root, cwd, tmp_path / "fold.json")
    row = data["sessions"][0]
    assert (row["folds"], row["prunes"]) == (1, 1), row
    assert data["rework"]["sessions_with_folds"] == 1, data["rework"]

    # 接线面：报告里真出现这一节（判据本体绿 ≠ 接线在，§28.2）
    code, out, err = _run(capsys, root, cwd)
    assert code == 0, err
    assert "有折叠的会话：1 个" in out, out
    assert "归因 ④" in out, out


# ── 判据 11：折叠后返工 = 同会话前后对照（分子分母都要精确） ────────────────
def test_post_fold_rework_is_compared_against_the_rest_of_the_session(tmp_path: Path) -> None:
    lines = [
        _session_header(0),
        _step(1_700_000_000_001, i=10, c=90, o=1),
        _tool(10, "bash", command="pytest tests/x"),  # 首次出现
        _tool(20, "read", file_path="/repo/a.py"),    # 首次出现
        _tool(30, "job_output", job_id="j1"),         # 不在 REPEAT_TOOLS ⇒ 不进分母
        _fold(100),
        _tool(110, "bash", command="pytest tests/x"),  # 重复 + 折叠后窗口 (100, 220]
        _tool(120, "read", file_path="/repo/a.py"),    # 重复 + 折叠后窗口
        _tool(130, "job_output", job_id="j1"),         # 不进分母
        _tool(300, "bash", command="pytest tests/x"),  # 重复，但**在窗口外**
        _tool(310, "bash", command="ls"),              # 不重复
    ]
    root, cwd = tmp_path / "sessions", str(tmp_path / "repo")
    _write(root, cwd, lines)
    data = _run_json(root, cwd, tmp_path / "rework.json")
    rw = data["rework"]
    assert (rw["post_calls"], rw["post_repeats"]) == (2, 2), rw
    # 窗口外 = 折叠点之前的两条首现（10 / 20）+ 窗口关闭后的两条（300 重复、310 不重复）。
    assert (rw["other_calls"], rw["other_repeats"]) == (4, 1), rw
