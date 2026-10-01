#!/usr/bin/env python3
"""token_ledger — 会话 token 账：把「上下文是计费单位」摆到台面上（issue #5920）。

## 为什么需要它

`roundtrip_report.py`（见 `migao-dev-flow` §21）把**步数**摆上台面；但**步数只是计费单位的个数，单价是上下文**。
2026-10-01 全量实测（migao 研发工作区，40 天）：**211,557 步 / 513.5 亿计费 token**，
其中 **97.8% 是历史重发**（缓存命中读取）、平均 **242k token/步**；
**90.7% 的花费集中在 661 个「步数>100」的会话**（而会话步数中位数只有 79）。
⇒ 「省 token」的真实杠杆不是「少说话」，而是**别让上下文长到几十万再往下干活**（§29 会话卫生）。

本脚本就是那台给分母的机器：**零 LLM、只读、可复算**。

## 口径（引用数值必须连口径一起给）

- **步**（step）= `assistant/message` 记录数 —— 一次模型往返，**这是计费单位**；
- 每步 `usage` = `inputTokens`（**未命中缓存**，全价）+ `cacheReadTokens`（**命中缓存**，折扣价）
  + `outputTokens`；恒等式 `totalTokens == 三者之和` **逐条自证**，不等则计数上报（不静默）；
- **计费合计** = input + cacheRead + output；
- **上下文**（context）= input + cacheRead —— 该步 prompt 的规模，也就是这一步的「单价」；
- **加权成本** = input×1 + cacheRead×`--price-cache` + output×`--price-output`。
  ⚠️ **单价是假设，必须随读数一起给**（默认 `0.1 / 3.0` =「缓存读 1 折、输出 3 倍」的常见档）。
  换套餐只改系数；**份额结论对单价不敏感**（历史重发占绝对多数）；
- **首步 prompt** = 会话第一步的上下文 ≈ system prompt + 工具 schema + 技能目录 + 首条用户消息
  ⇒ 即**每一步都要付的固定开销**；
- **停顿分桶** = 相邻两步的时间差。`<30s` 桶的全价输入 ≈ 本步**新增内容**；间隔更长 ⇒ **缓存失效**，
  历史按全价重算（2026-10-01 实测：`<30s` 桶 1,513 token/步 → `30s-2m` 桶 49,010 → `>60m` 桶 151,298）；
- **阈值投影** = `Σ min(context_i, T)` 的反事实重放：「上下文从未超过 T」能省多少 prompt 量。
  ⚠️ 这是**反事实**：真实折叠后步数可能变化，且每次折叠本身要花一次摘要调用 ⇒ 它是**上界**，不是承诺。

## 判据（不可判定 ≠ 通过）

- 找不到会话根 / 工作区目录 ⇒ 打印**候选**与原因 ⇒ `exit 3`；
- 一个会话文件都读不出来 / 解析不出任何**步** ⇒ `exit 3`（不得退化成一份「看起来很正常」的报告）；
- 用法错误 ⇒ `exit 2`；
- 指标再差也 **`exit 0`** —— 报告型，供人 / agent 决策（**不设阈值、不建基线、不拦合并**）。

## 用法（仓根）

    python3 scripts/token_ledger.py                    # 当前工作区，最近 14 天
    python3 scripts/token_ledger.py --days 30 --top 20
    python3 scripts/token_ledger.py --all              # 该工作区全部会话（分钟级）
    python3 scripts/token_ledger.py --sessions ~/.dsh/sessions --all-workspaces
    python3 scripts/token_ledger.py --json out.json    # 机读形态（唯一写盘点，需显式指定）
"""

from __future__ import annotations

import argparse
import collections
import datetime
import io
import json
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

#: zstd 帧魔数 —— 用它判「要不要解压」，而不是看扩展名（`.jsonl` 也可能被压缩）。
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

#: 退出码（三态，与 `roundtrip_report.py` / `pr_body_guard.py` / `merge_gate.py` 同族）：
#: `3` = 无法判定，**不得当 `0` 读**。
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_UNDECIDABLE = 3

#: 默认 DSH 会话根（`DSH_SESSIONS_ROOT` 可覆盖；非本机路径一律不写死）。
DEFAULT_SESSIONS_ROOT = "~/.dsh/sessions"

#: 停顿分桶（秒）—— 上界开区间。命名即口径：桶内 `fresh/n` = 该停顿下每步平均全价输入。
GAP_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0.0, 30.0, "<30s"),
    (30.0, 120.0, "30s-2m"),
    (120.0, 600.0, "2-10m"),
    (600.0, 3600.0, "10-60m"),
    (3600.0, float("inf"), ">60m"),
)

#: 阈值投影的参考档（绝对 token 数）。默认模型窗口 1M ⇒ 首行 = 现状（0 节省）。
CAP_LADDER: tuple[int, ...] = (1_000_000, 800_000, 600_000, 400_000, 300_000, 200_000, 150_000, 100_000)

#: 处置要求原文 —— 报告里必须原样出现（否则会被读成「仅供参考的统计」）。
REQUIRED_ACTION = (
    "本报告是**分母**不是门禁（指标再差也 exit 0）。按 `migao-dev-flow` §29 处置，优先级从高到低：\n"
    "  ① **别让上下文长到几十万再干活** —— 一个任务一个会话，做完就开新会话；\n"
    "  ② **折叠阈值**（preset 的 `compaction-basic.thresholdRatio`）比默认 0.8 早得多 ⇒ 见上面「阈值投影」；\n"
    "  ③ **停顿 >30s 会让缓存失效**（历史按全价重算）—— 大上下文会话别挂着去等/去开会，宁可开新会话；\n"
    "  ④ **子代理是第二份独立上下文**（实测占 38.9%）—— 派之前先问「这一趟值不值一份上下文」；\n"
    "  ⑤ **思维链会留在上下文里被反复重发** —— 按任务调低 reasoning effort，别一律用最高档；\n"
    "  ⑥ **工具输出进上下文就不再出来** —— bash 一律 `| head`、读大文件用 offset/limit（§29 P1~P4）。"
)


def workspace_key(cwd: Path) -> str:
    """把工作目录折成 DSH 的会话目录名（`/Users/x/ai native` ⇒ `Users-x-ai~0020native`）。

    口径（与 DSH 自身的编码一致）：去掉开头 `/`，`/` ⇒ `-`，其余非 `[A-Za-z0-9._-]` 字符
    按其 UTF-16 码元写成 `~%04X`（空格 = `~0020`）。本函数只**推导**，真伪由 `resolve_workspace`
    在磁盘上核对 —— 推导错了会 `exit 3` 并打印候选，不会静默报 0。
    """
    key: list[str] = []
    for ch in str(cwd).lstrip("/"):
        if ch == "/":
            key.append("-")
        elif ch.isascii() and (ch.isalnum() or ch in "._-"):
            key.append(ch)
        else:  # 非 BMP 字符按 UTF-16 码元逐个编码（与 DSH 的目录名编码同口径）
            raw = ch.encode("utf-16-be")
            key.extend(
                f"~{int.from_bytes(raw[i:i + 2], 'big'):04X}" for i in range(0, len(raw), 2)
            )
    return "".join(key)


def read_session_text(path: Path) -> tuple[str | None, str | None]:
    """读会话文本；返回 `(text, 失败原因)`。zstd 帧按魔数识别，先试模块再退 CLI。"""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"读不到文件：{exc}"
    if not raw.startswith(ZSTD_MAGIC):
        return raw.decode("utf-8", errors="replace"), None
    try:  # 优先纯 python（无外部进程）；CI 无 zstandard，故必须保留 CLI 退路。
        import zstandard  # type: ignore

        # ⚠️ 必须用 **stream_reader**：DSH 的会话日志是**逐条追加**写成的 zstd **多帧**文件
        # （实测单份 15,841 帧），而 `ZstdDecompressor().decompress()` **只解第一帧**
        # （实测：24.5MB 的日志只得到 206 字符 ⇒ 步数恒为 0 ⇒ 工具形同不可用）。
        # stream_reader 跨帧，读数与 `zstd -dc` 逐字节一致（实测 86,240,141 字符）。
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)) as reader:
            text = reader.read().decode("utf-8", errors="replace")
        if not text.strip():  # 损坏 / 截断的帧：stream_reader **不抛错**、只回空串 ⇒ 必须显式报原因
            return None, f"解压得到空内容（zstd 帧损坏或截断？原始 {len(raw)} 字节）"
        return text, None
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


def parse_session(text: str, caps: tuple[int, ...] = CAP_LADDER) -> dict:
    """把一个会话的 JSONL 折成 token 账（纯函数，便于对合成语料做精确值断言）。

    坏行 / 恒等式不符 / 违反排序的 usage **一律计数上报**，不静默丢弃。
    """
    steps = 0
    fresh = cache = out = reason = 0
    user_msgs = tool_calls = malformed = bad_identity = 0
    first_prompt: int | None = None
    sum_prompt = max_prompt = 0
    cap_sums = dict.fromkeys(caps, 0)
    gaps = {name: [0, 0, 0] for _, _, name in GAP_BUCKETS}  # name -> [n, fresh, prompt]
    depth: int | None = None
    title: str | None = None
    t0: int | None = None
    t1: int | None = None
    prev_t: int | None = None

    for line in text.splitlines():
        if not line.strip():
            continue
        if '"delegationDepth"' in line and depth is None:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                rec = None
            if isinstance(rec, dict) and isinstance(rec.get("data"), dict):
                value = rec["data"].get("delegationDepth")
                if isinstance(value, int):
                    depth = value
            continue
        if '"session/title"' in line and title is None:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                rec = None
            if isinstance(rec, dict) and isinstance(rec.get("data"), dict):
                value = rec["data"].get("title")
                if isinstance(value, str):
                    title = value
            continue
        if '"tool/call"' in line:
            tool_calls += 1
            continue
        if '"user/message"' in line:
            user_msgs += 1
            continue
        if '"assistant/message"' not in line or '"usage"' not in line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(rec, dict):
            malformed += 1
            continue
        data = rec.get("data")
        used = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(used, dict):
            malformed += 1
            continue
        i = used.get("inputTokens") or 0
        c = used.get("cacheReadTokens") or 0
        o = used.get("outputTokens") or 0
        total = used.get("totalTokens")
        if isinstance(total, int) and total != i + c + o:
            bad_identity += 1
        steps += 1
        fresh += i
        cache += c
        out += o
        reason += used.get("reasoningTokens") or 0
        prompt = i + c
        sum_prompt += prompt
        max_prompt = max(max_prompt, prompt)
        if first_prompt is None:
            first_prompt = prompt
        for cap in caps:
            cap_sums[cap] += min(prompt, cap)
        ts = rec.get("time")
        if isinstance(ts, int):
            t0 = ts if t0 is None else min(t0, ts)
            t1 = ts if t1 is None else max(t1, ts)
            if prev_t is not None:
                gap = (ts - prev_t) / 1000.0
                for lo, hi, name in GAP_BUCKETS:
                    if lo <= gap < hi:
                        bucket = gaps[name]
                        bucket[0] += 1
                        bucket[1] += i
                        bucket[2] += prompt
                        break
            prev_t = ts

    return {
        "steps": steps,
        "fresh": fresh,
        "cache": cache,
        "out": out,
        "reason": reason,
        "user_msgs": user_msgs,
        "tool_calls": tool_calls,
        "malformed": malformed,
        "bad_identity": bad_identity,
        "first_prompt": first_prompt,
        "sum_prompt": sum_prompt,
        "max_prompt": max_prompt,
        "cap_sums": cap_sums,
        "gaps": gaps,
        "depth": depth,
        "title": title,
        "t0": t0,
        "t1": t1,
    }


def pick_session_file(session_dir: Path) -> Path | None:
    """会话目录 ⇒ 最新写入的那个 `session*` 文件（排除 `*.lock`；空文件不算）。"""
    candidates = [p for p in session_dir.glob("session*") if p.is_file() and not p.name.endswith(".lock")]
    candidates = [p for p in candidates if p.stat().st_size > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda p: (p.stat().st_mtime, p.stat().st_size))


def resolve_workspaces(root: Path, cwd: Path, all_workspaces: bool) -> tuple[list[Path], str | None]:
    """定位要扫的工作区目录；找不到 ⇒ 返回候选供人核对（不静默扫 0 个）。"""
    if not root.is_dir():
        return [], f"会话根不存在：{root}（用 `--sessions` 指定，或设 `DSH_SESSIONS_ROOT`）"
    if all_workspaces:
        dirs = [p for p in sorted(root.iterdir()) if p.is_dir()]
        return (dirs, None) if dirs else ([], f"会话根下没有任何工作区目录：{root}")
    target = root / f"--{workspace_key(cwd)}--"
    if target.is_dir():
        return [target], None
    available = [p.name for p in sorted(root.iterdir()) if p.is_dir()][:8]
    return [], (
        f"按当前目录推导不出工作区目录：{target}\n"
        f"    候选（会话根下前 8 个）：{available or '（空）'}\n"
        f"    出口：`--cwd <实际工作目录>` 或 `--all-workspaces`"
    )


def collect(files: list[Path], caps: tuple[int, ...], jobs: int) -> tuple[list[dict], list[str]]:
    """并行读 + 解析各自的会话文件（IO 在子进程里并行，结果在主线程汇总）。"""

    def one(path: Path) -> dict:
        text, err = read_session_text(path)
        if text is None:
            return {"path": str(path), "error": err}
        row = parse_session(text, caps)
        row["path"] = str(path)
        row["sid"] = path.parent.name
        row["bytes"] = len(text)
        return row

    rows: list[dict] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for row in pool.map(one, files):
            if row.get("error"):
                errors.append(f"{row['path']}：{row['error']}")
            else:
                rows.append(row)
    return rows, errors


def local_date(ms: int | None) -> str | None:
    """epoch ms ⇒ 本机时区日期（时间口径见 `migao-dev-flow`：一切时间表达用本机时区）。"""
    if ms is None:
        return None
    return datetime.datetime.fromtimestamp(ms / 1000).astimezone().strftime("%Y-%m-%d")


def summarize(rows: list[dict], caps: tuple[int, ...], price_cache: float, price_output: float) -> dict:
    """把逐会话的账折成整本账（总量 / 按天 / 会话榜 / 归因 / 阈值投影）。"""
    tot = collections.Counter()
    by_day: dict[str, list[int]] = {}
    by_depth: dict[str, list[int]] = {}
    gaps = {name: [0, 0, 0] for _, _, name in GAP_BUCKETS}
    cap_total = dict.fromkeys(caps, 0)
    firsts: list[int] = []
    for row in rows:
        steps = row["steps"]
        tot["steps"] += steps
        tot["fresh"] += row["fresh"]
        tot["cache"] += row["cache"]
        tot["out"] += row["out"]
        tot["reason"] += row["reason"]
        tot["user_msgs"] += row["user_msgs"]
        tot["tool_calls"] += row["tool_calls"]
        tot["malformed"] += row["malformed"]
        tot["bad_identity"] += row["bad_identity"]
        tot["bytes"] += row.get("bytes", 0)
        if steps:
            tot["sessions_with_usage"] += 1
        if row["first_prompt"] is not None:
            firsts.append(row["first_prompt"])
        day = local_date(row["t0"])
        if day:
            slot = by_day.setdefault(day, [0, 0])
            slot[0] += row["fresh"] + row["cache"] + row["out"]
            slot[1] += steps
        key = "主会话" if row["depth"] == 0 else (f"子代理 depth={row['depth']}" if isinstance(row["depth"], int) else "未知")
        slot = by_depth.setdefault(key, [0, 0, 0])
        slot[0] += 1
        slot[1] += row["fresh"] + row["cache"] + row["out"]
        slot[2] += steps
        for name, bucket in row["gaps"].items():
            for idx in range(3):
                gaps[name][idx] += bucket[idx]
        for cap in caps:
            cap_total[cap] += row["cap_sums"][cap]

    billed = tot["fresh"] + tot["cache"] + tot["out"]
    weighted = tot["fresh"] + tot["cache"] * price_cache + tot["out"] * price_output
    return {
        "totals": {
            **tot,
            "sessions_scanned": len(rows),
            "billed": billed,
            "weighted": weighted,
            "weighted_fresh": tot["fresh"],
            "weighted_cache": tot["cache"] * price_cache,
            "weighted_out": tot["out"] * price_output,
            "avg_context": (tot["fresh"] + tot["cache"]) / tot["steps"] if tot["steps"] else 0.0,
            "per_user_msg": billed / tot["user_msgs"] if tot["user_msgs"] else 0.0,
            "calls_per_step": tot["tool_calls"] / tot["steps"] if tot["steps"] else 0.0,
            "price_cache": price_cache,
            "price_output": price_output,
        },
        "by_day": sorted(by_day.items()),
        "by_depth": sorted(by_depth.items(), key=lambda kv: -kv[1][1]),
        "gaps": gaps,
        "caps": [(cap, cap_total[cap]) for cap in caps],
        "base_prompt": cap_total[max(caps)],
        "overhead": {
            "n": len(firsts),
            "min": min(firsts) if firsts else 0,
            "p50": statistics.median(firsts) if firsts else 0,
            "p90": statistics.quantiles(firsts, n=10)[8] if len(firsts) >= 10 else (max(firsts) if firsts else 0),
            "max": max(firsts) if firsts else 0,
        },
        "sessions": rows,
    }


def fmt(n: float) -> str:
    """千分位整数（读数一律给绝对数，避免「看起来很大」的模糊说法）。"""
    return f"{int(n):,}"


def render(report: dict, scope: dict, top: int) -> str:
    """人读形态。每个数值都带口径；结尾必须出现处置要求原文。"""
    out: list[str] = []
    t = report["totals"]
    add = out.append
    add("=" * 78)
    add("会话 token 账（token_ledger）—— 上下文是计费单位（migao-dev-flow §29）")
    add("=" * 78)
    add(f"范围：{scope['workspaces']}")
    add(f"窗口：{scope['window']}    读了 {t['sessions_scanned']} 个会话 / {fmt(t['bytes'])} 字符（解压后）"
        f"    耗时 {scope['elapsed_s']:.1f}s")
    add(f"口径：步=模型往返；计费=未命中输入 + 缓存命中读取 + 输出；"
        f"加权成本按 缓存×{t['price_cache']} / 输出×{t['price_output']}（**假设**，随读数一起给）")
    add("")
    if not t["steps"]:
        add("不可判定：一个「步」都没解析出来 —— 这不是「消耗为 0」，是**解析不到**（格式漂移 / 扫错目录）。")
        return "\n".join(out)
    add("── 总量 ─────────────────────────────────────────────────────────────")
    add(f"模型往返（步）      {fmt(t['steps'])}")
    add(f"计费 token 合计     {fmt(t['billed'])}")
    add(f"├ 未命中输入（全价） {fmt(t['fresh'])}  ({t['fresh'] / t['billed']:.1%})")
    add(f"├ 缓存命中读取      {fmt(t['cache'])}  ({t['cache'] / t['billed']:.1%})")
    add(f"└ 输出              {fmt(t['out'])}  ({t['out'] / t['billed']:.1%}，其中思维链 {fmt(t['reason'])})")
    add(f"加权成本（同一口径） {fmt(t['weighted'])}   "
        f"＝ 全价输入 {t['weighted_fresh'] / t['weighted']:.1%} + 缓存 {t['weighted_cache'] / t['weighted']:.1%}"
        f" + 输出 {t['weighted_out'] / t['weighted']:.1%}")
    add(f"平均上下文/步        {fmt(t['avg_context'])}       工具调用/步 {t['calls_per_step']:.2f}")
    add(f"每条用户消息         {fmt(t['per_user_msg'])} 计费 token（{fmt(t['user_msgs'])} 条用户消息）")
    if t["malformed"] or t["bad_identity"]:
        add(f"⚠️ 坏行 {fmt(t['malformed'])} 条 / `totalTokens` 恒等式不符 {fmt(t['bad_identity'])} 条（**已计数**，未静默丢弃）")
    add("")
    add(f"── 花费集中度（会话步数 > 100 的部分）───────────────────────────────")
    big = [r for r in report["sessions"] if r["steps"] > 100]
    big_billed = sum(r["fresh"] + r["cache"] + r["out"] for r in big)
    add(f"步数>100 的会话：{len(big)} 个（占 {len(big) / max(t['sessions_with_usage'], 1):.0%}）"
        f"｜吃掉 {fmt(big_billed)} = **{big_billed / t['billed']:.1%}** 的计费 token")
    add(f"会话步数中位数：{statistics.median([r['steps'] for r in report['sessions'] if r['steps']]):.0f} 步")
    add("")
    add(f"── 会话榜（Top {top}，按计费 token）─────────────────────────────────")
    add(f"{'计费token':>15} {'步数':>6} {'最大上下文':>12} {'平均上下文':>12} {'输出':>10} {'工具':>6}  会话")
    for row in sorted(report["sessions"], key=lambda r: -(r["fresh"] + r["cache"] + r["out"]))[:top]:
        billed = row["fresh"] + row["cache"] + row["out"]
        avg = (row["fresh"] + row["cache"]) / row["steps"] if row["steps"] else 0
        add(f"{fmt(billed):>15} {row['steps']:>6} {fmt(row['max_prompt']):>12} {fmt(avg):>12} "
            f"{fmt(row['out']):>10} {row['tool_calls']:>6}  {row['sid'][:26]}  {(row['title'] or '')[:36]}")
    add("")
    add("── 归因 ①：谁花的（子代理是第二份独立上下文）────────────────────────")
    for key, (n, billed, steps) in report["by_depth"]:
        add(f"{key:<20} 会话 {n:>5}  计费 {fmt(billed):>15}  {billed / t['billed']:>6.1%}  步 {fmt(steps)}")
    add("")
    add("── 归因 ②：停顿 vs 全价输入（缓存是否失效）─────────────────────────")
    add(f"{'相邻两步间隔':<12} {'步数':>8} {'平均上下文':>11} {'平均全价输入':>13} {'全价占比':>9} {'占全部全价':>10}")
    total_fresh_in_gaps = sum(b[1] for b in report["gaps"].values()) or 1
    for _, _, name in GAP_BUCKETS:
        n, fresh, prompt = report["gaps"][name]
        if not n:
            continue
        add(f"{name:<12} {n:>8} {fmt(prompt / n):>11} {fmt(fresh / n):>13} "
            f"{fresh / max(prompt, 1):>8.1%} {fresh / total_fresh_in_gaps:>9.1%}")
    add("  ↳ `<30s` 桶的全价输入 ≈ 本步**新增内容**（缓存正常）；间隔更长 ⇒ 历史按全价重算。")
    add("")
    o = report["overhead"]
    add("── 归因 ③：固定开销（每步都要付）────────────────────────────────────")
    add(f"首步 prompt：min {fmt(o['min'])} / p50 {fmt(o['p50'])} / p90 {fmt(o['p90'])} / max {fmt(o['max'])}"
        f"（{o['n']} 个会话）")
    add(f"≈ system prompt + 工具 schema + 技能目录；合计 ≈ p50 × 步数 = **{fmt(o['p50'] * t['steps'])}** token"
        f"（{o['p50'] * t['steps'] / t['billed']:.1%}）")
    add("")
    base = report["base_prompt"] or 1
    add("── 阈值投影：折叠阈值降到 T（反事实上界，不是承诺）───────────────────")
    add(f"{'cap T':>12} {'Σ min(上下文,T)':>18} {'可省':>18} {'降幅':>8}")
    for cap, value in report["caps"]:
        add(f"{fmt(cap):>12} {fmt(value):>18} {fmt(base - value):>18} {(base - value) / base:>7.1%}")
    add("  ↳ 口径：真实折叠后步数可能变化，且每次折叠本身要花一次摘要调用 ⇒ **收益上界**。")
    add("")
    add("── 处置要求 ─────────────────────────────────────────────────────────")
    add(REQUIRED_ACTION)
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    """命令行（每个开关都写清它的口径）。"""
    parser = argparse.ArgumentParser(
        prog="token_ledger.py",
        description="会话 token 账：上下文是计费单位（只读 / 零 LLM / 报告型）",
    )
    parser.add_argument("--sessions", default=os.environ.get("DSH_SESSIONS_ROOT", DEFAULT_SESSIONS_ROOT),
                        help=f"DSH 会话根（默认 {DEFAULT_SESSIONS_ROOT}，可用 DSH_SESSIONS_ROOT 覆盖）")
    parser.add_argument("--cwd", default=".", help="用哪个目录推导工作区（默认当前目录）")
    parser.add_argument("--all-workspaces", action="store_true", help="不按工作区过滤，扫会话根下全部工作区")
    parser.add_argument("--days", type=float, default=14.0, help="只扫最近 N 天写过的会话文件（默认 14；`--all` 忽略）")
    parser.add_argument("--all", action="store_true", help="忽略 --days，扫全部会话（分钟级）")
    parser.add_argument("--top", type=int, default=15, help="会话榜长度（默认 15）")
    parser.add_argument("--jobs", type=int, default=8, help="并行读文件的线程数（默认 8）")
    parser.add_argument("--price-cache", type=float, default=0.1, help="缓存命中读取的单价系数（默认 0.1，**假设**）")
    parser.add_argument("--price-output", type=float, default=3.0, help="输出的单价系数（默认 3.0，**假设**）")
    parser.add_argument("--json", dest="json_path", default=None, help="机读形态写到该路径（唯一写盘点）")
    return parser


def main(argv: list[str] | None = None) -> int:
    """入口：三态退出码（0 报告 / 2 用法 / 3 不可判定）。"""
    args = build_parser().parse_args(argv)
    started = time.time()
    root = Path(os.path.expanduser(args.sessions))
    cwd = Path(args.cwd).resolve()
    workspaces, err = resolve_workspaces(root, cwd, args.all_workspaces)
    if err:
        print(f"不可判定：{err}", file=sys.stderr)
        return EXIT_UNDECIDABLE

    cutoff = None if args.all else time.time() - args.days * 86400
    files: list[Path] = []
    for workspace in workspaces:
        for session_dir in sorted(workspace.iterdir()):
            if not session_dir.is_dir():
                continue
            picked = pick_session_file(session_dir)
            if picked is None:
                continue
            if cutoff is not None and picked.stat().st_mtime < cutoff:
                continue
            files.append(picked)
    if not files:
        print(
            f"不可判定：窗口内一个会话文件都没有（工作区 {[w.name for w in workspaces]}，"
            f"{'全部' if args.all else f'最近 {args.days:g} 天'}）—— 换 `--days` / `--all` 再跑。",
            file=sys.stderr,
        )
        return EXIT_UNDECIDABLE

    rows, errors = collect(files, CAP_LADDER, args.jobs)
    for message in errors:
        print(f"⚠️ 读不出来（已计入 errors，未静默丢弃）：{message}", file=sys.stderr)
    if not any(row["steps"] for row in rows):
        print(
            f"不可判定：{len(files)} 个会话文件里解析不出任何一步（坏行或格式漂移）—— "
            "这不是「消耗为 0」。",
            file=sys.stderr,
        )
        return EXIT_UNDECIDABLE

    report = summarize(rows, CAP_LADDER, args.price_cache, args.price_output)
    scope = {
        "workspaces": "、".join(str(w) for w in workspaces),
        "window": "全部会话" if args.all else f"最近 {args.days:g} 天",
        "elapsed_s": time.time() - started,
        "errors": errors,
    }
    print(render(report, scope, args.top))
    if args.json_path:
        payload = {
            "scope": {**scope, "workspaces": [str(w) for w in workspaces]},
            "totals": report["totals"],
            "by_day": report["by_day"],
            "by_depth": report["by_depth"],
            "gaps": report["gaps"],
            "caps": report["caps"],
            "overhead": report["overhead"],
            "sessions": [
                {k: v for k, v in row.items() if k != "gaps"} for row in report["sessions"]
            ],
        }
        Path(args.json_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n（机读形态已写到 {args.json_path}）")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
