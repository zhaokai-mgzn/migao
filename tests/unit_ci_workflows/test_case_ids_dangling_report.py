# case_ids: MC-066
"""用例 id **悬空引用**的两条腿：变更集**阻塞** + 全库**报告**（issue #8310 收尾）。

## 病（2026-11-03 现取）

批合工具替在飞 PR 让号时改的是 `.github/cases/*.yml` 的用例块 id
（`git show 1524f1ce2 -- .github/cases/misc.yml`：`-  - id: MC-154` / `+  - id: MC-155`），
**改不到源码侧的 `// case_ids:` 头** ⇒ main 上出现「测试声明了用例库里不存在的 id」。

既有判据 `growth_gate.case_trace_check` **只看变更集** ⇒ 一个**只改 YAML** 的批次提交不触发它，
悬空引用可以**潜伏**，直到下一个碰那个文件的 PR 才爆 —— 而那时判红会指向**那个无辜的 PR**。

## 三条腿（分工是本节的核心，别混）

| 腿 | 判据 | 行为 | 本文件怎么测 |
|---|---|---|---|
| 变更集 | `growth_gate.case_trace_check`（`QA Growth Gate`，required） | 悬空 ⇒ **阻塞** | D1 用**合成 git 仓库**直连真函数（红/绿双向） |
| 全库 · 报告 | `.github/case_ids_dangling.py` + `docs/testing/case-ids-dangling.md` | 悬空 ⇒ **只列出、不阻塞**（全貌） | D2 合成语料具名 + D3 判别力自证 + D4 现网读数（**只报不拦**） |
| 全库 · 基线 | `.github/case-ids-dangling-baseline.json` + `baseline_violations()`（唯一实现） | **新增即红** / 少于基线 ⇒ 要求同批下沉 / `history` 回升 ⇒ 红 | D7（阻塞面，含「调大基线 ⇒ 报不得放宽」） |

🔴 **报告腿不许变成隐形门禁**（裁定：历史遗留不阻塞）⇒ D4 **不断言** `findings == []`，
只在**非空**时 `warnings.warn` 具名（出现在 CI 的 warnings summary 里），并断言扫描器**没有失明**。
🔴 **但「新增」必须拦住**（裁定 2026-11-03）：只改 YAML 的批合让号不碰测试文件 ⇒ 变更集腿看不见，
只 warn = 没人看 = 等于没有 ⇒ 由 **D7 的基线台账**承担阻塞（`entries` + `history` 读数链，只许缩短）。
🔴 **不复制解析实现**：三条腿都调 `growth_gate` 的 `extract_case_ids` / `load_case_index` / `_is_test_file`。

## 边界（照实登记，§19.1）

- 扫描面 = `growth_gate._is_test_file` 的同一口径（`.py` / `.java` / `.ts` / `.tsx` 且文件名含 test/spec）
  ⇒ `.mjs` / `.js` 判据不在面内；
- 「最近一次改动该文件的 commit」是**文件级**读数（不是行级 blame），只作归因入口；
- 报告腿**不阻塞**（全貌）；「新增即红」由基线台账 + D7 承担（台账只许缩短，不得放宽）；
- 本判据不改任何门禁的通过条件、不新增豁免。
"""
import json
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".github"))


def _load(name: str, filename: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / ".github" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


growth_gate = _load("growth_gate_for_dangling_test", "growth_gate.py")
dangling = _load("case_ids_dangling_for_test", "case_ids_dangling.py")

CASE_IDS = ["MC-066"]

#: 合成夹具的仓库相对路径（**不要**在源码里写成 `path:<行号>` 字面量，见 D2 的注释）
FIXTURE_REL = "tests/test_bad_thing.py"


# ── 合成语料（与真仓库结构同形：.github/cases/*.yml + 测试文件）────────────────────


def _make_repo(tmp_path: Path, *, bad_header: bool) -> Path:
    """造一个**只有一套最小语料**的 git 仓库：一条用例 `ZZ-001` + 两个测试文件。

    ⚠️ 用例库文件的形状必须与真实语料同形（顶层 `cases:` 列表）—— `growth_gate.load_case_index`
    是按 `data.get("cases")` 读的，写成顶层列表会得到空索引（那样本判据会在**错的前提**上跑）。
    """
    (tmp_path / ".github" / "cases").mkdir(parents=True)
    (tmp_path / ".github" / "cases" / "misc.yml").write_text(
        'schema: "case-contract/1.0"\ndomain: misc\n\ncases:\n  - id: ZZ-001\n    title: 合成用例\n',
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    # ⚠️ 夹具正文里**不能**出现弱断言形态（`assert True` 之类）：弱断言扫描器读的是**本文件源码文本**，
    # 会把字符串字面量里的形态当成真断言（实跑红了 `test_weak_assert_blindspots` 的「新增文件一律 fail-closed」）。
    body = "\n\ndef test_body():\n    return 1\n"
    (tests / "test_good_thing.py").write_text("# case_ids: ZZ-001" + body, encoding="utf-8")
    bad = ("# case_ids: ZZ-999" if bad_header else "# case_ids: ZZ-001") + body
    (tests / "test_bad_thing.py").write_text(bad, encoding="utf-8")
    for cmd in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed"],
    ):
        subprocess.run(cmd, cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_d1_changed_set_is_blocking_and_has_teeth(tmp_path: Path):
    """D1（**阻塞腿**）：变更集里声明了不存在的 id ⇒ `case_trace_check` 判 block；合规 ⇒ 不判。"""
    repo = _make_repo(tmp_path, bad_header=True)
    target = "tests/test_bad_thing.py"
    blocks, _warns, report = growth_gate.case_trace_check([], [target], str(repo), str(repo / ".github" / "cases"), base="HEAD")
    assert blocks, "变更集里的悬空引用必须**阻塞**（这条若空 ⇒ QA Growth Gate 的 G5 腿形同虚设）"
    assert "ZZ-999" in blocks[0]["reason"], f"判红必须**具名**那个 id，实际 = {blocks[0]['reason']!r}"

    good_blocks, _w, good_report = growth_gate.case_trace_check(
        [], ["tests/test_good_thing.py"], str(repo), str(repo / ".github" / "cases"), base="HEAD"
    )
    assert good_blocks == [], f"合规文件不该判红，实际 = {good_blocks!r}"
    assert [r for r in good_report if r.get("level") == "pass"], "合规文件必须落 pass 报告（防「绿了但没跑」）"

    # 判别力自证：把解析摘掉（恒返回空声明）⇒ 同一份语料**不再**判红
    original = growth_gate.extract_case_ids
    try:
        growth_gate.extract_case_ids = lambda _p: []
        muted, _w2, _r2 = growth_gate.case_trace_check(
            [], [target], str(repo), str(repo / ".github" / "cases"), base="HEAD"
        )
    finally:
        growth_gate.extract_case_ids = original
    assert muted, "摘掉解析后仍判红 ⇒ 说明判红来自别处（本判据没有判别力）"
    assert all("ZZ-999" not in b["reason"] for b in muted), "摘掉解析后仍具名悬空 id ⇒ 判别力自证不成立"


def test_d2_full_corpus_report_names_each_dangling_ref(tmp_path: Path):
    """D2（**报告腿**）：合成语料里的悬空引用被**具名**列出（文件:行 / id / 最近改动 commit）。"""
    repo = _make_repo(tmp_path, bad_header=True)
    report = dangling.scan(repo_root=repo, cases_dir=repo / ".github" / "cases")
    assert report["status"] == "found", report
    assert report["scanned"] == 2, f"扫描面必须看见两个测试文件，实际 = {report['scanned']}"
    findings = report["findings"]
    assert len(findings) == 1, findings
    f = findings[0]
    assert f["file"] == FIXTURE_REL
    assert f["line"] == 1
    assert f["case_id"] == "ZZ-999"
    assert f["last_commit"], "必须给出「最近一次改动该文件的 commit」（归因入口）"

    md = dangling.render_markdown(report, generated_on="2026-11-03")
    # ⚠️ 拼出来而不是写字面量：`path:<line>` 形态会被 Case Trust 当成**真仓行号引用**（合成夹具不存在 ⇒ 判红）
    located = FIXTURE_REL + ":" + "1"
    for needle in ("悬空引用：1 条", located, "ZZ-999", "复算", "报告型"):
        assert needle in md, f"清单缺 {needle!r}"

    clean = dangling.scan(repo_root=_make_repo(tmp_path / "clean", bad_header=False), cases_dir=tmp_path / "clean" / ".github" / "cases")
    assert clean["status"] == "clean", clean
    assert "全库无悬空引用" in dangling.render_markdown(clean, generated_on="2026-11-03")


def test_d3_report_scanner_is_not_a_no_op(tmp_path: Path):
    """D3（判别力自证）：把解析摘掉 ⇒ 全库报告变空（证明它真的在读声明，不是恒绿）。"""
    repo = _make_repo(tmp_path, bad_header=True)
    assert dangling.scan(repo_root=repo, cases_dir=repo / ".github" / "cases")["findings"], "前提：语料里本就有悬空"

    original = growth_gate.extract_case_ids
    class _NoDecl:
        @staticmethod
        def load_case_index(path):  # noqa: D401 - 替身保持原签名（**返回二元组**，与真实现一致）
            return original_index, None

        @staticmethod
        def _is_test_file(rel):  # noqa: D401
            return True

        @staticmethod
        def extract_case_ids(_p):
            return []

        CASE_IDS_RE = growth_gate.CASE_IDS_RE

    original_index = growth_gate.load_case_index(str(repo / ".github" / "cases"))[0]
    original_loader = dangling._growth_gate
    try:
        dangling._growth_gate = lambda: _NoDecl  # type: ignore[assignment]
        muted = dangling.scan(repo_root=repo, cases_dir=repo / ".github" / "cases")
    finally:
        dangling._growth_gate = original_loader  # type: ignore[assignment]
    assert muted["findings"] == [], "摘掉解析后必须变空（否则本报告在空跑）"
    # 摘掉解析 ⇒ 一个声明都读不到 ⇒ 扫描面为空 ⇒ 落 **undecidable**（fail-closed），**不是** clean：
    # 这条同时证明两件事：① 报告不是恒绿（它真的在读声明）；② 读不到时它**不会**冒充「全库干净」。
    assert muted["status"] == "undecidable", muted
    assert "失明" in muted["reason"], muted


def test_d4_live_corpus_reading_is_reported_never_blocking():
    """D4（现网读数，**报告型不阻塞**）：扫描器没失明；有悬空 ⇒ 具名 warn（不 assert 空）。"""
    report = dangling.scan()
    assert report["status"] != "undecidable", f"扫描器不可判定 ⇒ 判据失明，必须红：{report.get('reason')}"
    assert report["scanned"] > 1000, f"扫描面过窄（{report['scanned']}）⇒ 判据可能失明"
    assert report["corpus"] > 500, f"用例库读数过窄（{report['corpus']}）"

    # 本仓的合规样本必须在扫描面里（防「看起来扫了 2147 个、其实一个声明都没解析到」）
    ours = REPO_ROOT / "frontend/bmini-app/tests/inbound-print-capability-terminal.test.ts"
    assert ours.is_file()
    declared = growth_gate.extract_case_ids(str(ours))
    assert declared, "合规样本应声明 case_ids（它是 issue #8310 的判据载体）"
    assert all(c in growth_gate.load_case_index(str(REPO_ROOT / ".github" / "cases"))[0] for c in declared), (
        f"main 上出现悬空引用 ⇒ 报告腿必须列出（**不阻塞**），但文档要重生：{declared}"
    )

    if report["findings"]:
        warnings.warn(
            "全库有 %d 条悬空 case_ids 引用（报告型，不阻塞）：%s —— 复算 `python3 .github/case_ids_dangling.py`"
            % (len(report["findings"]), json.dumps(report["findings"], ensure_ascii=False)),
            stacklevel=1,
        )


def test_d5_doc_surface_exists_and_is_actionable():
    """D5：人读承接面（`docs/testing/case-ids-dangling.md`）在场，且带**复算命令**与分工表。"""
    doc = REPO_ROOT / "docs/testing/case-ids-dangling.md"
    assert doc.is_file(), "报告腿必须有可读承接面（与 casebook 做邻居）"
    text = doc.read_text(encoding="utf-8")
    for needle in ("python3 .github/case_ids_dangling.py", "报告型", "只列出、不阻塞", "本次读数"):
        assert needle in text, f"清单缺 {needle!r}（人读面必须能一眼看到怎么复算 + 它不阻塞）"


def test_d6_exit_codes_are_three_state():
    """D6：退出码三态（0 无 / 1 有悬空【报告型】/ 3 无法判定）—— 3 绝不能被读成 0。"""
    original = dangling.scan
    try:
        dangling.scan = lambda **_k: {"status": "clean", "scanned": 1, "corpus": 1, "findings": []}
        assert dangling.main(["x"]) == 0
        dangling.scan = lambda **_k: {
            "status": "found",
            "scanned": 1,
            "corpus": 1,
            "findings": [{"file": "a.py", "line": 1, "case_id": "ZZ-9", "last_commit": "`abc` 2026-11-03"}],
        }
        assert dangling.main(["x"]) == 1, "有悬空 ⇒ 1（报告型，但退出码要让调用方看得见）"
        dangling.scan = lambda **_k: {"status": "undecidable", "reason": "用例库读不到", "scanned": 0, "corpus": 0, "findings": []}
        assert dangling.main(["x"]) == 3, "不可判定 ⇒ 3（不得当 0 读）"
    finally:
        dangling.scan = original


def test_d7_baseline_ledger_new_dangling_blocks_and_cannot_widen():
    """D7（**基线面，阻塞**）：新增即红 / 只许缩短 / 基线不得放宽 / 未登记不得当 0 读。

    为什么这条必须**阻塞**（裁定 2026-11-03）：批合工具会把 main 上**已合入**的号也改掉 ⇒
    悬空引用会**继续产生**，而它**只改 YAML**（变更集腿看不见）⇒ 只 warn 的报告腿 = 没人看 = 等于没有。
    """
    baseline = dangling.load_baseline()
    assert baseline, "基线台账缺失 / 不可解析 ⇒ 不得当「0 条」读"
    problems = dangling.baseline_violations(baseline, len(dangling.scan()["findings"]))
    assert problems == [], (
        "实测与基线台账不一致（这是**阻塞面**）：\n  " + "\n  ".join(problems)
    )

    good = {"entries": {"dangling_total": 0}, "history": [{"date": "2026-11-03", "dangling_total": 0}]}
    # ① 新增即红：多出 1 条 ⇒ 判红，且要求「先修，不许调大基线」
    added = dangling.baseline_violations(good, 1)
    assert any("新增即红" in p for p in added), added
    # ② 只许缩短：实测比基线少 ⇒ 要求同批下沉
    shrunk = dangling.baseline_violations({"entries": {"dangling_total": 2}, "history": [{"dangling_total": 2}]}, 0)
    assert any("只许缩短" in p for p in shrunk), shrunk
    # ③ 基线不得放宽：history 出现回升 ⇒ 判红
    widened = {"entries": {"dangling_total": 2}, "history": [{"dangling_total": 0}, {"dangling_total": 2}]}
    assert any("基线不得放宽" in p for p in dangling.baseline_violations(widened, 2)), widened
    # ④ 台账链断开 / 未登记 ⇒ 判红（不得当 0 读）
    assert dangling.baseline_violations({}, 0), "空台账必须判红（否则删掉台账就绕过阻塞）"
    assert dangling.baseline_violations({"entries": {"dangling_total": 1}, "history": [{"dangling_total": 0}]}, 0)
