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

## 本文件锁五条（每条都带能单独变红的红证）

1. **红证 A**：把 **#5147 的真实坏输入**（`product.yml` 那条判据的两处未转义裸双引号，见
   `_REAL_5147_BAD_LINE`）放进**临时目录**（不污染真用例库）⇒ `render_cases.py` **非零退出**且
   **指名文件与位置**；换成 PR #5147 合入的转义写法 ⇒ 恢复绿。
   （改前形态：`render_cases.py` **退出 0** 并渲染成功 —— 本文件在改前必红。）
   ⚠️ **`case-truth-check` job 没有 PyYAML** ⇒ 同一场景**在无 PyYAML 配置下也必须红**
   （否则"渲染腿 fail-closed"在 CI 上只是名义上的，两层分歧原样保留）——
   单独一条 `test_render_leg_fails_closed_without_pyyaml_too` 钉住。
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
5. **两套后端判决一致**（同一个函数 ≠ 同一个判决）：同一组语料（真实事故形态 / 未闭合 flow /
   未闭合引号 / 转义双引号 / 中文与反引号 / 多行标量）在**有 PyYAML** 与**无 PyYAML** 两个子进程
   里跑 ⇒ **逐条判决一致**，且坏样本的报错都指名 `文件:行:列`。

## 边界（照实登记，未修）

· **后端②抓不到的形态**逐条登记在 `NOT_COVERED`，由
  `test_registered_gaps_are_still_gaps` 钉住 —— **登记有死亡条件**：谁补上了，那条断言当场变红
  （本仓 §17.3 ④ 的口径），逼他更新登记。
· 后端②覆盖不到的全部形态，由**本文件第 3 条**（真用例库在两条后端下都必须合法 + 生成物逐字节
  一致）与 CI 的 `tests/unit_ci_workflows/test_eval_cases_yaml_strictness.py`（PyYAML 环境对全量
  用例库用标准 YAML 复算）兜住。
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

#: **#5147 的真实坏输入**（原样收进夹具，不是构造样例）：`.github/cases/product.yml` 里那条
#: `inventory_manage` / `adjustment` 判据，PR #5147 之前有**两处未转义的裸双引号写在双引号标量内**。
#: 本常量 = 转义前的原文（下面 `_REAL_5147_FIXED_LINE` 给出 PR #5147 合入的转义版本，并**现取**
#: 真用例库核对它还在 —— 保证这份夹具钉的是**真实事故输入**而不是我的想象）。
_REAL_5147_FIXED_LINE = ('      - "判据 1·**AI 工具 schema 放宽**：`inventory_manage` 的 '
                         '`adjustment` 参数 `type == \\"number\\"`（改前 `\\"integer\\"`）；工具层对'
                         '该参数的整数判定不再把 `60.5` / `-2.7` 判成类型错误。注入红证：把 schema '
                         '改回 `integer` ⇒ 变红。"')
_REAL_5147_BAD_LINE = _REAL_5147_FIXED_LINE.replace('\\"', '"')

#: 完整夹具文件（含该坏行）。⚠️ 必须带 `adversarial` + 无 `skip_reason` 的冒烟/对抗两条用例：
#: 生成物自检要求这两个子集非空，否则**修好后**仍会因自检失败而 rc≠0（假红）。
BAD_CASE = ('schema: "1"\n'
            'domain: product\n'
            'cases:\n'
            '  - id: FX-001\n'
            '    title: 冒烟档\n'
            '    tier: smoke\n'
            '    domains: [product]\n'
            '    user_inputs:\n'
            '      - "随便"\n'
            '    expectations:\n'
            '      - tool: direct_reply\n'
            '  - id: FX-002\n'
            '    title: 对抗档\n'
            '    tier: adversarial\n'
            '    domains: [product]\n'
            '    user_inputs:\n'
            '      - "随便"\n'
            '    expectations:\n'
            '      - tool: direct_reply\n'
            '  - id: FX-5147\n'
            '    title: 真实事故形态\n'
            '    tier: normal\n'
            '    domains: [product]\n'
            '    user_inputs:\n'
            '      - "随便"\n'
            '    expectations:\n'
            '      - tool: direct_reply\n'
            '    data_checks:\n'
            + _REAL_5147_BAD_LINE + '\n')

#: 同一份文件的**已修复**写法（= main 上那条判据，PR #5147 的修法：把两处转义）⇒ 恢复绿。
FIXED_CASE = BAD_CASE.replace(_REAL_5147_BAD_LINE, _REAL_5147_FIXED_LINE)

#: **两套 loader 的一致性语料**（判决必须一致；真值 = 后端① `yaml.safe_load`）。
#: 覆盖父任务点名的五类：① 真实事故形态 ② 未闭合的 flow 集合/引号 ③ 合法但含转义双引号
#: ④ 含中文与反引号 ⑤ 多行标量（引号跨行 / 块标量 / flow 跨行）。
_CORPUS_HEAD = ('schema: "1"\ndomain: utils\ncases:\n  - id: FX-800\n    title: 语料\n'
                '    tier: smoke\n    domains: [utils]\n    user_inputs:\n      - "随便"\n'
                '    expectations:\n      - tool: direct_reply\n')
CORPUS: dict[str, dict] = {
    "real_5147_unescaped_quote": {"body": BAD_CASE, "bad": True},
    "unclosed_flow_sequence": {"body": _CORPUS_HEAD + "    data_checks:\n      - [a, b\n",
                               "bad": True},
    "unclosed_flow_mapping": {"body": _CORPUS_HEAD + "    subtitle: {a: 1\n", "bad": True},
    "unclosed_quote": {"body": _CORPUS_HEAD + '    subtitle: "没闭合\n', "bad": True},
    "escaped_quote_ok": {"body": _CORPUS_HEAD + '    subtitle: "转义 \\"引号\\" 混合"\n',
                         "bad": False},
    "chinese_backtick_ok": {"body": _CORPUS_HEAD + '    subtitle: "中文与反引号 `code` 并存"\n',
                            "bad": False},
    "multiline_block_scalar_ok": {
        "body": _CORPUS_HEAD + '    subtitle: |\n      第一行 "有引号"\n      第二行 - "像值位置"\n',
        "bad": False},
    "multiline_quoted_ok": {"body": _CORPUS_HEAD + '    subtitle: "第一行\n      第二行"\n',
                            "bad": False},
    "multiline_flow_ok": {"body": _CORPUS_HEAD + "    subtitle: [a,\n      b]\n", "bad": False},
}

#: **后端②已知抓不到的形态**（如实登记）。判据见 `test_registered_gaps_are_still_gaps` ——
#: 本表**有死亡条件**：谁把某条补上了，那条断言当场变红，逼他更新这张表（本仓 §17.3 ④ 的口径）。
NOT_COVERED: dict[str, str] = {
    "tab_indent": "cases:\n\t- id: FX-802\n    title: 制表符缩进\n",
}

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


# ─────────────────────────────────────────────────────────────────────────────
# 判据 5：两套后端判决一致（真实事故语料）+ 边界登记有死亡条件
# ─────────────────────────────────────────────────────────────────────────────
def _corpus_dir(tmp: Path) -> Path:
    d = tmp / "corpus"
    d.mkdir(parents=True, exist_ok=True)
    for name, spec in CORPUS.items():
        (d / f"{name}.yml").write_text(spec["body"], encoding="utf-8")
    for name, body in NOT_COVERED.items():
        (d / f"{name}.yml").write_text(body, encoding="utf-8")
    return d


def _verdicts(corpus: Path, env: dict | None) -> tuple[bool, dict[str, str | None]]:
    """在**指定环境**里对整份语料跑 `strict_error`（子进程：PyYAML 可用 / 不可用两条后端）。"""
    code = ("import sys, json, glob, os\n"
            f"sys.path.insert(0, r'{GH}')\n"
            "import cases_yaml\n"
            "print('AVAILABLE:%s' % cases_yaml.pyyaml_available())\n"
            f"files = sorted(glob.glob(os.path.join(r'{corpus}', '*.yml')))\n"
            "print(json.dumps({os.path.splitext(os.path.basename(f))[0]: cases_yaml.strict_error(f) "
            "for f in files}, ensure_ascii=False))\n")
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env=env, cwd=str(REPO_ROOT))
    assert p.returncode == 0, f"语料判定子进程失败：\n{p.stdout}\n{p.stderr}"
    lines = p.stdout.strip().split("\n")
    assert lines[0].startswith("AVAILABLE:"), p.stdout
    import json as _json
    return lines[0].endswith("True"), _json.loads(lines[-1])


def test_both_backends_agree_on_the_corpus(tmp_path):
    """**同一个函数 ≠ 同一个判决**：有 PyYAML / 无 PyYAML 两个子进程对同一组语料必须**逐条一致**。

    真值 = 后端①（`yaml.safe_load`）；语料覆盖父任务点名的五类（真实事故形态 / 未闭合 flow /
    未闭合引号 / 转义双引号 / 中文与反引号 / 多行标量）。「改前」形态：渲染腿根本没有严格判定
    （宽松 loader 一律放行）⇒ 本判据在改前必红（缺 `cases_yaml`）。
    """
    corpus = _corpus_dir(tmp_path)
    has1, v1 = _verdicts(corpus, dict(os.environ))
    has2, v2 = _verdicts(corpus, _no_pyyaml_env(tmp_path / "noyaml"))
    assert has1 is True and has2 is False, (
        f"两次没有跑在**不同**后端上（后端①可用={has1} / 后端②可用={has2}）⇒ 本判据会静默空跑")

    for name, spec in CORPUS.items():
        want = bool(spec["bad"])
        got1, got2 = v1[name] is not None, v2[name] is not None
        assert got1 is want, f"[{name}] 后端①（真值）判决={got1}，期望={want}（语料标注错了？）"
        assert got2 is want, f"[{name}] 后端②判决={got2}，与后端①（真值 {want}）**不一致**：{v2[name]}"
        if want:                      # 坏样本：两条后端都必须**指名文件与位置**
            for tag, msg in (("①", v1[name]), ("②", v2[name])):
                assert re.search(rf"{name}\.yml:\d+:\d+", msg or ""), (
                    f"[{name}] 后端{tag} 的报错没有指名 `文件:行:列`（#5151 判据 1）：{msg}")


def test_registered_gaps_are_still_gaps(tmp_path):
    """`NOT_COVERED` 是**有死亡条件的登记**：它现在还抓不到 ⇒ 绿；谁补上了 ⇒ 本判据**当场变红**。

    为什么要这条：不写它，"后端②的覆盖边界"就只是注释里的一句话 —— 下一个人无从知道
    「这些形态**现在**确实漏着」，也无从知道自己把它补上了（漏检缺口无人认领）。
    ⇒ 红了的修法是**更新 `NOT_COVERED` 与 `.github/cases_yaml.py` 模块头的那张表**，
    **不是**把本判据删掉。
    """
    corpus = _corpus_dir(tmp_path)
    has2, v2 = _verdicts(corpus, _no_pyyaml_env(tmp_path / "noyaml"))
    assert has2 is False, "没有跑到无 PyYAML 后端 ⇒ 本判据空跑"
    newly_covered = {k: v2[k] for k in NOT_COVERED if v2[k] is not None}
    assert not newly_covered, (
        f"这些形态**已经**被后端②抓到了（好消息）：{newly_covered} —— 请把它们从 `NOT_COVERED` "
        f"移到 `CORPUS`（并同步 `.github/cases_yaml.py` 模块头那张「抓不到」表），"
        f"再删掉本断言里对应的条目。")


def test_fixture_is_the_real_5147_input_not_a_lookalike(tmp_path):
    """红证素材必须是**真实事故输入**：夹具 = `.github/cases/product.yml` 那条判据转义前的原文。

    现取真用例库核对：PR #5147 合入的**转义版**那一行仍在（否则本夹具已与现场脱钩 ⇒ 红）。
    """
    fixed_line = _REAL_5147_FIXED_LINE
    assert '\\"' in fixed_line and '\\"' not in _REAL_5147_BAD_LINE, "夹具构造反了"
    text = (CASES / "product.yml").read_text(encoding="utf-8")
    assert fixed_line in text, (
        "真用例库里已找不到 PR #5147 那条判据的转义版原文 —— 本文件的坏输入夹具已与现场脱钩。\n"
        "处置：把 `_REAL_5147_FIXED_LINE` 更新成 `.github/cases/product.yml` 里那条判据的**现状**，"
        "并确认 `_REAL_5147_BAD_LINE` 仍是它「未转义」的形态（红证素材必须是真实事故输入）。")
