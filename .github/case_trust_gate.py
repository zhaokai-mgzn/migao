#!/usr/bin/env python3
"""断言可信度静态门禁 —— **假红/假绿结构性护栏 A 层**（#3483 T1 扩展格）。

判据的**单一源** = `.github/assertion_taxonomy.py`（本脚本只做「取 diff → 过滤 → 裁决 →
报错」的外壳，**不复制任何判据**）。静态门禁与后续 runner 侧动态分类器必须共用那一处口径，
两处各写一份就必然漂移（详见 taxonomy 模块 header）。

## 判定范围（**只判被本次改动/新增的用例条目**）

`git diff origin/main...HEAD` 命中的 `cases/*.yml` → 对每个文件比对 `origin/main` 版本与
HEAD 版本里用例块的文本 → 文本**新增或变化**的用例 ID 才参与判定。
⇒ **不阻塞存量**（存量在基线清单里），也不会因为「别人还没修的存量用例」把无关 PR 判红。

## 退出码（fail-closed）

* `0` = 无新增违规（存量放行）；`1` = 有**新增**违规 / 清单陈旧 / 判据加载失败；
* `2` = 用法错误。

## 用法

```bash
python3 .github/case_trust_gate.py                    # PR / 本地：diff origin/main...HEAD
python3 .github/case_trust_gate.py --base origin/main
python3 .github/case_trust_gate.py --files .github/cases/product.yml   # 只判指定文件（全部条目）
python3 .github/case_trust_gate.py --regen-baseline   # 重生成基线清单（锚定当前 main SHA）
python3 .github/case_trust_gate.py --regen-baseline --write-manifest  # 连未实装清单一起刷
```
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
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
    · 违规码**在**基线里 ⇒ 存量 ⇒ 放行（但打印出来，避免「放行了就没人知道」）；
    · 基线里记了、本次却不再违规 ⇒ 陈清单项（**只有调用方按 diff 范围判定是否强制移除**）。
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


def stale_baseline_entries(baseline: dict, changed_ids: set[str],
                           violations_by_case: dict[str, list[dict]]) -> list[dict]:
    """基线清单里「**本次 diff 命中且已不再命中原违规码**」的项 ⇒ 必须从清单移除。

    ⚠️ **只对本次 diff 涉及的用例生效**（关键，避免假红）：
    另一包可能正在修别的存量用例（实证：#3832 在修 `CU-003`、#3833 在修 `PG-013`）。
    若对**全库**做陈旧比对，别人一修好，本门禁就会自己判红（假红），还会挡住他们的 PR。
    故判定范围 = `changed_ids ∩ baseline.violations`。

    判据用**码级子集**而不是「整条用例零违规」：用例可能「修好一条、又犯另一条」
    （如 `CU-003` 改了标签名却仍缺效果层断言）—— 此时原记的码已不再命中 ⇒ 条目陈旧，
    必须重生成；**同时**新码不在基线里 ⇒ 由 `classify` 阻塞。两种情况都要报。

    语义与 `migao-acceptance`「登记表 + 陈旧即红」一致：报错说「你修好了，请删条目」
    —— **报错指向正确的行动**（有意设计，不是「修好即红」的自毁式真值主张）。

    已知边界（登记）：若**判据集合本身**变化（新增/改名规则）导致某些码不再出现，
    陈旧判定会要求重生成基线 —— 这是**期望行为**（口径变了就该重算基线），
    但会让「只加规则」的 PR 也要求重生成一次。
    """
    base_violations = baseline.get("violations") or {}
    stale = []
    for cid in sorted(set(changed_ids) & set(base_violations)):
        now_codes = {v["code"] for v in (violations_by_case.get(cid) or [])}
        entry = base_violations[cid]
        recorded = entry.get("codes") if isinstance(entry, dict) else entry
        recorded = set(recorded or [])
        still_hit = recorded & now_codes
        if still_hit:
            continue  # 原记的码仍在命中 —— 不是陈旧项（未记录的**新**码由 classify 阻塞）
        stale.append({
            "case_id": cid,
            "removed_codes": sorted(recorded),
            "now_codes": sorted(now_codes),
            "hint": (
                f"{cid} 本次已被改动，且基线里记的码不再命中"
                f"（{'、'.join(sorted(recorded))}）—— 请从 "
                f"{BASELINE_PATH.relative_to(REPO_ROOT)} 移除该条目"
                f"（清单只许缩短，防止债务僵化）。命令：{REGEN_COMMAND}"
            ),
        })
    return stale


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
                  refs: dict | None = None) -> str:
    """人类/agent 可读的失败报告 —— **每条都带「怎么改」**。"""
    out: list[str] = []
    out.append("═══ 断言可信度门禁（假红/假绿结构性护栏 A 层，单一判据源 "
               "= .github/assertion_taxonomy.py）═══")
    out.append(f"本次改动命中的用例条目：{len(changed_ids)} 条"
               f"（{'、'.join(sorted(changed_ids)) if changed_ids else '无'}）")
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
        out.append(f"⚠️ 基线清单可缩短 {len(stale)} 条（**不阻塞本次** —— 建议随本 PR 一并清理）：")
        for s in stale:
            out.append(f"  · {s['case_id']}（原记 {', '.join(s['removed_codes'])}）")
            out.append(f"    {s['hint']}")
        out.append("")
        out.append("  为什么只告警不阻塞：「清单只许缩短」的**判据**已实装（见下 `stale_baseline_entries`），"
                   "但**执行**必须是告警 —— 要求作者改 `.github/case-trust-baseline.json` 会与"
                   "**在飞的**基线重生成改动冲突（实证：另一包正在修 CU-003/PG-013，而基线文件同时被"
                   "本门禁的 PR 创建）。硬阻塞会把「修好用例」的人卡在一个非其所有权的文件上 = 假红"
                   "（migao-acceptance：不能因「改法写了但没照着改」就把**正确**形态判红）。"
                   "→ 机制现状照实说：清单缩短靠本告警 + 复盘；**没有**机械强制。")
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
    out.append("")
    out.append("✅ 通过" if not blocking else "❌ 阻塞（见上）")
    return "\n".join(out)


def render_regen_report(catalog: dict, cases: list[dict], anchor_sha: str) -> dict:
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
    return {
        "_comment": (
            "断言可信度门禁的**存量**违规清单（burn-down）。"
            "锚定 SHA 见 anchor_sha —— 计数是「该 SHA 上按 taxonomy 判出的存量违规」，"
            "**不是**『这些用例永远豁免』。"
        ),
        "_generated_by": REGEN_COMMAND,
        "regenerate_command": REGEN_COMMAND,
        "_when_to_regen": (
            "① 你**修改/新增**了某个用例条目 → 门禁会告诉你（清单只许缩短）；"
            "② 别人合并了用例修复（如 #3832 的 CU-003、#3833 的 PG-013）→ "
            "**重跑 ①后重生成**，把已修好的条目从清单里去掉；"
            "③ 规则集本身变化（新增/改名规则）→ 必须重生成。"
        ),
        "_scope_note": (
            "「已不再违规 ⇒ 必须移除」这条**只对本次 PR diff 命中的用例生效**"
            "（见 case_trust_gate.stale_baseline_entries）—— 否则别人修好一条存量用例，"
            "本门禁就会自己判红（假红）并挡住他们的 PR。"
        ),
        "anchor_sha": anchor_sha,
        "case_total": len(cases),
        "violation_case_count": len(violations),
        "rule_counts": rule_counts,
        "violations": dict(sorted(violations.items())),
    }


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
    ap.add_argument("--no-manifest", action="store_true",
                    help="与 --regen-baseline 同用时，不刷未实装清单")
    ap.add_argument("--baseline", default=str(BASELINE_PATH))
    args = ap.parse_args(argv)

    try:
        catalog = load_seed_catalog()
    except Exception as e:
        print(f"❌ 判据加载失败（fail-closed）：{type(e).__name__}: {e}", file=sys.stderr)
        return 1

    all_cases = load_cases_from_dir()

    if args.regen_baseline:
        data = render_regen_report(catalog, all_cases, _anchor_sha())
        Path(args.baseline).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"✅ 基线清单已重生成：{args.baseline}")
        print(f"   anchor_sha = {data['anchor_sha']}")
        print(f"   用例总数 = {data['case_total']}，"
              f"含违规的用例 = {data['violation_case_count']}")
        for code, n in sorted(data["rule_counts"].items(), key=lambda kv: -kv[1]):
            print(f"     {n:4d}  {code}")
        if not args.no_manifest:
            write_unimplemented_manifest()
            print(f"✅ 未实装清单已落盘：{UNIMPLEMENTED_PATH}（与 taxonomy.UNIMPLEMENTED 同源）")
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

    if args.files:
        # --files 语义 = 判这些文件的**全部**条目（本地调试用），故直接按文件过滤
        want_files = {Path(f).name for f in args.files}
        cases = [c for c in all_cases if f"{c.get('_domain')}.yml" in want_files]
        changed_ids = {str(c.get("id")) for c in cases}
        raw_by_id = {}
        for domain in {c.get("_domain") for c in cases}:
            p = CASES_DIR / f"{domain}.yml"
            for cid, block in _case_blocks(p.read_text(encoding="utf-8")).items():
                raw_by_id[cid] = block
    else:
        try:
            cases_files = changed_case_files(args.base)
        except Exception as e:
            print(f"❌ 取变更文件失败（fail-closed）：{e}", file=sys.stderr)
            return 1
        if not cases_files:
            refs = check_reference_freshness_in_diff(ref_files, args.base)
            print("⏭️ 本次改动未命中任何用例文件（.github/cases/*.yml）—— **用例条目未跑**"
                  "（「没跑」必须长得像「没跑」，不得读成通过）")
            print(render_report([], [], [], set(), list(tax.UNIMPLEMENTED), refs))
            if refs["blocking"]:
                for b in refs["blocking"]:
                    print(f"❌ [CASE-TRUST-STALE-LINE-REF] `{b['raw']}` — {b['reason']}")
                    print(f"    怎么改：{tax.RULES_BY_CODE['CASE-TRUST-STALE-LINE-REF']['fix']}")
                return 1
            return 0
        changed_ids, raw_by_id = collect_changed_ids(cases_files, args.base)
        if not changed_ids:
            print(f"⏭️ 变更文件 {cases_files} 里没有新增/内容变化的用例条目 —— 未跑")
            return 0
        cases = select_changed_cases(all_cases, changed_ids)

    judged = judge_all(cases, catalog, raw_by_id)
    violations_by_case = {j["case_id"]: j["violations"] for j in judged}

    if not Path(args.baseline).exists():
        print(f"❌ 基线清单缺失：{args.baseline}（fail-closed）—— 请先跑 {REGEN_COMMAND}",
              file=sys.stderr)
        return 1
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))

    verdict = classify(judged, baseline)
    stale = stale_baseline_entries(baseline, changed_ids, violations_by_case)
    refs = check_reference_freshness_in_diff(ref_files, args.base)

    print(render_report(verdict["blocking"], verdict["passed"], stale,
                        changed_ids, list(tax.UNIMPLEMENTED), refs))
    if refs["blocking"]:
        print("")
        for b in refs["blocking"]:
            print(f"❌ [CASE-TRUST-STALE-LINE-REF] `{b['raw']}` — {b['reason']}")
            print(f"    怎么改：{tax.RULES_BY_CODE['CASE-TRUST-STALE-LINE-REF']['fix']}")
    # 退出码只由**新增违规**与**确定错误的引用**决定：陈旧基线条目只告警
    # （见 render_report 里的为什么）。
    return 1 if (verdict["blocking"] or refs["blocking"]) else 0


if __name__ == "__main__":
    sys.exit(main())
