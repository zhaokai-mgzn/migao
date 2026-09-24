# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""#5309：受管引用面（`REF_SURFACE`）的**覆盖固化** —— 治「判定面外 ⇒ 永久免检」这一类。

病根（`#5298` → `#5309`）：`#5298` 只修好了判定面**内**的悬空引用；**同族**引用落在
`REF_SURFACE` **之外**（`tests/agent_eval/` 与 `.github/cases/`）⇒ 悬空**连读数都没有**
（不是"判绿"，是"没判"）。本文件把「这两个目录必须在判定面内」+「判定面是显式清单、
**新增目录必须同时进清单**」钉成**会红**的常驻判据（跑在 **required** 的
`ci workflow helper unit tests` 里，不只依赖 `Drift Audit`）。

四条判据，**每条都带注入式红证**：
  ① `REQUIRED_COVERED ⊆ REF_SURFACE`，且判定面的匹配语义 = **精确目录前缀**
     （不吃兄弟目录 `tests/agent_eval_extra/`，且豁免面 / 派生视图优先级不变）；
  ② **真实扫描**：这两个目录里出现 `path:NNN` 的裸/越界引用 ⇒ 审计必报（当前树 = 0 条）；
  ③ **两向注入**：同一个夹具仓库 —— 覆盖 ⇒ **必红**；把目录移出判定面 ⇒ **静默**
     （证明 ② 不是空断言：绿的成因是"真的判过且干净"，不是"没判"）；
  ④ **类级元守卫**：仓库里承载 `path:NNN` 的目录集合 ⊆ 判定面 ∪ 豁免面 ∪
     **显式登记的不判表**（带理由）⇒ 下一个人再引入一个**未被扫描的目录**会被拦住
     （差集暴露 + 指名怎么处置，不静默放过）。

⚠️ 本文件**不**改 `drift_audit.py` 的判定逻辑：只**读**它的 `REF_SURFACE` / `REF_PATH` /
`SCAN_EXTS` / `_in_surface`（判据本体单一真相源，不复制第二套正则或清单）。
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIFT = REPO_ROOT / "scripts" / "drift_audit.py"

# ── 判据 ① 的必需覆盖集：**本单裁定必须进判定面**的两个评测面目录 ───────────────
REQUIRED_COVERED = ("tests/agent_eval/", ".github/cases/")

# ── 判据 ④ 的**显式不判表**（每条必须给理由；粒度 = 顶层两级目录）──────────────
# 「不判」不是"没看见"：这里是**逐条裁定**的结果，差集非空即红 ⇒ 新增一条必须同时改这里。
# 判据是 `test_meta_guard_ref_bearing_dirs_are_declared`（含把 `tests/agent_eval/`
# 移出判定面 ⇒ 元守卫必红的注入式红证）。
DECLARED_NOT_COVERED = {
    "backend/ai-agent-service":
        "服务端源码 / 单测**自身的注释**：行号是局部读数，不是跨端契约引用 —— 判定面有意只收"
        "『契约性引用载体』（契约文档 / CI / runner / 用例源）。本单已把 `tests/agent_eval/` 纳入；"
        "服务源码面与代码改动强耦合，留待单独一轮。",
    "backend/admin-api":
        "同上（Java 侧）。注意：已发布的**迁移目录**是单独纳入判定面的"
        "（`backend/admin-api/src/main/resources/db/migration/`，见 `REF_SURFACE` 内的注释）。",
    "frontend/mini-app":
        "e2e 规格 / `e2e/lib` 里的选择器与组件位置引用（e2e 自述，非契约引用）。",
    "frontend/admin-web":
        "前端单测（`tests/unit/**`）里的引用（同上：测试自述）。",
    ".github":
        "`.github/*.py` 门禁脚本自身的引用。**本批有意不纳入**：加面会引入超出本单预算的"
        "存量（burn-down R4『只许缩短』）⇒ 登记为**下一批候选**（含 `.github/scripts/**`，"
        "#5309 不动它）。",
    "tests/e2e":
        "`tests/e2e/**` 的引用（e2e 自述，同 `frontend/mini-app` 一档）。",
}


# ─────────────────────────────────────────────────────────────────────────────
# 夹具与加载（按路径加载被测脚本：`dataclass` 要求模块在 `sys.modules` 里可达）
# ─────────────────────────────────────────────────────────────────────────────
def _drift_module():
    name = "drift_audit_ref_surface_under_test"
    spec = importlib.util.spec_from_file_location(name, DRIFT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _mk_repo(tmp: Path, files: dict[str, str]) -> Path:
    """临时 git 仓库（分支 `main`，一次提交）—— 文件必须**入库**（`git ls-files` 才算判定面）。"""
    repo = tmp / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "user.name", "fixture")
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _ref_findings(mod, repo: Path) -> dict[str, str]:
    """`ref-freshness` 的 findings（key → 判据内部标识）。

    `base="HEAD"`（不是 `origin/main`）：夹具仓库与 CI 检出都保证 `HEAD` 可达 ⇒
    行越界（`oor`）判定在任何检出深度下都**真跑**（不会因取不到 base 静默退化成"不判"）。
    """
    audit = mod.Audit(repo, base="HEAD", offline=True)
    return {f.key: f.key.rsplit("|", 1)[-1] for f in mod.check_refs(audit).findings}


def _refs_by_top_dir(mod, repo: Path) -> dict[str, int]:
    """仓库里**被判定**的文件中承载 `path:NNN` 的目录（顶层两级粒度）→ 引用处数。

    复用被测脚本自己的 `REF_PATH` / `SCAN_EXTS`（**不复制第二套口径**）。
    """
    audit = mod.Audit(repo, base="HEAD", offline=True)
    out: dict[str, int] = {}
    for rel in audit.tracked():
        if not rel.endswith(mod.SCAN_EXTS):
            continue
        txt = audit.read(rel)
        if not txt:
            continue
        n = len(mod.REF_PATH.findall(txt))
        if not n:
            continue
        parts = rel.split("/")
        top = "/".join(parts[:2]) if len(parts) > 2 else "/".join(parts[:-1] or ["<root>"])
        out[top] = out.get(top, 0) + n
    return out


def _uncovered_dirs(mod, repo: Path) -> dict[str, int]:
    """判定面 / 豁免面**之外**仍承载引用的目录（=「永久免检」的差集）。"""
    surface, exempt = tuple(mod.REF_SURFACE), tuple(mod.REF_SURFACE_EXEMPT)
    return {d: n for d, n in _refs_by_top_dir(mod, repo).items()
            if not any(d.startswith(s.rstrip("/")) or s.startswith(d + "/")
                       for s in surface)
            and not any(d.startswith(e.rstrip("/")) or e.startswith(d + "/")
                        for e in exempt)}


# ─────────────────────────────────────────────────────────────────────────────
# ① 必需覆盖 + 匹配语义（红证：把 `tests/agent_eval/` 移出 ⇒ 必红）
# ─────────────────────────────────────────────────────────────────────────────
def test_required_dirs_are_in_ref_surface_and_matching_is_exact_dir_prefix():
    """判据 ①：`REQUIRED_COVERED ⊆ REF_SURFACE`，且匹配 = **精确目录前缀**。

    红证（注入式）：把 `tests/agent_eval/` 从 `REF_SURFACE` 拿掉 ⇒ 覆盖断言**必红**
    （`#5309` 的原始形态：那两个目录整类免检，且**没有任何东西会变红**）。
    """
    mod = _drift_module()
    surface = tuple(mod.REF_SURFACE)

    def covered(entries) -> list[str]:
        return [d for d in REQUIRED_COVERED if d not in entries]

    missing = covered(surface)
    assert not missing, (
        f"这些目录不在 `REF_SURFACE` 里 ⇒ 其中的悬空/裸行号引用**整类永久免检**"
        f"（#5309 的确切形态：读数与事实不一致，且连读数都没有）：{missing}")

    # 每一条都必须以 `/` 结尾（= 目录前缀），否则 `startswith` 会吃进同名前缀的兄弟
    bad = [e for e in surface if not e.endswith("/")]
    assert not bad, f"`REF_SURFACE` 必须全部是**目录前缀**（以 `/` 结尾）：{bad}"
    for d in REQUIRED_COVERED:
        assert (REPO_ROOT / d).is_dir(), f"{d} 不在仓库里 ⇒ 覆盖断言指着一个不存在的目录"

    # 匹配语义（三向）：命中 / **不吃兄弟前缀** / 豁免面优先
    assert mod._in_surface("tests/agent_eval/local_runner.py")
    assert mod._in_surface(".github/cases/aftersales.yml")
    for sibling in ("tests/agent_eval_extra/x.py", "tests/agent_evalX/y.py",
                    ".github/casess/aftersales.yml"):
        assert not mod._in_surface(sibling), (
            f"{sibling} 被卷进判定面 ⇒ 匹配语义不是精确目录前缀（会扫不该扫的目录）")
    for exempt in ("docs/design/x.md", "docs/testing/acceptance/x.md", "acceptance/x.md"):
        assert not mod._in_surface(exempt), f"豁免面失效：{exempt} 被判进判定面"

    # 红证本体：拿掉必需项 ⇒ 断言函数必须能红
    redproof = covered(tuple(e for e in surface if e != "tests/agent_eval/"))
    assert redproof == ["tests/agent_eval/"], (
        f"把 `tests/agent_eval/` 移出 `REF_SURFACE` 却没让覆盖断言变红 ⇒ 本条是空断言：{redproof}")


# ─────────────────────────────────────────────────────────────────────────────
# ② 真实扫描：这两个目录的引用被**真的判过**（当前树 = 干净）
# ─────────────────────────────────────────────────────────────────────────────
def test_real_scan_has_no_bare_or_oor_refs_in_the_two_dirs():
    """判据 ②：**真实仓库**里，这两个目录不得有裸行号 / 越界引用。

    · 现在绿（#5309 第一批已把 29 条逐条改成符号/文本锚）；
    · **回归时会怎么红**：这两个目录里新增一条 `路径:行号`（无 `@<sha>`）或越界引用 ⇒
      失败消息逐字给出文件名 + ref + 判据类型（`|bare` / `|oor`）。
    """
    mod = _drift_module()
    findings = _ref_findings(mod, REPO_ROOT)
    in_two = {k: v for k, v in findings.items()
              if k.startswith(REQUIRED_COVERED)}
    assert not in_two, (
        "这两个目录（判定面已覆盖）里出现裸行号/越界引用 —— 按 dev-flow §16.7 改成**符号/文本锚**"
        f"（或 `第 N 行` + `@<sha>`）：{sorted(in_two.items())}")

    # 反向前提：判定面**非空**（否则上面那条会退化成"没判也绿"）
    audit = mod.Audit(REPO_ROOT, base="HEAD", offline=True)
    judged = [f for f in mod._iter_surface_files(audit) if f.startswith(REQUIRED_COVERED)]
    assert judged, (
        "这两个目录里一个**被判定**的文件都没有 ⇒ `ref-freshness` 对它们是空跑"
        "（绿 = 没判，不是判过）—— 这正是 #5309 要治的形态")


# ─────────────────────────────────────────────────────────────────────────────
# ③ 两向注入红证（夹具仓库）：覆盖 ⇒ 必红；移出判定面 ⇒ 静默
# ─────────────────────────────────────────────────────────────────────────────
def test_injection_two_dirs_red_when_covered_and_silent_when_uncovered(tmp_path):
    """判据 ③：同一个夹具仓库两向都钉住 —— 覆盖 ⇒ 报出；不覆盖 ⇒ **静默**。

    静默那一向才是 `#5309` 的病根证据：同样的悬空引用，目录不在面内时**一条读数都没有**
    （所以"改了目录清单"必须同时被元守卫拦住，见 ④）。
    """
    mod = _drift_module()
    target = "backend/ai-agent-service/app/tools/after_sales_manage.py"
    repo = _mk_repo(tmp_path, {
        # 5 行小文件：`:435` 必然越界
        target: "a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n",
        # 裸行号（在范围内、无 @<sha>）
        ".github/cases/aftersales.yml": f"# 探针读数见 `{target}:3`\n",
        # 越界（`#5309` 的现场形态：`after_sales_manage.py:435` 而该文件仅 259 行）
        "tests/agent_eval/local_runner.py": f'"""见 `{target}:435`。"""\n',
    })

    covered = _ref_findings(mod, repo)
    assert covered.get(f".github/cases/aftersales.yml|{target}#3|bare") == "bare", (
        f"`.github/cases/` 里的裸行号引用没被抓到 ⇒ 判定面没真的覆盖它：{covered}")
    assert covered.get(f"tests/agent_eval/local_runner.py|{target}#435|oor") == "oor", (
        f"`tests/agent_eval/` 里的**越界**引用没被抓到 ⇒ 判定面没真的覆盖它：{covered}")

    original = tuple(mod.REF_SURFACE)
    mod.REF_SURFACE = tuple(e for e in original if e not in REQUIRED_COVERED)
    try:
        silent = _ref_findings(mod, repo)
    finally:
        mod.REF_SURFACE = original
    assert not [k for k in silent if k.startswith(REQUIRED_COVERED)], (
        "把这两个目录移出判定面后**仍然**报出 ⇒ 上一条绿的成因不是判定面覆盖（夹具失效）："
        f"{silent}")


# ─────────────────────────────────────────────────────────────────────────────
# ④ 类级元守卫：承载引用的目录必须**显式**在判定面 / 豁免面 / 不判表里
# ─────────────────────────────────────────────────────────────────────────────
def test_meta_guard_ref_bearing_dirs_are_declared(tmp_path):
    """判据 ④：**没有任何目录能静默地落在判定面外**（差集必须为空）。

    为什么需要它（`#4708` 的 `ext-census` 同族）：判据面泄漏一次（漏一个目录 / 漏一类扩展名）
    就永久免检，而**没有任何东西会变红** —— 靠人记得更新清单是不可靠的，所以与"现实里真的有
    什么"对账（反推、不硬编码）。

    **回归时会怎么红**：① 必需覆盖目录被移出 `REF_SURFACE` ⇒ 覆盖断言红
    （把 `tests/agent_eval/` 从 `REF_SURFACE` 移出 ⇒ 本条必红，逐字记录见 PR body）；
    ② 新引入一个承载 `path:NNN` 的目录（粒度 = 顶层两级）而不改清单 ⇒ 失败消息逐字列出差集，
    并给出两条出口（契约载体 ⇒ 进 `REF_SURFACE`；不是 ⇒ 进 `DECLARED_NOT_COVERED` 并写理由）。
    """
    mod = _drift_module()
    surface = tuple(mod.REF_SURFACE)
    missing = [d for d in REQUIRED_COVERED if d not in surface]
    assert not missing, (
        f"必需覆盖的目录被移出 `REF_SURFACE` ⇒ 元守卫红（覆盖那一半）：{missing}"
        "（源文件单点变异的红证见本 PR body）")

    uncovered = _uncovered_dirs(mod, REPO_ROOT)
    undeclared = {d: n for d, n in uncovered.items() if d not in DECLARED_NOT_COVERED}
    assert not undeclared, (
        "这些目录承载 `路径:行号` 引用，却既不在 `REF_SURFACE`、也不在显式不判表里"
        "⇒ 里面的悬空引用**永久免检且无读数**（#5309 的形态）。两条出口：契约性引用载体 ⇒ "
        "加进 `scripts/drift_audit.py` 的 `REF_SURFACE`；不是 ⇒ 加进本文件的 "
        f"`DECLARED_NOT_COVERED` 并写清理由。差集：{sorted(undeclared.items())}")

    # 不判表自身不得腐烂：每条必须有理由、不得与判定面/豁免面重叠
    exempt = tuple(mod.REF_SURFACE_EXEMPT)
    for d, why in DECLARED_NOT_COVERED.items():
        assert why and len(why.strip()) >= 10, f"不判表的 `{d}` 没有写理由（不许留白）"
        assert not any(d.startswith(s) for s in surface), (
            f"`{d}` 已在 `REF_SURFACE` 里却又被登记为『不判』 ⇒ 两张表打架")
        assert not any(d.startswith(e) for e in exempt), (
            f"`{d}` 已在豁免面里，不必再登记：{d}")

    # 注入式红证（**两向**）：
    # ① 必需目录被移出判定面 ⇒ 上面那段覆盖断言**必红**（本文件源码单点变异的实测记录见 PR body）；
    # ② 给一个**未登记**的目录塞进一条引用 ⇒ 差集**必非空**（证明本条真的在与"现实里有什么"对账，
    #    而不是与清单自己的记忆对账 —— 后者永远绿）。
    # ⚠️ 这里**不**用「把 `tests/agent_eval/` 移出判定面 ⇒ 差集出现它」当红证：`#5309` 第一批已把
    #    那两个目录的引用**清零** ⇒ 无引用的目录**按定义**不在差集里（差集的口径是"承载引用的目录"）。
    #    拿它当红证 = 用一个结构性不成立的形态充数（`migao-acceptance`「空断言」同族）。
    fixture = _mk_repo(tmp_path, {
        "docs/wiki/ok.md": "见 `app/x.py:1 @abc1234`\n",   # 判定面内 + `@<sha>` 限定 ⇒ 合规
        "tools/notes.md": "见 `app/x.py:1`\n",             # **未登记目录**里的一条裸引用
    })
    injected = {d: n for d, n in _uncovered_dirs(mod, fixture).items()
                if d not in DECLARED_NOT_COVERED}
    assert "tools" in injected, (
        f"未登记目录里的 `路径:行号` 引用没被差集暴露 ⇒ 本条是空断言（下一个人新增目录拦不住）："
        f"{injected}")