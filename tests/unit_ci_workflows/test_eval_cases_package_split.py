# case_ids: MC-012
# （沿用 `tests/unit_ci_workflows/**` 的既有惯例：仓库结构类 L0 不变式统一挂 MC-012 ——
#   本判据与本目录 `test_loc_ratchet.py` 同族：守的是「仓库这个**台账**与源码实际状态是否一致」，
#   不新造用例族、不改任何既有门禁的通过条件。）
r"""生成物**按域分包**（issue #8188）：域 ⇄ 模块双向相等 / 逐值相等 / **收益判据**。

## 病（不是一个缺陷，是一个结构性成本）

`tests/agent_eval/eval_cases.py` 是渲染器产出的**生成物**，改前 **18344 行**、全仓 churn 第一。
它是**单文件** ⇒ 任何一条用例的 `data_checks` 改一个字，整份 18000 行文件都进 diff：
评审噪声（真实改动被淹没）+ 合并冲突高发（两个 PR 同时改用例 ⇒ 整文件 modify/modify）。
issue #8188 的处置 = 拆成**按域分包**的目录：

```
tests/agent_eval/eval_cases/
  __init__.py      # 按固定顺序汇总各域 CASES ⇒ ALL_CASES（+ 再导出 schema / 查询函数）
  _schema.py       # EvalCase / Skill / Difficulty（**唯一**一份定义）
  order.py         # 由 .github/cases/order.yml 渲染（26 个域文件 ⇒ 26 个域模块）
  ...
```

## 本文件锁什么（每条都带**能单独变红**的红证；红证一律建在 `tmp_path`，不落进本仓）

| # | 判据 | 变红的形态 |
|---|---|---|
| 1 | **域 ⇄ 模块双向相等** | `.github/cases/*.yml` 的域集合 == `eval_cases/` 的模块集合；**缺模块** / **未登记模块**（手塞一个 `.py`）⇒ 红；非域模块只有固定清单 `__init__.py` + `_schema.py` |
| 2 | **逐值相等** | 模块里的 `EvalCase(...)` 字面量与 yml 真值逐 `(文件, id, 字段)` 相等 —— **复用** `render_leg_compare.py`（唯一比较器，本文件**不写第二份**）；且比较器必须真的看到**每个模块**的用例（防「只解析 `__init__.py` 就宣称相等」） |
| 3 | **收益判据（本单的核心）** | 临时副本里**只改 `order.yml` 的一条 `data_check`** ⇒ 重渲染 ⇒ **只有 `order.py` 变化**，其余模块逐字节不变（拆分的收益就是这条） |
| 4 | **包顶层导入面不变** | `from eval_cases import ALL_CASES, EvalCase, Skill, Difficulty`（`tests/agent_eval/local_runner.py` 第 29 行的**逐字**导入）⇒ 条数 / ID 序列与 yml 真值**逐位相同** |
| 5 | **模块被删 ⇒ `ALL_CASES` 少条 ⇒ 红** | 注入：拷包 → 删 `order.py` **并**顺手删掉 `__init__.py` 的对应 import（「为了让 import 过」的坏修法）⇒ 包能导入、但条数**少 72** ⇒ 判据 1/4 都红 |
| 6 | **稳定点** | 同参数再渲染一次 ⇒ 与提交版**逐模块逐字节相同**（零 diff）；旧单文件 `eval_cases.py` **必须已不存在** |

## 边界（照实登记，不是「已全覆盖」）

- **判据 2 比的是「取值」**，不比 `skill` / `difficulty` 两个枚举（渲染派生字段；比它们等于比
  `SKILL_MAP`，那是 `test_render_cases_domain_map.py` 的面）；
- **目录里只认 `*.py`**：非 `.py` 的手塞文件不在本判据面内（生成物形态本来就是 `.py` 模块；
  真正会「让人以为被渲染过」的只有 `.py`）。`.py` 之外的手塞由人评审承担；
- **不判「模块切分粒度是否合理」**：域 ⇄ 模块是**机械映射**（一域一模块），拆不拆某个域是人的决定；
- **收益判据只证「只改一个域只动一个模块」**：它不证「diff 行数更少」（同一域的改动行数不变）。
"""
from __future__ import annotations

import importlib
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GH = REPO_ROOT / ".github"
CASES = GH / "cases"
RENDER = GH / "render_cases.py"
EVAL_DIR = REPO_ROOT / "tests" / "agent_eval"
PKG = EVAL_DIR / "eval_cases"

for _p in (str(GH), str(Path(__file__).parent), str(EVAL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import render_cases  # noqa: E402
import render_leg_compare as C  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# 真值 / 现取的取法（**唯一实现**：渲染器的 `module_name` + 固定清单都由它给）
# ══════════════════════════════════════════════════════════════════════════════


def _domains(cases_dir: Path = CASES) -> list[str]:
    """用例库的域集合 = `*.yml` 的文件名（不含后缀）；**现取**，不写死清单。"""
    return sorted(p.stem for p in Path(cases_dir).glob("*.yml"))


def _expected_modules(cases_dir: Path = CASES) -> list[str]:
    """域 → 期望的模块文件名（**调渲染器的 `module_name`**，不在这里复制映射）。"""
    return sorted(render_cases.module_name(d) for d in _domains(cases_dir))


def _module_files(pkg_dir: Path = PKG) -> list[str]:
    """包目录里的模块文件（`*.py`，不递归）—— 现取。"""
    return sorted(p.name for p in Path(pkg_dir).glob("*.py"))


def module_set_problems(cases_dir: Path = CASES, pkg_dir: Path = PKG) -> list[str]:
    """**纯函数**：域 ⇄ 模块双向相等 + 非域模块固定清单。空列表 = 绿。

    覆盖三种坏形态：**缺模块**（域有、包没有）/ **未登记模块**（包里有、既不是域也不是固定清单
    = 手塞）/ **包文件缺失**（`__init__.py` / `_schema.py` 不见了）。
    """
    expected = set(_expected_modules(cases_dir))
    actual = set(_module_files(pkg_dir))
    allowed_non_domain = set(render_cases.NON_DOMAIN_MODULES)
    problems: list[str] = []
    missing = sorted(expected - actual)
    if missing:
        problems.append(f"缺模块（域有、包没有）：{missing} ⇒ 重渲染并提交生成物")
    unregistered = sorted(actual - expected - allowed_non_domain)
    if unregistered:
        problems.append(
            f"未登记模块（包里有、既不是域模块也不是固定清单 {sorted(allowed_non_domain)}）："
            f"{unregistered} ⇒ 生成物目录**不许手塞**：删掉它（重渲染不会覆盖它）")
    missing_pkg = sorted(allowed_non_domain - actual)
    if missing_pkg:
        problems.append(f"包文件缺失：{missing_pkg} ⇒ 重渲染并提交生成物")
    return problems


def _render(cases_dir: Path, out_dir: Path, out_md: Path) -> None:
    """真调渲染器（`--out-eval` 的值是**目录**，issue #8188）。"""
    proc = subprocess.run(
        [sys.executable, str(RENDER), "--cases", str(cases_dir),
         "--out-eval", str(out_dir), "--out-md", str(out_md)],
        cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, f"渲染失败：\n{proc.stdout}\n{proc.stderr}"


def _pkg_bytes(pkg_dir: Path) -> dict[str, bytes]:
    """目录里的模块文件 → `{文件名: 字节}`（逐模块逐字节比较用）。"""
    return {p.name: p.read_bytes() for p in sorted(Path(pkg_dir).glob("*.py"))}


def _import_pkg(pkg_dir: Path, name: str):
    """把某个 `eval_cases/` **包目录**导入成模块（相对 import 需要 `submodule_search_locations`）。

    ⚠️ 不落 `__pycache__`（生成物目录 / 临时副本都不该被字节码弄脏）。
    """
    spec = importlib.util.spec_from_file_location(
        name, str(Path(pkg_dir) / "__init__.py"),
        submodule_search_locations=[str(pkg_dir)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = prev
        sys.modules.pop(spec.name, None)
    return module


def _copy_pkg(dest_root: Path) -> Path:
    """把提交版包目录拷进临时目录（注入式红证的语料）。"""
    dest = dest_root / "eval_cases"
    shutil.copytree(PKG, dest, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def _truth_cases() -> list[dict]:
    """yml 真值（用例 dict 列表，**顺序 = `sorted(os.listdir)`**；`load_case_dicts` 是唯一 loader）。"""
    return render_cases.load_case_dicts(str(CASES))


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1：域 ⇄ 模块双向相等（含「未登记模块 ⇒ 红」「缺模块 ⇒ 红」）
# ══════════════════════════════════════════════════════════════════════════════


class TestDomainModuleBijection:
    def test_live_domain_set_equals_module_set(self):
        """真语料：域集合 == 模块集合；非域模块只有固定清单（**多一个 / 少一个都红**）。"""
        problems = module_set_problems(CASES, PKG)
        assert problems == [], "\n".join(problems)
        # 扫描面非空自证：0 个域 / 0 个模块时上面的「相等」是恒真（假绿）
        domains, modules = _domains(), _module_files()
        assert len(domains) >= 20, f"用例库只解析出 {len(domains)} 个域 —— 判据会静默空跑"
        assert len(modules) == len(domains) + len(render_cases.NON_DOMAIN_MODULES), (
            f"模块数 {len(modules)} != 域数 {len(domains)} + 固定清单 "
            f"{len(render_cases.NON_DOMAIN_MODULES)}")

    def test_unregistered_module_turns_it_red(self, tmp_path):
        """**红证①（防手塞）**：往包里塞一个未登记 `.py` ⇒ 判据必须红且**点名**它。"""
        pkg = _copy_pkg(tmp_path)
        (pkg / "hand_stuffed.py").write_text("X = 1\n", encoding="utf-8")
        problems = module_set_problems(CASES, pkg)
        text = "\n".join(problems)
        assert problems, "手塞了一个未登记模块却没红 ⇒ 判据 1 是空断言"
        assert "未登记模块" in text and "hand_stuffed.py" in text, text

    def test_missing_module_turns_it_red(self, tmp_path):
        """**红证②**：删掉一个域模块（域还在）⇒ 判据必须红且点名它。"""
        pkg = _copy_pkg(tmp_path)
        victim = pkg / "order.py"
        assert victim.is_file()
        victim.unlink()
        problems = module_set_problems(CASES, pkg)
        text = "\n".join(problems)
        assert problems and "缺模块" in text and "order.py" in text, text

    def test_missing_package_file_turns_it_red(self, tmp_path):
        """**红证③**：`_schema.py` 不见了（schema 被并回某个域模块）⇒ 判据必须红。"""
        pkg = _copy_pkg(tmp_path)
        (pkg / "_schema.py").unlink()
        text = "\n".join(module_set_problems(CASES, pkg))
        assert "包文件缺失" in text and "_schema.py" in text, text

    def test_old_single_file_must_be_gone(self):
        """旧形态（单文件 `eval_cases.py`）不许与包**并存** —— 并存 = 两份生成物各自漂移。"""
        legacy = EVAL_DIR / "eval_cases.py"
        assert not legacy.exists(), (
            f"{legacy.relative_to(REPO_ROOT)} 仍存在 ⇒ 生成物有两种形态（读取方会各自读到不同的一份）；"
            "删掉它（生成物只允许 `eval_cases/` 包目录）")


# ══════════════════════════════════════════════════════════════════════════════
# 判据 2：逐值相等（**复用** render_leg_compare，不写第二份比较器）
# ══════════════════════════════════════════════════════════════════════════════


class TestValueIdentity:
    def test_every_module_value_equals_truth(self):
        """真用例库全量：产物取值与 `yaml.safe_load` 真值**逐 (文件, 用例, 字段) 相等**。"""
        rep = C.compare(CASES, PKG)
        rep.assert_sane()                      # 任一侧 0 条 ⇒ 这里就红了（0 条 ≠ 没有差异）
        assert rep.sites == [], (
            f"生成物取值与真值不等（{len(rep.sites)} 处）—— 渲染腿的取值保真度破了：\n"
            + C.format_sites(rep, limit=12))

    def test_comparator_sees_every_module(self):
        """**防「只解析 `__init__.py` 就宣称相等」**：比较器必须从**每个**模块里取到用例。

        判据 = ① 产物侧条数 == 真值条数（0 条由 `assert_sane` 拦）；② 包目录里**每个**含
        `EvalCase(` 的模块都贡献了至少一条（= 逐模块解析真的发生了，不是只读了汇总文件）。
        """
        artifact, _non_literal = C.artifact_cases(PKG)
        truth = C.truth_cases(CASES)
        assert len(artifact) == len(truth) > 0, (
            f"产物用例数 {len(artifact)} != 真值 {len(truth)} —— 比较器没把每个模块都读到")
        per_module = {
            p.name: len(C.artifact_cases(p)[0]) for p in sorted(PKG.glob("*.py"))
        }
        empty = [name for name, n in per_module.items()
                 if n == 0 and name not in render_cases.NON_DOMAIN_MODULES]
        assert empty == [], f"这些域模块里一条 EvalCase 都没解析到（域被架空？）：{empty}"
        assert sum(per_module.values()) == len(artifact), (
            f"逐模块条数之和 {sum(per_module.values())} != 合并后 {len(artifact)} ⇒ 有模块被覆盖")


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3：**收益判据（本单的核心）** —— 改一个域只动一个模块
# ══════════════════════════════════════════════════════════════════════════════


class TestBenefitCriterionOnlyTheChangedModule:
    def test_editing_one_order_data_check_changes_only_order_py(self, tmp_path):
        """临时副本里只改 `order.yml` 的**一条 `data_check`** ⇒ 重渲染 ⇒ 只有 `order.py` 变。

        这是拆分的**全部收益**（issue #8188）：单文件形态下这条改动会让整份 18000 行文件进 diff；
        分包后只有 `order.py` 进 diff ⇒ 另一个 PR 改 `product.yml` 时不会冲突。
        """
        cases_copy = tmp_path / "cases"
        shutil.copytree(CASES, cases_copy)
        before = tmp_path / "before"
        _render(cases_copy, before, tmp_path / "before.md")

        target = cases_copy / "order.yml"
        text = target.read_text(encoding="utf-8")
        anchor = "\n    data_checks:\n"
        assert anchor in text, "夹具锚点不存在（order.yml 的 data_checks 缩进变了？）"
        mutated = text.replace(
            anchor,
            anchor + '      - "只改这一条 data_check（issue #8188 收益判据的注入值）"\n', 1)
        assert mutated != text, "注入没生效（红证会是空断言）"
        target.write_text(mutated, encoding="utf-8")

        after = tmp_path / "after"
        _render(cases_copy, after, tmp_path / "after.md")

        b, a = _pkg_bytes(before), _pkg_bytes(after)
        assert set(b) == set(a), f"模块集合变了（不该）：{sorted(set(b) ^ set(a))}"
        changed = sorted(name for name in b if b[name] != a[name])
        assert changed == ["order.py"], (
            f"只改了 order.yml 的一条 data_check，却让这些模块变化：{changed} —— "
            "分包没起到作用（收益判据的核心）")
        # 反向自证：`order.py` 真的变了（否则「只有它变」可能是「谁都没变」）
        assert "只改这一条 data_check" in (after / "order.py").read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# 判据 4/5：包顶层导入面不变 + 模块被删 ⇒ ALL_CASES 少条
# ══════════════════════════════════════════════════════════════════════════════


class TestImportSurfaceAndDeletion:
    def test_import_surface_is_unchanged(self):
        """`local_runner.py` 的逐字导入面可用，且 `ALL_CASES` 与 yml 真值**逐位相同**。"""
        module = importlib.import_module("eval_cases")     # = `from eval_cases import ...` 的同一份
        assert module.EvalCase and module.Skill and module.Difficulty, (
            "包顶层必须能导入 EvalCase / Skill / Difficulty（local_runner.py 第 29 行）")
        truth = [c.get("id", "") for c in _truth_cases()]
        got = [c.id for c in module.ALL_CASES]
        assert got == truth, (
            f"ALL_CASES 与 yml 真值不是逐位相同：条数 {len(got)} vs {len(truth)}；"
            f"首个不同 {next(((i, x, y) for i, (x, y) in enumerate(zip(got, truth)) if x != y), None)}")
        assert len(got) > 0

    def test_deleting_a_module_drops_cases_and_turns_it_red(self, tmp_path):
        """**红证（本单最危险的坏修法）**：删掉一个模块**并**删掉 `__init__.py` 的对应 import
        （让它还能 import 成功）⇒ 包**能导入**，但 `ALL_CASES` **少 72 条** ⇒ 判据 1/4 必红。

        这条红证的价值：如果只判「包能不能导入」，删模块后一切照绿（少跑的用例无人发现）——
        正是本仓反复踩的「少跑长得像通过」。
        """
        pkg = _copy_pkg(tmp_path)
        domain_cases = [c for c in _truth_cases() if c.get("_domain") == "order"]
        assert len(domain_cases) > 0, "前提：order 域真值非空"
        (pkg / "order.py").unlink()
        init = (pkg / "__init__.py").read_text(encoding="utf-8")
        stripped = "\n".join(
            ln for ln in init.split("\n")
            if "from .order import CASES as _order" not in ln and "*_order," not in ln)
        assert stripped != init, "注入没生效（`__init__.py` 里没有 order 的 import/汇总行）"
        (pkg / "__init__.py").write_text(stripped, encoding="utf-8")

        module = _import_pkg(pkg, "_split_guard_missing_order")
        truth = _truth_cases()
        assert len(module.ALL_CASES) == len(truth) - len(domain_cases), (
            f"删掉 order 后 ALL_CASES 应少 {len(domain_cases)} 条（{len(truth)} → "
            f"{len(truth) - len(domain_cases)}），实得 {len(module.ALL_CASES)}")
        # 判据 1（域 ⇄ 模块）与判据 4（条数/序列）都必须能红
        assert module_set_problems(CASES, pkg) != [], "模块被删了，域 ⇄ 模块判据却没红"
        assert len(module.ALL_CASES) != len(truth), "条数没变 ⇒ 判据 4 抓不到这种删法"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 6：稳定点（同参数再渲染 ⇒ 零 diff；并与提交版逐模块逐字节相同）
# ══════════════════════════════════════════════════════════════════════════════


class TestStableFixpoint:
    def test_rerender_is_a_byte_identical_fixpoint(self, tmp_path):
        """渲染两次逐模块逐字节相同，且都与**已提交**的包相同（= `git diff --exit-code` 的等价断言）。"""
        a, b = tmp_path / "a", tmp_path / "b"
        _render(CASES, a, tmp_path / "a.md")
        _render(CASES, b, tmp_path / "b.md")
        assert _pkg_bytes(a) == _pkg_bytes(b), "两次渲染的包不同 —— 渲染腿不是纯函数（稳定点破了）"
        committed = _pkg_bytes(PKG)
        assert _pkg_bytes(a) == committed, (
            "eval_cases/ 与重渲染结果**不是逐模块逐字节一致** ⇒ 生成物不新鲜"
            "（改完用例库要跑 render_cases.py 并提交生成物）")
        assert set(_pkg_bytes(a)) == set(committed), (
            f"模块集合不同：{sorted(set(_pkg_bytes(a)) ^ set(committed))}")
