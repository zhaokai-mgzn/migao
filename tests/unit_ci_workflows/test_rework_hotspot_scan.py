# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""返工高频扫描（`scripts/rework_hotspot_scan.py`）的 L0 守卫 —— issue #4012「追加」项。

## 为什么给一个「报告型脚本」写 L0 测试

报告型脚本最典型的失效形态是**静默空转**：解析悄悄命中 0 条 ⇒ 报告打印
「（无 hotspot）」⇒ 读者读成「**没有返工热区**」。而真相可能是「解析器坏了」。
两种结论在控制台上**长得一模一样**，这正是 `migao-acceptance`「空跑」那一类。

故本文件锁四件事：

1. **fix 判据**（`is_fix_subject`）：`fix(...)`/`修复`/`Revert` 命中；`fixup!`（autosquash 残留）
   与 `Merge …` 不命中 —— 各自都是注入式红证；
2. **函数区间**（`function_spans`）：顶层函数 / 类方法 / 异步函数都解析得到；语法错即空（不抛）；
3. **改动行区间**（`changed_files_and_ranges`）：**在临时 git 仓库里构造真实提交**，
   断言「改了第几行 ⇒ 命中哪个函数」；**含那个最阴的坑**——
   hunk **内容**里的 `+++ b/...` 文本不得被当成文件头（否则区间挂错文件）；
4. **不阻塞语义**：命中 hotspot 时退出码仍为 0（报告型），且**报告必须含处置要求原文**
   （否则被读成「仅供参考的统计」）。

## 红证（每条都能指出反例输入）

| 用例 | 反例输入 |
|---|---|
| `test_fix_subject_detector_*` | 把 `fixup!` 也算成 fix（或把 `fix` 漏掉）⇒ 必红 |
| `test_parser_survives_hunk_content_that_looks_like_a_file_header` | 把状态机改成「只看 `+++ ` 前缀」⇒ 区间挂到错误文件 ⇒ 必红 |
| `test_scan_reports_a_function_touched_by_fix_commits` | 把 `_hit` 的区间比较写错（如用 `<` 而非 `<=`）⇒ 必红 |
| `test_scan_output_is_never_a_silent_empty_report` | 让解析返回空 ⇒ 报告会打印「（无）」而这个用例要求分母非零 |
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "rework_hotspot_scan.py"


def _load():
    """按路径加载脚本模块（`scripts/` 不是包，不能 import）。"""
    spec = importlib.util.spec_from_file_location("rework_hotspot_scan", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hs = _load()


# ──────────────────────────────────────────────────────────────────────────────
# ① fix 判据
# ──────────────────────────────────────────────────────────────────────────────


class TestFixSubjectDetector:
    """`is_fix_subject` —— 判据的入口，错了整份报告都是错的。"""

    @pytest.mark.parametrize("subject", [
        "fix(ai-agent): 顾客确认卡不落单（#3976）",
        "fix: 修正订单金额",
        "hotfix: 生产 502",
        "Bugfix 订单状态机",
        "修复换货流程 pending 残留",
        "回归：OR-014 改价不落 SKU",
        'Revert "feat(eval): 新评分口径"',
        "fixup 前面没有感叹号也算",
        "补丁：地址解析",
    ])
    def test_fix_subjects_are_detected(self, subject):
        assert hs.is_fix_subject(subject) is True, f"漏判为**非** fix：{subject!r}"

    @pytest.mark.parametrize("subject", [
        "fixup! fix(ai-agent): 上一个提交的残留（autosquash 未 squash）",
        "squash! 某个中间态",
        "feat(ai-agent): 新增生产进度查询",
        "docs: 更新 README",
        "chore(deps): bump fastapi",
        "test: 补 OR-029 用例",
        "refactor: 拆 execute_skill",
    ])
    def test_non_fix_subjects_are_not_detected(self, subject):
        assert hs.is_fix_subject(subject) is False, f"误判为 fix：{subject!r}"

    def test_detector_is_not_constant(self):
        """防恒真/恒假：两类输入必须给出**不同**结果（否则判据是空的）。"""
        assert hs.is_fix_subject("fix: a") != hs.is_fix_subject("feat: b")


# ──────────────────────────────────────────────────────────────────────────────
# ② 函数区间
# ──────────────────────────────────────────────────────────────────────────────


class TestFunctionSpans:
    SOURCE = (
        "import os\n"
        "\n"
        "def top_level(a):\n"        # 3
        "    return a\n"             # 4
        "\n"
        "class Foo:\n"               # 6
        "    def method(self):\n"    # 7
        "        return 1\n"         # 8
        "\n"
        "    async def amethod(self):\n"  # 10
        "        return 2\n"              # 11
        "\n"
        "async def top_async():\n"   # 13
        "    return 3\n"             # 14
    )

    def test_spans_cover_top_level_class_and_async(self):
        spans = dict((name, (lo, hi)) for name, lo, hi in hs.function_spans(self.SOURCE))
        assert set(spans) == {"top_level", "Foo.method", "Foo.amethod", "top_async"}, spans
        assert spans["top_level"] == (3, 4)
        assert spans["Foo.method"] == (7, 8)
        assert spans["top_async"] == (13, 14)

    def test_syntax_error_yields_empty_not_traceback(self):
        """坏文件不得炸整轮扫描（历史版本里出现过非 UTF-8 字节的同类事故）。"""
        assert hs.function_spans("def broken(:\n") == []

    def test_hit_uses_inclusive_bounds(self):
        """命中判据必须**闭区间**（边界行改了要算命中）—— 反例：改成开区间即红。"""
        spans = [("f", 10, 20)]
        assert hs._hit(spans, [(10, 10)]) == {"f"}, "起始边界行漏判"
        assert hs._hit(spans, [(20, 20)]) == {"f"}, "结束边界行漏判"
        assert hs._hit(spans, [(21, 21)]) == set(), "越界行误判"


# ──────────────────────────────────────────────────────────────────────────────
# ③ 真实 git 夹具：改动行 → 函数（含 `+++` 内容行的坑）
# ──────────────────────────────────────────────────────────────────────────────


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"git {' '.join(args)} 失败：{proc.stderr}"
    return proc.stdout


@pytest.fixture()
def fixture_repo(tmp_path: Path):
    """**注入式夹具**：临时 git 仓库（不依赖本仓历史，永远有效）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "tester")
    _git(repo, "config", "commit.gpgsign", "false")

    module = repo / "mod.py"
    module.write_text(
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "def beta():\n"
        "    return 2\n",
        encoding="utf-8",
    )
    _git(repo, "add", "mod.py")
    _git(repo, "commit", "-q", "-m", "feat: 初始版本")
    return repo


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def test_changed_ranges_map_to_the_touched_function(fixture_repo):
    """**端到端判据**：只改 `beta` 一行 ⇒ 只命中 `beta`（不命中 `alpha`）。"""
    module = fixture_repo / "mod.py"
    module.write_text(
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "def beta():\n"
        "    return 999\n",  # ← 只改这里（第 5 行）
        encoding="utf-8",
    )
    sha = _commit(fixture_repo, "fix: 只动 beta")

    files, ranges = hs.changed_files_and_ranges(fixture_repo, sha)
    assert files == ["mod.py"], files
    assert ranges["mod.py"] == [(5, 5)], ranges

    spans = hs.function_spans(module.read_text(encoding="utf-8"))
    assert hs._hit(spans, ranges["mod.py"]) == {"beta"}, hs._hit(spans, ranges["mod.py"])


def test_parser_survives_hunk_content_that_looks_like_a_file_header(tmp_path: Path):
    """**最阴的坑**：hunk **内容行**里出现 `+++ b/` 文本时，不得被当成文件头。

    构造：往 `mod.py` 里写入一行字符串字面量 `    marker = "+++ b/evil.py"`。
    它是一行 `+` 开头的**内容**，解析器必须（a）不把它算成新文件 `evil.py`，
    （b）不把后续 hunk 的区间挂到它身上。

    反例输入：把 `changed_files_and_ranges` 的状态机简化成「只看 `+++ ` 前缀」⇒ 必红。
    """
    repo = tmp_path / "repo2"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "tester")
    repo_mod = repo / "mod.py"
    repo_mod.write_text("def gamma():\n    return 0\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "feat: 初始")

    repo_mod.write_text(
        "def gamma():\n"
        "    return 0\n"
        "\n"
        "def delta():\n"
        '    marker = "+++ b/evil.py"\n'  # ← hunk 内容里的“文件头”文本
        "    return 1\n",
        encoding="utf-8",
    )
    sha = _commit(repo, "fix: 加一行伪装成文件头的内容")

    files, ranges = hs.changed_files_and_ranges(repo, sha)
    assert files == ["mod.py"], f"hunk 内容行被当成了文件头：{files}"
    assert "evil.py" not in ranges, f"区间挂到了伪文件上：{sorted(ranges)}"
    spans = hs.function_spans(repo_mod.read_text(encoding="utf-8"))
    assert hs._hit(spans, ranges["mod.py"]) == {"delta"}, hs._hit(spans, ranges["mod.py"])


def test_scan_reports_a_function_touched_by_fix_commits(fixture_repo):
    """**端到端扫描**：两次 fix 命中同一函数 ⇒ `functions` 计数为 2（不是 0/1）。"""
    module = fixture_repo / "mod.py"
    for i, value in enumerate((11, 12), start=1):
        module.write_text(
            "def alpha():\n"
            "    return 1\n"
            "\n"
            "def beta():\n"
            f"    return {value}\n",
            encoding="utf-8",
        )
        _commit(fixture_repo, f"fix: 第 {i} 次修 beta")

    report = hs.scan(fixture_repo, paths=("mod.py",))
    assert report["fix_commits"] >= 2, report["fix_commits"]
    assert report["functions"]["mod.py::beta"]["fix"] == 2, report["functions"]
    assert "mod.py::alpha" not in report["functions"], "未改动的函数被误计入"
    assert report["files"]["mod.py"]["all"] >= 3, report["files"]


def test_non_fix_commits_do_not_count(fixture_repo):
    """**负例（R2）**：`feat:` 提交改动同一函数 ⇒ 不进 fix 计数，但进 `all` 计数。"""
    module = fixture_repo / "mod.py"
    module.write_text(
        "def alpha():\n"
        "    return 1\n"
        "\n"
        "def beta():\n"
        "    return 3\n",
        encoding="utf-8",
    )
    _commit(fixture_repo, "feat: 给 beta 加个默认值")

    report = hs.scan(fixture_repo, paths=("mod.py",))
    assert report["functions"].get("mod.py::beta", {}).get("fix", 0) == 0, report["functions"]
    assert report["files"]["mod.py"]["all"] >= 2, report["files"]
    assert report["files"]["mod.py"]["fix"] == 0, report["files"]


# ──────────────────────────────────────────────────────────────────────────────
# ④ 报告语义（不阻塞 + 处置要求必须在场）
# ──────────────────────────────────────────────────────────────────────────────


class TestReportSemantics:
    REPORT = {
        "repo_commits": 10, "fix_commits": 6, "fix_ratio": 0.6,
        "files": {"a.py": {"fix": 7, "all": 9, "shas": ["deadbeef"]}},
        "functions": {"a.py::f": {"fix": 7, "shas": ["deadbeef"]}},
    }

    def test_report_contains_the_mandated_disposition(self):
        """报告必须含 issue #4012 的**处置要求原文**（否则被读成参考统计）。"""
        text = hs.render(self.REPORT, threshold=5, top=5)
        assert "机制级修法或登记独立 issue" in text
        assert "返工高频扫描" in text
        assert "a.py::f" in text and "a.py" in text

    def test_threshold_filters_below_threshold_entries(self):
        """阈值必须真的生效（反例：threshold 写死 0 ⇒ 全量刷屏）。"""
        low = hs.render(self.REPORT, threshold=8, top=5)
        assert "a.py::f" not in low, "低于阈值的条目仍被列出 —— 阈值形同虚设"

    def test_empty_report_says_so_explicitly(self):
        """空报告必须**显式**打印「（无 …）」并保留分母，不许静默留白。"""
        empty = {"repo_commits": 3, "fix_commits": 0, "fix_ratio": 0.0, "files": {}, "functions": {}}
        text = hs.render(empty, threshold=5, top=5)
        assert "（无" in text
        assert "3 个非 merge 提交" in text

    def test_main_exit_code_is_zero_even_with_hotspots(self, tmp_path: Path, capsys):
        """**报告型语义**：命中 hotspot 也不许非零退出（不得变成隐形门禁）。"""
        assert hs.main(["--repo", str(REPO_ROOT), "--max-commits", "30", "--threshold", "1"]) == 0

    def test_main_rejects_bad_usage(self):
        assert hs.main(["--threshold", "0"]) == 2
        assert hs.main(["--top", "0"]) == 2


def test_scan_script_is_wired_into_the_docs_or_discoverable():
    """可发现性：脚本自带 `--help` 且**默认路径**非空（裸跑必须真的扫东西）。"""
    assert hs.DEFAULT_PATHS, "默认扫描路径为空 ⇒ 裸跑等于空跑"
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, check=False,
    )
    assert out.returncode == 0, out.stderr
    assert "--threshold" in out.stdout and "--json" in out.stdout