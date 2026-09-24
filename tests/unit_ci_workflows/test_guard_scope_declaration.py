# case_ids: MC-012
"""「守卫**声称**的射程」必须等于「判据**实际**扫描的路径集」（issue #5284 的类级视角；承 #5260 / #5283）。

## 病根（一类缺陷，不是一个缺陷 —— 与 §23.7 A1/A2「声明 ≠ 射程」同族）

`tests/unit_ci_workflows/test_scripts_bash32_var_brace.py` 曾逐字写着「**不**扫 `scripts/**` 之外的
shell」，而同一族病灶当时正长在**仓库根**的 `check-ui-regression.sh` 里（#5284）⇒
**声称与事实脱节，且没有任何东西会因此变红**。根因不是「写漏了」，而是**声明是散文**：
散文不会被任何判据读 ⇒ 收窄射程只要改一行 glob，没人会红。本文件把射程变成
**结构化 + 机器可读 + 与实际对照**的四层：

| # | 判据 | 取法（结构化证据，**不读散文**） | 红证 |
|---|---|---|---|
| 1 | **引用语料即须登记**（未登记即红） | AST 取模块里**字符串常量**中的语料 glob：`*.sh` 是语料引用、`sync-main.sh` 不是 | 造一个引用语料却未入册的模块 ⇒ 必红 |
| 2 | **声称 == 实际**（承重） | 模块 `GUARD_SCOPE` ↔ 台账 `declaration` ↔ **本文件自己走一遍** `roots/glob/exclude_dirs` 的结果集；语料定义（根 / glob / 剪枝）由**本文件冻结** | 只改一边（代码或台账）⇒ 必红；把真守卫的 `roots` 收窄后加载 ⇒ 必红 |
| 3 | **语料闭包**：全仓语料文件 ∈ 射程 ∪ 已登记的未覆盖面 | 普查的根/剪枝取**本文件冻结值**（不取台账、不取被测守卫） | 代码与台账**一起**收窄 ⇒ 闭包报出仓库根那一批脚本 |
| 5 | **陈旧边界声明必须消失**（#5283 残余①）：同一族里「还有 N 处存量在别的脚本」这类**句面读数**必须现取 | 把该句写回文件 ⇒ 必红 |
| 4 | **未覆盖面台账只许缩短** + 条目**活着** | 每条须有 `face` / `reason` / `owner` / `issue`；条数 ≤ 本文件冻结上限；**已被覆盖**的条目 = 陈旧 ⇒ 红 | 加一条 face（或把已覆盖的面登记成未覆盖）⇒ 必红 |

判据 3 的「**冻结普查**」是关键：若普查的根也来自台账/守卫，则「两边一起收窄」永远查不出来
—— 那正是 #5284 得以存在的形态（射程声明与病灶面同时被写窄，`scripts/**` 之外无人看）。

## 台账 = `guard_scope_ledger.json`（数据文件，**diff 里看得见**）

- `guards` 逐条登记「引用该语料的模块」：`kind=scans`（真扫描，须给 `declaration` 与 `enumerator`）
  或 `kind=mentions`（只在**说明**里点名该语料，例如某个守卫声明「shell 面不在我射程内」）；
- 每条**必须**有 `issue` 与 `reason`；`kind=scans` 另有 `uncovered_faces_frozen`（现取条数）；
- **未登记即红 / 已登记而不再引用即红**（两个方向都判，避免「登记了就不管」与「删了还挂着」）。

## 有意不做的（照实登记，**不是**「已覆盖」）

- 语料识别靠「**字符串常量里出现 `<*>.sh`**」：glob 若是拼出来的（`"*" + ".sh"`）或从配置读的，
  本普查**看不见**（假绿方向，不会误伤）；同理**只**登记 `tests/unit_ci_workflows/**`、`.github/*.py`、
  `scripts/*.py` 三个 Python 判据面（**工作流 YAML 里的内联 shell 不在面内**）。
- 本文件**不**读任何守卫的 docstring —— 那正是被固化的对象（散文射程）。将来新增扫描语料的守卫，
  **必须**携带 `GUARD_SCOPE` 并入册；**没有机械锁**会拦住一个完全不声明射程的新守卫
  （它不会命中判据 1，因为判据 1 只认「引用了语料 glob 字面量」这一形态）。
"""
import ast
import fnmatch
import importlib.util
import json
import os
import re
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_CI_DIR = REPO_ROOT / "tests" / "unit_ci_workflows"
LEDGER_PATH = UNIT_CI_DIR / "guard_scope_ledger.json"
SELF_REL = "tests/unit_ci_workflows/test_guard_scope_declaration.py"
BASH32_GUARD_REL = "tests/unit_ci_workflows/test_scripts_bash32_var_brace.py"

#: 语料 + 普查定义（**本文件冻结**；台账与守卫必须逐字一致 —— 收窄射程或扩大剪枝都要先改这里）。
CORPUS = "*.sh"
CENSUS_ROOT = "."
CENSUS_EXCLUDE_DIRS = (
    ".git", "node_modules", ".venv", "venv", "site-packages", ".next", "dist", "build", "coverage",
)
#: 语料引用的**普查面**（Python 判据面；工作流 YAML 与业务测试面不在内，见 docstring 残余）。
CENSUS_MODULE_DIRS = ("tests/unit_ci_workflows", ".github", "scripts")
#: 未覆盖面台账的**现取**上限（只许缩短）：#5284 后全仓受控 `*.sh` 都在射程内 ⇒ 0 条。
UNCOVERED_FACE_CAP = 0


def _ledger() -> dict:
    """台账（缺文件 ⇒ fail-closed 抛错，**不是**静默跳过）。"""
    if not LEDGER_PATH.exists():
        raise AssertionError(
            f"射程台账不存在：{LEDGER_PATH} —— 本判据 fail-closed（缺台账 = 射程无人管，不是「无需登记」）"
        )
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def _frozen_declaration() -> dict:
    return {
        "roots": [CENSUS_ROOT],
        "glob": CORPUS,
        "exclude_dirs": list(CENSUS_EXCLUDE_DIRS),
        "uncovered_faces": [],
    }


def _string_constants(path: Path) -> list[str]:
    """模块里所有**字符串常量**（含 docstring / f-string 片段）—— 结构化取法，不 grep 散文行。"""
    with warnings.catch_warnings():
        # 解析**别的**模块的源码时，Python 会替它们报出源码里的告警（如某守卫把正则写在非 raw
        # 字符串里的无效转义序列）—— 那不是本判据的问题，不该污染 CI 日志。
        warnings.simplefilter("ignore")
        tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def corpus_referencing_modules(corpus: str = CORPUS, paths: list[Path] | None = None) -> dict:
    """→ `{相对路径: [命中的字符串常量, …]}`（只认**结构化常量**；`*.sh` 是语料、`x.sh` 不是）。"""
    rx = re.compile(r"\*" + re.escape(corpus.lstrip("*")))
    if paths is None:
        paths = [p for d in CENSUS_MODULE_DIRS for p in sorted((REPO_ROOT / d).glob("*.py"))]
    out: dict[str, list[str]] = {}
    for p in sorted(paths):
        try:
            rel = p.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = p.name
        hits = sorted({s for s in _string_constants(p) if rx.search(s)})
        if hits:
            out[rel] = hits
    return out


def walk_census(declaration: dict, root: Path | None = None) -> set[str]:
    """按**给定声明**走一遍语料（本文件自己的枚举器 —— 与被测守卫的实现相互独立）。

    用 `os.walk` 手动剪枝：剪枝必须发生在**下降之前**，否则耗时就取决于依赖树的形状。
    """
    root = root or REPO_ROOT
    exclude = set(declaration["exclude_dirs"])
    suffix = declaration["glob"].lstrip("*")
    out: set[str] = set()
    for r in declaration["roots"]:
        base = root / r if r != "." else root
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in exclude)
            for name in sorted(filenames):
                if name.endswith(suffix):
                    out.add((Path(dirpath) / name).resolve().relative_to(root.resolve()).as_posix())
    return out


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(f"_guard_scope_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def actual_scan(mod) -> set[str]:
    """被测守卫**实际**枚举出的路径集（射程的真身；声明点名了它的枚举函数）。"""
    decl = getattr(mod, "GUARD_SCOPE")
    fn = getattr(mod, decl["enumerator"])
    return {
        Path(p).resolve().relative_to(REPO_ROOT).as_posix()
        for p in fn()
    }


def _diff(want: set[str], got: set[str]) -> str:
    return (f"声称有而实际没扫 = {sorted(want - got)[:6]}；实际扫了而没声称 = {sorted(got - want)[:6]}"
            f"（声称 {len(want)} 个 / 实际 {len(got)} 个）")


def test_every_corpus_referencing_module_is_registered():
    """判据 1（**未登记即红**，两个方向都判）：引用语料字面量的模块 ⟺ 台账条目。

    红证：在 `tests/unit_ci_workflows/` 造一个引用语料却未入册的模块 ⇒ 必红（指名 + 给出的出口是
    「携带 `GUARD_SCOPE` 并入册」或「改写措辞使常量不再命中」（后者会连带被别的判据 red 掉，
    不会被当成修复））；反向：入册的模块不再引用语料 ⇒ 陈旧条目 ⇒ 必红。
    """
    ledger = _ledger()
    found = corpus_referencing_modules()
    assert found, "语料引用普查为空 ⇒ 本判据恒绿（fail-closed：要么语料被判错，要么普查面写错）"
    registered = set(ledger["guards"])
    unregistered = sorted(set(found) - registered)
    stale = sorted(registered - set(found))
    assert unregistered == [], (
        f"这些模块引用了语料 {CORPUS!r} 却没有入册 {LEDGER_PATH.name}：{unregistered}\n"
        f"  出口（真可行动）：① 该模块真扫描语料 ⇒ 加结构化常量 `GUARD_SCOPE` 并按 kind=scans 入册；"
        f"② 只在说明里点名 ⇒ 按 kind=mentions 入册并写清 reason/issue。"
    )
    assert stale == [], (
        f"这些台账条目已是陈旧登记（模块不再引用语料 {CORPUS!r}）：{stale}"
        " —— 删除条目（台账只许缩短）"
    )


def test_declared_range_equals_actually_scanned_path_set():
    """判据 2（**承重**）：`GUARD_SCOPE` == 台账 `declaration` == 实际枚举结果；语料定义不许被改窄/改宽。

    红证：① 只改代码里的 `roots`（或只改台账）⇒ 必红；② 把语料定义（根/glob/剪枝）改掉 ⇒ 必红
    （扩大剪枝 = 扩大豁免面，必须走本判据的显式改动）；③ 见 `test_real_guard_declaration_mutation_is_detected`。
    """
    ledger = _ledger()
    scans = {rel: e for rel, e in ledger["guards"].items() if e.get("kind") == "scans"}
    assert scans, "台账里没有 kind=scans 的守卫 ⇒ 本判据恒绿（fail-closed）"
    frozen = _frozen_declaration()
    bad: list[str] = []
    for rel, entry in sorted(scans.items()):
        decl = entry.get("declaration")
        if not isinstance(decl, dict):
            bad.append(f"{rel}: 台账缺 declaration（kind=scans 必须声明射程）")
            continue
        for key in ("roots", "glob", "exclude_dirs"):
            if decl.get(key) != frozen[key]:
                bad.append(
                    f"{rel}: 语料定义 {key!r} 与冻结值不一致（台账={decl.get(key)!r} / 冻结={frozen[key]!r}）"
                    " —— 收窄射程或扩大剪枝都是「射程/豁免面」的改动，必须先在判据里显式改"
                )
        if decl.get("uncovered_faces") != []:
            bad.append(f"{rel}: declaration.uncovered_faces 必须为空（未覆盖面另有上限约束，见判据 4）")
        mod = _load_module(REPO_ROOT / rel)
        code_decl = getattr(mod, "GUARD_SCOPE", None)
        if not isinstance(code_decl, dict):
            bad.append(f"{rel}: 守卫没有结构化射程常量 `GUARD_SCOPE`（射程仍是散文 ⇒ 本判据看不见它）")
            continue
        if code_decl != decl:
            bad.append(f"{rel}: 代码里的 GUARD_SCOPE 与台账 declaration 不一致：\n"
                       f"    代码 = {code_decl}\n    台账 = {decl}")
        want = walk_census(decl)
        got = actual_scan(mod)
        if want != got:
            bad.append(f"{rel}: **声称的射程 != 实际扫描集** —— {_diff(want, got)}")
    assert bad == [], "守卫射程与声称不符（#5284 的类级判据）：\n" + "\n".join(f"  · {b}" for b in bad)


def test_every_corpus_file_is_scanned_or_registered_as_uncovered():
    """判据 3（**语料闭包**）：全仓语料文件 ∈ 射程 ∪ 已登记的未覆盖面（未登记即红）。

    红证：把守卫的 `roots` 与台账 `declaration` **一起**收窄成 `["scripts"]` ⇒
    本判据报出 `check-ui-regression.sh` / `contract-check.sh` 等仓库根脚本（见
    `test_narrowed_declaration_is_caught_by_closure` 的同形态自证）。
    """
    ledger = _ledger()
    census = walk_census(_frozen_declaration())
    assert census, f"语料普查为空（根={CENSUS_ROOT!r} / glob={CORPUS!r}）⇒ 本判据恒绿（fail-closed）"
    covered: set[str] = set()
    faces: list[dict] = []
    for rel, entry in sorted(ledger["guards"].items()):
        if entry.get("kind") != "scans":
            continue
        covered |= actual_scan(_load_module(REPO_ROOT / rel))
        faces.extend(entry["declaration"]["uncovered_faces"])
    missing = sorted(
        f for f in census
        if f not in covered and not any(fnmatch.fnmatch(f, face["face"]) for face in faces)
    )
    assert missing == [], (
        f"这些语料文件既不在任何守卫的射程内、也没有登记为未覆盖面（现取 {len(missing)} 个，"
        f"全仓共 {len(census)} 个）：{missing}\n"
        "  出口（真可行动）：① 把它们纳入射程（改 `GUARD_SCOPE.roots`）；"
        "② 若确实不扫，逐条登记未覆盖面（face/reason/owner/issue）并在本判据里显式放宽上限。"
    )


def test_uncovered_face_ledger_only_shrinks_and_stays_live():
    """判据 4（**台账只许缩短** + 条目活着）：未覆盖面每条要有人看、且不得已是「已覆盖」。

    红证：① 往 `uncovered_faces` 加一条 ⇒ 超过 `UNCOVERED_FACE_CAP`（现取 0）⇒ 必红；
    ② 把**已被射程覆盖**的面登记成未覆盖 ⇒ 陈旧条目 ⇒ 必红（不许用登记吸收已解决的问题）。
    """
    ledger = _ledger()
    problems: list[str] = []
    for rel, entry in sorted(ledger["guards"].items()):
        if entry.get("kind") != "scans":
            continue
        faces = entry["declaration"]["uncovered_faces"]
        if len(faces) > UNCOVERED_FACE_CAP:
            problems.append(
                f"{rel}: 未覆盖面 {len(faces)} 条 > 现取上限 {UNCOVERED_FACE_CAP} 条"
                "（台账只许缩短；要扩豁免面必须显式改本判据的 UNCOVERED_FACE_CAP，diff 里看得见）"
            )
        if entry.get("uncovered_faces_frozen") != len(faces):
            problems.append(
                f"{rel}: uncovered_faces_frozen={entry.get('uncovered_faces_frozen')!r} "
                f"与实际条数 {len(faces)} 不一致（涨跌都要在同 PR 更新这个现取读数）"
            )
        covered = actual_scan(_load_module(REPO_ROOT / rel))
        for face in faces:
            for key in ("face", "reason", "owner", "issue"):
                if not face.get(key):
                    problems.append(f"{rel}: 未覆盖面条目缺 {key!r}（必须写清「谁看」）：{face}")
            if any(fnmatch.fnmatch(f, face.get("face", "")) for f in covered):
                problems.append(f"{rel}: 未覆盖面 {face.get('face')!r} 已被射程覆盖 ⇒ 陈旧条目，销账")
    assert problems == [], "未覆盖面台账不合规：\n" + "\n".join(f"  · {p}" for p in problems)


def test_corpus_census_detects_unregistered_module_on_mutated_tree(tmp_path):
    """判据 1 的**判别力自证**（造在临时目录，不碰真仓库）。

    红证：临时模块里写 `"*.sh"` ⇒ 普查必须抓到它；负例：只点名**具体脚本名**（不带 `*`）
    不得命中 —— 否则所有「调用某个 shell 脚本」的判据都会被拖进普查（假红方向）。
    """
    d = tmp_path / "unit_ci"
    d.mkdir()
    unregistered = d / "test_zz_unregistered.py"
    unregistered.write_text('GLOB = "*.sh"\n', encoding="utf-8")
    found = corpus_referencing_modules(paths=[unregistered])
    assert set(found) == {"test_zz_unregistered.py"}, f"普查没抓到未登记的语料引用：{found}"
    specific = d / "test_yy_specific_name.py"
    specific.write_text('SCRIPT = "scripts/sync-main.sh"\n# 说明里也提一句 scripts/sync-main.sh\n', encoding="utf-8")
    assert corpus_referencing_modules(paths=[specific]) == {}, (
        "只点名具体脚本名（无 `*`）被当成语料引用 ⇒ 普查会把无关判据全部拖入（假红）"
    )


def test_narrowed_declaration_is_caught_by_closure():
    """判据 2/3 的**判别力自证**：代码与台账**一起**收窄也逃不掉 —— 闭包会报出被排除的面。

    这正是 #5284 的形态本身（射程从「全仓」被写窄成 `scripts/**`，而病灶在仓库根）。
    """
    narrowed = {"roots": ["scripts"], "glob": CORPUS,
                "exclude_dirs": list(CENSUS_EXCLUDE_DIRS), "uncovered_faces": []}
    frozen = _frozen_declaration()
    assert narrowed != frozen, "变异未生效（自证失败 ⇒ 本判据的红证是空断言）"
    covered = walk_census(narrowed)
    census = walk_census(frozen)
    missing = sorted(census - covered)
    assert "scripts/sync-main.sh" in covered, "收窄后的射程应仍覆盖 scripts/**（否则自证前提错了）"
    for must_report in ("check-ui-regression.sh", "contract-check.sh", "verify-all.sh"):
        assert must_report in missing, (
            f"闭包判据没抓到「仓库根被排除」这一形态（{must_report} 不在缺口中）：{missing[:8]}"
        )


def test_real_guard_declaration_mutation_is_detected(tmp_path):
    """判据 2 对**真守卫源码**的单点变异红证（不是只对合成输入判）。

    变异：把 `test_scripts_bash32_var_brace.py` 的 `"roots": ["."]` 改成 `["scripts"]`
    （模拟「悄悄收窄射程」）⇒ 加载变异副本后必须同时满足：① 代码声明 != 台账声明；
    ② 实际扫描集 != 台账声称的集。缺任一条 ⇒ 判据 2 是空断言。
    """
    ledger = _ledger()
    entry = ledger["guards"][BASH32_GUARD_REL]
    src = (REPO_ROOT / BASH32_GUARD_REL).read_text(encoding="utf-8")
    needle = '"roots": ["."]'
    assert needle in src, f"定位射程声明失败（fail-closed）：找不到 {needle!r}"
    mutated = src.replace(needle, '"roots": ["scripts"]')
    assert mutated != src, "变异注入未生效（自证失败 ⇒ 本判据的红证是空断言）"
    p = tmp_path / "_mutated_bash32_guard.py"
    p.write_text(mutated, encoding="utf-8")
    mod = _load_module(p)
    mod.REPO_ROOT = REPO_ROOT  # 副本挪了位置：枚举器仍须指向真仓库
    code_decl = getattr(mod, "GUARD_SCOPE")
    assert code_decl != entry["declaration"], (
        "代码射程被收窄、台账却没察觉 ⇒ 判据 2 的第①半是空断言"
    )
    assert actual_scan(mod) != walk_census(entry["declaration"]), (
        "收窄后的实际扫描集竟与台账声称的一致 ⇒ 判据 2 的第②半无判别力"
    )


#: 同一族里**已被清掉的**边界声明（#5283 残余①）——「还有 N 处存量在别的脚本里」这类句面读数。
#: 存量清零后它必须消失：留着 = 声称与实际不符（本单固化的正是这一类）。
STALE_FAMILY_CLAIMS = ("另有两处同族存量", "两处同族存量在别的脚本")


def stale_family_claim_hits(modules_dir: Path = UNIT_CI_DIR) -> list[str]:
    """→ `["文件: 命中的句面", …]`。**跳过本文件**（判据自己会写下这些句面，不能喂自己 —— §17.3）。"""
    out: list[str] = []
    for p in sorted(modules_dir.glob("*.py")):
        try:
            rel = p.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = p.name  # 临时目录里的副本（判别力自证用）
        if rel == SELF_REL:
            continue
        txt = p.read_text(encoding="utf-8")
        out += [f"{p.name}: {c!r}" for c in STALE_FAMILY_CLAIMS if c in txt]
    return out


def test_stale_family_boundary_claims_are_gone():
    """判据 5（#5283 残余①）：陈旧边界声明不得留在任何判据文件里（**不许静默漏**）。

    红证：把「另有两处同族存量在别的脚本里」写回 `test_ui_smoke_worktree_deps.py` ⇒ 必红
    （见 `test_stale_claim_injection_reds` 的副本复跑）。
    """
    hits = stale_family_claim_hits()
    assert hits == [], (
        f"这些判据文件里还留着**已过期**的边界声明（存量已由 #5260 / #5284 清零）：{hits}\n"
        "  出口（真可行动）：改成现状读数 + 指向类级守卫 "
        f"({BASH32_GUARD_REL}) 与射程元守卫（{SELF_REL}）。"
    )


def test_stale_claim_injection_reds(tmp_path):
    """判据 5 的**判别力自证**：把过期句面写回副本 ⇒ 必红；真文件本身必须仍然合规。

    自证：`mutated != src`；且命中清单必须**指名**那个文件（不是笼统报错）。
    """
    victim = UNIT_CI_DIR / "test_ui_smoke_worktree_deps.py"
    src = victim.read_text(encoding="utf-8")
    claim = STALE_FAMILY_CLAIMS[0]
    anchor = "本判据只锁**本文件**自己。"
    assert anchor in src, f"定位现状读数失败（fail-closed）：找不到 {anchor!r}"
    mutated = src.replace(anchor, f"（{claim}在别的脚本里，未越界改动）" + anchor, 1)
    assert mutated != src, "变异注入未生效（自证失败 ⇒ 本判据的红证是空断言）"
    d = tmp_path / "unit_ci"
    d.mkdir()
    (d / victim.name).write_text(mutated, encoding="utf-8")
    hits = stale_family_claim_hits(d)
    assert any(victim.name in h for h in hits), f"写回过期句面后判据没指名它：{hits}"
    assert stale_family_claim_hits() == [], "真目录必须仍然合规（否则本红证分不清对象）"
