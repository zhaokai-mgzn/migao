# case_ids: MC-131
"""预设搬运通道台账的判据（issue #6060）—— 「搬出去的东西，字节是不是真在目标仓里」有读数了。

## 病（2026-10-02 实测，逐字见 issue）

S4（PR #6034 / `0e059836e`）删业务仓 `.agent-presets/**` 之前做「逐字节核对」，但用的是**过期基线**
（PR body 写「业务仓 1.102.0 vs 预设仓 1.103.0」，而业务仓 `origin/main` 当时**已是 1.104.0**）
⇒ 把「差一版」误判成「有意更新」⇒ **v1.104.0（#6033）从未被搬入预设仓就被删**（事后补搬，预设仓 `42283c2`）。
**下次同类丢版仍然只能靠人发现** —— 这就是本判据要治的类级缺陷。

## 判据（每条都能单独变红；红证**全部内存构造**，见本文件「判别力自证」组）

| # | 判据 | 变红的形态（具名报出对象） |
|---|---|---|
| 1 | 台账**非空且自洽**（schema / 坐标原点 / judged_by 与 generated_by 真实存在） | 空台账 / schema 漂移 / 判据或机具被改名却没人改台账 |
| 2 | 🔴 **文件集合双向相等**（本单的牙齿） | `deletion.commit^` 树里多一个预设文件而台账没登记 ⇒ 「未登记即红」；台账登记了但现取没有 ⇒ 「登记了但现取不存在」 |
| 3 | 🔴 **逐条与真值逐值相等**（blob / 版末提交 / 最后承载的版本 / 源→目标路径映射） | 内容被改过、基线换过、手改台账任一字段 ⇒ 「对不上」 |
| 4 | **版本面逐值相等**（每一版 = 版本号 + 版末提交） | 少一版 / 多一版 / 版本锚点漂移 |
| 5 | 🔴 **搬入证据必须齐备且可追溯** | 端口缺 `preset_repo_commit` / `ported_at`，或版本证据指向不存在的版本 ⇒ 红 |
| 6 | 🔴 **版本证据缺口只许缩短**（现取 ⇄ 台账 ⇄ 判据侧镜像常量三处一致） | 把某条证据删掉（缺口 9 → 98 > 97）⇒ 红；补证据（缺口下降）⇒ 绿 |
| 7 | **「已搬走」的前提不许被悄悄推翻** | 路径重新出现在 `HEAD`，或该路径在迁移退出点之后又被改动 ⇒ 红 |
| 8 | **覆盖面登记不许匿名存在** | `coverage_boundary` 缺 `face` / `reason` / `recompute`，或整段被清空 |

## 判别力自证（本文件内，内存注入；**不**临时改仓内文件）

八个坏形态各自必须报非空问题：**多一个端口 / 少一个端口 / blob 对不上 / 少一版 / 证据变长 /
端口证据字段缺失 / 路径重新出现在 HEAD / 空台账**。⇒ 把这八条换成「恒绿」的 `problems()`（例如直接 `return []`），
本组判据**当场红**（实测 9 failed：另有「手改缺口读数」一条同属恒绿形态）——
这就是「把判据改成恒绿 ⇒ 必红」的机械出口。

## 边界（照实登记，§19.1；与台账 `coverage_boundary` 同源）

- **预设仓侧证据的真实性不在 CI 射程**：预设仓私有 + 需网络 ⇒ CI 只核「业务仓侧逐值相等 + 证据字段形态」；
  镜像存在时本判据自动**加强**（逐条解析 `commit:path` 比 blob），镜像缺失时不报问题（方向是「本机更严」）。
- 只覆盖「迁移退出那一刻存在」的文件（`deletion.commit^` 的树），更早退场的预设文件不在面内。
- 判不了「预设仓里内容后来有没有被继续改坏」（那是活锚自检 / `drift_audit.py` 的 `sync-copy`）。
- **版本面**用冻结计数表达缺口（只许缩短），不逐版要求证据 —— 逐版要求会把 2026-09-14 之前的快照形态判成永久红。
- 判不了预设内容本身的质量；本判据只裁**搬运关系**。
- 本判据**不改**任何门禁的通过条件、不新增豁免。
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from unit_ci_workflows import preset_port_ledger as ppl  # noqa: E402  （机具与判据同包）

LEDGER_REL = "tests/unit_ci_workflows/preset_port_ledger.json"
LEDGER_PATH = REPO_ROOT / LEDGER_REL

#: 版本证据缺口的**冻结上限**（判据侧镜像，与机具 `preset_port_ledger.VERSION_EVIDENCE_GAP_MAX` 同值）。
#: 🔴 「只许缩短」靠**两处同时改**才放宽（diff 里看得见）—— 单边改数字不许消红。
VERSION_EVIDENCE_GAP_MAX = 97


@lru_cache(maxsize=1)
def _ledger() -> dict:
    """台账（只读一次；判据全程用深拷贝做内存注入）。"""
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _observed() -> dict:
    """现取读数（git 子进程只跑一次；本文件内的注入一律在拷贝上做）。"""
    return ppl.observe(REPO_ROOT)


def _live_mirror() -> Path | None:
    return ppl.mirror_root()


def _problems(ledger: dict | None = None, observed: dict | None = None) -> list[str]:
    return ppl.problems(
        _ledger() if ledger is None else ledger,
        _observed() if observed is None else observed,
        mirror=_live_mirror(),
    )


def _named(problems: list[str], needle: str) -> str:
    """→ 命中该关键词的第一条问题（没有命中则用空串，便于 `assert` 输出可读）。"""
    for item in problems:
        if needle in item:
            return item
    return ""


# ── 判据 1：台账非空且自洽 ────────────────────────────────────────────────


def test_ledger_is_non_empty_and_self_consistent():
    ledger = _ledger()
    assert ledger.get("schema") == ppl.SCHEMA, f"台账 schema 漂移：{ledger.get('schema')!r}"
    assert ledger.get("ports"), "台账 `ports` 为空 —— 没登记的搬运关系不许当通过（fail-closed）"
    assert ledger.get("versions"), "台账 `versions` 为空 —— 版本面没有对象可判（fail-closed）"
    deletion = ledger.get("deletion") or {}
    assert deletion.get("commit") == ppl.DELETION_COMMIT, (
        f"台账 `deletion.commit` 必须等于迁移退出点 {ppl.DELETION_COMMIT[:9]}，"
        f"现取 {str(deletion.get('commit'))[:9]}"
    )
    assert deletion.get("paths_from") == ppl.PRESET_PREFIX, (
        f"`deletion.paths_from` 必须是业务仓预设前缀 {ppl.PRESET_PREFIX!r}"
    )


def test_ledger_points_at_its_own_judge_and_generator():
    ledger = _ledger()
    assert ledger.get("judged_by") == "tests/unit_ci_workflows/test_preset_port_ledger.py"
    assert (REPO_ROOT / ledger["judged_by"]).is_file(), f"`judged_by` 指向不存在的文件：{ledger['judged_by']}"
    assert "tests/unit_ci_workflows/preset_port_ledger.py" in str(ledger.get("generated_by")), (
        f"`generated_by` 必须点名机具（不手抄）：{ledger.get('generated_by')!r}"
    )
    assert (REPO_ROOT / "tests" / "unit_ci_workflows" / "preset_port_ledger.py").is_file(), (
        "机具 `tests/unit_ci_workflows/preset_port_ledger.py` 不存在"
    )


def test_coverage_boundary_is_registered_not_anonymous():
    boundary = _ledger().get("coverage_boundary") or []
    assert len(boundary) >= 6, f"覆盖面登记被清空/缩到 {len(boundary)} 条 —— 缺口不许匿名存在"
    for idx, item in enumerate(boundary):
        for field in ("face", "reason", "recompute"):
            assert str(item.get(field) or "").strip(), f"coverage_boundary[{idx}] 缺 `{field}`：{item!r}"


# ── 判据 2/3/4/5/6/7：现取 ⇄ 台账（这一条是总闸；细分见下面各条）────────────


def test_no_problems_against_live_business_repo_history():
    found = _problems()
    assert found == [], "台账与业务仓 git 历史不一致：\n  · " + "\n  · ".join(found)


def test_registered_ports_match_the_migrated_tree_exactly():
    ledger, observed = _ledger(), _observed()
    ledger_paths = {entry["path"] for entry in ledger["ports"]}
    observed_paths = set(observed["paths"])
    assert observed_paths - ledger_paths == set(), (
        f"未登记即红：{sorted(observed_paths - ledger_paths)} 存在于 `deletion.commit^` 树里而台账没登记"
    )
    assert ledger_paths - observed_paths == set(), (
        f"登记了但现取不存在：{sorted(ledger_paths - observed_paths)}"
    )
    assert len(ledger["ports"]) == len(ledger_paths), "台账 `ports` 里出现重复 path（同一端口登两次）"


def test_each_port_is_byte_identical_to_the_last_carried_state():
    observed = _observed()
    mismatches = []
    for entry in _ledger()["ports"]:
        truth = observed["paths"].get(entry["path"])
        assert truth, f"端口不在 `deletion.commit^` 树里：{entry['path']}"
        if entry.get("blob") != truth["blob"]:
            mismatches.append(f"{entry['path']} blob 台账 {str(entry.get('blob'))[:9]} vs 现取 {str(truth['blob'])[:9]}")
        if entry.get("last_commit") != truth["last_commit"]:
            mismatches.append(f"{entry['path']} 版末提交对不上")
        if entry.get("version") != truth["version"]:
            mismatches.append(f"{entry['path']} 最后承载的版本 台账 {entry.get('version')!r} vs 现取 {truth['version']!r}")
        if entry.get("preset_path") != entry["path"][len(ppl.PRESET_PREFIX):]:
            mismatches.append(f"{entry['path']} 的 `preset_path` 与源路径不同源")
    assert mismatches == [], "逐值相等失败：\n  · " + "\n  · ".join(mismatches)


def test_version_history_is_reproduced_one_row_per_version():
    ledger_versions = [
        {"path": v.get("path"), "version": v.get("version"), "commit": v.get("commit")}
        for v in _ledger()["versions"]
    ]
    observed_versions = _observed()["versions"]
    assert len(observed_versions) > 0, "现取版本面为空 —— 对象缺失不是通过"
    assert ledger_versions == observed_versions, (
        f"版本面对不上：台账 {len(ledger_versions)} 条 vs 现取 {len(observed_versions)} 条"
    )
    keys = [(row["path"], row["version"]) for row in ledger_versions]
    assert len(keys) == len(set(keys)), "同一路径同一版本登记了两次"


def test_every_port_carries_a_usable_port_evidence():
    ledger = _ledger()
    observed = _observed()
    for entry in ledger["ports"]:
        assert ppl._sha(entry.get("preset_repo_commit")), (
            f"端口缺搬入证据：{entry['path']} ⇒ preset_repo_commit={entry.get('preset_repo_commit')!r}"
        )
        assert ppl._DATE_RE.match(str(entry.get("ported_at") or "")), (
            f"端口缺 `ported_at`（YYYY-MM-DD）：{entry['path']}"
        )
        for field in ("why", "restart_condition"):
            assert str(entry.get(field) or "").strip(), f"端口缺 `{field}`：{entry['path']}"
    assert ledger["version_ports"], "版本搬入证据为空 —— 证据面没有对象可判（fail-closed）"
    truth = {(v["path"], v["version"]): v["commit"] for v in observed["versions"]}
    for row in ledger["version_ports"]:
        key = (row.get("path"), row.get("version"))
        assert key in truth, f"版本证据指向不存在的版本：{key[0]} {key[1]}"
        assert row.get("business_commit") == truth[key], (
            f"版本证据的 business_commit 与现取不符：{key[0]} {key[1]}"
        )
        assert ppl._sha(row.get("preset_repo_commit")), f"版本证据缺 `preset_repo_commit`：{key[0]} {key[1]}"


def test_version_evidence_gap_is_pinned_and_may_only_shrink():
    ledger, observed = _ledger(), _observed()
    declared = (ledger.get("version_evidence_gap") or {}).get("count")
    with_evidence = {(row["path"], row["version"]) for row in ledger["version_ports"]}
    orphan = [row for row in ledger["version_ports"] if row.get("preset_repo_commit") is None]
    assert orphan == [], f"`version_ports` 里存在无证据的行（会把缺口读数洗成 0）：{orphan[:3]}"
    live_gap = len(observed["versions"]) - len(with_evidence)
    assert declared == live_gap, f"缺口读数对不上：台账 {declared!r} vs 现取 {live_gap}"
    assert ppl.VERSION_EVIDENCE_GAP_MAX == VERSION_EVIDENCE_GAP_MAX, (
        f"「只许缩短」的上限必须两侧同值：机具 {ppl.VERSION_EVIDENCE_GAP_MAX} vs 判据镜像 "
        f"{VERSION_EVIDENCE_GAP_MAX}（放宽要同时改两处）"
    )
    assert live_gap <= VERSION_EVIDENCE_GAP_MAX, (
        f"版本证据缺口变长：{live_gap} > 冻结上限 {VERSION_EVIDENCE_GAP_MAX}（只许缩短）"
    )


def test_migrated_paths_stay_gone_and_untouched():
    observed = _observed()
    resurrected = sorted(set(observed["head_present"]))
    assert resurrected == [], f"路径重新出现在 HEAD ⇒ 台账「已搬走」前提不成立：{resurrected}"
    moved = {
        path: observed["last_touch"].get(path)
        for path in observed["paths"]
        if observed["last_touch"].get(path) != ppl.DELETION_COMMIT
    }
    assert moved == {}, (
        f"迁移退出点之后这些路径又被改动（最近一次改动不是 {ppl.DELETION_COMMIT[:9]}）：{sorted(moved)}"
    )


# ── 判别力自证：七个坏形态各自必须报非空问题（内存注入，不改仓内文件）──────


def test_more_ports_than_registered_is_red():
    observed = copy.deepcopy(_observed())
    extra = ppl.PRESET_PREFIX + "skills/migao-dev-flow/ghost.md"
    observed["paths"][extra] = {"last_commit": ppl.DELETION_COMMIT, "blob": "0" * 40, "version": None}
    found = _problems(observed=observed)
    assert _named(found, "未登记即红"), f"多一个端口没有判红：{found!r}"


def test_registered_but_missing_port_is_red():
    observed = copy.deepcopy(_observed())
    observed["paths"].pop(sorted(observed["paths"])[0])
    found = _problems(observed=observed)
    assert _named(found, "登记了但现取不存在"), f"少一个端口没有判红：{found!r}"


def test_blob_mismatch_is_red():
    ledger = copy.deepcopy(_ledger())
    ledger["ports"][0]["blob"] = "f" * 40
    found = _problems(ledger=ledger)
    assert _named(found, "字节对不上"), f"blob 被改过却没有判红：{found!r}"


def test_missing_version_is_red():
    ledger = copy.deepcopy(_ledger())
    ledger["versions"].pop(len(ledger["versions"]) // 2)
    found = _problems(ledger=ledger)
    assert _named(found, "未登记即红（版本）"), f"少一版没有判红：{found!r}"


def test_hand_edited_gap_count_is_red():
    """只改数字、不动证据 ⇒ 读数对不上 ⇒ 红（不许用改数字的办法消红）。"""
    ledger = copy.deepcopy(_ledger())
    ledger["version_evidence_gap"]["count"] -= 1
    found = _problems(ledger=ledger)
    assert _named(found, "缺口读数对不上"), f"缺口读数被手改却没有判红：{found!r}"


def test_adding_evidence_shrinks_the_gap_and_is_green():
    """反向对照：真**补**一版证据（缺口 97 → 96）必须绿 —— 只许缩短 ≠ 一律判红。"""
    ledger, observed = copy.deepcopy(_ledger()), _observed()
    have = {(row["path"], row["version"]) for row in ledger["version_ports"]}
    missing = next(v for v in observed["versions"] if (v["path"], v["version"]) not in have)
    ledger["version_ports"].append({
        "path": missing["path"],
        "version": missing["version"],
        "business_commit": missing["commit"],
        "blob": "0" * 40,
        "preset_repo_commit": "1" * 40,
        "ported_at": "2026-10-02",
    })
    ledger["version_evidence_gap"]["count"] = len(observed["versions"]) - len(ledger["version_ports"])
    found = _problems(ledger=ledger)
    assert [item for item in found if "缺口" in item] == [], (
        f"补证据（缺口下降）不应判红：{found!r}"
    )


def test_growing_the_evidence_gap_is_red():
    ledger = copy.deepcopy(_ledger())
    ledger["version_ports"].pop(0)
    live = len(_observed()["versions"]) - len(ledger["version_ports"])
    ledger["version_evidence_gap"]["count"] = live
    found = _problems(ledger=ledger)
    assert _named(found, "版本证据缺口变长"), f"删掉一条证据使缺口变长却没有判红（{live}）：{found!r}"


def test_port_with_missing_evidence_is_red():
    ledger = copy.deepcopy(_ledger())
    ledger["ports"][0]["preset_repo_commit"] = None
    found = _problems(ledger=ledger)
    assert _named(found, "搬入证据缺失"), f"端口缺搬入证据没有判红：{found!r}"
    ledger = copy.deepcopy(_ledger())
    ledger["ports"][0]["why"] = "  "
    found = _problems(ledger=ledger)
    assert _named(found, "缺 `why`"), f"端口缺 why 没有判红：{found!r}"


def test_path_reappearing_in_head_is_red():
    observed = copy.deepcopy(_observed())
    observed["head_present"].append(sorted(observed["paths"])[0])
    found = _problems(observed=observed)
    assert _named(found, "路径重新出现在 HEAD"), f"路径回到 HEAD 却没有判红：{found!r}"


def test_empty_ledger_is_red_not_green():
    found = _problems(ledger={"schema": ppl.SCHEMA, "deletion": {"commit": ppl.DELETION_COMMIT}})
    assert _named(found, "`ports` 为空"), f"空台账被当成通过（fail-closed 失效）：{found!r}"


def test_problems_is_pure_and_deterministic():
    ledger, observed = _ledger(), _observed()
    before = (json.dumps(ledger, sort_keys=True), json.dumps(observed, sort_keys=True))
    first = _problems()
    second = _problems()
    after = (json.dumps(ledger, sort_keys=True), json.dumps(observed, sort_keys=True))
    assert first == second, "同一输入两次判定结果不同 ⇒ 判据不是确定性的"
    assert before == after, "判定过程改写了台账/现取读数（判定必须只读）"


# ── 不可判定必须红（不是「无对象可判」）─────────────────────────────────────


def test_unreachable_deletion_commit_is_a_named_error(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "fixture"], cwd=repo, check=True)
    with pytest.raises(ppl.LedgerToolError) as exc:
        ppl.observe(repo)
    assert "不可判定" in str(exc.value) or "取不到迁移退出点" in str(exc.value), (
        f"不可判定的报错必须可读、可归因：{exc.value}"
    )


def test_check_returns_three_when_environment_is_unjudgeable(tmp_path: Path):
    rc, detail = ppl.check(tmp_path, LEDGER_PATH)
    assert rc == 3, f"环境不可判定必须返回 3（不得当 0 读），现取 {rc}：{detail}"
