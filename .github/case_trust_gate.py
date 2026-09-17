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
故本 PR 改不动本次判定）。

## 退出码（fail-closed）

* `0` = 无新增违规 + 全量对账无残留 + 预算达标；
* `1` = 有**新增**违规 / **全量对账报红**（陈旧条目 / 被删条目 / 账本不自洽）/ **预算未达标**
      / 判据加载失败 / 基线缺失；

## 用法

```bash
python3 .github/case_trust_gate.py                    # PR / 本地：diff origin/main...HEAD + 全量对账
python3 .github/case_trust_gate.py --base origin/main
python3 .github/case_trust_gate.py --files .github/cases/product.yml   # 只判指定文件（全部条目）
python3 .github/case_trust_gate.py --prune-baseline   # 全量对账的机械修复：**只删不加**
python3 .github/case_trust_gate.py --regen-baseline   # 全量重建（口径变化时；默认拒绝增长）
python3 .github/case_trust_gate.py --regen-baseline --allow-growth    # 显式放行增长（会逐条打印）
python3 .github/case_trust_gate.py --today 2027-01-01 # 预算到期判定的确定性注入（红证用）
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
                       judged_cases: int | None = None) -> dict:
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
    · `unregistered`（报告）：全库判出、清单里没有的码（规则集变化 / 用例新增造成）。
      只报告不阻塞，理由见 `.github/case-trust-unimplemented.json` 的登记。

    ⚠️ **判定输入必须与 `--regen-baseline` 同源**（`judge_all(cases, catalog)`，**不传**
    `raw_text`）：基线的码是那条路径算出来的，用另一条路径（diff 路径会传 `raw_text`，
    轮次作用域的 `forbidden_text` 会少报码）对账就会凭空产出「陈旧项」= 假红。
    """
    recorded = {cid: _recorded_codes(e)
                for cid, e in (baseline.get("violations") or {}).items()}
    now = {cid: {v["code"] for v in vs} for cid, vs in violations_by_case.items() if vs}

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
                f"命中，任何条目都必须仍然真的违规）。命令：{PRUNE_COMMAND}"
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
            f"violations 实际 {sorted(agg.items())} ⇒ 跑 {PRUNE_COMMAND} 重算"
        )
    if isinstance(baseline.get("violation_case_count"), int) \
            and baseline["violation_case_count"] != len(recorded):
        integrity.append(
            f"violation_case_count={baseline['violation_case_count']} 与实际条目数 "
            f"{len(recorded)} 不一致 ⇒ 跑 {PRUNE_COMMAND} 重算"
        )

    return {
        "stale": stale,
        "dropped": dropped,
        "unregistered": unregistered,
        "integrity": integrity,
        "judged_cases": judged_cases if judged_cases is not None else len(now),
        "violating_cases": len(now),
        "recorded_entries": len(recorded),
        "blocking": bool(stale or dropped or integrity),
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
                      case_files_touched: bool) -> dict:
    """burn-down 预算裁决（#4009 裁定 1 的第三条）。

    四条判据（都可红 —— 对应的红证在 `.github/case-trust-redproof.md`）：

    1. **只许缩短**：本次相对 `--base` 的净变化不得为负（条目数与违规码数**都**不得增长）
       —— 增长就是新增豁免（R4）。加规则导致的新违规只有两个出口：本次修掉 / 开独立 issue；
    2. **每 PR 最低消减**：`per_pr_min` 条（`metric` 指定口径，默认「条目或码」任一）。
       口径 `scope` **默认 `case_touching_prs`**（只对改用例的 PR 生效）—— 字面口径
       （每个 PR，含不改用例的）会让**全仓每个 PR 都红**（Java 单测 PR 也得改用例库 + 清单），
       与「先把清单清干净再翻 required、避免阻塞所有人」的顺序铁律自相矛盾。
       要字面口径就把 `scope` 改成 `all_prs`（配置是数据，不是代码）；
    3. **`OR-*` 优先到期**：`priority_deadline` 之后清单里不得再有 `priority_prefixes` 条目
       （「先清 OR-*」的机械形态）；
    4. **到期清零**：`deadline` 之后清单必须为空。

    ⚠️ **生效配置读 `--base` 那一份**（`origin/main` 的基线文件）：否则本 PR 把
    `deadline` 往后一挪就本次生效 = 自证式豁免。同时比对「当前 vs base」的配置，
    禁止放宽（`per_pr_min` 变小 / 到期日推后 / 优先前缀被拿掉 / 整个块被删）。
    """
    base_cfg = (base_baseline or {}).get("burn_down")
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
    metric = str(eff.get("metric") or "entries_or_codes")
    scope = str(eff.get("scope") or "case_touching_prs")
    prefixes = [str(p) for p in (eff.get("priority_prefixes") or [])]
    pri_deadline, deadline = _date(eff.get("priority_deadline")), _date(eff.get("deadline"))

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

    before_e, before_c = _count_exemptions(base_baseline or {})
    after_e, after_c = _count_exemptions(baseline)
    net_e, net_c = before_e - after_e, before_c - after_c
    priority_remaining = sorted(cid for cid in (baseline.get("violations") or {})
                               if any(cid.startswith(p) for p in prefixes))

    if net_e < 0 or net_c < 0:
        reasons.append(
            f"基线**增长**了（条目 {before_e}→{after_e}，违规码 {before_c}→{after_c}）⇒ 新增豁免（R4）："
            "新违规只有两个出口 —— 本次修掉 / 开独立 issue 登记，**不得**记进豁免清单"
        )

    in_scope = (scope == "all_prs") or (scope == "case_touching_prs" and case_files_touched)
    if in_scope and after_e > 0:
        got = {"entries": net_e, "codes": net_c, "entries_or_codes": max(net_e, net_c)}.get(
            metric, max(net_e, net_c))
        if got < per_pr_min:
            reasons.append(
                f"burn-down 预算未达标：本次净消减 {got} 条（metric={metric}）< 每 PR 最低 "
                f"{per_pr_min} 条（条目 {before_e}→{after_e}，违规码 {before_c}→{after_c}）。"
                f"按**只许缩短**修掉 ≥{per_pr_min} 条存量违规（修法见 "
                f".github/case-trust-baseline.json 的 burn_down._how_to），"
                f"**先清 `{('、'.join(prefixes) or '—')}`**（现剩 {len(priority_remaining)} 条）"
            )
    elif not in_scope:
        notes.append(
            f"ℹ️ 本次未改用例文件（`.github/cases/*.yml`）⇒ 「每 PR 最低消减」不适用"
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
                  budget: dict | None = None) -> str:
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
        out.append(f"⚠️ 未登记违规 {len(recon['unregistered'])} 条（**只报告**，机制缺口已如实登记，"
                   f"见 .github/case-trust-unimplemented.json）：")
        for u in recon["unregistered"][:10]:
            out.append(f"  · {u['case_id']}：{'、'.join(u['codes'])}")
        if len(recon["unregistered"]) > 10:
            out.append(f"  · …共 {len(recon['unregistered'])} 条")
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
    for n in (budget or {}).get("notes") or []:
        out.append("")
        out.append(n)
    out.append("")
    blocked = bool(blocking or stale
                   or (recon or {}).get("blocking") or (budget or {}).get("blocking"))
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
    """把 taxonomy 的未实装清单落盘（供人读 + 让「未实装」这件事可见）。"""
    data = {
        "_comment": (
            "断言可信度护栏的**未实装项**（如实登记）。"
            "红线：判据在现有机制下无法判定时，**不得**写成恒真判断凑数 —— 登记在此，"
            "写明缺什么。"
        ),
        "_source": ".github/assertion_taxonomy.py 的 UNIMPLEMENTED",
        "unimplemented": list(tax.UNIMPLEMENTED),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


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
        if not removed:
            print("✅ 全量对账无残留：清单里没有「已不再命中」的码/条目（无需改动）")
            return 0
        baseline_path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        print(f"✅ 已按全量对账收窄清单：{len(removed)} 条被改动（**只删不加**）")
        for r in removed:
            print(f"  · {r['case_id']}：移除 {', '.join(r['removed_codes'])}"
                  f"{'（整条删除）' if r['case_id'] not in new['violations'] else '（收窄）'}")
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
    else:
        try:
            case_files = changed_case_files(args.base)
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
    base_baseline = load_base_baseline(args.base)

    verdict = classify(judged, baseline)
    recon = reconcile_baseline(baseline, violations_by_case, base_baseline,
                               judged_cases=len(all_cases))
    budget = burn_down_verdict(base_baseline, baseline, today,
                               case_files_touched=bool(case_files))
    refs = check_reference_freshness_in_diff(ref_files, args.base)

    print(render_report(verdict["blocking"], verdict["passed"], recon["stale"],
                        changed_ids, list(tax.UNIMPLEMENTED), refs, recon=recon, budget=budget))
    if refs["blocking"]:
        print("")
        for b in refs["blocking"]:
            print(f"❌ [CASE-TRUST-STALE-LINE-REF] `{b['raw']}` — {b['reason']}")
            print(f"    怎么改：{tax.RULES_BY_CODE['CASE-TRUST-STALE-LINE-REF']['fix']}")
    # 退出码由**新增违规**、**全量对账报红**（陈旧/被删/账本不自洽）、**预算未达标**
    # 与**确定错误的引用**共同决定（#4031：收紧为 fail-closed）。
    return 1 if (verdict["blocking"] or refs["blocking"]
                 or recon["blocking"] or budget["blocking"]) else 0


if __name__ == "__main__":
    sys.exit(main())
