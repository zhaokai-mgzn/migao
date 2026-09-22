# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""渲染腿 fail-closed（issue #5151）：用例源文件必须过**与判据腿同一个**严格 loader。

## 病灶（#5063 收尾实测 / PR #5147，差一步造成破坏）

`.github/cases/*.yml` 的解析在两条腿上**宽严不一**：

| 腿 | 用什么解析 |
|---|---|
| 渲染腿 `.github/render_cases.py` | `yaml_light`（**宽松**：能吃下标准 YAML 拒绝的文件） |
| 判据腿 `scripts/drift_audit.py` | `yaml.safe_load`（**严格**：抛 `ParserError`） |

⇒ 一个写在双引号标量内、**未转义的裸双引号**：渲染腿**照旧渲染成功**、生成物新鲜度也绿
（坏文件**零信号**），而判据腿整条抛错 ⇒ `findings = 0` ⇒ 9 条 `component|*` 合法豁免被读成
「已归零」⇒ 报「**基线归零未删 9（阻塞）**」并建议 `--regen-baseline`（照做＝**凭一次解析错误
永久删掉真豁免**）。

## 本文件锁四条（每条都带能单独变红的红证）

1. **红证 A**：注入含未转义双引号的用例 yml（**临时目录**，不污染真用例库）⇒ `render_cases.py`
   **非零退出**且**指名文件与位置**；把那一处改成转义写法 ⇒ 恢复绿。
   （改前形态：`render_cases.py` **退出 0** 并渲染成功 —— 本文件在改前必红。）
2. **反向护栏**：「一律拒绝」的实现必红 —— 合法 YAML（**转义双引号 / 中文 / 反引号 / 单引号里的
   字面双引号 / 行内注释 / 双引号跨行 / 块标量**）必须**判定通过且渲染成功**，且**两条后端都
   不得误拒**。
3. **不回归**：真用例库（`.github/cases/*.yml` 全量）全部合法，且渲染结果与已提交的两个生成物
   **逐字节一致** —— 改动只该让坏输入失败，不该改好输入的结果。
4. **「同一个 loader」机械成立**（不是"两边各写一个看起来一样的"）：
   · 两条腿解析出的 loader 模块 = **同一个文件**（`__file__` 与 `strict_error` 的
     `co_filename` 都相同）；
   · 两条腿的源码里**没有**第二条严格解析路径（AST 判据：渲染腿不得 `import yaml`，
     判据腿不得自己调 `yaml.safe_load`）；
   · **单点注入**：把那个共享函数的判定改坏 ⇒ **两条腿同时红**（渲染腿 `CasesYamlError`、
     判据腿 `status=error` 不可判）。

## 边界（照实登记，未修）

· 零依赖后端（无 PyYAML 时的严格闸）**只拒确定的语法非法**（引用提前闭合等形态的**子集**）⇒
  它覆盖不到 PyYAML 能拒的全部形态。这条边界由**本文件第 3 条**（在 PyYAML 环境对全量用例库用
  标准 YAML 复算）与 CI 的 `tests/unit_ci_workflows/test_eval_cases_yaml_strictness.py` 兜住。
· `yaml_light` 对**块标量**（`|` / `>`）的取值保真度是**既有**限制（不是本单引入、也不在本单
  范围内）：它不报错，但会丢行。夹具因此把块标量放在**最后一条用例**上，只断言"**不被判为失败**
  + 渲染成功"（= 本单的判据 3），不断言取值保真。
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GH = REPO_ROOT / ".github"
RENDER = GH / "render_cases.py"
SHARED = GH / "cases_yaml.py"
DRIFT = REPO_ROOT / "scripts" / "drift_audit.py"
CASES = GH / "cases"
GEN_EVAL = REPO_ROOT / "tests" / "agent_eval" / "eval_cases.py"
GEN_MD = REPO_ROOT / "docs" / "testing" / "mibao-verification-cases.md"

#: **红证 A 的注入形态 = #5147 的真实形态**：`data_checks` 里一条双引号标量内写了未转义的 `"`。
#: ⚠️ 必须带一条 `adversarial` 用例：生成物自检要求冒烟/对抗两个子集非空，否则**修好后**仍会
#: 因自检失败而 rc≠0（那会让"恢复绿"的断言变成假红）。
BAD_CASE = '''schema: "1"
domain: product
cases:
  - id: FX-001
    title: fixture
    tier: smoke
    domains: [product]
    user_inputs:
      - "随便"
    expectations:
      - tool: direct_reply
    data_checks:
      - "类型必须是 "number" 才算通过"
  - id: FX-002
    title: 对抗档
    tier: adversarial
    domains: [product]
    user_inputs:
      - "随便"
    expectations:
      - tool: direct_reply
'''

#: 同一份文件的**合法**写法（把那一处转义）—— 证明"修好即恢复绿"。
FIXED_CASE = BAD_CASE.replace('"类型必须是 "number" 才算通过"',
                              '"类型必须是 \\"number\\" 才算通过"')

#: **反向护栏夹具**：合法 YAML 的各种"看起来危险"的写法。⚠️ 冒烟/对抗两条用例**不能**带
#: `skip_reason`（生成物自检要求这两个子集非空，`skip_reason` 会让它们被过滤掉）。
#: ⚠️ 用 `r"""…"""` 而不是 `r'''…'''`：夹具里有 YAML 的单引号转义（`''`），末尾会拼出 `'''`
#: ⇒ 会当场截断 Python 字面量（`''转义'' 引号` 这种写法就是为了避开它）。
LEGIT_CASE = r"""schema: "1"
domain: utils
cases:
  - id: FX-900
    title: "合法：转义双引号 \"引号\" + 中文 + 反引号 `code`"
    tier: smoke          # 行内注释也要能吃
    domains: [utils]
    user_inputs:
      - '单引号里的字面 "双引号"，以及 ''转义'' 引号'
      - "反引号 `cmd` 与中文，值里有逗号, 也要保留"
    expectations:
      - tool: direct_reply
  - id: FX-901
    title: "对抗档：双引号跨行（合法多行标量）"
    tier: adversarial
    domains: [utils]
    subtitle: "第一行
      第二行"
    user_inputs:
      - "随便"
    expectations:
      - tool: direct_reply
  - id: FX-902
    title: "块标量（合法 YAML；放在最后：yaml_light 的保真度是既有边界，见文件头）"
    tier: normal
    domains: [utils]
    user_inputs:
      - "随便"
    expectations:
      - tool: direct_reply
    data_checks:
      - |
        这里 " 有引号" 且 - "看起来像值位置"
      - >-
        折叠标量 "也行"
    skip_reason: "[backend-contract] fixture"
"""


# ─────────────────────────────────────────────────────────────────────────────
# 夹具基础设施
# ─────────────────────────────────────────────────────────────────────────────
def _by_path(name: str, path: Path):
    """按**路径**加载模块（与既有契约测试同款：不往 `sys.path` 塞常驻条目）。

    ⚠️ 必须登记进 `sys.modules`：`drift_audit.py` 里有 `@dataclass`，模块不在
    `sys.modules` 里可达时 dataclass 装饰当场 `AttributeError`（既有契约测试的同一坑）。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"加载不了 {path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _render(cases_dir: Path, out: Path, *, env: dict | None = None) -> subprocess.CompletedProcess:
    """跑**真的**渲染器（与 CI 同命令形态）。"""
    return subprocess.run(
        [sys.executable, str(RENDER), "--cases", str(cases_dir),
         "--out-eval", str(out / "eval_cases.py"), "--out-md", str(out / "casebook.md")],
        cwd=str(REPO_ROOT), capture_output=True, text=True, env=env)


def _no_pyyaml_env(tmp: Path) -> dict:
    """造一个 PyYAML **不可导入**的环境（= CI 的 `case-truth-check` job 的真实形态：该 job
    不 `pip install`，runner 镜像也没有系统 PyYAML —— 见 `.github/cases_yaml.py` 模块头）。"""
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "yaml.py").write_text("raise ImportError('PyYAML 不在 CI 依赖里')\n",
                                 encoding="utf-8")
    return dict(os.environ, PYTHONPATH=str(tmp))


def _case_dir(tmp: Path, **files: str) -> Path:
    d = tmp / "cases"
    d.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (d / f"{name}.yml").write_text(body, encoding="utf-8")
    return d


def _imports_of(path: Path) -> set[str]:
    """源码里**语法层面**的 import 顶层模块名（AST，不是 grep —— 注释/文案喂不绿它）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def _attr_calls(path: Path, base: str, attr: str) -> int:
    """源码里 `base.attr(...)` 形式的调用数（AST：只看**真的调用**，不看注释/字符串）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == attr and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == base:
            n += 1
    return n


# ─────────────────────────────────────────────────────────────────────────────
# 判据 1：红证 A —— 坏用例源文件 ⇒ 渲染腿非零退出且指名文件/位置
# ─────────────────────────────────────────────────────────────────────────────
def test_render_leg_fails_closed_on_unescaped_quote(tmp_path):
    """**红证 A**：注入 #5147 的真实形态 ⇒ `render_cases.py` **必须红**并指名是哪一处。

    改前形态（本判据的红证）：宽松 loader 吃下它 ⇒ **退出 0**、照旧渲染成功、生成物新鲜度也绿
    ⇒ 坏文件在渲染腿上**零信号**，直到判据腿炸成「基线归零未删 9」。
    """
    out = tmp_path / "out"
    out.mkdir()
    cases = _case_dir(tmp_path, product=BAD_CASE)
    p = _render(cases, out)
    assert p.returncode != 0, (
        f"坏用例源文件在渲染腿上**没有红**（rc={p.returncode}）—— 宽松 loader 又回来了？\n"
        f"{p.stdout}\n{p.stderr}")
    both = p.stdout + p.stderr
    assert "product.yml" in both, f"报错没有**指名文件**（#5151 判据 1）：\n{both}"
    assert re.search(r"product\.yml:\d+:\d+", both), (
        f"报错没有**指明位置**（`文件:行:列`）：\n{both}")
    assert not (out / "eval_cases.py").exists(), (
        "严格判定失败后仍写出了生成物 —— 半成品生成物会被误读成「已渲染成功」")
    # 反向：把那一处**转义**（= 合法 YAML）⇒ 恢复绿（证明红的是"那个字符"，不是"这个夹具"）
    _case_dir(tmp_path, product=FIXED_CASE)
    p2 = _render(cases, out)
    assert p2.returncode == 0, f"合法的转义写法被误判为失败：\n{p2.stdout}\n{p2.stderr}"


def test_render_leg_fails_closed_without_pyyaml_too(tmp_path):
    """**零依赖环境下同样 fail-closed**：渲染腿的 CI job（`case-truth-check`）**没有 PyYAML**
    ⇒ 若只在"装了 pyyaml 的机器"上红，本单的病灶在 CI 上原样存在（这正是本判据的意义）。"""
    out = tmp_path / "out"
    out.mkdir()
    cases = _case_dir(tmp_path, product=BAD_CASE)
    env = _no_pyyaml_env(tmp_path / "noyaml")
    p = _render(cases, out, env=env)
    assert p.returncode != 0, f"零依赖环境下坏用例源文件没有红：\n{p.stdout}\n{p.stderr}"
    assert "product.yml" in p.stdout + p.stderr
    _case_dir(tmp_path, product=FIXED_CASE)
    p2 = _render(cases, out, env=env)
    assert p2.returncode == 0, f"零依赖环境下合法文件被误判：\n{p2.stdout}\n{p2.stderr}"


# ─────────────────────────────────────────────────────────────────────────────
# 判据 3：反向护栏 —— 合法 YAML 不得被误判为失败（「一律拒绝」的实现在此必红）
# ─────────────────────────────────────────────────────────────────────────────
def test_legit_yaml_is_not_rejected_by_either_backend(tmp_path):
    """含**转义双引号 / 中文 / 反引号 / 单引号里的字面双引号 / 行内注释 / 跨行标量 / 块标量**
    的合法用例 yml ⇒ 两条后端都判定通过，且**渲染成功**。"""
    cases_yaml = _by_path("cases_yaml_legit", SHARED)
    cases = _case_dir(tmp_path, legit=LEGIT_CASE)
    src = cases / "legit.yml"

    # ① 严格判定（当前后端）+ 标准 YAML 复算：都没有话说
    assert cases_yaml.strict_error(src) is None, "合法 YAML 被严格判定拒了（反向护栏失守）"
    doc = yaml.safe_load(src.read_text(encoding="utf-8"))
    assert len(doc["cases"]) == 3, f"夹具本身不合法/被改坏：{doc}"

    # ② 渲染成功（当前后端）
    out = tmp_path / "out"
    out.mkdir()
    p = _render(cases, out)
    assert p.returncode == 0, f"合法用例源文件渲染失败：\n{p.stdout}\n{p.stderr}"
    assert "3 条" in p.stdout, p.stdout

    # ③ 零依赖后端（无 PyYAML）也不得误拒 —— 这是"修成一律拒绝"最可能踩的坑
    env = _no_pyyaml_env(tmp_path / "noyaml")
    gate2 = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s'); import cases_yaml;"
         "print('pyyaml_available:', cases_yaml.pyyaml_available());"
         "print('strict_error:', cases_yaml.strict_error(r'%s'))" % (GH, src)],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT))
    assert gate2.returncode == 0, gate2.stdout + gate2.stderr
    assert "pyyaml_available: False" in gate2.stdout, (
        f"夹具没生效（PyYAML 仍可导入 ⇒ ③ 没有真的测到零依赖后端）：\n{gate2.stdout}")
    assert "strict_error: None" in gate2.stdout, (
        f"零依赖后端把合法 YAML 判成失败（反向护栏失守）：\n{gate2.stdout}{gate2.stderr}")
    p3 = _render(cases, out, env=env)
    assert p3.returncode == 0, f"零依赖后端下合法文件渲染失败：\n{p3.stdout}\n{p3.stderr}"


# ─────────────────────────────────────────────────────────────────────────────
# 判据 4：不回归 —— 真用例库全量合法，且生成物逐字节一致
# ─────────────────────────────────────────────────────────────────────────────
def test_real_case_library_passes_and_artifacts_are_byte_identical(tmp_path):
    """改动只该让**坏输入**失败：真用例库全量合法 + 两个生成物**逐字节**不变。"""
    cases_yaml = _by_path("cases_yaml_real", SHARED)
    files = sorted(CASES.glob("*.yml"))
    assert len(files) > 20, f"用例库没扫全（{len(files)} 个文件）—— 本判据会静默空跑"
    bad = {f.name: cases_yaml.strict_error(f) for f in files}
    assert not any(bad.values()), f"真用例库里出现了严格判定不通过的文件：{bad}"

    out = tmp_path / "out"
    out.mkdir()
    p = _render(CASES, out)
    assert p.returncode == 0, f"真用例库渲染失败：\n{p.stdout}\n{p.stderr}"
    for produced, committed in ((out / "eval_cases.py", GEN_EVAL), (out / "casebook.md", GEN_MD)):
        assert produced.read_bytes() == committed.read_bytes(), (
            f"{committed.relative_to(REPO_ROOT)} 与重新渲染结果**不是逐字节一致** —— "
            f"本改动只该让坏输入失败，不该改好输入的结果（跑 render_cases.py 重渲染并提交）")


# ─────────────────────────────────────────────────────────────────────────────
# 判据「同一个 loader」机械成立
# ─────────────────────────────────────────────────────────────────────────────
def test_both_legs_resolve_the_same_shared_loader():
    """两条腿的严格判定来自**同一个文件里的同一个函数**（不是各自一份）。"""
    render_mod = _by_path("render_cases_for_share", RENDER)
    drift_mod = _by_path("drift_audit_for_share", DRIFT)
    from_render = render_mod._cases_yaml()
    from_drift = drift_mod._load_cases_yaml()
    assert Path(from_render.__file__).resolve() == SHARED.resolve(), from_render.__file__
    assert Path(from_drift.__file__).resolve() == SHARED.resolve(), from_drift.__file__
    assert (from_render.strict_error.__code__.co_filename
            == from_drift.strict_error.__code__.co_filename
            == str(SHARED.resolve())), (
        "两条腿调的不是同一份实现（co_filename 不同 ⇒ 又分叉了）")


def test_no_leg_reimplements_the_strict_parse():
    """AST 判据：**只许有一处**严格解析实现（注释/文案喂不绿它）。

    · 渲染腿**不得** `import yaml`：它的 CI job（`case-truth-check`）不 `pip install`，
      硬依赖 PyYAML = 每个 PR 常红（且红的原因与用例质量无关）。这条同时锁住"以后有人图省事
      把 `yaml.safe_load` 直接塞进渲染腿"。
    · 判据腿**不得**自己调 `yaml.safe_load` 读用例：那会再造出"宽严不一"的第二处实现。
    """
    assert "yaml" not in _imports_of(RENDER), (
        "渲染腿 import 了 yaml —— 它跑在**没有 pip install 的 CI job** 里（见 cases_yaml.py 模块头）")
    assert "yaml" not in _imports_of(DRIFT), (
        "判据腿自己 import 了 yaml —— 严格判定必须走共享 loader（`.github/cases_yaml.py`）")
    assert _attr_calls(DRIFT, "yaml", "safe_load") == 0, (
        "判据腿又出现了第二处 `yaml.safe_load`（宽严不一的病根）")
    assert _attr_calls(RENDER, "yaml", "safe_load") == 0


def test_injecting_a_failure_into_the_shared_loader_reds_both_legs(monkeypatch):
    """**单点注入**：把共享 loader 的判定改坏 ⇒ 渲染腿与判据腿**同时红**。

    这是"同一个 loader"的**行为级**证据（比读源码强）：两条腿的严格性都只经过
    `cases_yaml.strict_error()` 这一个函数 ⇒ 改它一处，两条腿都得变红。
    """
    render_mod = _by_path("render_cases_for_inject", RENDER)
    drift_mod = _by_path("drift_audit_for_inject", DRIFT)

    # 前提自断言（否则"红了"可能来自别的原因）：不动它时，两条腿都是绿的
    assert drift_mod.check_mutable_locators(
        drift_mod.Audit(REPO_ROOT, offline=True)).status == "ok"
    assert len(render_mod.load_case_dicts(str(CASES))) > 100

    # ① 渲染腿：注入 ⇒ CasesYamlError（fail-closed，不是静默吃下）
    shared = render_mod._cases_yaml()
    monkeypatch.setattr(shared, "strict_error", lambda path: "INJECTED: 判据被改坏了")
    with pytest.raises(shared.CasesYamlError) as ei:
        render_mod.load_case_dicts(str(CASES))
    assert "INJECTED" in str(ei.value)

    # ② 判据腿：同一个注入 ⇒ status=error（不可判），**不是**「发现数为 0」
    monkeypatch.setattr(drift_mod, "_CASES_YAML_MOD", None)
    monkeypatch.setattr(drift_mod._load_cases_yaml(), "strict_error",
                        lambda path: "INJECTED: 判据被改坏了")
    res = drift_mod.check_mutable_locators(drift_mod.Audit(REPO_ROOT, offline=True))
    assert res.status == "error", f"判据腿没有因同一个注入变红：{res.status}"
    assert "INJECTED" in res.error, res.error
