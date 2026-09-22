# case_ids: PR-083, PR-084, PR-085, MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""渲染腿**转义解码**：生成物取值必须逐值等于真值（issue #5179）。

## 病灶：生成物里 33 处取值与真值不同，**任何检查都不会红**

`yaml_light` 的双引号标量原先**不做转义解码**（`_parse_scalar` 里直接 `s[1:-1]`）⇒ 取值里的
反斜杠原样留下，与 `yaml.safe_load` 真值**静默分叉**。**"生成物新鲜度"抓不到它** ——
那条检查比的是「能否由当前源重渲染出**已提交的**产物」，**不是**「产物是否等于真值」
⇒ 一份**稳定地错**的产物永远绿（同一份错产物每次都能重渲染出来）。

**修前实测（可复算，口径见 `render_leg_compare.py`）**：真值 **428** 条 / 产物 **428** 条
（id 序列逐位相同）⇒ 逐值不同的 `(文件, 用例, 字段)` = **33 处**、不同的字符串 **45** 个、
产物侧多出的转义序列 **163** 个（`\\"` 148 + `\\\\` 9 + `\\/` 1 + `\\n` 5），**成因只有一个**。

> ⚠️ issue #5179 原文写「36 处」：那个读数来自 #5171 的一次性 heredoc（**未入库**）、
> 且当时用例数是 424（现 428）⇒ **口径不可复算**。本文件以可复算的三个读数为准，
> **不把 33 写成 36**（订正并列写在本文件与 PR body）。

## 本文件锁五条（每条都带能单独变红的红证）

1. **比较器自证抓到了数据**：两侧条数 > 0 且 id 序列逐位相同 ——
   「0 条」必须**抛错**，不是「没有差异」（#5179 的复核方两次都栽在这里）。
2. **逐值相等**：真值（PyYAML）与产物取值 `sites == 0`；且**转义序列零外溢**。
3. **PyYAML 当裁判**：转义形态语料逐条 `yaml_light.load == yaml.safe_load`
   （含 `\\"` `\\\\` `\\/` `\\n` `\\t` `\\r` `\\b` `\\f` `\\0` `\\xXX` `\\uXXXX` `\\UXXXXXXXX`
   与单引号 `''`）—— 这是"**新值才是对的**"的机械判据：裁判是 PyYAML，不是"改完更一致"。
4. **零 diff 自证（稳定点）**：同参数渲染**两次**逐字节相同，且与已提交的两个生成物逐字节相同。
5. **判别力自证**：把当前产物按**改前形态**重新转义（`\\` → `\\\\`、`"` → `\\"`）喂给比较器
   ⇒ 必须报出差异（否则第 2 条就是"不会红的空断言"）。

## 边界（照实登记，未修；死亡条件在 test_yaml_light_scalar_fidelity.py）

· **未定义的转义序列**（`k: "a\\db"`）：宽松腿**原样保留**，而 PyYAML 对它是**语法错误**
  ⇒ 由渲染腿的严格判定（`.github/cases_yaml.py` 的 `require_strict`）拦下；真库 0 处。
· **被引号包起来的 key**：键不过 `_parse_scalar` ⇒ 不解码；真库 0 处。
· 跨行 flow 集合 / 跨行裸标量：#5171 已登记，本单未动。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GH = REPO_ROOT / ".github"
CASES = GH / "cases"
RENDER = GH / "render_cases.py"
GEN_EVAL = REPO_ROOT / "tests" / "agent_eval" / "eval_cases.py"
GEN_MD = REPO_ROOT / "docs" / "testing" / "mibao-verification-cases.md"

for _p in (str(GH), str(Path(__file__).parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml_light  # noqa: E402
import render_leg_compare as C  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# 判据 1：比较器**自证抓到了数据**（0 条 = 比较器坏了，不是"没差异"）
# ══════════════════════════════════════════════════════════════════════════════
def test_comparator_actually_sees_data():
    """两侧条数必须 > 0、id 序列逐位相同 —— 否则 `assert_sane()` 抛错。

    为什么单列这条：#5179 的复核方两次独立测量都"量不出来"，成因是**真值侧解析出 0 条**，
    而 0 条与"完全一致"在读数上**长得一模一样**。这条断言把那个假绿形态钉死。
    """
    rep = C.compare(CASES, GEN_EVAL)
    rep.assert_sane()                                     # 任一侧 0 条 ⇒ 这里就红了
    assert rep.truth_count == rep.artifact_count, (
        f"两侧条数不同：真值 {rep.truth_count} / 产物 {rep.artifact_count}")
    assert rep.truth_count >= len(list(CASES.glob("*.yml"))), (
        "真值侧条数少于用例库文件数 ⇒ 比较器多半只读到了部分文件")


def test_comparator_reds_when_a_side_is_empty(tmp_path):
    """**比较器自己的红证**：产物侧换成一份没有 `EvalCase(...)` 的文件 ⇒ 必须抛错。

    没有这条，`assert_sane()` 就是"不会红的断言"。同一形态的另一半（真值侧 0 条）由
    把 `cases_dir` 指到空目录来喂 —— 两侧都得红，只红一侧等于只守了一半。
    """
    empty_artifact = tmp_path / "no_cases.py"
    empty_artifact.write_text("# 没有任何 EvalCase(...) 的产物\n", encoding="utf-8")
    rep = C.compare(CASES, empty_artifact)
    assert rep.artifact_count == 0, "前提：这份替身产物应当解析出 0 条"
    with pytest.raises(AssertionError) as ei:
        rep.assert_sane()
    assert "0 条" in str(ei.value) and "没有差异" in str(ei.value), (
        f"红了但不是因为「比较器坏了」：{ei.value}")

    (tmp_path / "empty_cases").mkdir()
    rep2 = C.compare(tmp_path / "empty_cases", GEN_EVAL)
    assert rep2.truth_count == 0, "前提：空目录应当解析出 0 条真值"
    with pytest.raises(AssertionError):
        rep2.assert_sane()


# ══════════════════════════════════════════════════════════════════════════════
# 判据 2：逐值相等（真值 = PyYAML 解析用例库；产物 = 生成物里的字面量）
# ══════════════════════════════════════════════════════════════════════════════
def test_artifact_values_are_value_identical_to_truth():
    """真用例库全量：产物取值与 `yaml.safe_load` 真值**逐 (文件, 用例, 字段) 相等**。

    **修前红证**：同一条判据在修前报 **33 处**（`sites`）/ **45** 个不同字符串 /
    **163** 个多出的转义序列 —— 逐处清单由 `C.format_sites(rep)` 现取。
    """
    rep = C.compare(CASES, GEN_EVAL)
    rep.assert_sane()
    assert rep.sites == [], (
        f"生成物取值与真值不等（{len(rep.sites)} 处）—— 渲染腿的取值保真度破了：\n"
        + C.format_sites(rep, limit=12))


def test_artifact_has_no_escape_overflow():
    """**本单的靶心**：产物侧不得比真值多出任何转义序列（`\\"` / `\\\\` / `\\/` / `\\n` …）。

    与上一条分开写：上一条是"全字段逐值相等"（任何保真度缺口都会红），这一条**只在
    「转义未解码」这一族**上红，诊断信息直接点名是哪个转义序列 —— 两者红的原因不同。
    """
    rep = C.compare(CASES, GEN_EVAL)
    rep.assert_sane()
    assert rep.escape_overflow == {}, (
        f"产物里多出转义序列 {rep.escape_overflow}（合计 {rep.total_escape_overflow} 个）"
        f"—— 双引号标量又没解码？\n" + C.format_sites(rep, limit=8))


# ══════════════════════════════════════════════════════════════════════════════
# 判据 3：**PyYAML 当裁判** —— 新值才是对的（不是"改完更一致"）
# ══════════════════════════════════════════════════════════════════════════════
#: 转义形态语料：每条都必须是**合法** YAML（PyYAML 是裁判，它拒绝的形态不算语料）。
ESCAPE_CORPUS = {
    "escaped_double_quote": ('k: "a\\"b"\n', 'a"b'),
    "escaped_backslash": ('k: "a\\\\b"\n', "a\\b"),
    "escaped_slash": ('k: "a\\/b"\n', "a/b"),
    "escaped_newline_escape": ('k: "a\\nb"\n', "a\nb"),
    "escaped_tab": ('k: "a\\tb"\n', "a\tb"),
    "escaped_cr": ('k: "a\\rb"\n', "a\rb"),
    "escaped_backspace": ('k: "a\\bb"\n', "a\x08b"),
    "escaped_formfeed": ('k: "a\\fb"\n', "a\x0cb"),
    "escaped_null": ('k: "a\\0b"\n', "a\x00b"),
    "escaped_hex": ('k: "\\x41\\x42"\n', "AB"),
    "escaped_unicode_4": ('k: "\\u4e2d\\u6587"\n', "中文"),
    "escaped_unicode_8": ('k: "\\U0001F600"\n', "\U0001F600"),
    "escaped_surrogate_pair": ('k: "\\ud83d\\ude00"\n', "\ud83d\ude00"),
    "escaped_special_whitespace": ('k: "\\N\\_\\L\\P"\n', "\x85\xa0\u2028\u2029"),
    "escaped_space": ('k: "a\\ b"\n', "a b"),
    "single_quote_doubled": ("k: 'it''s ok'\n", "it's ok"),
    # 真库真实形态（#5179 那 33 处里三种代表）：`\\d` 正则 / `__FORM__` JSON / 多行 `\n`
    "real_regex_backslash": ('k: "工单号匹配 ^AS-\\\\d{8}-\\\\d{4}$"\n', r"工单号匹配 ^AS-\d{8}-\d{4}$"),
    "real_form_json": ('k: "__FORM__|{\\"a\\":\\"b\\"}"\n', '__FORM__|{"a":"b"}'),
    "real_multiline_newline": ('k: "第一行\\n第二行"\n', "第一行\n第二行"),
    # 反向护栏：不含转义的引号标量不得被改写
    "plain_no_escape": ('k: "plain 中文"\n', "plain 中文"),
    "empty_value": ('k: ""\n', ""),
}


@pytest.mark.parametrize("name", sorted(ESCAPE_CORPUS))
def test_pyyaml_is_the_judge(name):
    """逐形态：`yaml_light.load() == yaml.safe_load()`，并**逐字**等于 PyYAML 解出的值。

    两侧都断言：前者是"与裁判一致"的机械判据；后者把期望值钉成 **PyYAML 的产出**
    （写死的期望值只是副本 ⇒ 第三重自证：`yaml.safe_load` 自己也要给出同一个值，
    否则是**期望值**写错了，而不是实现错了）。
    """
    body, expected = ESCAPE_CORPUS[name]
    truth = yaml.safe_load(body)["k"]
    assert truth == expected, (
        f"[{name}] 语料期望值与 PyYAML 不符（期望值写错了，不是实现错了）：{truth!r}")
    got = yaml_light.load(body)["k"]
    assert got == truth, f"[{name}] yaml_light={got!r} / PyYAML={truth!r}"


def test_boundary_undefined_escape_is_not_taken_over():
    """**边界（照实登记）**：未定义的转义（`\\d`）**原样保留** —— 且 PyYAML 拒绝它。

    为什么这样定：这类文件是**标准 YAML 的语法错误**，渲染腿的严格判定
    （`.github/cases_yaml.py` 的 `require_strict`）会拦下它。宽松腿的职责只是
    "不把坏输入变成另一种坏"，不在这里抛异常打断整份用例加载。
    本判据同时钉住**两侧的行为**：PyYAML 必须拒绝（否则"边界"名不副实）。
    """
    body = 'k: "a\\db"\n'
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(body)
    assert yaml_light.load(body)["k"] == "a\\db", "宽松腿改变了未定义转义的既有形态"


# ══════════════════════════════════════════════════════════════════════════════
# 判据 4：零 diff 自证（同参数再渲染 ⇒ 逐字节相同 = 稳定点）
# ══════════════════════════════════════════════════════════════════════════════
def _render(out_dir: Path) -> None:
    p = subprocess.run(
        [sys.executable, str(RENDER), "--cases", str(CASES),
         "--out-eval", str(out_dir / "eval_cases.py"), "--out-md", str(out_dir / "casebook.md")],
        cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert p.returncode == 0, f"真用例库渲染失败：\n{p.stdout}\n{p.stderr}"


def test_render_is_a_stable_fixpoint_and_matches_committed(tmp_path):
    """两个生成物：① 渲染两次**逐字节相同**；② 与已提交版本**逐字节相同**（= 零 diff）。

    ① 是"稳定点"（派生物是源的纯函数）；② 就是 `git diff --exit-code` 的等价断言 ——
    有了它，"重渲染后还需要 `git diff` 才知道生成物是否新鲜"这件事在单测里就可见了。
    """
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _render(a)
    _render(b)
    for produced, committed in ((a / "eval_cases.py", GEN_EVAL),
                                (a / "casebook.md", GEN_MD)):
        twin = b / produced.name
        assert produced.read_bytes() == twin.read_bytes(), (
            f"{produced.name} 两次渲染结果不同 —— 渲染腿不是纯函数（稳定点破了）")
        assert produced.read_bytes() == committed.read_bytes(), (
            f"{committed.relative_to(REPO_ROOT)} 与重渲染结果**不是逐字节一致** ⇒ "
            f"生成物不新鲜（改完用例库要跑 render_cases.py 并提交生成物）")


# ══════════════════════════════════════════════════════════════════════════════
# 判据 5：判别力自证 —— 拿**改前形态**喂新判据 ⇒ 必红
# ══════════════════════════════════════════════════════════════════════════════
def _reescape(value):
    """把取值按**改前渲染腿的形态**重新转义（先 `\\` → `\\\\`、后 `"` → `\\"`）。

    这正是改前 `yaml_light` 的产出形态：双引号标量原样保留反斜杠 ⇒ 真值里的 `"` 在产物里
    变成 `\\"`、真值里的 `\\` 变成 `\\\\`。用它合成一份"改前产物"喂判据（**不依赖 git 历史**）。

    ⚠️ 覆盖 `\\"` / `\\\\` 两族（33 处里的 32 处）；`\\/` 那 1 处需要**源码侧**信息
    （源写 `\\/` 而真值是 `/`），本自证造不出来 ⇒ 由 PR body 里的 `git show origin/main:` 逐处
    对照承担。**不把"没覆盖"伪装成"已覆盖"**。
    """
    if isinstance(value, str):
        return value.replace("\\", "\\\\").replace('"', '\\"')
    if isinstance(value, list):
        return [_reescape(v) for v in value]
    if isinstance(value, dict):
        return {k: _reescape(v) for k, v in value.items()}
    return value


def test_value_diff_guard_can_actually_go_red(tmp_path):
    """**判别力自证**：修完的产物现在是"零差异" ⇒ 判据 2 永远是绿的，读者无从知道
    它"到底是守住了，还是根本不会红"。这里喂**改前形态**（同一份产物重新转义）⇒ 必红。

    不碰用例库、不碰生成物：只在临时目录里造一份替身产物。
    """
    rep_ok = C.compare(CASES, GEN_EVAL)
    rep_ok.assert_sane()
    assert rep_ok.sites == [], "前提破了：当前产物已与真值不等 —— 先修它，再谈判别力"

    artifact, _ = C.artifact_cases(GEN_EVAL)
    lines = ["# 改前形态的替身产物（测试内合成，非交付物）", ""]
    for cid, case in artifact.items():
        lines.append(f"_CASE_{cid.replace('-', '_')} = EvalCase(")
        lines.append(f"    id={cid!r},")
        for name in C.VERBATIM_FIELDS:
            if name in case:
                lines.append(f"    {name}={_reescape(case[name])!r},")
        if case.get("expectations"):
            lines.append(f"    expectations={case['expectations']!r},")
        lines.append(")")
    tmp = tmp_path / "before_fix_artifact.py"
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")

    rep_bad = C.compare(CASES, tmp)
    rep_bad.assert_sane()
    assert rep_bad.sites, "**判别力自证失败**：喂改前形态却报「零差异」⇒ 判据 2 是空断言"
    assert rep_bad.total_escape_overflow > 0, (
        "判别力自证失败：改前形态下应当报出多出的转义序列，实际为 0")
    assert rep_bad.escape_overflow.get("\\\"", 0) > 0, (
        f"改前形态下 `\\\"` 一族应当有外溢：{rep_bad.escape_overflow}")
