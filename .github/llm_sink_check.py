#!/usr/bin/env python3
"""LLM 红例 → 确定性下沉台账的机械检查（用户裁定 4′，issue #4034 ← #4009）。

═══════════════════════════════════════════════════════════════════════════════
用法（三条命令）
═══════════════════════════════════════════════════════════════════════════════

    # ① 台账自检（离线、确定性、不联网）—— CI / L0 单测走这条
    python3 .github/llm_sink_check.py --selftest
        0 = 台账完备：schema 合法 + 每条 sunk 的断言都**非空壳** + 每条 unsunk 都显式登记
        1 = 有违规（逐条打印 issue 号 + 违规码 + 原因）

    # ② 单条问答：「issue N 这条 LLM 红例有确定性断言了吗？」
    python3 .github/llm_sink_check.py --issue 3955
        0 = 已下沉，且断言非空、回填链完整（用例 merge_log 含 #N）
        1 = 未登记 / 未下沉 / 断言空壳 / 回填缺失
        3 = 无法判定 —— 需要 `gh` 才能核的东西核不了，**不谎报通过**
            （`--check-backfill` 会真的去 GitHub 核「发现它的 issue 上有没有回填记录」）

    # ③ 全量盘点：把所有 LLM 来源的 open issue 与台账对一遍
    python3 .github/llm_sink_check.py --all
        0 = 每个 open 的 LLM 来源 issue 都在台账里有条目
        1 = 存在**未登记**的 open LLM 红例（= 静默通过，正是裁定要禁的形态）
        3 = `gh` 不可用/未登录 ⇒ 看不了 ⇒ 不把「看不了」当「全清」

    加 `--json` 输出机读结果（供 agent / CI 消费）；加 `--check-backfill` 让 ② 额外
    去 GitHub 核「发现它的 issue 上有没有回填记录」（需网络）。

═══════════════════════════════════════════════════════════════════════════════
判据（口径一律取自既有单一源，不在这里另写一份）
═══════════════════════════════════════════════════════════════════════════════

* **效果层断言集合** = `.github/assertion_taxonomy.py` 的 `EFFECT_FIELDS`
  （`must_succeed` / `db_verify` / `output_verify` / `amount_verify` / `post_session`），
  可失败性判据 = 同模块的 `has_effect_assertion`。本脚本**直接 import 这两个符号**，
  绝不自己再列一份（两份清单必然漂移 ⇒ 静态放行 / 动态判红，门禁可信度归零）。
  该纪律由 L0 测试以**对象同一性**锁定（`llm_sink_check.EFFECT_FIELDS is tax.EFFECT_FIELDS`）。
* **用例库** = `.github/cases/*.yml`，经 `render_cases.load_case_dicts` 读取
  （零第三方依赖的 `yaml_light` loader，与渲染器 / 覆盖体检共用同一入口）。

`sunk` 条目逐项核（任一不过 ⇒ 退出 1）：

| 形态 | 判据 |
|---|---|
| `case_assertion` | 用例存在；声明的 `fields` ⊆ `EFFECT_FIELDS`；其中**至少一个字段非空**；`has_effect_assertion(case)` 为真；`merge_log` 含 `#<issue>`（「记入用例库 + 回填」链） |
| `l0_invariant` | `test_file` 存在；每个 `test_names` 在该文件里有字面 `def <name>(`；其 `cases` 的 `merge_log` 含 `#<issue>` |

`unsunk` 条目逐项核：`reason` 非空 **且** `follow_up` 是正整数 —— 未下沉必须**显式登记**，
不允许「停在半路」当成没事（裁定 4′ 原话：未下沉必须显式登记，不得静默通过）。

═══════════════════════════════════════════════════════════════════════════════
明确**未**机械化的部分（详见 `.github/llm-finding-ledger.json` 的 `unimplemented`）
═══════════════════════════════════════════════════════════════════════════════

1. **新红例的自动入账没有做**：本脚本只能检查「台账里已有的条目」，无法把一条新发现的
   LLM 红例自动写进台账 —— 入账仍需人或 agent 动手（`--all` 只能在 `gh` 可用时**发现缺失**）。
2. **GitHub issue 侧的回填核验依赖 `gh`/网络**，且**未接入 CI required check**：
   `--selftest`（离线那档）核的是**用例库侧**回填（`merge_log` 含 `#<issue>`）；
   GitHub 侧回填要走 `--check-backfill`/`--all`，`gh` 不可用时**返回 3（无法判定）**。
3. `[行为映射门禁] 规则命中用例失败` 这一族 issue 也是 LLM 来源，但**默认不在 `--all`
   的枚举范围内**（默认只认下面 4 条标题族）⇒ `--all` 的「全清」对那一族**不成立**。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# ── 路径：一律相对**仓库根**（由 __file__ 推），绝不用 CWD ─────────────────────
# 这样脚本既能在仓库根跑，也能在 worktree 根（或任何别处）跑：
#   <repo>/.github/llm_sink_check.py → GITHUB_DIR = <repo>/.github, REPO_ROOT = <repo>
GITHUB_DIR = Path(__file__).resolve().parent
REPO_ROOT = GITHUB_DIR.parent
CASES_DIR = GITHUB_DIR / "cases"
LEDGER_PATH = GITHUB_DIR / "llm-finding-ledger.json"

for _p in (str(GITHUB_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 单一判据源（**不要**在这里重新列举效果层字段）
from assertion_taxonomy import EFFECT_FIELDS, has_effect_assertion  # noqa: E402
from render_cases import load_case_dicts  # noqa: E402

# ── LLM 来源 issue 的标题族（真值 = 各 workflow 里建 issue 的 title 模板）─────
# 锚点（按文本检索，行号会漂移）：
#   .github/workflows/post-deploy-eval.yml      → `[Post-Deploy] 部署后回归失败 — `
#   .github/workflows/xiaobu-acceptance.yml     → `[Xiaobu] ${personaLabel} 验收失败 — `
#   .github/workflows/agent-eval.yml            → `[Agent Eval] 米宝冒烟评测失败 — `
#   .github/workflows/agent-eval-adversarial.yml→ `[Agent Eval] 米宝对抗评测失败 — `
#
# ⚠️ 为什么搜索之后还要**本地正则复核**：GitHub 的 `in:title` 是**分词模糊匹配**，不是
#    子串匹配 —— 实测 `in:title "[Post-Deploy]"` 会命中 #3778（标题里只有
#    `post-deploy-eval` 这个词，并不是这一族）。不复核就会把非本族 issue 判成「未登记」。
LLM_ISSUE_TITLE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("[Post-Deploy]", r"^\[Post-Deploy\]\s*部署后回归失败"),
    ("[Xiaobu]", r"^\[Xiaobu\]\s*.*验收失败"),
    ("[Agent Eval]", r"^\[Agent Eval\]\s*米宝冒烟评测失败"),
    ("[Agent Eval]", r"^\[Agent Eval\]\s*米宝对抗评测失败"),
)

# GitHub 侧回填的**机读标记**：发现红例的 issue 上应留有指向本台账的回填记录。
# 认可三种写法（任一命中即算回填）：机读标记 / 台账文件名 / 「下沉台账」字样。
#   <!-- llm-sink-backfill: #4014 sunk=OR-009,OR-010,OR-011 -->
BACKFILL_MARKER_RE = re.compile(r"llm-sink-backfill|llm-finding-ledger\.json|下沉台账")

VALID_STATUSES = ("sunk", "unsunk")
SINK_KINDS = ("case_assertion", "l0_invariant")

EXIT_OK = 0          # 已下沉且断言非空 / 台账完备 / 全量盘点无缺失
EXIT_VIOLATION = 1   # 未登记 / 断言空壳 / 回填缺失 / 存在未登记的 open LLM 红例
EXIT_UNKNOWN = 3     # 无法判定（同 .github/scripts/eval_slot_status.sh 的 0/2/3 约定）


# ══════════════════════════════════════════════════════════════════════════════
# 一、违规与条目判据（纯函数，可被 L0 测试直接注入夹具 —— 红证靠它们）
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Violation:
    """一条违规：`entry` 是定位键（`#4014` / `(schema)`），`code` 是机读码。"""
    entry: str
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.entry} [{self.code}] {self.detail}"

    def as_dict(self) -> dict:
        return {"entry": self.entry, "code": self.code, "detail": self.detail}


def _nonempty(value: object) -> bool:
    """值是否**非空**（空壳判据：空列表 / 空串 / 空 dict / 全空元素都算空）。

    为什么不用 `bool(value)`：`must_succeed: [{}]` 的 `bool` 为真（列表非空），
    但它**没有任何断言内容** —— 正是「断言空壳」要拦的形态。
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_nonempty(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_nonempty(v) for v in value)
    return True  # 数字 / 布尔等标量按「有值」处理


def _positive_int(value: object) -> bool:
    # 注意：`isinstance(True, int)` 为真，故显式排掉布尔。
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _mentions_issue(text: object, issue: int) -> bool:
    """文本里是否**回填**了该 issue（`#4014`）—— 用负向先行断言挡住 `#40140`。"""
    if not isinstance(text, str):
        return False
    return re.search(rf"#{issue}(?![0-9])", text) is not None


def check_case_assertion_sink(issue: int, sink: dict, cases_by_id: dict) -> list[Violation]:
    """`case_assertion` 型下沉：用例存在 + 声明的字段真非空 + 效果层判据为真 + 回填链在。"""
    out: list[Violation] = []
    key = f"#{issue}"
    ids = sink.get("cases")
    fields = sink.get("fields")
    if not isinstance(ids, list) or not ids:
        return [Violation(key, "SINK-CASE-LIST-EMPTY",
                          "sink.cases 必须是非空列表（没有用例 ID 就无法核「断言非空」）")]
    if not isinstance(fields, list) or not fields:
        return [Violation(key, "SINK-FIELD-LIST-EMPTY",
                          "sink.fields 必须是非空列表（没声明核哪个字段 = 无从核起）")]
    for field in fields:
        if field not in EFFECT_FIELDS:
            out.append(Violation(
                key, "SINK-FIELD-NOT-EFFECT",
                f"声明的字段 `{field}` 不在 EFFECT_FIELDS={list(EFFECT_FIELDS)} 里 —— "
                "「调用了 ≠ 成了」，非效果层字段（如 expectations/required_args）不构成下沉"))
    for cid in ids:
        case = cases_by_id.get(cid)
        if case is None:
            out.append(Violation(key, "SINK-CASE-MISSING",
                                 f"用例 `{cid}` 在 .github/cases/*.yml 里不存在"))
            continue
        if not any(_nonempty(case.get(f)) for f in fields):
            out.append(Violation(
                key, "SINK-CASE-FIELD-EMPTY",
                f"用例 `{cid}` 的 {list(fields)} 全为空壳（未声明 / 空列表 / 空 dict）"
                "—— 这就是「断言空壳」"))
        if not has_effect_assertion(case):
            out.append(Violation(
                key, "SINK-CASE-NO-EFFECT-ASSERTION",
                f"用例 `{cid}` 过不了 assertion_taxonomy.has_effect_assertion"
                "（无效果层断言）"))
        if not _mentions_issue(case.get("merge_log"), issue):
            out.append(Violation(
                key, "SINK-CASE-NO-BACKFILL",
                f"用例 `{cid}` 的 merge_log 未回填 `#{issue}`"
                "（「记入用例库 + 回填发现它的 issue」链断了）"))
    return out


def check_l0_invariant_sink(issue: int, sink: dict, cases_by_id: dict,
                            repo_root: Path = REPO_ROOT) -> list[Violation]:
    """`l0_invariant` 型下沉：测试文件在 + 测试函数名真的存在 + 回填链在。"""
    out: list[Violation] = []
    key = f"#{issue}"
    rel = sink.get("test_file")
    names = sink.get("test_names")
    ids = sink.get("cases")
    if not isinstance(rel, str) or not rel.strip():
        return [Violation(key, "SINK-TEST-FILE-EMPTY", "l0_invariant 缺 test_file")]
    if not isinstance(names, list) or not names:
        return [Violation(key, "SINK-TEST-NAME-LIST-EMPTY",
                          "l0_invariant 的 test_names 必须是非空列表"
                          "（不点名到具体测试函数 = 无从核「断言真的存在」）")]
    if not isinstance(ids, list) or not ids:
        return [Violation(key, "SINK-CASE-LIST-EMPTY",
                          "l0_invariant 的 cases 必须是非空列表（下沉要能追回它的来源用例）")]
    path = repo_root / rel
    if not path.is_file():
        out.append(Violation(key, "SINK-TEST-FILE-MISSING", f"测试文件不存在：{rel}"))
        return out
    text = path.read_text(encoding="utf-8")
    for name in names:
        # 字面 `def <name>(` —— 有 `def ` 前缀才不会把调用点（`await test_x(`）误判成定义。
        if not re.search(rf"def {re.escape(str(name))}\(", text):
            out.append(Violation(key, "SINK-TEST-NAME-MISSING",
                                 f"{rel} 里没有字面 `def {name}(`"))
    for cid in ids:
        case = cases_by_id.get(cid)
        if case is None:
            out.append(Violation(key, "SINK-CASE-MISSING",
                                 f"用例 `{cid}` 在 .github/cases/*.yml 里不存在"))
            continue
        if not _mentions_issue(case.get("merge_log"), issue):
            out.append(Violation(key, "SINK-CASE-NO-BACKFILL",
                                 f"用例 `{cid}` 的 merge_log 未回填 `#{issue}`"))
    return out


def check_entry(entry: dict, cases_by_id: dict, repo_root: Path = REPO_ROOT) -> list[Violation]:
    """核一条台账条目（sunk 逐 sink 核；unsunk 核显式登记）。"""
    if not isinstance(entry, dict):
        return [Violation("(entry)", "ENTRY-NOT-OBJECT", f"条目不是对象：{entry!r}")]
    issue = entry.get("issue")
    if not _positive_int(issue):
        return [Violation(str(entry.get("issue")), "ENTRY-ISSUE-INVALID",
                          f"issue 必须是正整数，实得 {issue!r}")]
    key = f"#{issue}"
    status = entry.get("status")
    out: list[Violation] = []

    if status == "unsunk":
        jump = entry.get("follow_up")
        if not _nonempty(entry.get("reason")):
            out.append(Violation(key, "UNSUNK-NO-REASON",
                                 "unsunk 必须写明 reason（未下沉要**显式登记**，不许停在半路）"))
        if not _positive_int(jump):
            out.append(Violation(key, "UNSUNK-NO-FOLLOWUP",
                                 f"unsunk 的 follow_up 必须是正整数（跟踪单号），实得 {jump!r}"))
        return out

    if status != "sunk":
        return [Violation(key, "ENTRY-STATUS-INVALID",
                          f"status 必须是 {list(VALID_STATUSES)} 之一，实得 {status!r}")]

    if not _nonempty(entry.get("evidence")):
        out.append(Violation(key, "SUNK-NO-EVIDENCE",
                             "sunk 条目必须写明 evidence（凭什么说它下沉了）"))
    sinks = entry.get("sinks")
    if not isinstance(sinks, list) or not sinks:
        out.append(Violation(key, "SUNK-NO-SINKS",
                             "sunk 条目必须给 ≥1 条 sinks（裁定 4′：≥1 条确定性断言）"))
        return out
    for sink in sinks:
        if not isinstance(sink, dict):
            out.append(Violation(key, "SINK-NOT-OBJECT", f"sink 不是对象：{sink!r}"))
            continue
        kind = sink.get("kind")
        if kind == "case_assertion":
            out.extend(check_case_assertion_sink(issue, sink, cases_by_id))
        elif kind == "l0_invariant":
            out.extend(check_l0_invariant_sink(issue, sink, cases_by_id, repo_root))
        else:
            out.append(Violation(key, "SINK-UNKNOWN-KIND",
                                 f"kind 必须是 {list(SINK_KINDS)} 之一，实得 {kind!r}"))
    return out


def check_ledger_schema(ledger: dict) -> list[Violation]:
    """台账骨架：version / note / entries / unimplemented。"""
    if not isinstance(ledger, dict):
        return [Violation("(schema)", "LEDGER-NOT-OBJECT", "台账根必须是 JSON 对象")]
    out: list[Violation] = []
    if ledger.get("version") != 1:
        out.append(Violation("(schema)", "LEDGER-VERSION",
                             f"version 必须为 1，实得 {ledger.get('version')!r}"))
    if not _nonempty(ledger.get("note")):
        out.append(Violation("(schema)", "LEDGER-NO-NOTE", "note 不得为空（台账要自解释）"))
    entries = ledger.get("entries")
    if not isinstance(entries, list) or not entries:
        out.append(Violation("(schema)", "LEDGER-NO-ENTRIES", "entries 必须是非空列表"))
        entries = []
    seen: set[int] = set()
    for entry in entries:
        num = entry.get("issue") if isinstance(entry, dict) else None
        if _positive_int(num):
            if num in seen:
                out.append(Violation(f"#{num}", "LEDGER-DUP-ENTRY", "同一 issue 重复登记"))
            seen.add(num)
    unimpl = ledger.get("unimplemented")
    if not isinstance(unimpl, list) or not [_x for _x in unimpl if _nonempty(_x)]:
        out.append(Violation(
            "(schema)", "LEDGER-NO-UNIMPLEMENTED",
            "unimplemented 必须非空 —— 未机械化的部分要**如实登记**，"
            "不得写成恒真判据凑数"))
    return out


def validate_ledger(ledger: dict, cases_by_id: dict,
                    repo_root: Path = REPO_ROOT) -> list[Violation]:
    """全台账：schema + 每条条目。返回违规列表（空 = 完备）。"""
    violations = check_ledger_schema(ledger)
    entries = ledger.get("entries") if isinstance(ledger, dict) else None
    for entry in (entries or []):
        violations.extend(check_entry(entry, cases_by_id, repo_root))
    return violations


# ══════════════════════════════════════════════════════════════════════════════
# 二、加载（用例库 / 台账）
# ══════════════════════════════════════════════════════════════════════════════

def load_case_index(cases_dir: Path = CASES_DIR) -> dict:
    """`{case_id: case_dict}` —— 复用 render_cases.load_case_dicts（零第三方依赖）。"""
    cases = load_case_dicts(str(cases_dir))
    return {c["id"]: c for c in cases if c.get("id")}


def load_ledger(path: Path = LEDGER_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def entry_for(ledger: dict, issue: int) -> dict | None:
    for entry in (ledger.get("entries") or []):
        if isinstance(entry, dict) and entry.get("issue") == issue:
            return entry
    return None


def describe_entry(entry: dict) -> str:
    """一行摘要（给 --selftest 打）—— 不带状态图标，图标由调用方按核验结果加。"""
    issue = entry.get("issue")
    status = entry.get("status")
    if status == "sunk":
        bits = []
        for sink in (entry.get("sinks") or []):
            if not isinstance(sink, dict):
                continue
            if sink.get("kind") == "case_assertion":
                bits.append(f"{'+'.join(sink.get('fields') or [])}@"
                            f"{','.join(sink.get('cases') or [])}")
            elif sink.get("kind") == "l0_invariant":
                bits.append(f"L0:{sink.get('test_file')}"
                            f"({','.join(sink.get('test_names') or [])})")
        return f"#{issue} sunk ← {'; '.join(bits)}"
    return (f"#{issue} unsunk（显式登记）reason={entry.get('reason')!r} "
            f"follow_up=#{entry.get('follow_up')}")


# ══════════════════════════════════════════════════════════════════════════════
# 三、GitHub 侧（唯一需要网络的格子；不可用 ⇒ 3，绝不谎报）
# ══════════════════════════════════════════════════════════════════════════════

def _run_gh(args: list[str]) -> tuple[bool, str]:
    """跑一条 gh 命令 → (ok, stdout | 错误说明)。"""
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return False, "gh 未安装（PATH 里找不到 gh）"
    except OSError as exc:  # 权限 / 环境异常
        return False, f"gh 无法执行：{exc}"
    except subprocess.TimeoutExpired:
        return False, "gh 超时（60s）"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()[:400] or f"gh 退出码 {proc.returncode}"
    return True, proc.stdout


# 可注入：L0 测试用假 runner 造「gh 不可用 ⇒ 3」的红证。
GH_RUNNER = _run_gh


def enumerate_llm_issues() -> tuple[bool, list[dict], str]:
    """枚举 open 的 LLM 来源 issue → (ok, [{'number','title'}], 错误说明)。"""
    seen: dict[int, dict] = {}
    terms = list(dict.fromkeys(term for term, _pat in LLM_ISSUE_TITLE_PATTERNS))
    for term in terms:
        ok, raw = GH_RUNNER(["issue", "list", "--state", "open", "--limit", "200",
                             "--search", f'in:title "{term}"',
                             "--json", "number,title"])
        if not ok:
            return False, [], f"`gh issue list`（搜索 {term}）失败：{raw}"
        try:
            rows = json.loads(raw)
        except json.JSONDecodeError:
            return False, [], f"`gh issue list` 返回的不是 JSON：{raw[:200]}"
        if not isinstance(rows, list):
            return False, [], f"`gh issue list` 返回的不是数组：{raw[:200]}"
        for row in rows:
            title = str(row.get("title") or "")
            # 本地正则复核（GitHub 的 in:title 是分词模糊匹配，会带进无关 issue）
            if any(re.search(pat, title) for _term, pat in LLM_ISSUE_TITLE_PATTERNS):
                seen[int(row["number"])] = {"number": int(row["number"]), "title": title}
    return True, sorted(seen.values(), key=lambda r: r["number"]), ""


def issue_backfill_state(issue: int) -> tuple[bool, bool, str]:
    """GitHub 侧回填核验 → (ok, 已回填, 说明)。ok=False ⇒ 调用方必须给退出码 3。"""
    ok, raw = GH_RUNNER(["issue", "view", str(issue), "--json", "title,state,comments"])
    if not ok:
        return False, False, f"`gh issue view {issue}` 失败：{raw}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False, False, f"`gh issue view {issue}` 返回的不是 JSON：{raw[:200]}"
    for comment in (data.get("comments") or []):
        if BACKFILL_MARKER_RE.search(str(comment.get("body") or "")):
            return True, True, f"issue #{issue} 上有回填记录（评论 {comment.get('createdAt')}）"
    return True, False, (
        f"issue #{issue} 上找不到回填记录（认的标记：`{BACKFILL_MARKER_RE.pattern}`）"
        "—— 下限写法 `<!-- llm-sink-backfill: #<issue> sunk=<cases> -->`")


# ══════════════════════════════════════════════════════════════════════════════
# 四、三种模式
# ══════════════════════════════════════════════════════════════════════════════

def mode_selftest(ledger: dict, cases_by_id: dict,
                  repo_root: Path = REPO_ROOT,
                  ledger_path: Path = LEDGER_PATH) -> tuple[int, list[str], dict]:
    lines = [f"台账：{ledger_path}",
             f"用例库：{CASES_DIR}（{len(cases_by_id)} 条用例）",
             f"效果层字段（源自 assertion_taxonomy.EFFECT_FIELDS）：{list(EFFECT_FIELDS)}"]
    entries = ledger.get("entries") or []
    schema_violations = check_ledger_schema(ledger)
    per_entry = [(entry, check_entry(entry, cases_by_id, repo_root)
                  if isinstance(entry, dict) else []) for entry in entries]
    violations = schema_violations + [v for _e, vs in per_entry for v in vs]
    for entry, bad in per_entry:
        line = describe_entry(entry) if isinstance(entry, dict) else repr(entry)
        # 图标按**核验结果**给：违规 ⇒ ❌（不看台账自己声明的状态），未下沉 ⇒ ⚠️
        icon = "❌" if bad else ("⚠️" if entry.get("status") == "unsunk" else "✅")
        lines.append(f"{icon} {line}")
        lines.extend(f"       ↳ {v.code}: {v.detail}" for v in bad)
    lines.extend(f"❌ {v.code}: {v.detail}" for v in schema_violations)
    lines.append(f"未实装登记：{len(ledger.get('unimplemented') or [])} 条"
                 "（见 .github/llm-finding-ledger.json 的 unimplemented）")
    if violations:
        lines.append(f"❌ 台账自检失败：{len(violations)} 条违规")
    else:
        lines.append("✅ 台账自检通过：每条 sunk 的断言均非空壳且回填链完整，"
                     "每条 unsunk 均已显式登记")
    result = {
        "mode": "selftest",
        "exit_code": EXIT_VIOLATION if violations else EXIT_OK,
        "ok": not violations,
        "ledger": str(ledger_path),
        "entry_count": len(ledger.get("entries") or []),
        "violations": [v.as_dict() for v in violations],
        "unimplemented": ledger.get("unimplemented") or [],
    }
    return result["exit_code"], lines, result


def mode_issue(ledger: dict, cases_by_id: dict, issue: int,
               check_backfill: bool = False,
               repo_root: Path = REPO_ROOT) -> tuple[int, list[str], dict]:
    """回答「issue #N 有确定性断言了吗？」—— 0 / 1 / 3 三态。"""
    lines: list[str] = []
    result: dict = {"mode": "issue", "issue": issue}
    entry = entry_for(ledger, issue)
    if entry is None:
        lines.append(f"❌ #{issue} 未登记 —— 台账里没有这条 LLM 红例的条目")
        lines.append("   （新发现的 LLM 红例必须显式入账；本脚本不会自动入账，"
                     "见 unimplemented 第 1 条）")
        result.update({"exit_code": EXIT_VIOLATION, "ok": False,
                       "registered": False, "status": None, "sunk": False,
                       "violations": [], "hint": "未登记"})
        return EXIT_VIOLATION, lines, result

    status = entry.get("status")
    if status == "unsunk":
        lines.append(f"❌ #{issue} 未下沉（unsunk，**已显式登记**）："
                     f"reason={entry.get('reason')!r}；follow_up=#{entry.get('follow_up')}")
        lines.append("   ⇒ 尚未产出确定性断言；显式登记 ≠ 已闭环")
        result.update({"exit_code": EXIT_VIOLATION, "ok": False, "registered": True,
                       "status": status, "sunk": False, "violations": [],
                       "reason": entry.get("reason"), "follow_up": entry.get("follow_up"),
                       "hint": "未下沉（已登记）"})
        return EXIT_VIOLATION, lines, result

    violations = check_entry(entry, cases_by_id, repo_root)
    if violations:
        lines.append(f"❌ #{issue} 登记为 sunk，但核不过：{len(violations)} 条违规")
        lines.extend(f"   ↳ {v.code}: {v.detail}" for v in violations)
        result.update({"exit_code": EXIT_VIOLATION, "ok": False, "registered": True,
                       "status": status, "sunk": False,
                       "violations": [v.as_dict() for v in violations],
                       "hint": "断言空壳 / 回填缺失"})
        return EXIT_VIOLATION, lines, result

    lines.append(f"✅ #{issue} 已下沉且断言非空：")
    for sink in (entry.get("sinks") or []):
        if not isinstance(sink, dict):
            continue
        if sink.get("kind") == "case_assertion":
            lines.append(f"   · 用例断言 {sink.get('fields')} @ {sink.get('cases')}"
                         "（字段非空 + has_effect_assertion + merge_log 回填 `#"
                         f"{issue}` 均通过）")
        else:
            lines.append(f"   · L0 不变式 {sink.get('test_file')} :: "
                         f"{sink.get('test_names')}（函数名真实存在 + 用例回填通过）")
    lines.append(f"   · 证据：{entry.get('evidence')}")

    if not check_backfill:
        lines.append("   · GitHub 侧回填：**未核验**（离线档只核用例库侧 merge_log；"
                     "要核请加 `--check-backfill`）—— 未核验不等于已核验")
        result.update({"exit_code": EXIT_OK, "ok": True, "registered": True,
                       "status": status, "sunk": True, "violations": [],
                       "backfill_checked": False, "hint": "已下沉（GitHub 侧回填未核验）"})
        return EXIT_OK, lines, result

    ok, backfilled, note = issue_backfill_state(issue)
    lines.append(f"   · GitHub 侧回填：{note}")
    if not ok:
        lines.append("   ⇒ 退出码 3（无法判定）：**不把「核不了」写成「通过」**")
        result.update({"exit_code": EXIT_UNKNOWN, "ok": False, "registered": True,
                       "status": status, "sunk": True, "violations": [],
                       "backfill_checked": True, "backfill": None,
                       "hint": "无法判定（gh 不可用）"})
        return EXIT_UNKNOWN, lines, result
    if not backfilled:
        result.update({"exit_code": EXIT_VIOLATION, "ok": False, "registered": True,
                       "status": status, "sunk": True,
                       "violations": [Violation(f"#{issue}", "SINK-ISSUE-NO-BACKFILL",
                                                note).as_dict()],
                       "backfill_checked": True, "backfill": False,
                       "hint": "回填缺失"})
        return EXIT_VIOLATION, lines, result
    result.update({"exit_code": EXIT_OK, "ok": True, "registered": True, "status": status,
                   "sunk": True, "violations": [], "backfill_checked": True,
                   "backfill": True, "hint": "已下沉且已回填"})
    return EXIT_OK, lines, result


def mode_all(ledger: dict) -> tuple[int, list[str], dict]:
    """盘点所有 open 的 LLM 来源 issue ↔ 台账。"""
    ok, rows, err = enumerate_llm_issues()
    if not ok:
        lines = [f"⚠️ 无法判定：{err}",
                 "   ⇒ 退出码 3：**看不了 ≠ 全清**（不把「查不到」报成「都登记了」）"]
        return EXIT_UNKNOWN, lines, {"mode": "all", "exit_code": EXIT_UNKNOWN,
                                     "ok": False, "reason": err, "issues": []}
    lines = [f"open 的 LLM 来源 issue：{len(rows)} 条"
             f"（标题族 {len(LLM_ISSUE_TITLE_PATTERNS)} 条，本地正则复核过）"]
    issues, unregistered, registered_unsunk = [], [], []
    for row in rows:
        entry = entry_for(ledger, row["number"])
        state = "未登记" if entry is None else (
            "已下沉" if entry.get("status") == "sunk" else "未下沉（已登记）")
        lines.append(f"  · #{row['number']} {state} — {row['title']}")
        issues.append({"issue": row["number"], "title": row["title"],
                       "registered": entry is not None,
                       "status": entry.get("status") if entry else None,
                       "state": state})
        if entry is None:
            unregistered.append(row["number"])
        elif entry.get("status") != "sunk":
            registered_unsunk.append(row["number"])
    if registered_unsunk:
        lines.append(f"⚠️ 已登记但未下沉 {len(registered_unsunk)} 条：{registered_unsunk}"
                     "（显式登记，不算静默通过；但要闭环仍需产出确定性断言）")
    if unregistered:
        lines.append(f"❌ 未登记 {len(unregistered)} 条：{unregistered}"
                     " —— 这就是「静默通过」的形态（裁定 4′ 明令禁止）")
        code = EXIT_VIOLATION
    else:
        lines.append("✅ 所有 open 的 LLM 来源 issue 都在台账里有条目")
        code = EXIT_OK
    result = {"mode": "all", "exit_code": code, "ok": code == EXIT_OK,
              "checked": len(rows), "issues": issues, "unregistered": unregistered,
              "registered_unsunk": registered_unsunk}
    return code, lines, result


# ══════════════════════════════════════════════════════════════════════════════
# 五、CLI
# ══════════════════════════════════════════════════════════════════════════════

EPILOG = """退出码（三态，同 .github/scripts/eval_slot_status.sh 的 0/2/3 约定）
  0 = OK        已下沉且断言非空 / 台账完备 / open 的 LLM 红例全有条目
  1 = 违规      未登记 / 未下沉 / 断言空壳 / 回填缺失 / 存在未登记的 open LLM 红例
  3 = 无法判定  gh 不可用或查询失败 —— 绝不把「核不了」报成「通过」

未机械化（如实登记在 .github/llm-finding-ledger.json 的 unimplemented）
  · 新发现的 LLM 红例**自动入账**没有做（`--all` 只能在 gh 可用时发现缺失）；
  · GitHub issue 侧的回填核验依赖 gh/网络，**未接入 CI required check**
    （离线档 `--selftest` 只核用例库侧 merge_log 回填）；
  · `[行为映射门禁] 规则命中用例失败` 一族默认不在 `--all` 的枚举范围内。
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="llm_sink_check.py",
        description="LLM 红例 → 确定性下沉台账的机械检查（用户裁定 4′ / issue #4034）",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--selftest", action="store_true",
                   help="离线自检整个台账（schema + 每条条目 + unimplemented 非空）；退出码 0/1")
    g.add_argument("--issue", type=int, metavar="N",
                   help="回答「issue N 有确定性断言了吗？」；退出码 0/1，核不了给 3")
    g.add_argument("--all", action="store_true",
                   help="盘点所有 open 的 LLM 来源 issue ↔ 台账；退出码 0/1，gh 不可用给 3")
    p.add_argument("--check-backfill", action="store_true",
                   help="配合 --issue：额外用 gh 核「发现它的 issue 上有没有回填记录」（需网络）")
    p.add_argument("--json", action="store_true", help="输出机读 JSON（给 agent / CI 用）")
    p.add_argument("--ledger", default=str(LEDGER_PATH), help="台账路径（默认 .github/llm-finding-ledger.json）")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ledger = load_ledger(Path(args.ledger))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"❌ 台账读不了：{exc}", file=sys.stderr)
        return EXIT_VIOLATION

    if args.selftest:
        code, lines, result = mode_selftest(ledger, load_case_index(),
                                            ledger_path=Path(args.ledger))
    elif args.issue is not None:
        code, lines, result = mode_issue(ledger, load_case_index(), args.issue,
                                         check_backfill=args.check_backfill)
    else:
        code, lines, result = mode_all(ledger)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("\n".join(lines))
        print(f"\n退出码 {code} = "
              + {EXIT_OK: "OK", EXIT_VIOLATION: "违规", EXIT_UNKNOWN: "无法判定"}[code])
    return code


if __name__ == "__main__":
    sys.exit(main())