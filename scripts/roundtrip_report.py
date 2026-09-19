#!/usr/bin/env python3
"""roundtrip_report — 会话往返账：把「**步数才是计费单位**」摆到台面上（issue #4428）。

## 为什么需要它

#4419（客户管理收货信息，一个「小需求」）实测：会话墙钟 **46.3 min** / **279 步**，
而**前台工具执行合计只有 8.1 min**、单个最慢命令 16.6s —— **没有任何一条命令慢，慢的是往返次数**。
最刺眼的一条：`read` 32 + `edit` 49 + `write` 6 = **87 次往返**，执行合计 **1.7s**
⇒ 约 12 min 花在「逐点小步编辑」上。

`migao-dev-flow` §21 把「读要成批 / 改要成批 / 查要合并 / 验证不来回」写成了纪律，
但**纪律没有分母就退化成人人自称遵守**。本脚本就是那台给分母的机器：**零 LLM、只读、秒级**。

## 它**不**做什么（诚实登记，防被读成门禁）

- **不阻塞**：指标再差也 `exit 0` —— 报告型，供人/agent 决策（同 `rework_hotspot_scan.py` 的定位）；
- **不判**「这次会话是否高效」：步数预算**因任务而异**（改 30 个文件与改 1 行不同分母），
  本脚本只给**计数证据**，不设阈值、不建基线、不写文件（除 `--json` 显式指定）；
- **不覆盖**「模型生成时间」的精确值：见下「口径」。

## 口径（引用数值必须连口径一起给）

- **步**（step）= `assistant/message` 记录数 —— **一次模型往返**，这是计费单位；
- **调用**（call）= `tool/call` 记录数；**往返比** = 调用 / 步（>1 说明同一步发了多个调用 = 批量化生效）；
- **工具执行** = 同一 `callId` 的 `tool/call` → `tool/result` 时间差，**只算前台**；
- **模型时间（上界）** = 墙钟 − 前台工具执行。
  ⚠️ 这是**上界**：后台 job（`run_in_background`）与模型生成**重叠**，其耗时既不在「墙钟之外」也不全在
  「工具执行」里 ⇒ 本项**只用于排序让人去看，不是可引用的绝对数**
  （与 `rework_hotspot_scan.py` 的函数级「近似」同族，同为有意取舍）；
- **空等** = 相邻两步之间的间隔 Top N（含上一步的工具执行）——「模型在想」与「在等后台 job」在这里**同形**，
  故一律标注为**空等**而不猜归属。

## 判据（不可判定 ≠ 通过）

- 解析不出任何**步** ⇒ 打印「不可判定」块并 `exit 3` —— **不得**退化成一份看起来正常的报告
  （这正是 `migao-acceptance` 的「空跑」形态：绿了但没跑）；
- 解压工具缺失 / 输入不是会话日志 ⇒ 同上（`exit 3`），**不谎报正常**；
- 用法错误 ⇒ `exit 2`。

## 用法（仓根）

    python3 scripts/roundtrip_report.py <session.jsonl|session.v3.jsonl.zst>
    python3 scripts/roundtrip_report.py <会话目录>        # 取该目录下最新的 session.*.jsonl[.zst]
    python3 scripts/roundtrip_report.py <文件> --json     # 机读形态
    python3 scripts/roundtrip_report.py <文件> --top 10   # 空等榜长度（默认 5）
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

#: zstd 帧魔数 —— 用它判「要不要解压」，而不是看扩展名（`.jsonl` 也可能是压缩的）。
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

#: 「等待型调用」判据（issue #4455）：bash 命令里出现 `sleep <数字>` ⇒ 纯空等 + 一轮往返。
#: ⚠️ 只匹配**独立词** `sleep`（`sleepy 5` / `xsleep 5` 不算），且只看 **bash** 的 `command` 字段。
SLEEP_RE = re.compile(r"\bsleep\s+\d+")

#: 退出码（三态，与 `pr_body_guard.py` / `merge_gate.py` 同族）：`3` = 无法判定，**不得当 `0` 读**。
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_UNDECIDABLE = 3

#: 处置要求原文 —— 报告里必须原样出现（否则会被读成「仅供参考的统计」，同 `rework_hotspot_scan.py`）。
REQUIRED_ACTION = (
    "命中「往返占比高」时（判据：某工具的**调用数占比**显著高于其**执行耗时占比**）⇒ "
    "按 `migao-dev-flow` §21 的 P1~P4 处置：读要成批 / 改要成批（同一步多个 edit，>3 处用一次 write）/ "
    "查要合并（多条 grep 合成一条 bash）/ 验证不来回（先窄跑再全量）；"
    "命中「等待型调用」时 ⇒ 按 **P7** 处置：用 `gh pr checks <PR> --watch`（一次阻塞调用）"
    "或把它丢**后台 job**（完成时被通知）替代 `sleep N` 轮询。"
)


def bash_command_of(data: dict) -> str:
    """取 bash 调用的命令行；非 bash / 解析失败 ⇒ 空串（判据只看 bash 的 `command`）。"""
    if str(data.get("name") or "") != "bash":
        return ""
    try:
        args = json.loads(data.get("arguments") or "{}")
    except json.JSONDecodeError:
        return ""
    return str(args.get("command") or "") if isinstance(args, dict) else ""


def read_session_text(path: Path) -> tuple[str | None, str | None]:
    """读会话文本；返回 `(text, 失败原因)`。zstd 帧按魔数识别，先试模块再退 CLI。"""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"读不到文件：{exc}"
    if not raw.startswith(ZSTD_MAGIC):
        return raw.decode("utf-8", errors="replace"), None
    try:  # 优先纯 python（无外部进程）；本机未装 zstandard，故必须保留 CLI 退路。
        import zstandard  # type: ignore

        return zstandard.ZstdDecompressor().decompress(raw, max_output_size=1 << 30).decode(
            "utf-8", errors="replace"
        ), None
    except ImportError:
        pass
    except Exception as exc:  # 解压失败也要有原因，不能静默
        return None, f"zstandard 解压失败：{exc}"
    try:
        proc = subprocess.run(["zstd", "-dc", str(path)], capture_output=True)
    except FileNotFoundError:
        return None, "既无 `zstandard` 模块也无 `zstd` CLI —— 无法解压（装其一，或喂未压缩的 .jsonl）"
    if proc.returncode != 0:
        return None, f"`zstd -dc` 退出 {proc.returncode}：{proc.stderr.decode('utf-8', 'replace').strip()}"
    return proc.stdout.decode("utf-8", errors="replace"), None


def resolve_input(path: Path) -> tuple[Path | None, str | None]:
    """目录 ⇒ 取其中最新的 `session*.jsonl[.zst]`（递归一层：DSH 按 cwd 分目录）。"""
    if path.is_file():
        return path, None
    if not path.is_dir():
        return None, f"既不是文件也不是目录：{path}"
    candidates = [p for p in path.rglob("session*.jsonl*") if p.is_file()]
    if not candidates:
        return None, f"目录下没有 `session*.jsonl*`：{path}"
    return max(candidates, key=lambda p: p.stat().st_mtime), None


def analyze(text: str) -> dict:
    """把会话 JSONL 折成往返账。坏行**计数**上报，不静默丢弃。"""
    calls: dict[str, tuple[int, str, str]] = {}  # callId -> (time_ms, tool name, bash 命令行)
    tool_calls: collections.Counter = collections.Counter()
    tool_exec: collections.defaultdict = collections.defaultdict(float)
    unpaired = 0
    malformed = 0
    wait_calls = 0
    wait_s = 0.0
    steps: list[tuple[int, tuple]] = []  # (time_ms, (turn, step))
    first = last = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(rec, dict):
            malformed += 1
            continue
        kind = rec.get("type")
        data = rec.get("data") or {}
        ts = rec.get("time")
        if isinstance(ts, int):
            first = ts if first is None else min(first, ts)
            last = ts if last is None else max(last, ts)
        if kind == "assistant/message":
            steps.append((ts if isinstance(ts, int) else 0, (data.get("turn"), data.get("step"))))
        elif kind == "tool/call":
            cid = data.get("callId")
            if isinstance(cid, str) and isinstance(ts, int):
                name = str(data.get("name") or "?")
                calls[cid] = (ts, name, bash_command_of(data))
                tool_calls[name] += 1
        elif kind == "tool/result":
            cid = ((data.get("message") or {}).get("source") or {}).get("callId")
            if isinstance(cid, str) and cid in calls and isinstance(ts, int):
                started, name, command = calls.pop(cid)
                elapsed = max(0.0, (ts - started) / 1000.0)
                tool_exec[name] += elapsed
                if command and SLEEP_RE.search(command):
                    wait_calls += 1
                    wait_s += elapsed

    unpaired = len(calls)
    span_s = ((last - first) / 1000.0) if (first is not None and last is not None) else 0.0
    exec_total = sum(tool_exec.values())
    steps.sort(key=lambda s: s[0])
    gaps = [
        ((steps[i][1]), (steps[i][0] - steps[i - 1][0]) / 1000.0)
        for i in range(1, len(steps))
        if steps[i][0] and steps[i - 1][0]
    ]
    return {
        "steps": len(steps),
        "calls": sum(tool_calls.values()),
        "ratio": (sum(tool_calls.values()) / len(steps)) if steps else 0.0,
        "span_s": span_s,
        "exec_total_s": exec_total,
        "model_upper_s": max(0.0, span_s - exec_total),
        "tools": {n: {"calls": tool_calls[n], "exec_s": tool_exec.get(n, 0.0)} for n in tool_calls},
        "gaps": gaps,
        "wait_calls": wait_calls,
        "wait_s": wait_s,
        "unpaired_calls": unpaired,
        "malformed_lines": malformed,
    }


def render(report: dict, path: Path, top: int) -> str:
    out: list[str] = []
    out.append("=" * 78)
    out.append("会话往返账（roundtrip_report）—— 步数才是计费单位（migao-dev-flow §21）")
    out.append("=" * 78)
    out.append(f"输入：{path}")

    if report["steps"] == 0:
        out.append("")
        out.append("⚠️  **不可判定**：解析出 0 步 —— 这份输入不是会话日志，或格式已漂移。")
        out.append("    这**不是**「本次会话往返很少」。判据：`assistant/message` 记录数 = 0。")
        if report["malformed_lines"]:
            out.append(f"    旁证：{report['malformed_lines']} 行不是合法 JSON。")
        return "\n".join(out)

    out.append("")
    out.append(f"墙钟        {report['span_s'] / 60:8.1f} min")
    out.append(f"步数        {report['steps']:8d}      ← 模型往返次数（计费单位）")
    out.append(f"工具调用    {report['calls']:8d}      往返比 {report['ratio']:.2f} 调用/步（>1 = 批量化生效）")
    out.append(f"工具执行    {report['exec_total_s'] / 60:8.1f} min  （仅前台）")
    out.append(f"模型时间    {report['model_upper_s'] / 60:8.1f} min  （**上界** = 墙钟 − 前台工具执行；后台 job 与生成重叠）")
    if report["unpaired_calls"]:
        out.append(f"⚠️  未配对的 tool/call：{report['unpaired_calls']}（会话中断 / 仍在跑）—— 其耗时**不在**上面的工具执行里")
    if report["malformed_lines"]:
        out.append(f"⚠️  非 JSON 行：{report['malformed_lines']}（已跳过，未计入步/调用）")

    out.append("")
    out.append("── 各工具往返占比（**调用数占比 vs 执行耗时占比**）" + " " * 20)
    out.append(f"{'工具':<14}{'调用':>6}{'调用占比':>10}{'执行(s)':>12}{'耗时占比':>10}")
    calls_total = report["calls"] or 1
    exec_total = report["exec_total_s"] or 1e-9
    ranked = sorted(report["tools"].items(), key=lambda kv: -kv[1]["calls"])
    for name, stat in ranked:
        out.append(
            f"{name:<14}{stat['calls']:>6}{stat['calls'] / calls_total * 100:>9.1f}%"
            f"{stat['exec_s']:>12.1f}{stat['exec_s'] / exec_total * 100:>9.1f}%"
        )

    out.append("")
    out.append("── 等待型调用（`sleep N` 轮询；判据 = bash 的 `command` 匹配 `\\bsleep\\s+\\d+`）")
    if report["wait_calls"]:
        share = report["wait_s"] / exec_total * 100
        out.append(
            f"  {report['wait_calls']} 次 / {report['wait_s']:.0f}s —— 占工具执行 {share:.0f}%"
            "（纯空等，且每次都是一轮模型往返）"
        )
        out.append(
            "  处置：改 `gh pr checks <PR> --watch`（一次阻塞调用）；**首选丢后台 job**（完成时被通知，期间做别的）"
        )
    else:
        out.append("  0 次（未发现 `sleep N` 轮询）")

    out.append("")
    out.append(f"── 空等榜 Top {top}（相邻两步间隔；「模型在想」与「在等后台 job」同形，不猜归属）")
    for (turn, step), sec in sorted(report["gaps"], key=lambda g: -g[1])[:top]:
        out.append(f"  {sec:8.1f}s  turn={turn} step={step}")

    out.append("")
    out.append("── 处置要求（原文，勿读成「仅供参考的统计」）")
    out.append("  " + REQUIRED_ACTION)
    out.append("")
    out.append("边界：模型时间是**上界**（后台 job 与生成重叠）⇒ 只用于排序让人去看，不是可引用的绝对数。")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="会话往返账（报告型：指标再差也 exit 0；不可判定 = exit 3）"
    )
    parser.add_argument("path", type=Path, help="会话 jsonl / jsonl.zst / 含会话的目录")
    parser.add_argument("--json", action="store_true", help="机读形态（不打印报告）")
    parser.add_argument("--top", type=int, default=5, help="空等榜长度（默认 5）")
    args = parser.parse_args(argv)

    target, why = resolve_input(args.path)
    if target is None:
        print(f"❌ {why}", file=sys.stderr)
        return EXIT_USAGE
    text, why = read_session_text(target)
    if text is None:
        print(f"❌ 不可判定：{why}", file=sys.stderr)
        return EXIT_UNDECIDABLE

    report = analyze(text)
    if args.json:
        print(json.dumps({"path": str(target), **report}, ensure_ascii=False, indent=2))
    else:
        print(render(report, target, args.top))
    # 不可判定**不是**「通过」：报告照打（含原因），但退出码照实读。
    return EXIT_OK if report["steps"] else EXIT_UNDECIDABLE


if __name__ == "__main__":
    sys.exit(main())
