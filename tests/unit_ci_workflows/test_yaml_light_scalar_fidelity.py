# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""`yaml_light` 对**多行标量**的取值保真度（issue #5171）。

## 病灶：`data_checks` 会**静默丢条**，而没有任何检查会红

`yaml_light` 是**面向行**的状态机（`load()` 先 `text.split('\\n')` 再逐行喂）。
块标量（`|` / `>`）与跨行标量让这个前提失效：

| 写法 | 改前 `yaml_light` 的取值 | 连带后果 |
|---|---|---|
| `data_checks:` 下的 `- \\|`（块标量做**序列项**） | 值 = **字面字符串** `'\\|'` | 内容行缩进更大 ⇒ `parse_sequence()` 当场 `break` ⇒ **该条目之后的兄弟条目整段消失** |
| `subtitle: \\|`（块标量做**映射值**） | 值 = `'\\|'` | 内容行被当独立行跳过（值变，不丢兄弟） |
| `subtitle: "第一行`（引号**跨行**） | 值 = `'"第一行'` | 续行与后续兄弟条目一起消失 |

**红证（改前实测，本机 PyYAML 6.0.3）**：一份含块标量的用例源，`data_checks`
在 `yaml.safe_load` 下是 **3 条**，在 `yaml_light` 下是 **1 条** ——
`['这里 " 有引号" 且 - "看起来像值位置"\\n', '折叠标量 "也行"', '第三条普通检查']`
变成了 `['|']`。而 `render_cases.py` **照旧退出 0**、生成物新鲜度**照旧绿** = **零信号**
（`migao-acceptance` 的「绿了但没跑」家族：真值源静默缩水，下游全部跟着失真）。

⇒ 本单修 `.github/yaml_light.py`：`_logical_rows()` 先把块标量 / 跨行引号标量整段读成
**一个逻辑行**，取值按 YAML 8.1.3 的折叠 / chomping 规则算。

## 为什么修解析器（甲）而不是"渲染腿改走严格 loader"（乙）

`case-truth-check` job（`pr-check.yml` 的「Verify generated artifacts fresh」那一步）
**只 `actions/checkout`，没有 `pip install`** ⇒ 那个环境**没有 PyYAML**
（见 `.github/cases_yaml.py` 模块头）。选乙的后果可判定：同一个生成物在"装了 PyYAML 的
本机"与"没装的 CI"两侧取值不同 ⇒ **生成物新鲜度校验在每个 PR 上常红**
（与用例质量无关，比缺口本身更糟）。故只能修**零依赖**那条腿。

## 本文件锁四条（每条都带能单独变红的红证）

1. **不丢条**：块标量 / 跨行标量做序列项时，**兄弟条目一条不少**、取值逐字正确。
   （改前必红：3 条 ⇒ 1 条。）
2. **与 PyYAML 逐值一致**：`CORPUS` 里每种形态（字面/折叠 × clip/strip/keep ×
   空行/更缩进/显式缩进指示数字 × 双引号/单引号 × 序列项/映射值）都**深比较相等**。
   真值 = `yaml.safe_load`（本 job 装了 pyyaml）。
3. **不回归**：真用例库（`.github/cases/*.yml` 全量）里 ① 用例**条数与 id 序列**不变、
   ② 每个列表字段的**长度**不变、③ 与 PyYAML **逐值相等**（任何一处取值差异即红 ——
   #5179 把 `escaped_*` 一族修好之后，原先那条"差异可由 `STILL_UNFAITHFUL` 解释就放行"的
   容忍口径**整条退场** ⇒ 本判据是**收紧**，不是放宽）。生成物**逐字节不变**由同目录
   `test_render_cases_yaml_fail_closed.py::test_real_case_library_passes_and_artifacts_are_byte_identical`
   兜住。
4. **边界登记 + 死亡条件**：`STILL_UNFAITHFUL` 逐条断言"现在**仍然**不保真" ——
   谁补上了，那条断言**当场变红**，逼他更新登记（本仓 §17.3 ④ 的口径）。
   **不许**把"没覆盖"伪装成"已覆盖"。

## 边界（照实登记，未修）

· `escaped_*` 一族（`\\"` / `\\\\` / `\\/` / `\\n`）**已由 #5179 修好** —— 双引号标量按 YAML 8.1.3
  解码。该单落地时它们的**死亡条件按设计触发**（4 条 `test_registered_gaps_are_still_gaps`
  红）⇒ 已从 `STILL_UNFAITHFUL` **移出并加进 `CORPUS`**；靶心判据在
  `tests/unit_ci_workflows/test_render_leg_escape_decode.py`（含比较器自证与判别力自证）。
· `STILL_UNFAITHFUL` 现存**三种**形态：跨行 flow 集合 / 跨行裸标量 / **被引号包起来的 key**。
· 本文件只在**装了 PyYAML** 的 job（`tests/unit_ci_workflows`）里跑；渲染腿的 CI job
  没有 PyYAML，它的判据在 `test_render_cases_yaml_fail_closed.py`（零依赖后端）。
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

sys.path.insert(0, str(GH))          # yaml_light 是零依赖模块，直接导入即可
import yaml_light  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# 语料：必须能过**标准 YAML**（真值 = PyYAML），且覆盖多行标量的各种形态
# ─────────────────────────────────────────────────────────────────────────────
#: 两条「冒烟 + 对抗」壳用例（**不能**带 `skip_reason`：生成物自检要求这两个子集非空，
#: 下列用例里的 `render` 场景若被渲染会因自检失败而 rc≠0 造成假红）。
_SHELL = ('  - id: FX-{n}\n    title: 壳{n}\n    tier: {tier}\n    domains: [utils]\n'
          '    user_inputs:\n      - "随便"\n    expectations:\n      - tool: direct_reply\n')
_HEAD = ('schema: "1"\ndomain: utils\ncases:\n'
         + _SHELL.format(n="001", tier="smoke") + _SHELL.format(n="002", tier="adversarial"))


def _case(extra: str, cid: str = "FX-900", tier: str = "normal") -> str:
    return (_HEAD + f'  - id: {cid}\n    title: 语料\n    tier: {tier}\n    domains: [utils]\n'
            + extra
            + '    user_inputs:\n      - "随便"\n    expectations:\n      - tool: direct_reply\n')


CORPUS: dict[str, str] = {
    # ① 红证本体：块标量做**序列项**（这是 `data_checks` 的天然写法）
    "block_as_sequence_item": _case(
        '    data_checks:\n'
        '      - |\n        这里 " 有引号" 且 - "看起来像值位置"\n'
        '      - >-\n        折叠标量 "也行"\n'
        '      - 第三条普通检查\n    skip_reason: "x"\n'),
    # ② 块标量做**映射值**，且后面还有兄弟键（值变 + 后续键是否还在）
    "block_as_mapping_value": _case(
        '    subtitle: |\n      第一行\n      第二行\n'
        '    data_checks:\n      - 甲\n      - 乙\n      - 丙\n    skip_reason: "x"\n'),
    # ③ 引号**跨行**做序列项（同一类丢行）
    "multiline_quote_as_sequence_item": _case(
        '    data_checks:\n      - "第一行\n        第二行"\n      - 尾条\n    skip_reason: "x"\n'),
    # ④ 引号**跨行**做映射值（双引号 / 单引号）
    "multiline_double_quoted_value": _case(
        '    subtitle: "第一行\n      第二行"\n    skip_reason: "x"\n'),
    "multiline_single_quoted_value": _case(
        "    subtitle: '第一行\n      第二行'\n    skip_reason: \"x\"\n"),
    # ⑤ 双引号里的 `\` 续行（转义换行 ⇒ 不留空格）
    "multiline_quoted_escaped_break": _case(
        '    subtitle: "第一行\\\n      第二行"\n    skip_reason: "x"\n'),
    # ⑥ 块标量在**第一条用例**里（丢行会不会连带吃掉后面两条用例）
    "block_in_first_case": (
        _HEAD.replace('  - id: FX-001\n    title: 壳001\n    tier: smoke\n    domains: [utils]\n',
                      '  - id: FX-001\n    title: 壳001\n    tier: smoke\n    domains: [utils]\n'
                      '    data_checks:\n      - |\n        块内容一\n        块内容二\n      - 尾条\n')),
    # ⑦ chomping × style × 空行 × 更缩进 × 显式缩进指示数字（一次性钉全）
    "block_chomping_matrix": _case(
        '    a: |\n      x\n      y\n'
        '    b: |-\n      x\n      y\n'
        '    c: |+\n      x\n      y\n\n'
        '    d: >\n      x\n      y\n'
        '    e: >-\n      x\n      y\n'
        '    f: >\n      x\n\n      y\n'
        '    g: >\n      x\n\n\n      y\n'
        '    h: >\n      x\n        more\n      z\n'
        '    i: |2\n        ind\n       less\n'
        '    j: |\n      单行\n'
        '    skip_reason: "x"\n'),
    # ⑧ 块标量带行内注释的头（`|  # 说明` 必须仍被认成块标量头）
    "block_head_with_inline_comment": _case(
        '    subtitle: |   # 说明\n      内容行\n    skip_reason: "x"\n'),
    # ⑨ 反向护栏：`""` / `"a"` / `''` 这类**同一行就闭合**的引号标量不得被多行读取器接管
    "quotes_closing_on_the_same_line": _case(
        '    a: ""\n    b: "x"\n    c: \'\'\n    d: "a: b"\n    skip_reason: "x"\n'),
    # ⑩ 双引号标量里的**转义序列必须解码**（issue #5179）。这四条原先住在 `STILL_UNFAITHFUL`
    #    的 `escaped_*` 一族里（"有意不修"），#5179 修好后按死亡条件移到这里 —— 真库实测
    #    33 处取值差异 / 45 个不同字符串 / 163 个多余的转义序列，全部由此解码消除。
    "escaped_double_quote": _case('    k: "a\\"b"\n    skip_reason: "x"\n'),
    "escaped_backslash": _case('    k: "a\\\\b"\n    skip_reason: "x"\n'),
    "escaped_slash": _case('    k: "a\\/b"\n    skip_reason: "x"\n'),
    "escaped_newline_escape": _case('    k: "a\\nb"\n    skip_reason: "x"\n'),
}

#: **仍未保真**的形态（如实登记）——**有死亡条件**：谁把它补上了，`test_registered_gaps_are_still_gaps`
#: 当场变红，逼他把该条移出本表并同步 `.github/yaml_light.py` 模块头那张表。
#: 每条的 `why` = **有意不修**的理由（不是"忘了"）。
#: ⚠️ `escaped_*` 一族已于 #5179 修好并移出本表（死亡条件按设计触发过 4 条）—— 不要再把它们加回来。
STILL_UNFAITHFUL: dict[str, dict[str, str]] = {
    "quoted_key": {"body": '"a\\"b": 1\n', "why":
                   "**被引号包起来的 key**：`parse_mapping` 只做 `key.strip()`，不经 `_parse_scalar` "
                   "⇒ 键不解码（值解码了、键没解码）。真用例库 0 处；给键加解码要动两个 `parse_*` "
                   "的键切片口径，风险大于收益"},
    "multiline_flow_collection": {"body": 'k: [a,\n  b]\n', "why":
                                  "跨行 **flow 集合**不是标量（`yaml_light` 本就不支持 flow style）；"
                                  "真用例库 0 处，且渲染腿的严格判定不拦它"},
    "multiline_plain_scalar": {"body": 'k: 第一行\n  第二行\n', "why":
                               "跨行**裸标量**：把它当续行会改变「没有冒号的行」的既有语义"
                               "（那是 `parse_mapping` 现在跳过的形态），风险大于收益；真用例库 0 处"},
}


# ─────────────────────────────────────────────────────────────────────────────
# 判据 1：不丢条 —— 块标量 / 跨行标量做序列项时兄弟条目一条不少
# ─────────────────────────────────────────────────────────────────────────────
def test_block_scalar_in_sequence_does_not_swallow_following_entries():
    """**红证本体**：`data_checks` 3 条必须是 3 条，且第一条取值 = 块内容（不是 `'|'`）。

    改前实测（本机 PyYAML 6.0.3 + 改前的 `yaml_light`）：
    `data_checks` = `['|']`（**3 条 ⇒ 1 条**，值还是块标量头本身）⇒ 本断言三处同时红。
    块标量的内容行缩进更大 ⇒ `parse_sequence()` 直接 `break` ⇒ `- >-` 与 `- 第三条普通检查`
    一起消失 —— 这正是 issue #5171 说的「静默丢行」。
    """
    doc = yaml_light.load(CORPUS["block_as_sequence_item"])
    checks = [c for c in doc["cases"] if c["id"] == "FX-900"][0]["data_checks"]
    assert len(checks) == 3, (
        f"`data_checks` 丢条了（{len(checks)} 条，应为 3）—— 块标量的内容行又被当成独立行喂给"
        f"状态机了？实测值：{checks!r}")
    assert checks[0] == '这里 " 有引号" 且 - "看起来像值位置"\n', (
        f"块标量的取值不是内容，而是头本身：{checks[0]!r}")
    assert checks[2] == "第三条普通检查", f"块标量之后的兄弟条目丢了：{checks!r}"


def test_multiline_quote_in_sequence_does_not_swallow_following_entries():
    """同类形态的第二个面：引号**跨行**时后续兄弟条目也会一起消失。"""
    doc = yaml_light.load(CORPUS["multiline_quote_as_sequence_item"])
    checks = [c for c in doc["cases"] if c["id"] == "FX-900"][0]["data_checks"]
    assert checks == ["第一行 第二行", "尾条"], f"跨行引号标量丢条/取值不对：{checks!r}"


def test_block_scalar_does_not_swallow_following_cases():
    """块标量出现在**第一条用例**里时，后面两条用例必须还在（丢行的最坏形态）。"""
    doc = yaml_light.load(CORPUS["block_in_first_case"])
    assert [c["id"] for c in doc["cases"]] == ["FX-001", "FX-002"], (
        f"用例整条消失：{[c['id'] for c in doc['cases']]!r}")
    assert doc["cases"][0]["data_checks"] == ["块内容一\n块内容二\n", "尾条"]


# ─────────────────────────────────────────────────────────────────────────────
# 判据 2：与 PyYAML **逐值一致**（真值 = yaml.safe_load）
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", sorted(CORPUS))
def test_corpus_is_value_identical_to_pyyaml(name):
    """`CORPUS` 每一条：`yaml_light.load()` 必须与 `yaml.safe_load()` **深比较相等**。

    断言的是**取值**（不是"能解析"）—— 「解析成功但取值不同」正是本单治的形态。
    """
    body = CORPUS[name]
    truth = yaml.safe_load(body)                     # 夹具本身必须是合法 YAML（真值来源）
    got = yaml_light.load(body)
    assert got == truth, (
        f"[{name}] yaml_light 与 PyYAML 取值不一致：\n  PyYAML   ={truth!r}\n  yaml_light={got!r}")


# ─────────────────────────────────────────────────────────────────────────────
# 判据 3：不回归 —— 真用例库的条数 / 长度 / 差异归属都不变
# ─────────────────────────────────────────────────────────────────────────────
def _diffs(txt: str):
    """先过严格判定（PyYAML 拒绝的文件不参与对照 —— 那是另一条腿的事）。"""
    truth = yaml.safe_load(txt)
    got = yaml_light.load(txt)
    return truth, got


def _assert_no_row_loss(truth, got, label):
    """真库「不丢行」判据的**单一实现**：id 序列 + 每个列表字段的长度都必须一致。

    单独抽出来是为了**让这条判据自己能红**：真用例库当前一处都不丢 ⇒ 直接跑它永远是绿的
    （"不会红的断言 = 空断言"）。`test_row_loss_guard_can_actually_go_red` 拿**改前形态**
    （`data_checks` 3 条 ⇒ 1 条）喂它，证明它**确有判别力**。
    """
    tc, gc = truth.get("cases") or [], got.get("cases") or []
    assert [c.get("id") for c in tc] == [c.get("id") for c in gc], (
        f"{label}: 用例条数/id 序列变了 —— PyYAML {len(tc)} 条 / yaml_light {len(gc)} 条")
    by_id = {c.get("id"): c for c in gc}
    for c in tc:
        g = by_id[c["id"]]
        for k, v in c.items():
            if isinstance(v, list):
                assert isinstance(g.get(k), list) and len(g[k]) == len(v), (
                    f"{label} {c['id']}.{k}: 条数 {len(v)} ⇒ {g.get(k)!r} —— **静默丢行**"
                    f"（块标量 / 跨行标量又没被整段读走了？）")


def test_real_case_library_keeps_every_case_and_every_row():
    """真用例库 25 文件：用例**条数与 id 序列**不变、每个**列表字段的长度**不变。

    这是"不丢行"在真库上的机械判据 —— 它**不依赖**取值是否与 PyYAML 相同
    （那由下一条管），所以「取值差异」与「内容缩水」两类问题不会互相掩盖。
    """
    files = sorted(CASES.glob("*.yml"))
    assert len(files) == 25, f"用例库文件数变了（{len(files)}）—— 本判据会静默空跑"
    for f in files:
        truth, got = _diffs(f.read_text(encoding="utf-8"))
        _assert_no_row_loss(truth, got, f.name)


def test_row_loss_guard_can_actually_go_red():
    """**判别力自证**：把**改前形态**（块标量做序列项 ⇒ 3 条并成 1 条）喂给上面那条判据 ⇒ 必红。

    为什么必须有这条：真用例库**当前一处都不丢** ⇒ 上一条判据永远是绿的，
    读者无从知道它"到底是守住了，还是根本不会红"。这里**不碰真用例库**
    （它是产物唯一源头，本单一个字都不许改），只用 `CORPUS` 里的真实夹具喂它。
    """
    truth = yaml.safe_load(CORPUS["block_as_sequence_item"])
    got = yaml_light.load(CORPUS["block_as_sequence_item"])
    _assert_no_row_loss(truth, got, "（自证：修好后的形态）")      # 前提自断言：现在不丢

    broken = yaml.safe_load(CORPUS["block_as_sequence_item"])
    for c in broken["cases"]:
        if c["id"] == "FX-900":
            c["data_checks"] = ["|"]          # = 改前 `yaml_light` 的真实产出（3 条 ⇒ 1 条）
    with pytest.raises(AssertionError) as ei:
        _assert_no_row_loss(broken, got, "（自证：改前形态）")
    assert "静默丢行" in str(ei.value), f"红了但不是因为丢行：{ei.value}"


def test_real_library_values_are_py_yaml_identical():
    """真用例库与 PyYAML 必须**逐值相等** —— 任何一处差异即红（**零容忍**）。

    为什么单开这条：`STILL_UNFAITHFUL` 是**枚举**，"枚举里那几条之外还有没有别的差异"
    才是真正要守的东西。

    口径沿革（**收紧**，不是放宽）：#5171 放行口径是"差异都能由 `STILL_UNFAITHFUL` 解释"
    （修前实测 **33 处**全是 `escaped_*`）；#5179 把 `escaped_*` 修好之后，那条容忍口径
    **整条退场**，本判据改为零容忍 —— 块标量 / 跨行标量 / 转义解码任一族再破，都在这里
    逐处点名（诊断信息含真值 vs `yaml_light` 两侧取值）。
    """
    diffs = []
    for f in sorted(CASES.glob("*.yml")):
        truth, got = _diffs(f.read_text(encoding="utf-8"))
        by_id = {c.get("id"): c for c in got.get("cases") or []}
        for c in truth.get("cases") or []:
            g = by_id[c["id"]]
            for k in set(c) | set(g):
                if c.get(k) != g.get(k):
                    diffs.append(f"{f.name} {c['id']}.{k}: "
                                 f"PyYAML={c.get(k)!r} / yaml_light={g.get(k)!r}")
    assert not diffs, (
        f"真用例库 **{len(diffs)} 处**取值与 PyYAML 不同（渲染腿的取值保真度破了）：\n  "
        + "\n  ".join(diffs[:20])
        + "\n⇒ **修 `yaml_light`**（渲染腿与真值同源是硬要求）；确属有意不修的形态才登记进 "
          "`STILL_UNFAITHFUL` 并在 `.github/yaml_light.py` 模块头同步 —— 登记是**例外**，不是默认。")


def test_render_leg_still_produces_byte_identical_artifacts(tmp_path):
    """生成物**逐字节不变**（本单最要害的一条）：渲染腿走的就是 `yaml_light` 那条路。

    ⚠️ 同目录 `test_render_cases_yaml_fail_closed.py` 有一条同款 —— 这里**不省**它：
    那条锚的是 #5151（严格判定），本单改的是**取值**，红的原因不同、诊断信息不同。
    """
    out = tmp_path / "out"
    out.mkdir()
    p = subprocess.run(
        [sys.executable, str(RENDER), "--cases", str(CASES),
         "--out-eval", str(out / "eval_cases.py"), "--out-md", str(out / "casebook.md")],
        cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert p.returncode == 0, f"真用例库渲染失败：\n{p.stdout}\n{p.stderr}"
    for produced, committed in ((out / "eval_cases.py", GEN_EVAL), (out / "casebook.md", GEN_MD)):
        assert produced.read_bytes() == committed.read_bytes(), (
            f"{committed.relative_to(REPO_ROOT)} 与重新渲染结果**不是逐字节一致** —— "
            f"改动只该让多行标量取值变对，不该改真用例库的产物")


# ─────────────────────────────────────────────────────────────────────────────
# 判据 4：边界登记**有死亡条件**
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", sorted(STILL_UNFAITHFUL))
def test_registered_gaps_are_still_gaps(name):
    """`STILL_UNFAITHFUL` 是**有死亡条件的登记**：它现在**仍**不保真 ⇒ 绿；谁补上了 ⇒ 当场红。

    为什么要这条：不写它，"剩下的缺口"就只是注释里的一句话 —— 下一个人既无从知道
    这些形态**现在确实漏着**，也无从知道自己把它补上了（漏检缺口无人认领）。
    ⇒ 红了的修法是**更新 `STILL_UNFAITHFUL` 与 `.github/yaml_light.py` 模块头那张表**，
    **不是**把本判据删掉。
    """
    spec = STILL_UNFAITHFUL[name]
    body = spec["body"]
    truth, got = _diffs(body)
    if got == truth:
        pytest.fail(
            f"[{name}] 这条缺口**已经被补上了**（好消息）：yaml_light 现在与 PyYAML 取值一致 "
            f"（{truth!r}）⇒ 请把它从 `STILL_UNFAITHFUL` 移出、加进上面的 `CORPUS`，"
            f"并同步 `.github/yaml_light.py` 模块头那张表。\n原登记理由：{spec['why']}")


def test_gaps_table_records_a_reason_for_every_entry():
    """登记表本身**不许有空条目**：每条都要写清"为什么有意不修"（否则就成了"忘了"）。"""
    empty = [k for k, v in STILL_UNFAITHFUL.items() if not v.get("why", "").strip()]
    assert not empty, f"这些登记条目没写理由：{empty}"
