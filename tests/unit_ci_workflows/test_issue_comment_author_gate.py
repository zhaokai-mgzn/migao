# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 tests/unit_ci_workflows/test_required_check_no_paths_filter.py 的同款声明。）
"""`issue_comment` 触发的腿必须同时做**身份**门控（issue #8397 ①）。

## 病灶（公开仓里真实存在）

`.github/workflows/case-redraft.yml` 的 `if:` 此前**只按评论正文关键词**筛
（`contains(body,'<!-- REVIEW_JSON')` + `"reject"`/`"supplement"` + 非 bot），**没有
`author_association`**：仓库 public 之后，**任何陌生人**在本仓任一 issue 下贴一段含这些串的评论，
就能触发这条跑在 base 仓、带 `issues: write` 的腿（改 label、隐藏既有 DRAFT 评论）。

**关键词是内容判据，不是身份判据** —— 内容判据挡不住"谁来说这句话"。

现取读数（复核命令）：
`git grep -c "author_association" origin/main -- .github/workflows` ⇒ 修复前 **0 处**。

## 判据（每条都能单独变红）

| # | 判据 | 红证（只改一处即翻转） |
|---|---|---|
| 1 | 凡 `on.issue_comment` 的 workflow，**每个** job 的 job 级 `if:` 必须引用 `author_association` | 删掉 `case-redraft.yml` 的那一行 ⇒ 判据 1 具名报出 |
| 2 | 该 `if:` 必须是**白名单**：`OWNER` / `MEMBER` / `COLLABORATOR` 三者齐全 | 把 `MEMBER` 从白名单里删掉 ⇒ 判据 2 红 |
| 3 | 只看**真 `if:` 的取值**，注释里的字样不算（`# author_association` 不能"充数"） | 把白名单移进注释 ⇒ 判据 3 红 |
| 4 | 语料下限：现取至少 1 条 `issue_comment` 腿（否则判据在空集上恒真 = 空跑成绿） | 把 `case-redraft.yml` 的触发面改掉 ⇒ 判据 4 红 |
| 5 | 豁免必须**具名登记**（`workflow` + `reason` + `issue`），未登记即红 | 往语料里塞一条无门控腿 ⇒ 判据 5 红 |
| 6 | 判别力自证：三种坏形态（无 `if` / 白名单缺项 / 只在注释里写）在内存夹具上各自判红 | 判定函数退化成恒空 ⇒ 判据 6 红 |

## 边界（照实登记）

- 判**静态形态**，不跑 GitHub：判不了「作者是不是真的陌生人」（那是运行期事实），只保证
  「**身份门控存在且是白名单**」。
- 只覆盖 `issue_comment` 一族；`pull_request_target` 的身份面由 `contribution-gate.yml` 的
  `sensitive_path_guard` 覆盖，`pull_request` 面由 `scripts/external_authorship_guard.py` 覆盖。
- 白名单是**流程护栏**，不是安全边界：拿到 write 的人本就能改这一切。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
LEDGER = Path(__file__).resolve().parent / "issue_comment_author_gate_ledger.json"

#: 白名单必须齐全的三个关联（少任何一个都会放行一类陌生人）。
REQUIRED_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")
#: 语料下限：现取至少有这么多条 `issue_comment` 腿，判定面塌了要出声（不许静默变绿）。
CORPUS_FLOOR = 1


def _on(doc: dict) -> dict:
    value = doc.get(True, doc.get("on"))
    return value if isinstance(value, dict) else {}


def _if_text(job: dict) -> str:
    value = job.get("if")
    return value if isinstance(value, str) else ""


def strip_comments(text: str) -> str:
    """去掉行内注释与整行注释 —— 注释里的字样不是门控。

    `if: |` 块标量里整行 `# …` 会**原样留在取值里**（YAML 只在块标量外剥注释）⇒ 必须先剥掉，
    否则「在注释里写一遍白名单」就能给判据盖章（假绿）。
    """
    out: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        out.append(line.split("  #", 1)[0] if "  #" in line else line)
    return "\n".join(out)


def job_problems(name: str, jid: str, job: dict) -> list[str]:
    """单个 job 的问题清单（空 = 合规）。"""
    text = strip_comments(_if_text(job)).strip()
    if not text:
        return [f"{name}::{jid}：`issue_comment` 腿缺 job 级 `if:` ⇒ 任何人评论都会触发该 job（必须加身份白名单）"]
    problems: list[str] = []
    if "author_association" not in text:
        problems.append(
            f"{name}::{jid}：`if:` 未引用 `author_association` ⇒ 评论正文关键词挡不住陌生人（issue #8397）"
        )
    missing = [a for a in REQUIRED_ASSOCIATIONS if a not in text]
    if missing:
        problems.append(
            f"{name}::{jid}：`author_association` 白名单缺 {missing} ⇒ 该关联的账号会被放行（白名单必须三者齐全）"
        )
    return problems


def scan(directory: Path = WORKFLOWS) -> tuple[list[str], list[tuple[str, dict]]]:
    """→ `(问题清单, 命中的 workflow 语料)`。读不到 / 解析不了 ⇒ 抛（fail-closed）。"""
    if not directory.exists():
        raise ValueError(f"workflow 目录不存在：{directory}（fail-closed，不许当成「零违规」）")
    problems: list[str] = []
    corpus: list[tuple[str, dict]] = []
    for path in sorted(directory.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or "issue_comment" not in _on(doc):
            continue
        corpus.append((path.name, doc))
        for jid, job in (doc.get("jobs") or {}).items():
            if isinstance(job, dict):
                problems.extend(job_problems(path.name, jid, job))
    return problems, corpus


def exempt_names() -> set[str]:
    if not LEDGER.exists():
        return set()
    data = json.loads(LEDGER.read_text(encoding="utf-8"))
    return {str(entry.get("workflow") or "") for entry in (data.get("exemptions") or [])}


def test_issue_comment_legs_have_author_gate() -> None:
    """判据 1+2：现取语料里每条 `issue_comment` 腿都必须有完整白名单（豁免须具名登记）。"""
    problems, corpus = scan()
    assert len(corpus) >= CORPUS_FLOOR, (
        f"现取 `issue_comment` 腿只有 {len(corpus)} 条（下限 {CORPUS_FLOOR}）⇒ 判定面塌了，本判据会空跑成绿"
    )
    exempt = exempt_names()
    problems = [p for p in problems if p.split("::")[0] not in exempt]
    assert not problems, "「评论正文关键词」不是身份判据：\n" + "\n".join("  " + p for p in problems)


def test_comment_mention_does_not_count() -> None:
    """判据 3：把白名单写进注释不算 —— 判的是 `if:` 的真实取值（两种注释形态各一条）。"""
    inline = yaml.safe_load(
        """
on:
  issue_comment:
    types: [created]
jobs:
  j:
    if: contains(github.event.comment.body, 'x')  # author_association OWNER MEMBER COLLABORATOR
"""
    )
    block = yaml.safe_load(
        """
on:
  issue_comment:
    types: [created]
jobs:
  j:
    if: |
      # author_association OWNER MEMBER COLLABORATOR
      contains(github.event.comment.body, 'x')
"""
    )
    for name, doc in (("行内注释", inline), ("块标量注释行", block)):
        job = (doc.get("jobs") or {})["j"]
        assert job_problems("wf.yml", "j", job), f"{name}里的白名单被当成了门控 ⇒ 判据 3 失去判别力"


def test_discriminating_power_on_injected_jobs() -> None:
    """判据 6：三种坏形态各自判红、合规形态判不红（对照）。"""
    good = (
        "contains(fromJSON('[\"OWNER\",\"MEMBER\",\"COLLABORATOR\"]'), "
        "github.event.comment.author_association)"
    )
    assert job_problems("wf.yml", "j", {"if": good}) == [], "合规形态被误判 ⇒ 判据会把好腿也判红"
    assert job_problems("wf.yml", "j", {}), "无 `if:` 未判红"
    assert job_problems("wf.yml", "j", {"if": "contains(github.event.comment.body, 'x')"}), "无 author_association 未判红"
    partial = "contains(fromJSON('[\"OWNER\",\"COLLABORATOR\"]'), github.event.comment.author_association)"
    assert job_problems("wf.yml", "j", {"if": partial}), "白名单缺 MEMBER 未判红"


def test_exemptions_are_registered_and_complete() -> None:
    """判据 5：豁免不许匿名存在，且只许缩短（每条都要 reason + issue）。"""
    if not LEDGER.exists():
        return
    data = json.loads(LEDGER.read_text(encoding="utf-8"))
    for entry in data.get("exemptions") or []:
        assert str(entry.get("workflow") or "").strip(), f"豁免缺 `workflow`：{entry}"
        assert str(entry.get("reason") or "").strip(), f"豁免缺理由：{entry}"
        assert str(entry.get("issue") or "").strip(), f"豁免缺单号：{entry}"
