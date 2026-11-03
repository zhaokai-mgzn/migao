# case_ids: MC-137
"""仓库文本语料的**读面**必须与 CI 同口径：读 git 索引，不读工作树（issue #6594）。

## 病（issue #6594 逐字读数）

`./verify-all.sh gate` 的 bmini 腿（`frontend/bmini-app/tests/inbound-print-geometry-single-source.test.ts`
的 C2b）的语料原先 = `readCorpus(['frontend', 'backend'])` = **工作树文本扫描** ⇒ 扫到
**被 `.gitignore` 命中 / 未跟踪**的本地产物（实证 `backend/ai-agent-service/coverage.json`：
python coverage 的输出、496KB、天然含大量数字字面量，其中就有打印头宽的像素口径）⇒
**本机判红、CI 判绿**（干净检出里没有这个文件）⇒ 人会去修一个不存在的问题。

## 被测对象 = **读面**（不是谓词）

谓词（`384` 只许出现在介质矩阵）**一字未改**；本单只换「语料从哪来」。
故本文件的断言全部是**语料成员关系**，不重写第二份谓词（`migao-dev-flow` §23.7 A6：不造第二套真相）。

## 判据

| # | 判据 | 会怎么红 |
|---|---|---|
| ① | 临时夹具：**工作树有被 ignore 的旧产物 + 索引干净** ⇒ 语料**不含**它（与 CI 同口径 = 绿） | 读面退回工作树 ⇒ 该文件进语料 ⇒ 红 |
| ② | 索引里**真有**违规 ⇒ 必须进语料（**判别力不降**：修法不许把判据变成空断言） | 一律读空 / 全排除 ⇒ 红 |
| ③ | **单变量对照**（红证）：同一夹具只把读面换成 `worktree` ⇒ 那一行**必须**进语料 | 夹具不具判别力 ⇒ 两边都「没事」⇒ 红 |
| ④ | 默认读面 = 索引（行为面，不读源码字面量） | 默认翻成 worktree ⇒ 红 |
| ⑤ | 接线：守卫必须走共享读面，且旧的工作树遍历不许留在守卫里 | 摘掉 `trackedCorpus` 引用 / 塞回 `readdirSync` ⇒ 红 |
| ⑥ | **真仓库**上：语料 ⊆ `git ls-files` 的跟踪集合（回归面，正是本单的缺陷形态） | 任何未跟踪产物混进语料 ⇒ 红 |
| ⑦ | 读不到（不是 git 仓 / 缺参数）⇒ **非零退出**（不得当「空语料 = 通过」） | 退化成空 ⇒ 红 |
| ⑧ | 选项 A 的残余**必须出声**：未跟踪且未被 ignore 的代码文件进 `untracked`（不静默漏扫） | 静默漏 ⇒ 红 |

## 边界（照实登记，§19.1）

- 判不了「工作树里有没有别的**已跟踪**产物造成假红」—— 已跟踪文件在 CI 里也在，那本来就不是本单的形态。
- 判不了「守卫的谓词还能不能抓真违规」—— 那是 jest 判据本身（本单未改谓词，红证见
  `frontend/bmini-app/tests/inbound-print-geometry-single-source.test.ts` 的 C2/C2b 注入式用例）。
- 本文件**不含**类级元守卫：那份在 `tests/unit_ci_workflows/test_repo_corpus_read_face_ledger.py`
  （台账 `repo_corpus_read_face_ledger.json`）。
- 依赖 `node`（bmini 的运行时）。缺 node ⇒ **判红并给出安装出口**，**不 skip**（skip 会被读成通过）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_REL = "frontend/bmini-app/tests/helpers/trackedCorpus.js"
GUARD_REL = "frontend/bmini-app/tests/inbound-print-geometry-single-source.test.ts"
MATRIX_REL = "frontend/admin-web/src/lib/print-media.json"
PIPELINE_REL = "frontend/bmini-app/src/utils/inbound/labelCanvas.ts"
ARTIFACT_REL = "backend/ai-agent-service/coverage.json"
#: 守卫的真实射程（C2b 是**全仓**那一条 —— 本单的缺陷就在它上面发作）
REAL_ROOTS = ["frontend", "backend"]

NODE = shutil.which("node")


def _require_node() -> str:
    assert NODE, (
        "缺 `node` ⇒ 本判据**不可判定**（不得当通过）："
        "装 Node 18+ 后重跑 `python3 -m pytest tests/unit_ci_workflows/test_bmini_corpus_read_face.py -q`"
    )
    return NODE


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=ci@example.com", "-c", "user.name=ci", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )


def _run(repo: Path, roots: list[str], source: str | None = None) -> dict:
    """跑**真实现**（`trackedCorpus.js` 的 CLI）——不重写第二份读面。

    ⚠️ 实现文件取自**本仓**（`REPO_ROOT`），`--repo` 指向夹具 ⇒ 夹具里不必再放一份实现
    （放一份就等于在测试里造第二份读面，且它自己还会进 `frontend` 射程）。
    """
    cmd = [_require_node(), str(REPO_ROOT / HELPER_REL), "--repo", str(repo), "--roots", ",".join(roots)]
    if source is not None:
        cmd += ["--source", source]
    proc = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, (
        f"读面退出码 {proc.returncode}（应为 0）；stderr={proc.stderr[:600]!r}"
    )
    return json.loads(proc.stdout)


def _fixture(tmp_path: Path) -> Path:
    """临时 git 仓：**索引干净**（只有真值源 + 一份干净源码），工作树里**额外**放一份被 ignore 的旧产物。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / ".gitignore").write_text(f"{ARTIFACT_REL}\n", encoding="utf-8")

    matrix = repo / MATRIX_REL
    matrix.parent.mkdir(parents=True)
    matrix.write_text('{\n  "headWidthPx": 384\n}\n', encoding="utf-8")

    pipeline = repo / PIPELINE_REL
    pipeline.parent.mkdir(parents=True)
    pipeline.write_text("export const canvasWidthPx = effectiveWidthPx\n", encoding="utf-8")

    # ⚠️ 旧覆盖率产物：**被 .gitignore 命中**、**未跟踪**，且**含违规字面量**
    artifact = repo / ARTIFACT_REL
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"totals": {"num_statements": 384}}\n', encoding="utf-8")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture: 索引干净（产物被 ignore）")
    assert (repo / ARTIFACT_REL).exists(), "夹具自证：旧产物必须**真的**在工作树里"
    return repo


def test_ignored_stale_artifact_is_outside_the_verdict_corpus(tmp_path: Path) -> None:
    """① 工作树有被 ignore 的旧产物 + 索引干净 ⇒ 语料不含它（= CI 同口径，守卫必须绿）"""
    repo = _fixture(tmp_path)
    data = _run(repo, REAL_ROOTS)
    files = data["files"]
    assert ARTIFACT_REL not in files, (
        f"被 `.gitignore` 命中的旧产物进了判决语料 ⇒ 本机假红（CI 干净检出里没有它）：{ARTIFACT_REL}"
    )
    assert MATRIX_REL in files and PIPELINE_REL in files, (
        f"反空跑：索引里**真有**的跟踪文件必须还在语料里（否则「不含产物」是空断言）；实得 {files}"
    )
    # 被 ignore 的文件**不是**「未跟踪待出声」那一类（它已由 .gitignore 明确排除）⇒ 不许刷告警
    assert data["untracked"] == [], f"被 ignore 的产物不该进 `untracked`（噪声）：{data['untracked']}"


def test_same_fixture_read_from_the_worktree_turns_red(tmp_path: Path) -> None:
    """③ 红证（**单变量对照**）：同一夹具、只把读面换成工作树 ⇒ 那一行**必须**进语料（判据必红）"""
    repo = _fixture(tmp_path)
    index_files = _run(repo, REAL_ROOTS)["files"]
    worktree_files = _run(repo, REAL_ROOTS, source="worktree")["files"]
    assert ARTIFACT_REL not in index_files, "索引读面不该看见被 ignore 的产物"
    assert ARTIFACT_REL in worktree_files, (
        "夹具**不具判别力**：工作树读面也没看见那份旧产物 ⇒ 上一条「绿」不能证明本单修好了什么。"
        f"实得工作树语料 {len(worktree_files)} 个文件、不含 {ARTIFACT_REL}"
    )


def test_tracked_violation_still_enters_the_corpus(tmp_path: Path) -> None:
    """② 索引里**真有**违规 ⇒ 必须进语料（修法不许把判据变成空断言）"""
    repo = _fixture(tmp_path)
    # 强制入库（`-f` 越过 .gitignore）⇒ 此时它是**已跟踪**文件，CI 里也会有它
    _git(repo, "add", "-f", ARTIFACT_REL)
    _git(repo, "commit", "-q", "-m", "fixture: 违规内容入库")
    files = _run(repo, REAL_ROOTS)["files"]
    assert ARTIFACT_REL in files, (
        "已跟踪的违规文件没进语料 ⇒ 判别力下降（那种内容在 CI 里也会红，本判据必须看得见）"
    )


def test_default_read_face_is_the_index(tmp_path: Path) -> None:
    """④ 默认读面 = 索引（行为面：不给 `--source`，读数必须自报 index）"""
    repo = _fixture(tmp_path)
    data = _run(repo, REAL_ROOTS)
    assert data["source"] == "index", (
        f"默认读面被改成了 {data['source']!r} ⇒ 谁忘了传参数就又回到工作树（本单的缺陷形态）"
    )


def test_guard_is_wired_to_the_shared_read_face() -> None:
    """⑤ 接线：守卫必须走共享读面，旧的工作树遍历不许留在守卫里（§28.2「判据绿 ≠ 接线在」）"""
    src = (REPO_ROOT / GUARD_REL).read_text(encoding="utf-8")
    assert "trackedCorpus" in src, (
        f"{GUARD_REL} 不再引用共享读面 `tests/helpers/trackedCorpus.js` ⇒ 接线被摘掉"
    )
    assert "readdirSync" not in src, (
        f"{GUARD_REL} 又出现了 `readdirSync`（工作树遍历）⇒ 旧读面回来了"
    )
    helper = (REPO_ROOT / HELPER_REL).read_text(encoding="utf-8")
    assert "ls-files" in helper, f"{HELPER_REL} 的索引读面不见了（`git ls-files` 是本单的根因修法）"


def test_real_repo_corpus_is_a_subset_of_tracked_files() -> None:
    """⑥ **真仓库**回归面：守卫语料 ⊆ `git ls-files` 的跟踪集合（本单的缺陷形态）"""
    data = _run(REPO_ROOT, REAL_ROOTS)
    files = data["files"]
    assert len(files) >= 1000, f"反空跑：真仓库语料只读到 {len(files)} 个文件 ⇒ 归一化有误 / 读面坏了"
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", *REAL_ROOTS],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180, check=True,
    ).stdout
    tracked_set = {p for p in tracked.split("\0") if p}
    stray = sorted(set(files) - tracked_set)
    assert stray == [], f"语料里有**未跟踪**的文件（本机假红的来源）：{stray[:10]}"


def test_unreadable_corpus_fails_closed(tmp_path: Path) -> None:
    """⑦ 读不到 ⇒ 非零退出（不得当「空语料 = 通过」）"""
    repo = tmp_path / "not_a_git_repo"
    (repo / "frontend").mkdir(parents=True)
    cmd = [_require_node(), str(REPO_ROOT / HELPER_REL), "--repo", str(repo), "--roots", "frontend"]
    proc = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0, f"不是 git 仓却退出 0 ⇒ 「读不到」被读成「空语料 = 通过」；stdout={proc.stdout[:300]!r}"
    assert "不可判定" in proc.stderr, f"非零退出没有说清原因（stderr={proc.stderr[:300]!r}）"


def test_untracked_but_not_ignored_files_are_surfaced(tmp_path: Path) -> None:
    """⑧ 选项 A 的残余**必须出声**：未跟踪且未被 ignore 的代码文件进 `untracked`（不静默漏扫）"""
    repo = _fixture(tmp_path)
    fresh = repo / "frontend/bmini-app/src/utils/inbound/newFile.ts"
    fresh.write_text("export const x = 1\n", encoding="utf-8")  # 未跟踪、且**不在** .gitignore 里
    data = _run(repo, REAL_ROOTS)
    assert "frontend/bmini-app/src/utils/inbound/newFile.ts" in data["untracked"], (
        f"未跟踪的新文件必须被印出来（否则本地把违规写进新文件时静默漏扫）：{data['untracked']}"
    )
    assert "frontend/bmini-app/src/utils/inbound/newFile.ts" not in data["files"], (
        "未跟踪文件不该进判决语料（那正是「本机红 / CI 绿」的来源）"
    )
