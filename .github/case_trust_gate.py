#!/usr/bin/env python3
"""断言可信度静态门禁 —— **假红/假绿结构性护栏 A 层**（#3483 T1 扩展格）。

判据的**单一源** = `.github/assertion_taxonomy.py`（本脚本只做「取 diff → 过滤 → 裁决 →
报错」的外壳，**不复制任何判据**）。静态门禁与后续 runner 侧动态分类器必须共用那一处口径，
两处各写一份就必然漂移（详见 taxonomy 模块 header）。

## 判定范围（两层，缺任一层都会留下「永久豁免」）

**① 逐条判定（diff 命中）**：`git diff origin/main...HEAD` 命中的 `cases/*.yml` → 对每个文件
比对 `origin/main` 版本与 HEAD 版本里用例块的文本 → 文本**新增或变化**的用例 ID 才参与裁决。
⇒ **不阻塞存量**（存量在基线清单里），也不会因为「别人还没修的存量用例」把无关 PR 判红。

**② 全量对账（整个豁免清单，**不限 diff 命中**，#4031）**：豁免清单是**债务账本**，
不是「这些用例永远豁免」。故每次运行都对**全库**重算一遍，逐条核对：
  · 记了却已不再违规 ⇒ **阻塞**，必须从清单移除/收窄（清单只许缩短）；
  · **`origin/main` 记了、现在仍违规，却被本 PR 删掉** ⇒ **阻塞**（删条目 = 偷偷新增豁免）；
  · `rule_counts` / `violation_case_count` 与 `violations` 不自洽 ⇒ **阻塞**（假读数）。
⇒ 修法是机械的：`--prune-baseline`（**只删不加**）。

**③ burn-down 预算**：每（改用例的）PR 至少净缩 N 条 + `OR-*` 优先到期 + 全清单到期清零
（配置在 `.github/case-trust-baseline.json` 的 `burn_down` 块，**生效口径读 `--base` 那一份**，
故本 PR 改不动本次判定）。`metric=entries` = **只认整条销账**（收窄一条多码条目不达标）；
配置四个维度（per_pr_min / 到期日 / 优先前缀 / **metric**）**只许收紧**。

**④ 未实装登记的约束**（本次收紧）：`.github/case-trust-unimplemented.json` 每条登记必须带
`issue` / `expires` / `how_to_verify` / `hit_probe`，四条判据都可红（缺字段 / 已到期 /
追踪单已 CLOSED / **僵尸**）。判据本体在 `assertion_taxonomy.judge_unimplemented`。

**⑤ 对账基准与被测对象对齐**（本次纠偏）：**未触碰受管面**（既没改 `.github/cases/**`
也没改豁免清单）的 PR，对账/计数基准取**分支分叉点**那份清单 —— main 侧别人的 prune
不算它的账（实测：纯文档 PR 因 main 侧 prune 被判「基线增长」= 假红）；触碰了任一受管面
⇒ 一律按当前 `origin/main` 比（一个字不松）；生效**配置**永远取 `origin/main`。

## 退出码（fail-closed）

* `0` = 无新增违规 + 全量对账无残留 + 预算达标 + 未实装登记合规；
* `1` = 有**新增**违规 / **全量对账报红**（陈旧条目 / 被删条目 / 账本不自洽）/ **预算未达标**
      / **未实装登记不合规**（缺字段 / 到期 / 僵尸 / 追踪单已 CLOSED）/ 判据加载失败 / 基线缺失；
* 网络格（追踪单状态）取不到 ⇒ **不计入退出码**，但报告里打印
  `⏭️ 未跑判定 … 不是「通过」`（「没跑」必须长得像「没跑」）。

## 用法

```bash
python3 .github/case_trust_gate.py                    # PR / 本地：diff origin/main...HEAD + 全量对账
python3 .github/case_trust_gate.py --base origin/main
python3 .github/case_trust_gate.py --files .github/cases/product.yml   # 只判指定文件（全部条目）
python3 .github/case_trust_gate.py --prune-baseline   # 全量对账的机械修复：**只删不加**
python3 .github/case_trust_gate.py --regen-baseline   # 全量重建（口径变化时；默认拒绝增长）
python3 .github/case_trust_gate.py --regen-baseline --allow-growth    # 显式放行增长（会逐条打印）
python3 .github/case_trust_gate.py --today 2027-01-01 # 预算到期判定的确定性注入（红证用）
python3 .github/case_trust_gate.py --no-issue-check   # 跳过追踪单状态查询（离线）
```
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GH_DIR = REPO_ROOT / ".github"
sys.path.insert(0, str(GH_DIR))

import assertion_taxonomy as tax  # noqa: E402

CASES_DIR = GH_DIR / "cases"
FIXTURES_DIR = REPO_ROOT / "tests" / "agent_eval" / "fixtures"
BASELINE_PATH = GH_DIR / "case-trust-baseline.json"
UNIMPLEMENTED_PATH = GH_DIR / "case-trust-unimplemented.json"
SEED_FILES = ("mibao_eval_seed.sql", "xiaobu_eval_seed.sql")
REGEN_COMMAND = "python3 .github/case_trust_gate.py --regen-baseline"
# 全量对账的机械修复命令：**只删不加**（`--regen-baseline` 是重建，默认拒绝增长）
PRUNE_COMMAND = "python3 .github/case_trust_gate.py --prune-baseline"
# `burn_down.metric` 的**严格度序**（数字越大越严；只许往上，不许往下）：
#   entries_or_codes（0）= 条目**或**码任一净缩即达标 ⇒ 删一个码也算「消了一条」；
#   codes（1）           = 只认码数 ⇒ 收窄一条多码条目即达标（仍是账面口径）；
#   entries（2）         = 只认**整条销账**（该用例不再命中任何码）⇒ 收窄 ≠ 修好。
METRIC_STRICTNESS: dict[str, int] = {"entries_or_codes": 0, "codes": 1, "entries": 2}
# 缺 `metric` 字段时的回落口径。⚠️ 它**仍是宽松档**（历史默认），因此「删掉 metric 字段」
# 会被「只许收紧」判成放宽 —— 这是有意的：口径只能显式收紧，不许靠删字段悄悄回退。
DEFAULT_METRIC = "entries_or_codes"


# ══════════════════════════════════════════════════════════════════════════════
# 输入层
# ══════════════════════════════════════════════════════════════════════════════

def load_seed_catalog(fixtures_dir: Path = FIXTURES_DIR) -> dict[str, set[str]]:
    """从两份种子 SQL 现算真值集合。

    **fail-closed**：文件缺失或解析不出任何表 ⇒ 抛异常（**不得**静默返回空 dict ——
    空 catalog 会让「种子可解析」规则把每条 pre_clean 都判成不可解析（恒红），
    或被写成「无 catalog 就跳过」（恒绿）。两者都是空壳，故直接失败）。
    """
    fixtures_dir = Path(fixtures_dir)
    catalog: dict[str, set[str]] = {}
    found_files = 0
    for fn in SEED_FILES:
        p = fixtures_dir / fn
        if not p.exists():
            raise FileNotFoundError(f"种子文件缺失（fail-closed）：{p}")
        found_files += 1
        for table, names in tax.extract_seed_catalog(p.read_text(encoding="utf-8")).items():
            catalog.setdefault(table, set()).update(names)
    non_empty = {k: v for k, v in catalog.items() if v}
    if found_files == 0 or not non_empty:
        raise RuntimeError(
            f"种子真值解析为空（fail-closed）：{fixtures_dir} —— "
            "空 catalog 会让「pre_clean 目标可解析」规则失去判别力"
        )
    # 关键表必须存在（否则规则会静默失去目标）
    for required in ("customer_tags", "products"):
        if not non_empty.get(required):
            raise RuntimeError(
                f"种子真值里缺少关键表 {required!r}（解析器失效？）—— "
                f"实际解析到：{sorted(non_empty)}"
            )
    return catalog


def load_cases_from_dir(cases_dir: Path = CASES_DIR) -> list[dict]:
    """读 cases/*.yml → [case_dict]（复用 render_cases 的单一源装载器）。"""
    from render_cases import load_case_dicts  # 延迟导入：保持一致装载语义
    return load_case_dicts(str(cases_dir))


def _case_blocks(yaml_text: str) -> dict[str, str]:
    """把 cases/*.yml 文本切成 {case_id: 该用例块的原文}。

    用**文本**切块（不走 YAML 解析）的两个理由：
      1. 规则 c 需要看 `forbidden_text` 附近的**注释**（轮次作用域标注常写在注释里）；
      2. diff 过滤要能识别「同一 id 的块内容变了」—— 结构化比对会被等价改写（引号/
         行内注释）触发误判，而文本比对与「作者是否动过这条用例」直接对齐。
    """
    lines = yaml_text.splitlines()
    starts: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("- id:"):
            cid = stripped[len("- id:"):].strip().strip("\"'")
            starts.append((i, cid))
    blocks: dict[str, str] = {}
    for idx, (i, cid) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        # 末尾的 `traces:`/`verifies:` 属于该用例；下一条 - id: 之前全部归它
        block = "\n".join(lines[i:end]).rstrip() + "\n"
        blocks[cid] = block
    return blocks


def _git_show(rev: str, path: str) -> str | None:
    """`git show <rev>:<path>`（不存在 → None）。"""
    r = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"{rev}:{path}"],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def _diff_files(base: str) -> list[str]:
    """`git diff --name-only <base>...HEAD` 的全部文件（Rule G 用）。"""
    r = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--name-only", f"{base}...HEAD"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git diff 失败（base={base}）：{r.stderr.strip()}")
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def changed_case_files(base: str) -> list[str]:
    """`git diff --name-only <base>...HEAD` 里命中的用例文件（相对路径）。"""
    r = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--name-only", f"{base}...HEAD"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git diff 失败（base={base}）：{r.stderr.strip()}")
    return [ln.strip() for ln in r.stdout.splitlines()
            if ln.strip().startswith(".github/cases/") and ln.strip().endswith(".yml")]


def select_changed_cases(cases: list[dict], changed_ids: set[str]) -> list[dict]:
    """只保留被本次改动/新增的用例条目（**不阻塞存量**）。"""
    return [c for c in cases if str(c.get("id") or "") in changed_ids]


def managed_surface(base: str) -> dict[str, list[str]]:
    """本 PR 触碰的**受管面**（一次 `git diff` 扫描，两个读数都从这里派生）。

    受管面 = ① 用例库目录 `.github/cases/**`（行为用例单一源）② 豁免清单文件
    `.github/case-trust-baseline.json`（债务账本）。两者是**同一件事的两面**：
    改了用例就可能改变判定，改了清单就是动了账本。

    ⚠️ **为什么不各写一份判据**：`burn_down.scope=case_touching_prs` 的「改用例的 PR」
    与「对账基准是否退回分叉点」必须是**同一个 `case_touching` 概念** ——
    再造第三套「算不算碰了用例库」的判据，就必然与 scope 的口径漂移
    （`migao-dev-flow` §19.1：同一个概念两处实现 = 迟早对不上）。
    故这里**一次扫描**给出两个读数，各自的用途写在返回键注释里：

    · `"case_yml"` —— 参与**逐条判定**的用例文件（`.github/cases/*.yml`，与
      `changed_case_files` 同口径）⇒ 同时决定 `burn_down.scope` 是否生效；
    · `"cases_dir"` —— 用例库目录下的**任何**改动（含非 yml）⇒ 参与「受管面」判定；
    · `"baseline"` —— 豁免清单文件的改动。
    """
    files = _diff_files(base)
    baseline_rel = str(BASELINE_PATH.relative_to(REPO_ROOT))
    return {
        "case_yml": [p for p in files
                     if p.startswith(".github/cases/") and p.endswith(".yml")],
        "cases_dir": [p for p in files if p.startswith(".github/cases/")],
        "baseline": [p for p in files if p == baseline_rel],
    }


def merge_base(base: str) -> str | None:
    """`git merge-base <base> HEAD`（取不到 ⇒ None；**不抛**）。

    取不到不是异常路径而是**要如实报告的读数**：浅克隆（`actions/checkout@v7` 默认
    `fetch-depth: 1`）下 merge-base 不可得 ⇒ 调用方必须**退回严格口径并打印出来**
    （fail-closed：不因为拿不到基准就偷偷放宽）。
    """
    r = subprocess.run(["git", "-C", str(REPO_ROOT), "merge-base", base, "HEAD"],
                       capture_output=True, text=True)
    sha = r.stdout.strip()
    return sha if r.returncode == 0 and sha else None


def select_reconcile_base(args_base: str, touched: dict[str, list[str]],
                          main_baseline: dict | None) -> tuple[dict | None, str, str]:
    """选**对账基准**那份清单 → `(baseline, 基准名, 说明)`。

    ## 病灶（实测，2026-09-18）

    纯文档 PR（零用例改动、零清单改动）会因为「基线陈旧」被判红 —— 门禁把**分支里那份**
    清单与**当前 `origin/main`** 比对，于是只要 main 上**别的 PR** prune 过清单，这个 PR
    就"看起来像新增豁免"。实测（`docs/4041-archive`，`--base origin/main`）：

    ```
    ❌ burn-down 预算（生效配置读 base(origin/main)）：…
       本次净变化：条目 135→135（+0），违规码 214→215（+1）
      · 基线**增长**了 … ⇒ 新增豁免（R4）
    ```

    分支里那份 215 码的清单是**它的分叉点状态**（它一个字节都没改），
    214 是 main 侧别人的 prune 结果 ⇒ 判据与被测对象不对齐：**没碰清单的 PR，
    不该替别人的 prune 背「基线增长」的账**（同族 #4140/#4143/#4144/#4151/#4153/#4154）。

    ## 规则（**不是放宽，是纠偏**；两侧都判）

    · **未触碰受管面**（既没改 `.github/cases/**` 也没改豁免清单）⇒ 对账/计数基准取
      **分支分叉点**（`git merge-base <base> HEAD`）那一份。此时 `dropped`
      （「仍在违规却被删掉」）退化成**自我比对**——它本来就无法成立：**一个没改过清单的
      PR 不可能删掉清单里的条目**。`stale` / `unregistered` / 账本自洽三条**与基准无关**
      （只用分支自己那份清单 + 全库重算），照旧生效 ⇒ 「只许收紧」不受影响；
    · **触碰了任一受管面** ⇒ 一律按**当前 `origin/main`** 比（原口径，一个字不松）：
      删条目、偷偷新增豁免、收窄账本全都照旧阻塞；
    · 生效**配置**（per_pr_min / 到期日 / 优先前缀 / metric）**永远**取 `origin/main`
      （由 `burn_down_verdict` 的 `config_baseline` 保证）—— 口径不随分支新旧漂移；
    · merge-base 取不到（浅克隆）⇒ **退回严格口径**并在报告里说明（fail-closed）。
    """
    managed = bool(touched.get("cases_dir") or touched.get("baseline"))
    if managed:
        which = "、".join(sorted([*(touched.get("cases_dir") or []),
                                  *(touched.get("baseline") or [])]))
        return (main_baseline, f"base({args_base})",
                f"本 PR **触碰了受管面**（{which}）⇒ 对账基准 = {args_base}（原口径，一个字不松）")
    sha = merge_base(args_base)
    if not sha:
        return (main_baseline, f"base({args_base})",
                f"⚠️ 未触碰受管面，但 `git merge-base {args_base} HEAD` 取不到"
                f"（浅克隆？）⇒ **退回严格口径** {args_base}（fail-closed，可能对 main 侧 "
                f"prune 误判为「基线增长」，请 checkout 时带 fetch-depth: 0）")
    fork_baseline = load_base_baseline(sha)
    if fork_baseline is None:
        # 分叉点上没有清单 ⇒ 计数基准会是**空账本**（before=0 ⇒ 「只许缩短」退化成恒真）
        # ⇒ 退回严格口径（fail-closed）：宁可按 main 比，也不在空账本上静默通过。
        return (main_baseline, f"base({args_base})",
                f"⚠️ 未触碰受管面，但分叉点 {sha[:7]} 上没有 `case-trust-baseline.json`"
                f"（历史异常）⇒ **退回严格口径** {args_base}（fail-closed：不在空账本上判）")
    return (fork_baseline, f"merge-base({sha[:7]})",
            f"本 PR **未触碰受管面**（用例库目录 + 豁免清单都没改）⇒ 对账/计数基准取"
            f"**分支分叉点** {sha[:7]}（main 侧别人的 prune 不算本次的账）"
            f"；生效配置仍读 {args_base}")


def collect_changed_ids(files: list[str], base: str,
                        cases_dir: Path = CASES_DIR) -> tuple[set[str], dict[str, str]]:
    """对每个变更用例文件，算出「新增或内容变化的用例 ID」+ 其 HEAD 原文。

    返回 `(changed_ids, raw_text_by_id)`。`raw_text` 供规则 c 识别轮次作用域标注。
    """
    changed: set[str] = set()
    raw_by_id: dict[str, str] = {}
    for rel in files:
        p = REPO_ROOT / rel
        if not p.exists():
            continue  # 文件被删除：没有新条目要判
        head_text = p.read_text(encoding="utf-8")
        old_text = _git_show(base, rel) or ""
        head_blocks = _case_blocks(head_text)
        old_blocks = _case_blocks(old_text)
        for cid, block in head_blocks.items():
            if old_blocks.get(cid) != block:
                changed.add(cid)
                raw_by_id[cid] = block
    return changed, raw_by_id


# ══════════════════════════════════════════════════════════════════════════════
# 裁决层
# ══════════════════════════════════════════════════════════════════════════════

def judge_all(cases: list[dict], catalog: dict[str, set[str]],
              raw_by_id: dict[str, str] | None = None) -> list[dict]:
    """逐用例裁决 → [{"case_id", "violations"}]（**只调 taxonomy，不重复实现判据**）。"""
    raw_by_id = raw_by_id or {}
    out = []
    for case in cases:
        cid = str(case.get("id") or "?")
        out.append({
            "case_id": cid,
            "violations": tax.judge_case(case, catalog=catalog,
                                         raw_text=raw_by_id.get(cid)),
        })
    return out


def classify(judged: list[dict], baseline: dict) -> dict:
    """把裁决结果分成「阻塞（新增）」/「放行（存量）」/「陈旧清单项」。

    · 违规码**不在**基线里 ⇒ 新增 ⇒ 阻塞（fail-closed）；
    · 违规码**在**基线里 ⇒ 存量 ⇒ 放行（但打印出来，避免「放行了就没人知道」）。
    ⚠️ 本函数**不管**清单陈旧与否：「记了却不再违规」由 `reconcile_baseline` 做**全库**对账
    （#4031 起不再限定 diff 命中），两者分工不同、都不许省。
    """
    base_violations = baseline.get("violations") or {}
    blocking: list[dict] = []
    passed: list[dict] = []
    for item in judged:
        cid = item["case_id"]
        known = set()
        entry = base_violations.get(cid)
        if isinstance(entry, dict):
            known = set(entry.get("codes") or [])
        elif isinstance(entry, list):
            known = set(entry)
        new_codes = [v for v in item["violations"] if v["code"] not in known]
        old_codes = [v for v in item["violations"] if v["code"] in known]
        if new_codes:
            blocking.append({"case_id": cid, "violations": new_codes})
        if old_codes:
            passed.append({"case_id": cid, "violations": old_codes})
    return {"blocking": blocking, "passed": passed}


def _recorded_codes(entry) -> set[str]:
    """基线条目里的违规码（兼容 `{codes: [...]}` 与裸列表两种形态）。"""
    if isinstance(entry, dict):
        return set(entry.get("codes") or [])
    return set(entry or [])


def load_base_baseline(base: str) -> dict | None:
    """读 `--base`（通常是 `origin/main`）上的基线清单（不存在/读不出 → None）。

    为什么需要它：全量对账要回答两个方向的问题 ——「记了却不再违规」（陈旧）与
    **「原本记了、现在仍违规、却被删掉」**（偷偷新增豁免）。后者只能拿**基线那一份**
    当参照物（本 PR 的清单正是被审对象）。
    """
    text = _git_show(base, str(BASELINE_PATH.relative_to(REPO_ROOT)))
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def reconcile_baseline(baseline: dict, violations_by_case: dict[str, list[dict]],
                       base_baseline: dict | None = None,
                       judged_cases: int | None = None,
                       prune_command: str | None = None,
                       regen_command: str | None = None) -> dict:
    """**全量对账**（#4031）：豁免清单必须与**全库**判定逐条一致，**不限 diff 命中**。

    为什么必须全量（这是「永久豁免」的来源，实证见 #4009 裁定 1）：旧口径把
    「已不再违规 ⇒ 必须移除」限定在 `changed_ids ∩ baseline`，于是**只要没人再碰那条用例**，
    条目就永远躺着 —— 陈旧的违规码成了不会过期的通行证。实测（`git log -p --
    .github/case-trust-baseline.json`）：建账 110 → 加规则涨到 143 → **净缩 1 条后冻结**。

    三个方向（前两个阻塞、第三个只报告，均**如实登记**不静默）：

    · `stale`（阻塞）：记了、但该码在**全库重算**里已不再命中 ⇒ 必须移除/收窄。
      判据用**码级差集**而不是「整条用例零违规」：用例可能「这条码修好了、另一条码还在」
      （实证 `PG-013`：`NO-EFFECT` 已修、`NO-PRECONDITION` 仍在）⇒ 条目该收窄；
    · `dropped`（阻塞）：`--base` 清单里记着、现在**仍命中**，却被本 PR 从清单删掉 ⇒
      **偷偷新增豁免**（R4）。没有这一条，「只许缩短」就退化成「随便删都算缩短」——
      而 burn-down 预算恰恰在施压让人删条目；
    · `unregistered`（**阻塞**，`#4046` 已于本 PR 翻转）：全库判出、清单里没有的码
      （规则集变化 / 用例新增造成）⇒ 本次修掉，或按 R4 开独立 issue 登记。
      翻转前的前置条件 =「存量未登记清零」（`#4078` 修 `PR-026` + 本 PR 修 `PR-025`/`PR-027`
      ⇒ 全库判出 139 == 清单 139）；旧措辞「只报告不阻塞」已撤 —— 与实现相反的注释 = 假真值。

    ⚠️ **判定输入必须与 `--regen-baseline` 同源**（`judge_all(cases, catalog)`，**不传**
    `raw_text`）：基线的码是那条路径算出来的，用另一条路径（diff 路径会传 `raw_text`，
    轮次作用域的 `forbidden_text` 会少报码）对账就会凭空产出「陈旧项」= 假红。
    """
    recorded = {cid: _recorded_codes(e)
                for cid, e in (baseline.get("violations") or {}).items()}
    now = {cid: {v["code"] for v in vs} for cid, vs in violations_by_case.items() if vs}
    # 两个「修法命令」的**可注入**形态（默认 = 本门禁自己的命令；drift_audit 那侧传自己的
    # —— 报错必须指向**能修好它的那个入口**，指错入口比不指更贵）。
    prune_cmd = prune_command or PRUNE_COMMAND
    regen_cmd = regen_command or REGEN_COMMAND

    stale: list[dict] = []
    for cid in sorted(recorded):
        gone = sorted(recorded[cid] - now.get(cid, set()))
        if not gone:
            continue
        stale.append({
            "case_id": cid,
            "removed_codes": gone,
            "now_codes": sorted(now.get(cid, set())),
            "hint": (
                f"{cid} 记的码已不再命中（{'、'.join(gone)}）—— 请从 "
                f"{BASELINE_PATH.relative_to(REPO_ROOT)} 移除（**全量对账**：不再限于本次 diff "
                f"命中，任何条目都必须仍然真的违规）。命令：{prune_cmd}"
            ),
        })

    dropped: list[dict] = []
    for cid in sorted((base_baseline or {}).get("violations") or {}):
        still_hit = _recorded_codes(base_baseline["violations"][cid]) & now.get(cid, set())
        missing = sorted(still_hit - recorded.get(cid, set()))
        if not missing:
            continue
        dropped.append({
            "case_id": cid,
            "dropped_codes": missing,
            "hint": (
                f"{cid} 在 `origin/main` 清单里记着 {('、'.join(missing))}，且该码**现在仍然违规**，"
                f"却被从清单删掉 ⇒ 这是**新增豁免**（基线只许缩短，R4：新违规只有两个出口"
                f"—— 本次修掉 / 开独立 issue）。请恢复该条，或在本次把用例修好。"
            ),
        })

    unregistered = [
        {"case_id": cid, "codes": sorted(now[cid] - recorded.get(cid, set()))}
        for cid in sorted(now) if now[cid] - recorded.get(cid, set())
    ]

    # 账本自洽：`rule_counts` / `violation_case_count` 是从 `violations` 派生的读数，
    # 派生量撒谎 = 假读数（`migao-acceptance`：看板与真相不一致本身就是缺陷）。
    # ⚠️ **报错指引必须指向真能修好它的命令**（实测缺陷）：漂移只发生在派生字段时
    # `--prune-baseline` 旧实现会回「无残留（无需改动）」而门禁照旧红 —— 一条把人
    # 引到死路的报错，比不报还贵（排查 2 轮才发现该用 `--regen-baseline`）。
    # 现在 `--prune-baseline` 自身会重算派生读数（只删不加通道内），故两者都能修好。
    def _derived_fix_hint() -> str:
        """派生读数漂移的修法（**必须指向真能修好它的入口**）。

        实测缺陷：漂移只在派生字段时，旧 `--prune-baseline` 回「无残留（无需改动）」
        而门禁照旧红 ⇒ 报错把人引到死路。现在该入口自身会重算派生读数（只删不加通道内，
        重算若会增长则拒绝写回），故它确实是修法；并给出 `--regen-baseline` 作兜底。
        """
        return (f"{prune_cmd} 重算（该入口**会同时重算派生读数**：`rule_counts` / "
                f"`violation_case_count` / `case_total`，**不动 `burn_down` 与 `anchor_sha`**；"
                f"只删不加、重算若会增长或夹带语义变化会拒绝写回）；"
                f"若它报「无残留」而门禁仍红，用 `{regen_cmd}` 全量重建"
                f"（默认拒绝增长；**它会推进 `anchor_sha`**，那是独立的语义变化）")

    integrity: list[str] = []
    agg: dict[str, int] = {}
    for codes in recorded.values():
        for c in codes:
            agg[c] = agg.get(c, 0) + 1
    rc = baseline.get("rule_counts")
    if isinstance(rc, dict) and {k: v for k, v in rc.items() if v} != agg:
        integrity.append(
            f"rule_counts 与 violations 不一致（派生读数撒谎）："
            f"rule_counts 非零项 {sorted((k, v) for k, v in rc.items() if v)} vs "
            f"violations 实际 {sorted(agg.items())} ⇒ 跑 {_derived_fix_hint()}"
        )
    if isinstance(baseline.get("violation_case_count"), int) \
            and baseline["violation_case_count"] != len(recorded):
        integrity.append(
            f"violation_case_count={baseline['violation_case_count']} 与实际条目数 "
            f"{len(recorded)} 不一致 ⇒ 跑 {_derived_fix_hint()}"
        )

    return {
        "stale": stale,
        "dropped": dropped,
        "unregistered": unregistered,
        "integrity": integrity,
        "judged_cases": judged_cases if judged_cases is not None else len(now),
        "violating_cases": len(now),
        "recorded_entries": len(recorded),
        # `unregistered`（#4046，本 PR 翻转）：全库判出、基线里没有的码
        # ⇒ 阻塞。翻转的前置是「存量未登记清零」（#4078 修 PR-026 + 本 PR 修 PR-025/027
        # ⇒ 全库 判出 139 == 清单 139，未登记 0 条），故此刻翻转不会误伤任何在飞 PR。
        "blocking": bool(stale or dropped or unregistered or integrity),
    }


# ══════════════════════════════════════════════════════════════════════════════
# burn-down 预算（#4031）：清单必须**持续**变短，而不是冻结在某个数
# ══════════════════════════════════════════════════════════════════════════════

def _count_exemptions(baseline: dict) -> tuple[int, int]:
    """返回 `(条目数, 违规码总数)` —— 两个口径都是「豁免面」的真实大小。"""
    v = baseline.get("violations") or {}
    return len(v), sum(len(_recorded_codes(e)) for e in v.values())


def _date(v) -> str:
    """规范化日期（fail-closed：非法日期按**已到期**处理，不静默放行）。"""
    s = str(v or "").strip()
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else "0000-00-00"


def burn_down_verdict(base_baseline: dict | None, baseline: dict, today: str,
                      case_files_touched: bool, label: str = "用例文件",
                      hint_extra: str = "", config_baseline: dict | None = None,
                      count_base: str = "base(origin/main)") -> dict:
    """burn-down 预算裁决（#4009 裁定 1 的第三条）。

    四条判据（都可红 —— 对应的红证在 `.github/case-trust-redproof.md`）：

    1. **只许缩短**：本次相对计数基准的净变化不得为负（条目数与违规码数**都**不得增长）
       —— 增长就是新增豁免（R4）。加规则导致的新违规只有两个出口：本次修掉 / 开独立 issue；
    2. **每 PR 最低消减**：`per_pr_min` 条（`metric` 指定口径）。口径 `scope` **默认
       `case_touching_prs`**（只对改用例的 PR 生效）—— 字面口径（每个 PR，含不改用例的）
       会让**全仓每个 PR 都红**（Java 单测 PR 也得改用例库 + 清单），与「先把清单清干净
       再翻 required、避免阻塞所有人」的顺序铁律自相矛盾。要字面口径就把 `scope` 改成
       `all_prs`（配置是数据，不是代码）；
    3. **`OR-*` 优先到期**：`priority_deadline` 之后清单里不得再有 `priority_prefixes` 条目
       （「先清 OR-*」的机械形态）；
    4. **到期清零**：`deadline` 之后清单必须为空。

    ## `metric` 口径（**本次收紧：`entries_or_codes` → `entries`**）

    · `entries_or_codes`（**旧的宽松口径，已弃用**）：条目数**或**违规码数任一净缩达标即算
      达标。病根 —— **删一个码也算达标**，于是把一条多码条目**收窄**成少码就能过门禁；
      而**收窄 ≠ 修好**（该用例仍然命中违规码，豁免面只是账面变小）⇒ 典型的「为绿而绿」
      （实证：本轮就有多次靠 `--prune-baseline` 掉一个码过门禁）；
    · `entries`（**现行口径**）：只认**整条销账** —— 该用例不再命中任何码、条目真的从清单
      消失才算一条。门槛因此落在「真修到不再违规」，而不是「把账做小」；
    · `codes`：中间档（只认码数），保留给「一条真修不动、另一条已整条修好」的口径讨论；
    · 🔒 **未知 / 缺失的 metric ⇒ 阻塞**（fail-closed）：旧实现 `dict.get(metric, max(...))`
      会把**拼错的** metric 静默降级成最宽松口径（写错一个字母 = 悄悄降低门槛）。

    ## 生效配置与「只许收紧」

    ⚠️ **生效配置读 `--base` 那一份**（`origin/main` 的基线文件）：否则本 PR 把
    `deadline` 往后一挪就本次生效 = 自证式豁免。同时比对「当前 vs base」的配置，
    **四个维度都不得放宽**：`per_pr_min` 变小 / 到期日推后 / 优先前缀被拿掉 /
    **`metric` 放宽**（含「删掉 `metric` 字段」⇒ 回落到默认口径）/ 整个块被删。
    ⚠️ 本函数原先**只**校验前三个维度 —— `metric` 没校验就是一条**不会红的判据**，
    等于把收紧后的门槛又留了个「改成宽松就回退」的后门（本次补上 + 注入式红证）。

    ## 参数语义（`label` / `hint_extra` / `config_baseline`）

    🔗 **复用（单一真相源）**：`scripts/drift_audit.py` 的 burn-down 预算**也调本函数**
    （#4045）—— 它把 `{条目: 计数}` 摊平成同形清单后传 `case_files_touched=<本 PR 改了
    自己的基线/判据面>`。三个可选参数只改**文案措辞**与**计数基准**，判据数字一字不改：
    · `label` = 计入口径的名字（drift_audit 用「判据面」）；
    · `hint_extra` = 该门禁自己的修法提示（默认空 = case-trust 原样，提示语见
      `case-trust-baseline.json` 的 `burn_down._how_to`）；
    · `config_baseline` = **生效配置**的来源（默认 = `base_baseline`）。`main()` 在
      「本 PR 未触碰受管面」时把**计数基准**换成**分叉点**那份清单（见 `main()` 的注释：
      没碰清单的 PR 不该替 main 侧别人的 prune 背「基线增长」的账），但**配置仍取
      `origin/main`** —— 预算口径不随分支新旧漂移，否则陈旧分支会被按旧口径放行。
    · `count_base` = 计数基准的**人类可读名字**（只进报告与失败文案：读者必须能看出
      「135→135」是跟谁比的 —— 基准不说清 = 「没跑」与「跑过」在报告里同形）。
    """
    base_cfg = ((config_baseline if isinstance(config_baseline, dict) else base_baseline)
                or {}).get("burn_down")
    cur_cfg = baseline.get("burn_down")
    eff = base_cfg if isinstance(base_cfg, dict) else cur_cfg
    reasons: list[str] = []
    notes: list[str] = []
    if not isinstance(eff, dict):
        notes.append(
            "⏳ burn-down 预算**未激活**：`--base` 与当前清单里都没有 `burn_down` 块"
            "（机制引入 PR 的合法形态）—— 合并后才对所有后续 PR 生效"
        )
        return {"active": False, "reasons": [], "notes": notes, "blocking": False,
                "net": None, "remaining": None, "priority_remaining": []}

    per_pr_min = int(eff.get("per_pr_min") or 0)
    metric = str(eff.get("metric") or DEFAULT_METRIC)
    scope = str(eff.get("scope") or "case_touching_prs")
    prefixes = [str(p) for p in (eff.get("priority_prefixes") or [])]
    pri_deadline, deadline = _date(eff.get("priority_deadline")), _date(eff.get("deadline"))

    if metric not in METRIC_STRICTNESS:
        reasons.append(
            f"`burn_down.metric`={metric!r} **不是已知口径**（可用：{sorted(METRIC_STRICTNESS)}）"
            f"⇒ fail-closed 阻塞：旧实现会把未知口径**静默降级成最宽松的 max(条目, 码)**，"
            f"写错一个字母就能悄悄降低门槛"
        )

    # ── 配置不得放宽（只能不变或收紧）──
    if isinstance(base_cfg, dict):
        if not isinstance(cur_cfg, dict):
            reasons.append(
                "当前清单**删掉了 `burn_down` 块** ⇒ 放宽预算（R4：预算只能收紧，不能取消）"
            )
        else:
            if int(cur_cfg.get("per_pr_min") or 0) < per_pr_min:
                reasons.append(
                    f"`burn_down.per_pr_min` 由 {per_pr_min} 降到 "
                    f"{cur_cfg.get('per_pr_min')} ⇒ 放宽预算"
                )
            if _date(cur_cfg.get("deadline")) > deadline:
                reasons.append(
                    f"`burn_down.deadline` 由 {deadline} 推到 "
                    f"{_date(cur_cfg.get('deadline'))} ⇒ 放宽预算（到期日只许提前）"
                )
            if _date(cur_cfg.get("priority_deadline")) > pri_deadline:
                reasons.append(
                    f"`burn_down.priority_deadline` 由 {pri_deadline} 推到 "
                    f"{_date(cur_cfg.get('priority_deadline'))} ⇒ 放宽预算"
                )
            lost = [p for p in prefixes if p not in (cur_cfg.get("priority_prefixes") or [])]
            if lost:
                reasons.append(f"`burn_down.priority_prefixes` 去掉了 {lost} ⇒ 放宽预算（先清谁不许改）")
            # 🔒 `metric` 维度的「只许收紧」（本次补上；缺它 = 后端可被改成宽松口径回退）
            # 「删掉/留空 metric」按**默认口径**算（默认仍是宽松档）⇒ 同样命中放宽判定。
            # ⚠️ base 的 metric 未知时**只**由上面那条「未知口径」判（不在这里重复判，
            # 否则会报出「由 ENTRIES 放宽为 entries」这种读不通的话）。
            cur_metric = str(cur_cfg.get("metric") or DEFAULT_METRIC)
            if metric in METRIC_STRICTNESS \
                    and METRIC_STRICTNESS.get(cur_metric, -1) < METRIC_STRICTNESS[metric]:
                reasons.append(
                    f"`burn_down.metric` 由 {metric}（严格度 "
                    f"{METRIC_STRICTNESS[metric]}）放宽为 {cur_metric}（严格度 "
                    f"{METRIC_STRICTNESS.get(cur_metric, -1)}）⇒ 放宽预算："
                    f"`entries` 认「整条销账」，放宽回 `entries_or_codes` 后"
                    f"**删一个码就能过门禁**（收窄 ≠ 修好）；填未知口径同样按放宽处理"
                )

    before_e, before_c = _count_exemptions(base_baseline or {})
    after_e, after_c = _count_exemptions(baseline)
    net_e, net_c = before_e - after_e, before_c - after_c
    priority_remaining = sorted(cid for cid in (baseline.get("violations") or {})
                               if any(cid.startswith(p) for p in prefixes))

    if net_e < 0 or net_c < 0:
        reasons.append(
            f"基线**增长**了（条目 {before_e}→{after_e}，违规码 {before_c}→{after_c}）⇒ 新增豁免（R4）："
            "新违规只有两个出口 —— 本次修掉 / 开独立 issue 登记，**不得**记进豁免清单"
            + (f"（计数基准 = {count_base}；本 PR 未触碰受管面 ⇒ 基准取分支分叉点，"
               f"main 侧别人的 prune 不算本次的账）" if count_base.startswith("merge-base")
               else "")
        )

    in_scope = (scope == "all_prs") or (scope == "case_touching_prs" and case_files_touched)
    if in_scope and after_e > 0:
        got = ({"entries": net_e, "codes": net_c,
                "entries_or_codes": max(net_e, net_c)}.get(metric, net_e))
        if got < per_pr_min:
            reasons.append(
                f"burn-down 预算未达标：本次净消减 {got} 条（metric={metric}）< 每 PR 最低 "
                f"{per_pr_min} 条（条目 {before_e}→{after_e}，违规码 {before_c}→{after_c}）。"
                + (f"⚠️ metric=entries ⇒ **收窄不算**：只删掉一条多码条目里的一个码"
                   f"（本次净变化 码 {net_c:+d}／条目 {net_e:+d}）**不计分**，"
                   f"必须整条销账（该用例不再命中任何码）"
                   if metric == "entries" and net_c > net_e else "")
                + f"按**只许缩短**修掉 ≥{per_pr_min} 条存量违规"
                + (hint_extra or
                   f"（修法见 .github/case-trust-baseline.json 的 burn_down._how_to）")
                + f"，**先清 `{('、'.join(prefixes) or '—')}`**（现剩 {len(priority_remaining)} 条）"
            )
    elif not in_scope:
        notes.append(
            f"ℹ️ 本次未改 {label} ⇒ 「每 PR 最低消减」不适用"
            f"（`scope={scope}`；到期清零与只许缩短**仍然**生效）"
        )

    if pri_deadline and today >= pri_deadline and priority_remaining:
        reasons.append(
            f"`{'/'.join(prefixes)}` 优先档已到期（{pri_deadline} ≤ {today}，先清 OR-*）："
            f"清单里仍有 {len(priority_remaining)} 条 —— {('、'.join(priority_remaining[:8]))}"
            + ("…" if len(priority_remaining) > 8 else "")
        )
    if deadline and today >= deadline and after_e > 0:
        reasons.append(
            f"burn-down **到期清零**未达成（{deadline} ≤ {today}）：清单里仍有 {after_e} 条"
            f"（违规码 {after_c} 条）必须清零"
        )

    if in_scope and after_e == 0:
        notes.append("✅ 清单已清零（豁免面为 0）—— 「每 PR 最低消减」自动满足")

    return {
        "active": True,
        "source": "base(origin/main)" if isinstance(base_cfg, dict) else "本 PR 清单",
        "count_base": count_base,
        "config": {"per_pr_min": per_pr_min, "metric": metric, "scope": scope,
                   "priority_prefixes": prefixes, "priority_deadline": pri_deadline,
                   "deadline": deadline},
        "net": {"entries": [before_e, after_e], "codes": [before_c, after_c]},
        "remaining": {"entries": after_e, "codes": after_c},
        "priority_remaining": priority_remaining,
        "in_scope": in_scope,
        "today": today,
        "reasons": reasons,
        "notes": notes,
        "blocking": bool(reasons),
    }


# 内容缓存：**必须与路径解析缓存分开**。两者键空间与**值类型**都不同
# （解析缓存 raw→repo 相对路径；内容缓存 repo 相对路径→行列表），
# 共用一个 dict 会互相污染 —— 实测初版即踩：`git show` 失败后返回 None，
# 而错误信息里的行数取自被解析结果顶掉的缓存项，报出「只有 32 行」这类**假读数**，
# 把合法引用误判成「行号越界」（典型的假红，且读数自相矛盾）。
_ORIGIN_LINES_CACHE: dict[tuple[str, str], list[str] | None] = {}


def origin_main_lines(path: str, base: str = "origin/main") -> list[str] | None:
    """读 `origin/main` 上某文件的全部行（不存在 → None）。带缓存，避免反复起 git 进程。"""
    key = (base, path)
    if key in _ORIGIN_LINES_CACHE:
        return _ORIGIN_LINES_CACHE[key]
    r = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{base}:{path}"],
        capture_output=True, text=True)
    val = r.stdout.splitlines() if r.returncode == 0 else None
    _ORIGIN_LINES_CACHE[key] = val
    return val


# 规则 G 的**自指豁免**：本门禁自己的实现/测试/红证留档里必然出现「故意不存在的路径」
# 与「行为用例形态的 path:NNN」—— 那些是**夹具与说明**，不是仓库引用。
# 不豁免就会自己判自己红（实测：初版 E2E 直接产出 11 条误报）。
_REF_EXEMPT_FILES: frozenset[str] = frozenset({
    ".github/case_trust_gate.py",
    ".github/case-trust-redproof.md",
    "tests/unit_ci_workflows/test_case_trust_gate.py",
})
# 明显不是仓库引用路径的形态（夹具/占位符）—— 只在**无法解析**时才用来降噪
_PLACEHOLDER_PATH_RE = re.compile(
    r"^(no/such|a/b\.py|x/y|foo/bar|path/to|\.\.\.|<)", re.IGNORECASE)


def _resolve_repo_path(path: str, base: str, cache: dict) -> str | None:
    """把引用里的路径解析成**仓库相对路径**（解析不到 → None）。

    支持三种写法（仓库里三种都真实存在）：
      ① 仓库相对全路径：`tests/agent_eval/local_runner.py:2000`；
      ② **裸文件名**：`local_runner.py:2000`（`aftersales.yml` 的注释就这么写）——
         按 basename 在仓库里唯一匹配（`git ls-files`）；
      ③ 带目录但省略前缀：逐个后缀匹配 `git ls-files`。
    """
    if path in cache:
        return cache[path]
    r = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "--", path],
                       capture_output=True, text=True)
    hits = [x for x in r.stdout.splitlines() if x.strip()] if r.returncode == 0 else []
    resolved = hits[0] if len(hits) == 1 else None
    if resolved is None and len(hits) > 1:
        # 多命中：优先精确相对路径，其次唯一的 basename
        exact = [h for h in hits if h == path]
        if exact:
            resolved = exact[0]
        else:
            same_base = [h for h in hits if h.endswith("/" + path) or h == path]
            if len(same_base) == 1:
                resolved = same_base[0]
    if resolved is None:
        base_name = path.rsplit("/", 1)[-1]
        r2 = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "--", f"*{base_name}"],
                            capture_output=True, text=True)
        cands = [x for x in r2.stdout.splitlines() if x.strip()]
        if len(cands) == 1:
            resolved = cands[0]
    cache[path] = resolved
    return resolved


def check_reference_freshness_in_diff(files: list[str], base: str = "origin/main") -> dict:
    """规则 G：扫本次 diff 新增/修改的 `path:NNN` 引用，核 `origin/main` 是否命中。

    三条降噪纪律（缺任一条都会产出**误报**）：
      ① **只扫本次新增/改动行**（不把存量过期引用算到本 PR 头上）；
      ② **豁免门禁自身的实现/测试/红证留档**（那里的「不存在路径」是夹具）；
      ③ **先去重、再解析路径**（裸文件名按 basename 唯一匹配；`git ls-files` 解析不到的
         占位符形态直接丢弃，不算引用）。
    返回 `tax.check_reference_freshness` 的结果，外加 `scanned_files` / `skipped_placeholders`。
    """
    cache: dict = {}
    refs: list[dict] = []
    scanned: list[str] = []
    skipped: list[str] = []
    seen: set[tuple[str, int]] = set()
    for rel in files:
        p = REPO_ROOT / rel
        if not p.exists():
            continue
        scanned.append(rel)
        if rel in _REF_EXEMPT_FILES:
            continue
        text = p.read_text(encoding="utf-8")
        old = _git_show(base, rel) or ""
        old_lines = set(old.splitlines())
        for ln in text.splitlines():
            if ln in old_lines and ln.strip():
                continue
            for raw in tax.find_path_line_refs(ln):
                path = raw["path"]
                resolved = _resolve_repo_path(path, base, cache)
                if resolved is None:
                    # 解析不到：占位符形态直接丢弃（不是仓库引用）；其余保留为阻塞候选
                    if _PLACEHOLDER_PATH_RE.match(path):
                        skipped.append(path)
                        continue
                    refs.append(raw)
                    seen.add((path, raw["line"]))
                    continue
                key = (resolved, raw["line"])
                if key in seen:
                    continue
                seen.add(key)
                refs.append({**raw, "path": resolved})
    res = tax.check_reference_freshness(refs, lambda path: origin_main_lines(path, base))
    res["scanned_files"] = scanned
    res["ref_count"] = len(refs)
    res["skipped_placeholders"] = sorted(set(skipped))
    return res


# ══════════════════════════════════════════════════════════════════════════════
# 输出层
# ══════════════════════════════════════════════════════════════════════════════

def render_report(blocking: list[dict], passed: list[dict], stale: list[dict],
                  changed_ids: set[str], unimplemented: list[dict],
                  refs: dict | None = None, recon: dict | None = None,
                  budget: dict | None = None,
                  unimpl_guard: dict | None = None) -> str:
    """人类/agent 可读的失败报告 —— **每条都带「怎么改」**。"""
    out: list[str] = []
    out.append("═══ 断言可信度门禁（假红/假绿结构性护栏 A 层，单一判据源 "
               "= .github/assertion_taxonomy.py）═══")
    out.append(f"本次改动命中的用例条目：{len(changed_ids)} 条"
               f"（{'、'.join(sorted(changed_ids)) if changed_ids else '无'}）")
    if recon:
        out.append(f"全量对账范围：**全库 {recon['judged_cases']} 条用例**重算"
                   f"（判出违规 {recon['violating_cases']} 条，豁免清单 {recon['recorded_entries']} 条"
                   f" —— 不限本次 diff 命中，#4031）")
    if recon and recon.get("base_note"):
        out.append(f"对账基准：{recon['base_note']}")
    if blocking:
        out.append("")
        out.append(f"❌ 新增违规 {sum(len(b['violations']) for b in blocking)} 条"
                   f"（**阻塞** —— 不在基线清单里）：")
        for b in blocking:
            for v in b["violations"]:
                rule = tax.RULES_BY_CODE.get(v["code"], {})
                out.append("")
                out.append(f"  · [{v['code']}] {b['case_id']} — {rule.get('title', '')}")
                out.append(f"    现象：{v['detail']}")
                out.append(f"    为什么算缺陷：{rule.get('why', '')}")
                out.append(f"    怎么改：{v.get('fix') or rule.get('fix', '')}")
    if stale:
        out.append("")
        out.append(f"❌ 豁免清单**已不再违规** {len(stale)} 条（**阻塞** —— 全量对账："
                   f"「清单只许缩短」的执行，#4031）：")
        for s in stale:
            out.append(f"  · {s['case_id']}（应移除 {', '.join(s['removed_codes'])}"
                       f"{'；该条目清空 ⇒ 整条删除' if not s['now_codes'] else '；该条目收窄'}）")
            out.append(f"    {s['hint']}")
    for d in (recon or {}).get("dropped") or []:
        out.append("")
        out.append(f"❌ 仍在违规的条目被从清单**删掉**（**阻塞** —— 那是新增豁免，R4）：")
        out.append(f"  · {d['case_id']}：{', '.join(d['dropped_codes'])}")
        out.append(f"    {d['hint']}")
    for msg in (recon or {}).get("integrity") or []:
        out.append("")
        out.append(f"❌ 账本不自洽（**阻塞** —— 派生读数撒谎 = 假读数）：{msg}")
    if budget and budget.get("active"):
        cfg = budget["config"]
        out.append("")
        head = (f"burn-down 预算（生效配置读 {budget['source']}）：每 PR ≥ {cfg['per_pr_min']} 条"
                f"（metric={cfg['metric']}，scope={cfg['scope']}）"
                f"｜ 优先档 {'/'.join(cfg['priority_prefixes']) or '—'} 到期 {cfg['priority_deadline']}"
                f"｜ 全清单清零 {cfg['deadline']}｜ 今天 {budget['today']}")
        out.append(("❌ " if budget["blocking"] else "ℹ️ ") + head)
        ne, nc = budget["net"]["entries"], budget["net"]["codes"]
        out.append(f"   本次净变化：条目 {ne[0]}→{ne[1]}（{ne[1] - ne[0]:+d}），"
                   f"违规码 {nc[0]}→{nc[1]}（{nc[1] - nc[0]:+d}）；"
                   f"剩余 {budget['remaining']['entries']} 条"
                   f"／码 {budget['remaining']['codes']}")
        if budget["priority_remaining"]:
            show = budget["priority_remaining"][:8]
            out.append(f"   先清 {'/'.join(cfg['priority_prefixes'])}：剩 "
                       f"{len(budget['priority_remaining'])} 条 —— {'、'.join(show)}"
                       + ("…" if len(budget["priority_remaining"]) > 8 else ""))
        for r in budget["reasons"]:
            out.append(f"  · {r}")
    if recon and (recon.get("unregistered") or []):
        out.append("")
        out.append(f"❌ 未登记违规 {len(recon['unregistered'])} 条（**阻塞** —— 基线里没有、"
                   f"全库判出）：")
        for u in recon["unregistered"][:10]:
            out.append(f"  · {u['case_id']}：{'、'.join(u['codes'])}")
        if len(recon["unregistered"]) > 10:
            out.append(f"  · …共 {len(recon['unregistered'])} 条")
        out.append("    怎么改（#4046：本口径已 fail-closed，前置「存量未登记清零」"
                   "由 #4078 + 本 PR 完成）：**本次把用例修掉**；确属需要入账的新违规，"
                   "按 R4 开独立 issue 登记后再由裁定决定 —— 未登记一律阻塞，"
                   "不许静默躺在基线外（「不会红的判据」的另一种形态）。")
    if passed:
        out.append("")
        out.append(f"ℹ️ 存量违规放行 {sum(len(p['violations']) for p in passed)} 条"
                   f"（在基线清单里，不阻塞本次）：")
        for p in passed:
            codes = "、".join(v["code"] for v in p["violations"])
            out.append(f"  · {p['case_id']}：{codes}")
    if refs and (refs.get("ref_count") or refs.get("warnings")):
        warn_refs = refs.get("warnings") or []
        out.append("")
        out.append(f"ℹ️ 引用新鲜度（规则 G）：本次新增/改动行里 {refs.get('ref_count', 0)} 处 "
                   f"`path:NNN` 引用，已核对 `origin/main`"
                   + (f"；**行号漂移 {len(warn_refs)} 处**（不阻塞，建议换符号锚点）："
                      if warn_refs else "；无漂移。"))
        for w in warn_refs:
            out.append(f"  · `{w['raw']}` 第 {w['line']} 行 — {w['reason']}")
    if unimplemented:
        out.append("")
        out.append(f"⚠️ 未实装规则 {len(unimplemented)} 条（**如实登记**，"
                   f"见 .github/case-trust-unimplemented.json）：")
        for u in unimplemented:
            out.append(f"  · [{u['code']}] {u['title']}")
            out.append(f"    为什么不实装：{u['why_not']}")
            out.append(f"    缺什么：{u['needs']}")
            ev = (unimpl_guard or {}).get("evidence", {}).get(u["code"])
            out.append(f"    约束：追踪单 #{u.get('issue')}"
                       f"｜到期 {u.get('expires')}"
                       f"｜僵尸判据 {u.get('hit_probe')}"
                       f"（存活证据 {len(ev) if ev is not None else '?'} 项"
                       f"{'，如 ' + ev[0] if ev else ''}）")
            out.append(f"    怎么算已实装：{u.get('how_to_verify')}")
    if unimpl_guard is not None:
        guard = unimpl_guard
        if guard.get("violations") or guard.get("sync") or guard.get("closed"):
            out.append("")
            out.append(f"❌ 未实装登记不合规 {len(guard.get('violations') or []) + len(guard.get('sync') or []) + len(guard.get('closed') or [])} 条"
                       f"（**阻塞** —— 「未实装」不许当永久借口）：")
            for v in guard.get("violations") or []:
                out.append(f"  · [{v['code']}] {v['entry']}：{v['detail']}")
                out.append(f"    怎么改：{v['fix']}")
            for msg in guard.get("sync") or []:
                out.append(f"  · [{tax.UNIMPLEMENTED_VIOLATION_CODES['MISSING_FIELD']['code']}] "
                           f"（同源）{msg}")
            for c in guard.get("closed") or []:
                spec = tax.UNIMPLEMENTED_VIOLATION_CODES["ISSUE_CLOSED"]
                out.append(f"  · [{spec['code']}] {c['detail']}")
                out.append(f"    怎么改：{spec['fix']}")
        if guard.get("checked"):
            # 「跑了」也要长得像「跑了」：否则「5 条都核过且都是 OPEN」与「压根没跑」
            # 在报告里同形（同族：§16.7 禁空跑的第二面）。
            out.append("")
            out.append(f"✅ 追踪单状态已核 {guard['checked']} 条，全部 **OPEN**"
                       f"（无 CLOSED 借口；判据 = 公开仓库匿名 API）")
        if guard.get("unverifiable"):
            out.append("")
            out.append(f"⏭️ 未跑判定：{len(guard['unverifiable'])} 条登记的追踪单状态**查不到**"
                       f"（本门禁唯一的网络格；已查 {guard.get('checked', 0)} 条）"
                       f"—— **不是「通过」**：")
            for u in guard["unverifiable"]:
                out.append(f"  · {u}")
            out.append("    为什么不判红：网络抖动/匿名限额不该制造假红；"
                       "但**也不静默** —— 需要断开网络就绕过这条判据的口子，"
                       "由「到期即红」与「僵尸即红」两条**零网络**判据兜住。")
    for n in (budget or {}).get("notes") or []:
        out.append("")
        out.append(n)
    out.append("")
    blocked = bool(blocking or stale
                   or (recon or {}).get("blocking") or (budget or {}).get("blocking")
                   or (unimpl_guard or {}).get("blocking"))
    out.append("❌ 阻塞（见上）" if blocked else "✅ 通过")
    return "\n".join(out)


def render_regen_report(catalog: dict, cases: list[dict], anchor_sha: str,
                        previous: dict | None = None) -> dict:
    """生成基线清单内容（`--regen-baseline`）。"""
    results = judge_all(cases, catalog)
    violations: dict[str, dict] = {}
    rule_counts: dict[str, int] = {r["code"]: 0 for r in tax.RULES}
    for item in results:
        if not item["violations"]:
            continue
        codes = sorted({v["code"] for v in item["violations"]})
        violations[item["case_id"]] = {"codes": codes}
        for c in codes:
            rule_counts[c] = rule_counts.get(c, 0) + 1
    # burn-down 预算**必须跨重生成存活**（否则「重建一次」就把预算刷没了 = 自证式放宽）。
    burn_down = (previous or {}).get("burn_down")
    data = {
        "_comment": (
            "断言可信度门禁的**存量**违规清单（burn-down）。"
            "锚定 SHA 见 anchor_sha —— 计数是「该 SHA 上按 taxonomy 判出的存量违规」，"
            "**不是**『这些用例永远豁免』。"
            "`violations` 是**活账本**：每次门禁运行都对**全库**重算并逐条对账"
            "（#4031 全量对账）—— 记了却不再违规 ⇒ 阻塞要求移除；"
            "仍在违规却被删掉 ⇒ 阻塞（新增豁免）。"
        ),
        "_generated_by": REGEN_COMMAND,
        "regenerate_command": REGEN_COMMAND,
        "prune_command": PRUNE_COMMAND,
        "_when_to_regen": (
            "① 口径变化（taxonomy 新增/改名规则、种子真值大改）⇒ 全量重建（默认拒绝增长）；"
            "② 只是**别人修好了若干条**（清单该变短）⇒ 别重建，用 `--prune-baseline`（只删不加），"
            "或按门禁报错逐条删；③ 清单增长 = 新增豁免（R4 禁止）—— 新违规只有两个出口："
            "本次修掉 / 开独立 issue。"
        ),
        "_scope_note": (
            "**全量对账**（#4031 / #4009 裁定 1）：清单里**任何**已不再违规的条目一律阻塞要求移除"
            "（不再限定「本次 PR diff 命中的用例」）—— 旧口径正是「永久豁免」的来源"
            "（建账 110 → 加规则涨到 143 → 净缩 1 条后冻结）。"
            "反向也判：`origin/main` 记着、现在仍违规、却被删掉的条目 ⇒ 阻塞（偷偷新增豁免）。"
        ),
        "anchor_sha": anchor_sha,
        "case_total": len(cases),
        "violation_case_count": len(violations),
        "rule_counts": rule_counts,
        "violations": dict(sorted(violations.items())),
    }
    if isinstance(burn_down, dict):
        data["burn_down"] = burn_down
    return data


def derived_growth_guard(old: dict, new: dict) -> list[str]:
    """重算派生读数时的**只许收紧 + 语义不动**守卫：违反任一条 ⇒ 返回拒绝理由（fail-closed）。

    允许被重算的**只有三个纯派生字段**：`rule_counts` / `violation_case_count` / `case_total`
    （它们完全由 `violations` + 用例库派生 ⇒ 重算**不改变事实**）。

    为什么单独成函数：`--prune-baseline` 与「重算派生读数」共用一个写入口，而**写回派生读数**
    这件事必须证明「没有引入增长、也没有夹带语义变化」—— 不能靠「构造上不会」的口头保证
    （那是「基于错误真相模型写的护栏」）。可注入的纯函数 ⇒ 每种违反都有确定性红证。

    四类拒绝理由：
      ① **增长**（条目/码）⇒ 那不是「重算读数」，是在放宽豁免面；
      ② `case_total` 变小 ⇒ 意味着「用例被删」，属另一个裁定面；
      ③ **夹带语义变化**：`burn_down`（预算配置）被改动 ⇒ 拒绝（口径只能由显式收紧动作改）；
      ④ **夹带语义变化**：`anchor_sha`（账本锚点）被推进 ⇒ 拒绝 ——「锚点前移」是**独立的
         语义变化**（账本改锚到另一个 main），必须由 `--regen-baseline` 这种显式动作完成
         并**打印出来**，不许混在一条「重算读数」的提交里悄悄发生（那正是「为绿而绿」最爱藏的地方）。
    """
    reasons: list[str] = []
    old_e, old_c = _count_exemptions(old or {})
    new_e, new_c = _count_exemptions(new or {})
    if new_e > old_e:
        reasons.append(f"条目数会**增长**（{old_e} → {new_e}）")
    if new_c > old_c:
        reasons.append(f"违规码数会**增长**（{old_c} → {new_c}）")
    if isinstance(old.get("case_total"), int) and isinstance(new.get("case_total"), int) \
            and new["case_total"] < old["case_total"]:
        # 用例总数是**事实读数**：它变小意味着「用例被删」——那是另一个裁定面，
        # 不许由「重算派生读数」这条通道悄悄发生。
        reasons.append(f"`case_total` 会**变小**（{old['case_total']} → {new['case_total']}）")
    if (old or {}).get("burn_down") != (new or {}).get("burn_down"):
        reasons.append(
            "`burn_down` 会被改动 ⇒ 拒绝：预算配置只能由**显式的收紧动作**改"
            "（重算派生读数不改口径）"
        )
    if (old or {}).get("anchor_sha") != (new or {}).get("anchor_sha"):
        reasons.append(
            f"`anchor_sha` 会被推进（{(old or {}).get('anchor_sha')} → "
            f"{(new or {}).get('anchor_sha')}）⇒ 拒绝：**锚点前移是独立的语义变化**"
            f"（账本改锚到另一个 main），必须由 `--regen-baseline` 显式完成并打印，"
            f"不许夹带在「重算派生读数」里"
        )
    return reasons


def render_pruned_baseline(baseline: dict, violations_by_case: dict[str, list[dict]],
                           case_total: int | None = None) -> tuple[dict, list[dict]]:
    """全量对账的**机械修复**：删掉「已不再命中」的码/条目，**只删不加**。

    为什么不直接 `--regen-baseline`：重建会把「全库判出的新违规」一并**记进**清单
    （= 新增豁免，R4 禁止），而这里的唯一目标是「清单只许缩短」。
    """
    recorded = {cid: _recorded_codes(e) for cid, e in (baseline.get("violations") or {}).items()}
    now = {cid: {v["code"] for v in vs} for cid, vs in violations_by_case.items() if vs}
    new_violations: dict[str, dict] = {}
    removed: list[dict] = []
    for cid in sorted(recorded):
        gone = sorted(recorded[cid] - now.get(cid, set()))
        if gone:
            removed.append({"case_id": cid, "removed_codes": gone})
        keep = sorted(recorded[cid] & now.get(cid, set()))
        if keep:
            new_violations[cid] = {"codes": keep}
    new = dict(baseline)
    new["violations"] = new_violations
    new["violation_case_count"] = len(new_violations)
    rule_counts = {r["code"]: 0 for r in tax.RULES}
    for entry in new_violations.values():
        for c in entry["codes"]:
            rule_counts[c] = rule_counts.get(c, 0) + 1
    new["rule_counts"] = rule_counts
    if case_total is not None:
        new["case_total"] = case_total
    return new, removed


def write_unimplemented_manifest(path: Path = UNIMPLEMENTED_PATH) -> dict:
    """把 taxonomy 的未实装清单落盘（供人读 + 让「未实装」这件事可见）。

    ⚠️ 落盘内容与 `tax.UNIMPLEMENTED` **必须同源**：门禁会比对两者
    （`unimplemented_sync_issues`），不同源即红 —— 否则判据读 A、人读 B。
    """
    data = {
        "_comment": (
            "断言可信度护栏的**未实装项**（如实登记）。"
            "红线：判据在现有机制下无法判定时，**不得**写成恒真判断凑数 —— 登记在此，"
            "写明缺什么。"
        ),
        "_source": ".github/assertion_taxonomy.py 的 UNIMPLEMENTED",
        "_constraints": (
            "**每条登记必须带 `issue`（正整数追踪号）/ `expires`（YYYY-MM-DD）/ "
            "`how_to_verify`（怎么算已实装的可执行判据/命令）/ `hit_probe`（僵尸判据）。**"
            "四条判据都可红（判据本体 = assertion_taxonomy.judge_unimplemented，"
            "门禁壳 = case_trust_gate.judge_unimplemented_manifest）："
            "① 缺任一字段 ⇒ 红（指名缺哪个）；② `expires` 已过 ⇒ 红（到期未实装**不许静默续期**）；"
            "③ `issue` 指向的单已 CLOSED（或编号不存在）⇒ 红（借口不能过期不销："
            "实装了就该撤登记，没实装就该开新单）；④ **僵尸登记** ⇒ 红"
            "（`hit_probe` 探不到存活证据 = 登记所述口径已不成立，留着会被读成「还没做」）。"
            "`why_not`/`needs` 只是理由与缺口，**不构成约束**。"
        ),
        "unimplemented": list(tax.UNIMPLEMENTED),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


# ══════════════════════════════════════════════════════════════════════════════
# 未实装登记的裁决（本次收紧）：字段 / 到期 / 僵尸 + issue CLOSED（网络格）
# ══════════════════════════════════════════════════════════════════════════════
#
# 判据**本体**在 `.github/assertion_taxonomy.py` 的 `judge_unimplemented()`（纯函数），
# 本段只做三件外壳的事：① 读登记清单与探针所需的输入；② 查追踪单状态（唯一网络格）；
# ③ 把结论交给报告层。为什么必须收紧：登记原来只有 `why_not`/`needs` 两个自由文本
# ⇒ **可以永久当借口**（无追踪号、无到期日、无「怎么算已实装」）。

GITHUB_REPO = "zhaokai-mgzn/migao"  # 公开仓库 ⇒ 匿名 API 可读 issue 状态（无需 token/gh）
ISSUE_API = "https://api.github.com/repos/{repo}/issues/{n}"


def load_unimplemented(path: Path | str = UNIMPLEMENTED_PATH) -> list[dict]:
    """读未实装登记清单（fail-closed：缺失/坏 JSON/结构不对 ⇒ 抛，由 `main` 判红）。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"未实装登记清单缺失：{p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    entries = data.get("unimplemented")
    if not isinstance(entries, list):
        raise ValueError(f"未实装登记清单结构不对（缺 `unimplemented` 数组）：{p}")
    return entries


def unimplemented_probe_context(cases: list[dict], baseline: dict,
                                repo_root: Path = REPO_ROOT) -> dict:
    """给 taxonomy 的**纯**探针取数（所有 IO 留在门禁这一侧）。

    `drift_audit_source` 取不到时给 `None`（探针按**存活**处理并如实说明）——
    绝不把「读不到文件」静默读成「已实装 ⇒ 僵尸」（那会凭空判红一个别人的包）。
    """
    drift = repo_root / "scripts" / "drift_audit.py"
    try:
        drift_src: str | None = drift.read_text(encoding="utf-8")
    except OSError:
        drift_src = None
    return {"cases": cases, "baseline": baseline, "drift_audit_source": drift_src}


def unimplemented_sync_issues(entries: list[dict], taxonomy_entries) -> list[str]:
    """登记清单必须与 `tax.UNIMPLEMENTED` **同源**（`_source` 字段的机械形态）。

    病根：若只改一处，判据读的是 A、人读的是 B —— 两处口径立刻分叉
    （与「基线与用例必须同源」同一族）。比较用**规范化 JSON**（键序无关）。
    """
    a = json.dumps(entries, ensure_ascii=False, sort_keys=True)
    b = json.dumps(list(taxonomy_entries), ensure_ascii=False, sort_keys=True)
    if a == b:
        return []
    only_file = {str(e.get("code")) for e in entries} - {str(e.get("code")) for e in taxonomy_entries}
    only_tax = {str(e.get("code")) for e in taxonomy_entries} - {str(e.get("code")) for e in entries}
    return [
        "未实装登记清单与 `.github/assertion_taxonomy.py` 的 `UNIMPLEMENTED` **不同源**"
        f"（只在该文件：{sorted(only_file) or '—'}；只在 taxonomy：{sorted(only_tax) or '—'}；"
        "同码但字段不同也会命中）⇒ 判据读的与人读的必须是同一份："
        "改 taxonomy 后跑 `write_unimplemented_manifest()` 落盘"
    ]


def _fetch_issue_state(issue: int, timeout: float = 10.0) -> tuple[bool, str]:
    """查 issue 状态 → `(ok, "open"/"closed"/"missing" | 失败原因)`。

    **为什么用匿名 HTTP 而不是 `gh`**：仓库是 public ⇒ 匿名 API 可读，而 CI 的
    `case-trust-gate` job **没有** GH_TOKEN（`gh` 会直接拒绝：「please run gh auth login」）
    ⇒ 用 gh 会让这条判据在 CI 里永远「未跑」（= 一条不会红的判据）。
    匿名限额 60 次/小时/IP，本门禁最多 5 次 ⇒ 通常够；拿不到时**如实报「未跑」**，
    绝不谎报通过（同族：`.github/llm_sink_check.py` 的「不可用 ⇒ 3，绝不谎报」）。
    """
    import urllib.error
    import urllib.request
    url = ISSUE_API.format(repo=GITHUB_REPO, n=int(issue))
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "migao-case-trust-gate",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return True, "missing"
        return False, f"HTTP {e.code}（{url}）"
    except Exception as e:  # 网络不可达/DNS/超时/解析失败 —— 一律「未跑」，不谎报
        return False, f"{type(e).__name__}: {e}"
    return True, str(data.get("state") or "unknown").lower()


# 可注入：L0 测试用假 fetcher 造「已 CLOSED / 取不到」的红证（不依赖网络）。
ISSUE_STATE_FETCHER = _fetch_issue_state


def check_unimplemented_issues(entries: list[dict],
                               fetcher=None) -> dict:
    """`issue` 指向的追踪单**已 CLOSED** ⇒ 阻塞（「借口不能过期不销」）。

    三态照实读（`migao-dev-flow` §16.7：**「没跑」必须长得像「没跑」**）：
      · `closed` / `missing`（编号不存在 = 笔误/假借口）⇒ **阻塞**；
      · `open` ⇒ 通过；
      · 取不到（无网络 / 限额 / 超时）⇒ `unverifiable`，报告里打印
        `⏭️ 未跑判定 … 不是「通过」`，**不**因此判红（网络抖动不该制造假红）——
        但也不静默：它是本门禁**唯一**的网络格，取不到必须看得见。
    """
    fetch = fetcher or ISSUE_STATE_FETCHER
    closed: list[dict] = []
    unverifiable: list[str] = []
    checked = 0
    for item in entries or []:
        issue = (item or {}).get("issue")
        code = str((item or {}).get("code") or "?")
        if isinstance(issue, bool) or not isinstance(issue, int) or issue <= 0:
            continue  # 非法 issue 由 taxonomy 的 MISSING_FIELD 判（这里不重复判、不崩）
        ok, state = fetch(issue)
        if not ok:
            unverifiable.append(f"{code}（#{issue}）：{state}")
            continue
        checked += 1
        if state == "closed":
            closed.append({"entry": code, "issue": issue,
                           "detail": f"登记 {code} 的追踪单 #{issue} 已 **CLOSED** —— "
                                     f"借口不能过期不销：实装了就该撤登记，没实装就该开新单"})
        elif state == "missing":
            closed.append({"entry": code, "issue": issue,
                           "detail": f"登记 {code} 的追踪单 #{issue} **不存在**（编号笔误？）——"
                                     f"指向不存在的单 = 假借口"})
    return {"closed": closed, "unverifiable": unverifiable, "checked": checked}


def judge_unimplemented_manifest(path: Path | str = UNIMPLEMENTED_PATH, *,
                                 today: str, cases: list[dict], baseline: dict,
                                 issue_check: bool = True,
                                 fetcher=None) -> dict:
    """门禁侧的「取数 → 裁决」外壳（判据本体在 taxonomy，本函数不复制判据）。"""
    try:
        entries = load_unimplemented(path)
    except Exception as e:
        return {"violations": [{"code": tax.UNIMPLEMENTED_VIOLATION_CODES["MISSING_FIELD"]["code"],
                                "entry": str(path), "detail": f"读不到未实装登记清单：{e}",
                                "fix": "补回 .github/case-trust-unimplemented.json"
                                       "（由 write_unimplemented_manifest() 从 taxonomy 落盘）"}],
                "evidence": {}, "closed": [], "unverifiable": [], "checked": 0,
                "entries": [], "sync": [], "blocking": True}
    ctx = unimplemented_probe_context(cases, baseline)
    violations = tax.judge_unimplemented(entries, today=today, probe_context=ctx)
    sync = unimplemented_sync_issues(entries, tax.UNIMPLEMENTED)
    evidence = tax.unimplemented_evidence(entries, ctx)
    issues = (check_unimplemented_issues(entries, fetcher=fetcher) if issue_check
              else {"closed": [], "unverifiable": [], "checked": 0})
    return {
        "violations": violations,
        "evidence": evidence,
        "closed": issues["closed"],
        "unverifiable": issues["unverifiable"],
        "checked": issues["checked"],
        "entries": entries,
        "sync": sync,
        "blocking": bool(violations or sync or issues["closed"]),
    }


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

def _anchor_sha() -> str:
    r = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "origin/main"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="断言可信度静态门禁（fail-closed）")
    ap.add_argument("--base", default="origin/main",
                    help="对比基线（默认 origin/main）")
    ap.add_argument("--files", nargs="*", default=None,
                    help="只判这些用例文件（全部条目，供本地调试）；"
                         "省略时按 git diff 过滤")
    ap.add_argument("--regen-baseline", action="store_true",
                    help="重生成基线清单（锚定 origin/main 的 SHA）")
    ap.add_argument("--prune-baseline", action="store_true",
                    help="全量对账的机械修复：从清单删掉「已不再命中」的码/条目（**只删不加**）")
    ap.add_argument("--allow-growth", action="store_true",
                    help="与 --regen-baseline 同用时，显式放行「清单增长」（= 新增豁免，R4 禁止；"
                         "会逐条打印）")
    ap.add_argument("--today", default=None,
                    help="注入「今天」（YYYY-MM-DD），用于 burn-down 到期判定的确定性红证")
    ap.add_argument("--no-manifest", action="store_true",
                    help="与 --regen-baseline 同用时，不刷未实装清单")
    ap.add_argument("--baseline", default=str(BASELINE_PATH))
    ap.add_argument("--unimplemented", default=str(UNIMPLEMENTED_PATH),
                    help="未实装登记清单（默认 .github/case-trust-unimplemented.json；"
                         "红证用夹具清单覆盖）")
    ap.add_argument("--no-issue-check", action="store_true",
                    help="跳过「`issue` 已 CLOSED ⇒ 红」的网络格（离线/限额时用；"
                         "跳过会在报告里如实打印「未跑判定」，不谎报通过）")
    args = ap.parse_args(argv)
    today = args.today or date.today().isoformat()

    try:
        catalog = load_seed_catalog()
    except Exception as e:
        print(f"❌ 判据加载失败（fail-closed）：{type(e).__name__}: {e}", file=sys.stderr)
        return 1

    all_cases = load_cases_from_dir()
    # 全库判定（**全量对账**与 burn-down 预算共用；成本 ~0.2s，纯静态零 LLM）。
    # 输入与 `--regen-baseline` 同源（不传 raw_text）——理由见 reconcile_baseline 文档。
    all_judged = judge_all(all_cases, catalog)
    violations_by_case = {j["case_id"]: j["violations"] for j in all_judged}
    baseline_path = Path(args.baseline)
    old_baseline = json.loads(baseline_path.read_text(encoding="utf-8")) \
        if baseline_path.exists() else None

    if args.regen_baseline:
        data = render_regen_report(catalog, all_cases, _anchor_sha(), previous=old_baseline)
        added = []
        if old_baseline:
            old_codes = {(cid, c) for cid, e in (old_baseline.get("violations") or {}).items()
                         for c in _recorded_codes(e)}
            new_codes = {(cid, c) for cid, e in data["violations"].items() for c in e["codes"]}
            added = sorted(new_codes - old_codes)
        if added and not args.allow_growth:
            print(f"❌ 重生成会让清单**增长** {len(added)} 条（= 新增豁免，R4 禁止）：")
            for cid, code in added[:20]:
                print(f"  · {cid}：{code}")
            print("  新违规只有两个出口：**本次修掉** / **开独立 issue**；只想清理陈旧条目的请用 "
                  f"`{PRUNE_COMMAND}`。确实要放行增长（口径变化且已接受这批存量）⇒ 加 "
                  "`--allow-growth` 显式承担，并在 PR 里说明为什么不是新增豁免。")
            return 1
        baseline_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"✅ 基线清单已重生成：{args.baseline}")
        if added:
            print(f"⚠️ 已放行增长 {len(added)} 条（--allow-growth）：{added[:20]}")
        print(f"   anchor_sha = {data['anchor_sha']}")
        print(f"   用例总数 = {data['case_total']}，"
              f"含违规的用例 = {data['violation_case_count']}")
        for code, n in sorted(data["rule_counts"].items(), key=lambda kv: -kv[1]):
            print(f"     {n:4d}  {code}")
        if not args.no_manifest:
            write_unimplemented_manifest()
            print(f"✅ 未实装清单已落盘：{UNIMPLEMENTED_PATH}（与 taxonomy.UNIMPLEMENTED 同源）")
        return 0

    if args.prune_baseline:
        if old_baseline is None:
            print(f"❌ 基线清单缺失：{args.baseline}（fail-closed）", file=sys.stderr)
            return 1
        new, removed = render_pruned_baseline(old_baseline, violations_by_case,
                                              case_total=len(all_cases))
        # 🔒 写回前先证明「没有引入增长」（fail-closed）：重算派生读数**不改变事实**，
        # 所以它可以走「只删不加」这条通道；一旦重算会增长，就说明它改变的不只是读数
        # ⇒ 拒绝写回并报错（同 `--regen-baseline` 的默认拒绝增长）。
        growth = derived_growth_guard(old_baseline, new)
        if growth:
            print("❌ `--prune-baseline` 拒绝写回：重算后的清单会**增长**"
                  f"（{'；'.join(growth)}）—— 只删不加的通道不许改变事实；"
                  f"确需重算增长请用 `{REGEN_COMMAND}`（默认拒绝增长）或 `--allow-growth` 显式承担。",
                  file=sys.stderr)
            return 1
        # ⚠️ 派生读数（`rule_counts` / `violation_case_count` / `case_total`）与 `violations`
        # 是同一份账本的两个视图：**只要有漂移就得重算**，哪怕没有条目被删。
        # 旧实现只在 `removed` 非空时写回 ⇒ 「counts 漂移」这条报错指引到的命令**修不好它**
        # （实测：门禁让跑 `--prune-baseline`，它回「无残留（无需改动）」而门禁照旧红）。
        derived_drift = (new.get("rule_counts") != old_baseline.get("rule_counts")
                         or new.get("violation_case_count")
                         != old_baseline.get("violation_case_count")
                         or new.get("case_total") != old_baseline.get("case_total"))
        if not removed and not derived_drift:
            print("✅ 全量对账无残留：清单里没有「已不再命中」的码/条目，派生读数也一致（无需改动）")
            return 0
        baseline_path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        if removed:
            print(f"✅ 已按全量对账收窄清单：{len(removed)} 条被改动（**只删不加**）")
            for r in removed:
                print(f"  · {r['case_id']}：移除 {', '.join(r['removed_codes'])}"
                      f"{'（整条删除）' if r['case_id'] not in new['violations'] else '（收窄）'}")
        if derived_drift:
            print("✅ 已重算派生读数（`rule_counts` / `violation_case_count` / `case_total`）"
                  "—— 事实（`violations`）不变，只让读数与事实一致")
            print(f"   （**未改动 `burn_down` 与 `anchor_sha`**：预算配置只能由显式收紧动作改；"
                  f"锚点前移（{old_baseline.get('anchor_sha')} → …）是独立的语义变化，"
                  f"由 `{REGEN_COMMAND}` 显式完成）")
        print(f"   条目 {len(old_baseline.get('violations') or {})} → "
              f"{len(new['violations'])}；违规码 "
              f"{sum(len(_recorded_codes(e)) for e in (old_baseline.get('violations') or {}).values())}"
              f" → {sum(len(e['codes']) for e in new['violations'].values())}")
        return 0

    # 规则 G（引用新鲜度）与用例条目无关，扫**本次全部改动文件**；
    # 与主判据同口径：只报**本次新增/改动行**里的 `path:NNN`。
    if args.files:
        ref_files = list(args.files)
    else:
        try:
            ref_files = _diff_files(args.base)
        except Exception:
            ref_files = []

    case_files: list[str] = []
    judged: list[dict] = []
    changed_ids: set[str] = set()
    raw_by_id: dict[str, str] = {}
    touched: dict[str, list[str]] = {"case_yml": [], "cases_dir": [], "baseline": []}
    if args.files:
        # --files 语义 = 判这些文件的**全部**条目（本地调试用），故直接按文件过滤
        want_files = {Path(f).name for f in args.files}
        cases = [c for c in all_cases if f"{c.get('_domain')}.yml" in want_files]
        changed_ids = {str(c.get("id")) for c in cases}
        for domain in {c.get("_domain") for c in cases}:
            p = CASES_DIR / f"{domain}.yml"
            for cid, block in _case_blocks(p.read_text(encoding="utf-8")).items():
                raw_by_id[cid] = block
        judged = judge_all(cases, catalog, raw_by_id)
        # `--files` 是「当作这些文件被改过」的调试语义 ⇒ 受管面按显式传入算（否则
        # 「本地按文件复现」与「CI 按 diff 判定」会得到不同的对账基准 = 两套口径）。
        touched["cases_dir"] = [f for f in args.files
                                if str(f).startswith(".github/cases/")]
    else:
        try:
            touched = managed_surface(args.base)
            case_files = list(touched["case_yml"])
        except Exception as e:
            print(f"❌ 取变更文件失败（fail-closed）：{e}", file=sys.stderr)
            return 1
        if case_files:
            changed_ids, raw_by_id = collect_changed_ids(case_files, args.base)
            cases = select_changed_cases(all_cases, changed_ids)
            judged = judge_all(cases, catalog, raw_by_id)
        else:
            print("⏭️ 本次改动未命中任何用例文件（.github/cases/*.yml）—— **逐条判定未跑**"
                  "（「没跑」必须长得像「没跑」，不得读成通过）；"
                  "**全量对账**仍然执行（#4031：与 diff 无关）")

    if old_baseline is None:
        print(f"❌ 基线清单缺失：{args.baseline}（fail-closed）—— 请先跑 {REGEN_COMMAND}",
              file=sys.stderr)
        return 1
    baseline = old_baseline
    # 严格那份（`origin/main`）：生效**配置**与「触碰受管面时的对账基准」都用它。
    base_baseline_main = load_base_baseline(args.base)
    reconcile_base, count_base, base_note = select_reconcile_base(
        args.base, touched, base_baseline_main)

    verdict = classify(judged, baseline)
    recon = reconcile_baseline(baseline, violations_by_case, reconcile_base,
                               judged_cases=len(all_cases))
    recon["base_note"] = base_note
    budget = burn_down_verdict(reconcile_base, baseline, today,
                               case_files_touched=bool(case_files),
                               config_baseline=base_baseline_main,
                               count_base=count_base)
    refs = check_reference_freshness_in_diff(ref_files, args.base)
    unimpl_guard = judge_unimplemented_manifest(
        args.unimplemented, today=today, cases=all_cases, baseline=baseline,
        issue_check=not args.no_issue_check)

    print(render_report(verdict["blocking"], verdict["passed"], recon["stale"],
                        changed_ids, unimpl_guard["entries"], refs, recon=recon,
                        budget=budget, unimpl_guard=unimpl_guard))
    if refs["blocking"]:
        print("")
        for b in refs["blocking"]:
            print(f"❌ [CASE-TRUST-STALE-LINE-REF] `{b['raw']}` — {b['reason']}")
            print(f"    怎么改：{tax.RULES_BY_CODE['CASE-TRUST-STALE-LINE-REF']['fix']}")
    # 退出码由**新增违规**、**全量对账报红**（陈旧/被删/账本不自洽）、**预算未达标**、
    # **未实装登记不合规**（缺字段/到期/僵尸/追踪单已 CLOSED）与**确定错误的引用**共同决定
    # （#4031 + 本次收紧：全部 fail-closed）。
    return 1 if (verdict["blocking"] or refs["blocking"]
                 or recon["blocking"] or budget["blocking"]
                 or unimpl_guard["blocking"]) else 0


if __name__ == "__main__":
    sys.exit(main())
