# case_ids: MC-012
# （沿用 `tests/unit_ci_workflows/**` 的既有惯例：CI / 流程结构类 L0 不变式统一挂 MC-012 ——
#   见 `.github/cases/misc.yml` 的 MC-012「CI workflow 行为由 tests/unit_ci_workflows/ 单测验证」。）
"""审计引用的**容器**判据：上线审计的 finding 不得挂在 dependabot PR 的号上。

## 病（2026-10-31 现场形态，逐条可复算）

main 上曾有 **20 个文件 / 44 处**把「上线审计 P1-xx」的容器写成了同一个**依赖升级 PR 的号**
（dependabot，`chore(deps): bump sqlalchemy from 2.1.4 to 2.1.6`，state=OPEN），
两者语义完全不同。复算（改前）：

```bash
git grep -nE -- '#\\s?8218' origin/main | wc -l    # 44
gh pr view 8218 --json title --jq .title           # chore(deps): bump sqlalchemy ...
```

⚠️ 上面那条命令里的号是**故意拆开写的**（`#` 与数字分开）：本文件若出现「`#` + 该号」的**字面量**，
本判据会扫描到**自己**并恒红 —— 即 `migao-dev-flow` §2.2 的「**引用即实例**」（内容扫描式机制
分不清「引用」与「使用」）。同族纪律：解释触发式缺陷时**不要原样写出触发串**。

病根不是「写错一个数字」，而是**转述链上没有一步核对**（铁律 11「转述即未核实」）：
finding 的 ID（`P1-08`）是稳定的，容器号却是**从别人嘴里抄来的** ⇒ 抄错也不会红。
⇒ 本判据把「**finding ⇄ 容器**」的绑定做成断言，并在 docstring 里**逐个核过**那一次。

## 已核实的容器映射（`gh issue view` / `gh pr view` 逐个核过；**不靠记忆、不靠转述**）

| 对象 | 号 | 类型 / 状态 | 标题（截断） |
|---|---|---|---|
| **上线审计 issue**（P1 finding 的容器） | 8197 | issue OPEN | [上线·审计] 正式上线前 P0/P1 全量审计（首批试用客户） |
| 上线审计 PR（`acceptance/2026-10-31-launch-audit/` 的交付） | 8200 | PR MERGED | docs(audit): 上线前只读全量审计（P0×4 / P1×12 / P2×3） |
| P0-01 | 8201 | issue CLOSED | [上线·P0] TLS 证书 2026-11-27 到期且无续期机制… |
| P0-03 + P0-04 | 8203 | issue OPEN | [上线·P0] 白屏无出口 + 零可观测… |
| **本判据要挡的那个号** | 8218 | PR OPEN | chore(deps): bump sqlalchemy from 2.1.4 to 2.1.6 in /backend/ai-agent-service |

⚠️ **P0-02 不在表里**：8198 / 8199 / 8204 / 8205 逐个核过都不是它 ⇒ **不写**（宁缺勿滥；将来核到了再补）。
⚠️ 上表是**人核一次**的产物（`gh` 命令可复算）；本判据不联网 —— 它保证的是「**号不会再被悄悄换掉**」。

## 判据（两条，各自能单独变红）

| # | 判据 | 变红形态 |
|---|---|---|
| 1 | 仓库内**任何**对该号的引用都必须落在 **dependabot / 依赖语境**（同一行含 `dependabot` / `chore(deps)` / `bump … from … to` / `sqlalchemy`） | 把任何审计 finding 写回**那个号**（相邻的 `#` + 数字；本文件故意不写相邻形态）⇒ 红；**无法归类**的裸引用也红（**未登记即红**，fail-closed） |
| 2 | 被误标过的 7 条 finding（`P1-02/04/05/08/09/10/12`）必须各自仍有 **≥1 处**与已核实容器（`#8197` / `#8200`）**同行** | 用「把引用删掉」代替订正 ⇒ 红（订正 ≠ 抹掉痕迹） |

## 为什么第 2 条不可省

第 1 条只判「**不许写错**」—— **删干净同样能变绿**，而删掉之后 finding 与容器的绑定就消失了，
下一个人只能重新猜（**这正是本病的成因**）。⇒ 第 2 条把「绑定**还在**」也做成断言，且只判**下限**。

## 豁免与边界（照实登记，§19.1）

- **dependabot 语境 = 合法豁免**：该号在依赖语境的引用是**对的**（dependabot PR 本体就是它），
  本单只订正审计语境的 44 处。豁免判据 = **同一行**的依赖语境正则；**不跨行匹配**
  （跨行写法会被判红 ⇒ 写的人把词放进同一行即可，代价极小、口径确定）。
  **没有人工豁免台账**：凡「既不是依赖语境」的引用一律红 —— 这就是「**未登记即红**」。
- 扫描面 = `git grep` 的**已跟踪文本文件**（`-I` 跳二进制）：**未跟踪的新文件不在面内**（本地临时文件不误红）；
  `git grep` 读**工作树** ⇒ 已提交文件的本地改动**在面内**（开发期就能看到红）。
- 判**引用形态**，不判「这个号此刻是否真对应那个对象」：后者的机械面是 `gh`（需联网，**故意不接**）；
  本判据保证的是「它不会再被悄悄换成别的号」+「换掉之后有人要解释」。
- 本判据**不改任何门禁的通过条件、不新增豁免**；它不覆盖「别的审计族」（如 `docs/audit-2026-08/` 的
  `审计 07` 一族有**自己的**编号体系，见 `docs/audit-2026-08/07-security-and-llm-attack-audit.md`）。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ⚠️ 本文件**不得**出现「`#` + 该号」的字面量（否则判据扫自己 ⇒ 恒红，见 docstring）。
MISLABEL_NUMBER = 8218
REF_RE = re.compile(r"#\s?" + str(MISLABEL_NUMBER) + r"\b")

# 依赖语境的标记（豁免面）。**同一行**才算，见 docstring「边界」。
DEP_CONTEXT_RE = re.compile(
    r"dependabot|chore\(deps\)|bump\s+\S+\s+from\s+\S+\s+to\s|\bsqlalchemy\b",
    re.IGNORECASE,
)
# 归因用（只影响判红时的说明，不影响判绿/判红）
AUDIT_HINT_RE = re.compile(r"上线审计|审计\s*P[01]-\d{2}|P[01]-\d{2}")

AUDIT_ISSUE = 8197
AUDIT_REPORT_PR = 8200
CONTAINER_RE = re.compile(r"#\s?(?:%d|%d)\b" % (AUDIT_ISSUE, AUDIT_REPORT_PR))

# 被误标过的 7 条 finding（审计 `findings.md` 的 P1 面；P0 各自有自己的单）
MISLABELLED_FINDINGS = ("P1-02", "P1-04", "P1-05", "P1-08", "P1-09", "P1-10", "P1-12")

FINDINGS_RE = r"P[01]-[0-9][0-9]"


def _git_grep_files(pattern: str) -> list[str]:
    """已跟踪文本文件里命中 pattern 的路径（`-I` 跳二进制）。

    fail-closed：git 不可用 / 仓库损坏 ⇒ **判据不可判定**，直接 raise（**不得**当成「没有命中」）。
    """
    proc = subprocess.run(
        ["git", "grep", "-lIE", "--", pattern],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 1:  # grep 的「无命中」
        return []
    if proc.returncode != 0:
        raise AssertionError(
            f"git grep 失败（rc={proc.returncode}）：{proc.stderr.strip()}  ⇒ 判据不可判定，不得当通过"
        )
    return [line for line in proc.stdout.splitlines() if line]


#: 🔴 **具名豁免：只此一条**（判据 1 的扫描面排除它）。
#:
#: 为什么：`scripts/drift_audit_baseline.json` 的 `reason` 字段记的是「这条豁免**当年为什么被批准**」，
#: 其中必然引用**当时**的 issue / PR 号。若当时那个号就是错挂的，把它写进 reason 恰恰是**历史事实**
#: —— 判据 1 的意图是防「**活跃**引用错挂」，不是改写记账（改了反而抹掉「曾经错挂过」这件事）。
#:
#: **重启条件**（不满足就必须撤销本豁免）：一旦该文件的 `reason` 被用于**活跃引用**
#: （指向当前对象的定位 / 判据可解析的坐标），本豁免立即失效。
#: 台账**只许缩短**：新增任何豁免都必须改 `test_exemption_is_named_and_only_shrinks` 并写明理由。
EXEMPT_FILES = frozenset({"scripts/drift_audit_baseline.json"})


def _scanned_files(pattern: str) -> list[str]:
    """判据 1/2 的扫描面 = `git grep` 命中的已跟踪文本文件**减去具名豁免**。"""
    return [path for path in _git_grep_files(pattern) if path not in EXEMPT_FILES]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def judge_refs(files: dict[str, str]) -> list[str]:
    """判据 1：该号的每一处引用都必须落在依赖语境；否则红（含审计语境与「无法归类」两种）。"""
    violations: list[str] = []
    for path in sorted(files):
        lines = files[path].splitlines()
        for idx, line in enumerate(lines):
            if not REF_RE.search(line):
                continue
            if DEP_CONTEXT_RE.search(line):  # 豁免只在同一行 ⇒ fail-closed
                continue
            window = "\n".join(lines[max(0, idx - 2): idx + 3])
            hint = AUDIT_HINT_RE.search(window)
            if hint:
                why = f"疑似审计语境（{hint.group(0)}）"
            else:
                why = "未登记：既不属 dependabot / 依赖语境"
            violations.append(f"{path}:{idx + 1}: {line.strip()[:140]}  ← {why}")
    return violations


def judge_finding_containers(files: dict[str, str]) -> list[str]:
    """判据 2：每条被误标过的 finding 必须仍有 ≥1 处与已核实容器**同行**（下限，不是全覆盖）。"""
    missing: list[str] = []
    for finding in MISLABELLED_FINDINGS:
        bound = any(
            finding in line and CONTAINER_RE.search(line)
            for text in files.values()
            for line in text.splitlines()
        )
        if not bound:
            missing.append(finding)
    return missing


# ── 判据 1 ────────────────────────────────────────────────────────────────────


def test_no_audit_finding_is_labelled_with_the_dependency_pr_number():
    """仓库内该号的引用只允许出现在依赖语境；审计语境 / 裸引用一律红。"""
    violations = judge_refs({path: _read(path) for path in _scanned_files(REF_RE.pattern)})
    assert violations == [], (
        "上线审计 finding 被挂到了 dependabot PR 的号上（或出现无法归类的裸引用）。\n"
        "订正口径 = 审计 finding 挂 上线审计 issue 8197 / 审计 PR 8200；依赖升级才挂那个号。\n"
        "复算：git grep -nE -- '#\\s?8218'\n"
        + "\n".join(violations)
    )


# ── 判据 2 ────────────────────────────────────────────────────────────────────


def test_mislabelled_findings_still_carry_a_verified_container():
    """订正不得退化成「删引用」：7 条 P1 finding 必须仍有与容器同行的引用。"""
    files = {path: _read(path) for path in _scanned_files(FINDINGS_RE)}
    missing = judge_finding_containers(files)
    assert missing == [], (
        f"这些 finding 已没有任何与已核实容器（#{AUDIT_ISSUE} / #{AUDIT_REPORT_PR}）同行的引用：{missing}\n"
        "订正 ≠ 抹掉痕迹：删掉引用会让下一个人只能重新猜（本病的成因）。"
    )


# ── 红证（注入式；各自能单独变红）──────────────────────────────────────────────


def test_red_proof_audit_context_is_caught():
    """红证①：审计语境 + 该号 ⇒ 红，且归因写「疑似审计语境」。"""
    injected = {
        "deploy/swas/nginx.conf": "    # ── 安全响应头（issue #" + str(MISLABEL_NUMBER) + " P1-08 / P1-09）\n"
    }
    violations = judge_refs(injected)
    assert len(violations) == 1, violations
    assert violations[0].startswith("deploy/swas/nginx.conf:1:")
    assert "疑似审计语境" in violations[0] and "P1-08" in violations[0], violations[0]


def test_red_proof_unclassified_reference_is_caught():
    """红证②：既不属依赖语境、也不是审计语境的裸引用 ⇒ 红（未登记即红）。"""
    injected = {"docs/x.md": "见 PR #" + str(MISLABEL_NUMBER) + "\n"}
    violations = judge_refs(injected)
    assert len(violations) == 1, violations
    assert "未登记" in violations[0], violations[0]


def test_red_proof_real_nginx_comment_is_caught_and_original_is_green():
    """红证③：真文件**内存变异**（不动盘）⇒ 红；原样 ⇒ 绿（反向对照，证明红证不是空断言）。"""
    rel = "deploy/swas/nginx.conf"
    text = _read(rel)
    assert CONTAINER_RE.search(text), "原文件里应已有已核实的容器号（前提不成立 ⇒ 先修文件）"

    mutated = text.replace(
        "issue #%d P1-08 / P1-09" % AUDIT_ISSUE,
        "issue #" + str(MISLABEL_NUMBER) + " P1-08 / P1-09",
        1,
    )
    assert mutated != text, "变异注入未生效（自证失败 ⇒ 下面的红证是空断言）"
    violations = judge_refs({rel: mutated})
    assert len(violations) == 1, violations
    assert violations[0].startswith(f"{rel}:"), violations[0]

    assert judge_refs({rel: text}) == [], "未变异时不得报红（否则上面的红证是空断言）"


def test_red_proof_deleting_references_breaks_the_finding_binding():
    """红证④：把容器引用整体剥掉（= 用删除代替订正）⇒ 判据 2 对 7 条 finding 全红。"""
    files = {path: _read(path) for path in _git_grep_files(FINDINGS_RE)}
    assert judge_finding_containers(files) == [], "前提：当前仓库应已绑定"

    stripped = {path: CONTAINER_RE.sub("", text) for path, text in files.items()}
    missing = judge_finding_containers(stripped)
    assert set(missing) == set(MISLABELLED_FINDINGS), missing


def test_dependency_context_is_exempt():
    """负控⑤：该号在 **dependabot / 依赖语境**下是**对的**，必须保持绿（豁免不是摆设）。"""
    exempt = {
        "CHANGELOG.md": (
            "- chore(deps): bump sqlalchemy from 2.1.4 to 2.1.6 (#"
            + str(MISLABEL_NUMBER)
            + ")\n"
        )
    }
    assert judge_refs(exempt) == []


def test_exemption_is_named_and_only_shrinks():
    """豁免台账**只许缩短**：新增豁免必须具名 + 写理由 + 写重启条件。

    判别力：把 `EXEMPT_FILES` 改成空集 ⇒ 判据 1 立刻重新扫到 baseline 的 reason 而红（红证见
    `test_red_proof_exempt_file_would_otherwise_be_flagged`）；往里加第二个文件 ⇒ 本条红。
    """
    assert EXEMPT_FILES == frozenset({"scripts/drift_audit_baseline.json"}), (
        f"豁免台账只许缩短，且只允许这一条具名项；实际 = {sorted(EXEMPT_FILES)}"
    )


def test_red_proof_exempt_file_would_otherwise_be_flagged():
    """**红证**：把豁免拿掉 ⇒ 同一份 baseline 内容会被判红（证明豁免真的在起作用，不是空集）。"""
    text = _read("scripts/drift_audit_baseline.json")
    flagged = judge_refs({"scripts/drift_audit_baseline.json": text})
    assert flagged, (
        "拿掉豁免后该文件本应被判红 —— 若这里是空的，说明它本来就不含审计语境引用，"
        "那本条豁免就是**多余的门**，应删除"
    )
