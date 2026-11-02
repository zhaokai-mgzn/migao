#!/usr/bin/env python3
"""distill_agent_sessions — 从黄金策（B 端 `mibao`）会话里离线抽取「口径候选」（issue #8175 P1a）。

## 为什么需要它

现成的 `KnowledgeDistillService` 读的是 `agent_sessions`（**人工客服**会话），而黄金策的 AI 会话
在 `sessions` / `session_messages`（`agent_type = 'mibao'`）—— **结构上不在蒸馏面内**。
P1a 先**不接线**：用一个人工导出的小样本，验证「能不能从 B 端会话里抽出值得记的口径」，
零运行时风险；候选落库 / 运行时触发留给 P1b。

## 边界（本脚本的全部承诺）

- **纯标准库**；**不联网**；**不调 LLM**；**不连库**；**默认只读**（不给 `--out` 就一个字节都不写）；
- `--write` 是**显式拒绝**：落库属 P1b，未实现 —— 防止有人误以为跑这条命令就能落库；
- 抽取是**确定性**的：同一输入连跑两次，输出 JSON 逐字节相同；
- `context_before` 是**截断**的上一轮 assistant 原文（≤120 字），**不是** LLM 摘要 —— 本脚本没有模型。

## 输入

`--in <目录 | .json | .jsonl>`。每个会话形如：

    {"tenant_id": 1, "session_id": "s1", "agent_type": "mibao",
     "messages": [{"role": "user", "content": "..."},
                  {"role": "assistant", "content": "..."}]}

- 目录：递归读取 `*.json` / `*.jsonl`（按相对路径排序；其它扩展名忽略）；
- `.jsonl`：一行一个会话对象；`.json`：单个会话对象、对象列表、或 `{"sessions": [...]}`；
- 真实数据由人从 DB 导出；**本脚本不连库、不猜租户** —— 缺 `tenant_id` 的会话整段跳过（fail-closed）。

## 抽取规则（只看 user 消息；一条消息至多一条候选）

| category | 触发关键词（正则） |
|---|---|
| 纠正 | `不对`（排除「对不起」）/ `不是这样` / `错了` / `应该是` / `不是`（排除「是不是」） |
| 口径 | `我们按` / `我们家` / `记住` / `以后都` / `统一按` / `一律` |
| 例外 | `除非` / `特殊情况` / `如果…就` |

一条消息同时命中多类时按 **纠正 > 口径 > 例外** 取 `category`，其余命中写进 `reason`。
`confidence` 是**启发式排序分**（0.6~0.95），**不是概率**；`reason` 给出命中词，便于人工复核。

## 过滤

- `agent_type != "mibao"` ⇒ 整段跳过（C 端会话不抽）；
- 空会话 / 全空消息 ⇒ 跳过；缺 `tenant_id` / `session_id` ⇒ 跳过（绝不猜租户）；
- 单条消息超过 500 字 ⇒ 截断后再抽；
- **PII 拦截**：手机号 / 身份证号 / 邮箱 / 详细地址命中 ⇒ **该条不抽**并计入 `pii_skipped`。

## 输出

不给 `--out`：只在 stdout 打印统计（会话数 / 按原因跳过数 / 候选数），不写任何文件。
给 `--out <file.json>`：写出 `{"schema_version", "phase", "input", "stats", "candidates"}`。

## 退出码

- `0` = 正常（0 条候选也是正常结果）；
- `2` = 用法 / 输入错误（读不到、JSON 坏、`--out` 写不出）；
- `--write` ⇒ `SystemExit`（非零 + 文案说明写库是 P1b）。

## 用法（仓根）

    python3 scripts/distill_agent_sessions.py --in export/            # 只打印摘要
    python3 scripts/distill_agent_sessions.py --in export/ --out candidates.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2

#: 单条消息的抽取长度上限（超出截断；PII 扫描在截断**之前**做，避免漏掉尾部的隐私串）。
MESSAGE_CHAR_LIMIT = 500

#: `context_before` 长度上限（截断原文，不是摘要）。
CONTEXT_CHAR_LIMIT = 120

#: 分类优先级：一条消息至多一条候选。纠正信号最强（说明上一轮答错了）。
CATEGORY_ORDER = ("纠正", "口径", "例外")

#: 启发式排序分（不是概率；越靠前的类别越高，多类命中略加分）。
BASE_CONFIDENCE = {"纠正": 0.8, "口径": 0.7, "例外": 0.6}

#: 抽取规则。每条 = (category, label, compiled regex)。label 只用于 `reason` 的可读输出。
RULES = (
    ("纠正", "不对", re.compile(r"不对(?!起)")),
    ("纠正", "不是这样", re.compile(r"(?<!是)不是这样")),
    ("纠正", "错了", re.compile(r"错了")),
    ("纠正", "应该是", re.compile(r"应该是")),
    ("纠正", "不是", re.compile(r"(?<!是)不是(?!这样)")),
    ("口径", "我们按", re.compile(r"我们按")),
    ("口径", "我们家", re.compile(r"我们家")),
    ("口径", "记住", re.compile(r"记住")),
    ("口径", "以后都", re.compile(r"以后都")),
    ("口径", "统一按", re.compile(r"统一按")),
    ("口径", "一律", re.compile(r"一律")),
    ("例外", "除非", re.compile(r"除非")),
    ("例外", "特殊情况", re.compile(r"特殊情况")),
    ("例外", "如果…就", re.compile(r"如果[^。！？\n]{0,40}?就")),
)

#: PII 形态（顺序即命中优先级；身份证在手机号之前，避免 18 位号被误当 11 位手机号）。
PII_RULES = (
    ("身份证号", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("邮箱", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    (
        "详细地址",
        re.compile(
            r"(?:[\u4e00-\u9fa5]{2,8}(?:省|市|区|县|镇|街道|乡))"
            r"[^\n，。；;]{0,24}?(?:\d+号(?:楼|院)?|\d+栋|\d+幢|\d+单元|\d+室|\d+楼)"
        ),
    ),
    (
        "详细地址",
        re.compile(
            r"(?:[\u4e00-\u9fa5]{2,10}(?:小区|花园|大厦|广场|公寓|工业园|产业园))"
            r"[^\n，。；;]{0,12}?(?:\d+号(?:楼|院)?|\d+栋|\d+幢|\d+单元|\d+室|\d+楼)"
        ),
    ),
)

#: 跳过原因（固定顺序 ⇒ 统计 JSON 稳定、可逐字节复算）。
SKIP_REASONS = (
    "agent_type_not_mibao",
    "empty_session",
    "missing_tenant_id",
    "missing_session_id",
    "invalid_record",
)

#: 一句之内的边界（用于 `trigger_text` 截取；逗号**不**截，否则「不对，我们按整卷算」会丢触发词）。
_SENTENCE_ENDS = "。！？；;!\n"


def _normalize(text: str) -> str:
    """折叠空白；确定性、不改标点（触发词/地址形态都依赖原文标点）。"""
    return re.sub(r"\s+", " ", text).strip()


def _pii_hit(text: str) -> "str | None":
    """→ 命中的 PII 类别名；未命中 → None。"""
    for label, pattern in PII_RULES:
        if pattern.search(text):
            return label
    return None


def _category_hits(text: str) -> "list[tuple[str, str, re.Match[str]]]":
    """→ 按优先级去重后的命中列表 `[(category, label, match), ...]`（每类至多一条）。"""
    hits: "list[tuple[str, str, re.Match[str]]]" = []
    seen: set[str] = set()
    for category in CATEGORY_ORDER:
        for rule_category, label, pattern in RULES:
            if rule_category != category or category in seen:
                continue
            match = pattern.search(text)
            if match is not None:
                hits.append((category, label, match))
                seen.add(category)
    return hits


def _snippet(text: str, match: "re.Match[str]") -> str:
    """取命中词所在的整句（≤120 字），保留触发词本身。"""
    left = 0
    for sep in _SENTENCE_ENDS:
        pos = text.rfind(sep, 0, match.start())
        left = max(left, pos + 1)
    right = len(text)
    for sep in _SENTENCE_ENDS:
        pos = text.find(sep, match.end())
        if pos != -1:
            right = min(right, pos)
    snippet = text[left:right].strip()
    return (snippet or text)[:CONTEXT_CHAR_LIMIT]


def _context_before(messages: "list[dict]", index: int) -> str:
    """上一轮 assistant 原文（最近的、位于该 user 消息之前的那条），截断到 ≤120 字。"""
    for pos in range(index - 1, -1, -1):
        message = messages[pos]
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            return ""
        return _normalize(content)[:CONTEXT_CHAR_LIMIT]
    return ""


def _iter_file_records(path: Path) -> "list[dict]":
    """读一个输入文件 → 会话对象列表（坏 JSON fail-closed，具名报错）。"""
    if path.suffix.lower() == ".jsonl":
        records = []
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    records.append(json.loads(stripped))
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"输入 JSON 解析失败: {path}:{line_no}: {exc}")
        return records
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"输入 JSON 解析失败: {path}: {exc}")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        sessions = data.get("sessions")
        if isinstance(sessions, list):
            return sessions
        return [data]
    raise SystemExit(f"输入 JSON 顶层既不是对象也不是数组: {path}")


def _input_files(input_path: Path) -> "list[Path]":
    if input_path.is_dir():
        return sorted(
            (p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() in (".json", ".jsonl")),
            key=lambda p: p.as_posix(),
        )
    if input_path.is_file():
        if input_path.suffix.lower() not in (".json", ".jsonl"):
            raise SystemExit(f"--in 只接受目录 / .json / .jsonl: {input_path}")
        return [input_path]
    raise SystemExit(f"--in 不存在: {input_path}")


def distill(sessions: "list[dict]") -> "dict":
    """纯函数：会话对象列表 → `{"stats": ..., "candidates": ...}`（无 I/O、无时间、无随机）。"""
    stats = {
        "sessions_read": 0,
        "sessions_distilled": 0,
        "sessions_skipped": {reason: 0 for reason in SKIP_REASONS},
        "messages_scanned": 0,
        "pii_skipped": 0,
        "truncated_messages": 0,
        "candidates": 0,
    }
    candidates: "list[dict]" = []

    for record in sessions:
        stats["sessions_read"] += 1
        if not isinstance(record, dict):
            stats["sessions_skipped"]["invalid_record"] += 1
            continue

        tenant_id = record.get("tenant_id")
        if tenant_id is None or str(tenant_id).strip() == "":
            stats["sessions_skipped"]["missing_tenant_id"] += 1
            continue
        session_id = record.get("session_id")
        if session_id is None or str(session_id).strip() == "":
            stats["sessions_skipped"]["missing_session_id"] += 1
            continue

        agent_type = str(record.get("agent_type") or "").strip().lower()
        if agent_type != "mibao":
            stats["sessions_skipped"]["agent_type_not_mibao"] += 1
            continue

        messages = record.get("messages")
        if not isinstance(messages, list) or not messages:
            stats["sessions_skipped"]["empty_session"] += 1
            continue
        if not any(isinstance(m, dict) and isinstance(m.get("content"), str) and m["content"].strip()
                   for m in messages):
            stats["sessions_skipped"]["empty_session"] += 1
            continue

        stats["sessions_distilled"] += 1
        user_turn = 0
        for index, message in enumerate(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            user_turn += 1
            content = message.get("content")
            if not isinstance(content, str):
                continue
            stats["messages_scanned"] += 1
            text = _normalize(content)
            if not text:
                continue

            # PII 在截断**之前**扫（尾部的隐私串不能被 500 字上限藏掉）。
            pii_label = _pii_hit(text)
            if pii_label is not None:
                stats["pii_skipped"] += 1
                continue

            if len(text) > MESSAGE_CHAR_LIMIT:
                text = text[:MESSAGE_CHAR_LIMIT]
                stats["truncated_messages"] += 1

            hits = _category_hits(text)
            if not hits:
                continue

            primary_category, primary_label, match = hits[0]
            reason = f"命中{primary_category}规则「{primary_label}」"
            if len(hits) > 1:
                extras = "、".join(f"{category}「{label}」" for category, label, _ in hits[1:])
                reason += f"；同时命中{extras}"

            confidence = BASE_CONFIDENCE[primary_category]
            if len(hits) > 1:
                confidence += 0.05 * (len(hits) - 1)
            candidates.append(
                {
                    "tenant_id": tenant_id,
                    "session_id": session_id,
                    "turn": user_turn,
                    "category": primary_category,
                    "trigger_text": _snippet(text, match),
                    "context_before": _context_before(messages, index),
                    "confidence": round(min(confidence, 0.95), 2),
                    "reason": reason,
                }
            )
            stats["candidates"] += 1

    return {"stats": stats, "candidates": candidates}


def _render_summary(input_path: str, result: dict, out_path: "str | None") -> str:
    stats = result["stats"]
    skipped = stats["sessions_skipped"]
    skipped_text = ", ".join(f"{reason}={count}" for reason, count in skipped.items() if count)
    by_category = {category: 0 for category in CATEGORY_ORDER}
    for candidate in result["candidates"]:
        by_category[candidate["category"]] += 1
    lines = [
        f"distill_agent_sessions: input={input_path}",
        f"会话: 读取 {stats['sessions_read']} / 进入抽取 {stats['sessions_distilled']}"
        f" / 跳过 {sum(skipped.values())}"
        + (f"（{skipped_text}）" if skipped_text else ""),
        f"消息: 扫描 {stats['messages_scanned']} / PII 拦截 {stats['pii_skipped']}"
        f" / 截断 {stats['truncated_messages']}",
        f"候选: {stats['candidates']}（"
        + " / ".join(f"{category} {by_category[category]}" for category in CATEGORY_ORDER)
        + "）",
        f"输出: {out_path}" if out_path else "输出: 未写文件（未给 --out；本脚本默认只读）",
    ]
    return "\n".join(lines)


def _reject_write() -> None:
    raise SystemExit(
        "拒绝 --write：本脚本是 issue #8175 P1a 的离线只读验证，不写任何库。"
        "候选落库 / 运行时触发属 P1b，尚未实现；请用 --out 输出 JSON 供人工复核。"
    )


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="从 B 端 mibao 会话离线抽取纠正 / 口径 / 例外候选（只读，不调 LLM）。",
    )
    parser.add_argument("--in", dest="input_path", required=True,
                        help="输入目录或 .json/.jsonl 文件")
    parser.add_argument("--out", dest="out_path", default=None,
                        help="候选 JSON 输出路径；不给则只打印摘要、不写任何文件")
    parser.add_argument("--write", action="store_true",
                        help="保留参数位：显式拒绝（落库属 P1b）")
    args = parser.parse_args(argv)

    if args.write:
        _reject_write()

    input_path = Path(args.input_path)
    sessions: "list[dict]" = []
    files = _input_files(input_path)
    for path in files:
        sessions.extend(_iter_file_records(path))

    result = distill(sessions)
    payload = {
        "schema_version": 1,
        "phase": "P1a-offline",
        "issue": 8175,
        "input": args.input_path,
        "stats": result["stats"],
        "candidates": result["candidates"],
    }

    summary = _render_summary(args.input_path, result, args.out_path)
    print(summary)

    if args.out_path:
        rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        try:
            with open(args.out_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(rendered)
        except OSError as exc:
            raise SystemExit(f"无法写出 --out {args.out_path}: {exc}")

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
