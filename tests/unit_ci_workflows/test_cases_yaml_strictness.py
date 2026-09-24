# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 既有惯例：CI 结构类 L0 不变式统一挂 MC-012）
"""用例源文件的**严格性**：重复键 / 非法 YAML / 两侧判定不一致（issue #4265 + #4291 + #4336）。

## 病灶（同一族：宽松路径把「断言 / 真值」**静默吞掉**）

| 单 | 形态 | 修复前实测读数（`origin/main @` 本 PR 分叉点） |
|---|---|---|
| #4265 | `yaml_light` 吃得下标准 YAML 拒绝的文件 ⇒ 渲染腿照旧产出生成物 | 语法面已由 #5151 收口（`cases_yaml.strict_error`），本文件钉住它**不许回退** |
| #4291 | `.github/templates/*.yml` 同一 mapping 里 **5 个 `expect:`** ⇒ 装载后只剩最后一个 | 真值断言**静默丢 4 条**（fabric-calc） |
| #4336 | `.github/cases/*.yml` 5 个映射共 **12 处**重复键（OR-017 / OR-024 / OR-026 / OR-030 / PR-102） | 整套 `data_checks` / `skip_reason` / `merge_log` / `traces` **静默丢弃** |

⚠️ **重复键不是"换个严格解析器"能治的**：YAML 规范不禁止同一 mapping 里出现重复键，
**PyYAML 也只保留最后一个、不报错**（实测）⇒ 本单在 `.github/cases_yaml.py` 里加了一层
**零依赖**的行级键异常扫描（`_scan_key_anomalies`），**两个后端共用同一份实现** ⇒
"两侧判定一致"是**构造上**成立的；CI 的 `case-truth-check` job **没有 PyYAML**（模块头），
而渲染腿正是在那里跑的 ⇒ 复用同一份扫描才能让**渲染腿在 CI 上真的 fail-closed**。

## 本文件锁七条（每条都能单独变红）

1. **`.github/cases/**` 零键异常**（重复键 / 键落在标量项续行区）：判据 = `cases_yaml.key_anomalies()`
   **现取**（无豁免白名单、无台账 —— 比"只许缩短的台账"更强）；
2. **`.github/cases/**` 必须能被标准 YAML 解析**（`yaml.safe_load`）⇒ 自带红证：
   往临时用例文件里塞一个未转义双引号，判据当场红；
3. **`.github/templates/**` 零键异常**（#4291 的类级面：真值注册表断言不许再被静默丢弃）；
4. **渲染腿 fail-closed 逐条实跑**：临时用例目录里塞「重复键」/「非法 YAML」⇒
   `.github/render_cases.py` **非零退出 + 指名文件与行号**，且**一个生成物都不产出**；
5. **零依赖后端同样红**（CI 真实形态）：把 PyYAML 变成不可导入 ⇒ 同一批坏样本仍判红；
6. **两侧判定一致**：真库上 `yaml_light` 接受 ⟺ PyYAML 接受 ⟺ 门禁放行（三者必须同极）；
   并且**门禁必须严于宽松腿** —— 「宽松腿吃得下 + 标准 YAML 拒绝」的样本必须被门禁拒；
7. **#4291 判据 3②（现取）**：模板里**源断言原文**必须与**装载后的断言**一致
   （`expect:` 键数 ≠ 断言数 = 有断言被吞）。

## 红证（逐条实跑，注入先自证生效）

| 注入 | 期望 |
|---|---|
| 临时用例文件写重复键（`namespaces:` 两次） | 判据 1/4 **红**（渲染腿非零退出、点名 `行:列`）+ `mutated != src` 自证 |
| 临时用例文件写未转义双引号（#5147 真实形态） | 判据 2/4 **红**（PyYAML 拒、宽松腿吃下 ⇒ 正是 #4265 的形态） |
| 把 `cases_yaml.strict_error` 单点改瞎（两侧判定被人为改成一致） | 判据 6 **红**（门禁放行了标准 YAML 拒绝的文件），且**变异生效自证** |

## 未固化 / 边界（照实登记，§19.1）

| 登记 | 现取读数 | 为什么**不**修 | 谁看 |
|---|---|---|---|
| `.github/templates/*.yml` **整体**不是标准 YAML（`- [真值 ID] 说明` 是**有意**的类 YAML 约定） | 见 `test_registered_gaps_are_still_gaps` 现取（26） | 修它 = 改真值模板的**格式**（26 个文件 + 消费方 `truths.py`），不在本单面内；且它们是"类 YAML"而非坏 YAML | 真值模板面 owner / 集成侧（本单未另开 issue） |
| 模板断言文本里的 ` #NNNN` 被**标准 YAML 当行内注释**吃掉（值在 `issue` 处截断） | 同上现取（3） | 属**另一族**（纯标量截断，与技能 v1.21 的 frontmatter 同族），要改 26 个模板的散文 | 同上 |
| flow 映射里的重复键（`{a: 1, a: 2}`）**不在**扫描面内 | 见 `NOT_COVERED_DUPLICATE` | 行级扫描按"flow 整段跳过"实现（保守：不误拒合法用例） | 判据面 owner（谁做 flow 级解析谁补） |

⚠️ 前两条**不是"可以不管"**：它们由 `test_registered_gaps_are_still_gaps` 以**现取计数 + 死亡条件**
钉住（读数变了 ⇒ 本文件红 ⇒ 逼登记更新，本仓 §17.3 ④ 的口径）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GITHUB = REPO_ROOT / ".github"
sys.path.insert(0, str(GITHUB))                      # cases_yaml（严格 loader 的单一真相源）
sys.path.insert(0, str(Path(__file__).resolve().parent))   # 复用同目录既有夹具（不复制规则）
import cases_yaml  # noqa: E402
from yaml_light import load_file  # noqa: E402
from test_render_cases_yaml_fail_closed import _case_dir, _no_pyyaml_env, _render  # noqa: E402

CASES_DIR = GITHUB / "cases"
TEMPLATES_DIR = GITHUB / "templates"
CASE_FILES = sorted(CASES_DIR.glob("*.yml"))
TEMPLATE_FILES = sorted(TEMPLATES_DIR.glob("*.yml"))

#: 坏样本①：**同一 mapping 内重复键**（`#4336` 的真实形态，`OR-017` 缩样）。
#: ⚠️ PyYAML 与 `yaml_light` **都**只保留最后一个、都不报错 ⇒ 只有键异常扫描能抓。
_DUP_KEY_BODY = (
    'schema: "1"\ndomain: utils\ncases:\n  - id: FX-810\n    title: "重复键样本"\n'
    '    tier: smoke\n    domains: [utils]\n    user_inputs:\n      - "随便"\n'
    '    expectations:\n      - tool: direct_reply\n'
    '    namespaces:\n      - "customer_phone:13800138000"\n'
    '    namespaces:\n      - "product_name:遮光窗帘"\n'
    '    skip_reason: "[backend-contract] fixture"\n'
)

#: 坏样本②：**未转义的双引号**（`#5147` / `#4265` 的真实形态）—— 标准 YAML 拒绝、宽松腿吃下。
_BAD_QUOTE_BODY = (
    'schema: "1"\ndomain: utils\ncases:\n  - id: FX-811\n    title: "未转义引号样本"\n'
    '    tier: smoke\n    domains: [utils]\n    user_inputs:\n      - "随便"\n'
    '    expectations:\n      - tool: direct_reply\n'
    '    subtitle: "这里有个未转义的 " 引号"\n'
    '    skip_reason: "[backend-contract] fixture"\n'
)

#: 登记：模板面两条已登记缺口（**现取**，涨跌都红 ⇒ 逼登记更新）。
_TEMPLATES_NOT_STANDARD_YAML = 26        # `- [真值 ID] 说明` 约定 ⇒ 标准 YAML 全拒
_TEMPLATE_ASSERTIONS_COMMENT_TRUNCATED = 3   # ` #NNNN` 被当行内注释 ⇒ 断言原文被截断


# ─────────────────────────────────────────────────────────────────────────────
# 判定辅助（三侧：宽松腿 / 标准 YAML / 门禁）—— **不各写一份解析**，只调既有入口
# ─────────────────────────────────────────────────────────────────────────────
def _yaml_light_ok(path) -> bool:
    """宽松腿（渲染口径）能否吃下这个文件。"""
    try:
        load_file(str(path))
    except Exception:
        return False
    return True


def _pyyaml_ok(path) -> bool:
    """标准 YAML 能否解析这个文件。"""
    try:
        yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return False
    return True


def _gate_blindness(files) -> list[str]:
    """**门禁放行了**哪些文件（判据被改瞎 / 比标准 YAML 更宽时，这里会非空 ⇒ 红）。"""
    out = []
    for f in files:
        if cases_yaml.strict_error(f) is None:
            out.append(f"{f}: strict_error() 放行")
    return out


def _corpus_disagreements(files) -> list[tuple]:
    """真库上三侧判定**不同极**的文件（`(名字, 宽松腿, 标准YAML, 门禁)`）。"""
    bad = []
    for f in files:
        loose, strict, gate = _yaml_light_ok(f), _pyyaml_ok(f), cases_yaml.strict_error(f) is None
        if not (loose == strict == gate):
            bad.append((Path(f).name, loose, strict, gate))
    return bad


# ─────────────────────────────────────────────────────────────────────────────
# 判据 1~3：真库零异常（**现取**，无白名单）
# ─────────────────────────────────────────────────────────────────────────────
def test_corpus_premise():
    """判据的**前提**：两个面都被扫到且非空（否则逐文件参数化会静默空跑 = 假绿）。"""
    if not CASE_FILES:
        raise AssertionError(f"没扫到任何 cases/*.yml（{CASES_DIR}）—— 本文件会静默空跑")
    if not TEMPLATE_FILES:
        raise AssertionError(f"没扫到任何 templates/*.yml（{TEMPLATES_DIR}）—— #4291 面会静默空跑")
    if not (CASES_DIR / "order.yml").exists() or not (TEMPLATES_DIR / "fabric-calc.yml").exists():
        raise AssertionError("两个曾出事的文件不在扫描集里 ⇒ 判据的靶子没了")


@pytest.mark.parametrize("path", CASE_FILES, ids=[p.name for p in CASE_FILES])
def test_case_file_has_no_key_anomalies(path: Path):
    """判据 1：`.github/cases/**` 不许有重复键 / 键落在标量项续行区（现取，无豁免）。"""
    hits = cases_yaml.key_anomalies(path.read_text(encoding="utf-8"))
    if hits:
        raise AssertionError(
            f"{path} 有 {len(hits)} 处行级键异常（重复键 = 前一份被静默丢弃；"
            f"标量项续行里的键 = 标准 YAML 直接拒绝）：\n  " + "\n  ".join(hits)
            + "\n⇒ 修法：同一 mapping 里只留一个键（断言改写成列表项 / 独立条目），"
              "**不要**靠调宽判据")


@pytest.mark.parametrize("path", CASE_FILES, ids=[p.name for p in CASE_FILES])
def test_case_file_parses_with_standard_yaml(path: Path):
    """判据 2：`.github/cases/**` 必须能被**标准 YAML**解析（拒绝 ⇒ 红）。"""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"{mark.line + 1}:{mark.column + 1}" if mark else "<位置不明>"
        raise AssertionError(
            f"{path}:{where} 标准 YAML 拒绝（{getattr(e, 'problem', None) or e}）"
            f" —— 宽松腿 `yaml_light` 会照旧渲染出生成物（#4265 的形态）") from e
    if not (doc or {}).get("cases"):
        raise AssertionError(f"{path}: 解析结果里没有非空 cases 列表（防「清空文件也照样绿」）")


@pytest.mark.parametrize("path", TEMPLATE_FILES, ids=[p.name for p in TEMPLATE_FILES])
def test_template_file_has_no_key_anomalies(path: Path):
    """判据 3：`.github/templates/**` 零键异常（#4291：真值注册表的断言不许再被静默丢弃）。"""
    hits = cases_yaml.key_anomalies(path.read_text(encoding="utf-8"))
    if hits:
        raise AssertionError(
            f"{path} 有 {len(hits)} 处行级键异常（#4291 家族：装载后只剩最后一份，"
            f"前面的断言**静默消失**）：\n  " + "\n  ".join(hits)
            + "\n⇒ 修法：一条断言一行 —— `expect:` 写成列表，或断言各自成一条目")


# ─────────────────────────────────────────────────────────────────────────────
# 判据 4~5：渲染腿 fail-closed 逐条实跑（红证）
# ─────────────────────────────────────────────────────────────────────────────
def _assert_render_rejects(tmp_path: Path, body: str, *, needle: str, env: dict | None = None,
                           name: str = "injected") -> str:
    """把 `body` 塞进临时用例目录 ⇒ 渲染腿**必须非零退出**、指名 `needle`、且不产出生成物。"""
    src = body
    cases_dir = _case_dir(tmp_path, **{name: src})
    target = cases_dir / f"{name}.yml"
    mutated = target.read_text(encoding="utf-8")
    if mutated == "" or mutated != src:            # ★ 注入先自证生效（§23 G7：变异必须先证明生效）
        raise AssertionError(f"注入没生效：写进 {target} 的内容与样本不一致")
    out = tmp_path / "out"
    proc = _render(cases_dir, out, env=env)
    if proc.returncode == 0:
        raise AssertionError(
            f"渲染腿**退出 0**（应当 fail-closed）：注入的是 {name}，样本= {src[:60]!r}\n"
            f"stdout={proc.stdout[-400:]}")
    combined = proc.stdout + proc.stderr
    if needle not in combined:
        raise AssertionError(f"渲染腿红了但**没指名** {needle!r} ⇒ 判红不可归因：\n{combined[-600:]}")
    if (out / "eval_cases.py").exists() or (out / "casebook.md").exists():
        raise AssertionError("渲染腿红了却**仍产出了生成物**（半成品生成物会被下游当真相读）")
    return combined


def test_render_leg_rejects_duplicate_keys(tmp_path):
    """判据 4·红证①：重复键 ⇒ 非零退出 + 点名 `行:列` + 键名 + 不产出生成物。"""
    combined = _assert_render_rejects(
        tmp_path, _DUP_KEY_BODY, needle="重复键 `namespaces`", name="dupkey")
    if "14:5" not in combined:                     # 第二次 namespaces 的行:列（1-based）
        raise AssertionError(f"报错没给出行号（可归因性不足）：\n{combined[-500:]}")


def test_render_leg_rejects_illegal_yaml(tmp_path):
    """判据 4·红证②：非法 YAML（未转义引号 = #5147/#4265 真实形态）⇒ 非零退出 + 指名位置。"""
    combined = _assert_render_rejects(
        tmp_path, _BAD_QUOTE_BODY, needle="标准 YAML 解析失败", name="badquote")
    if not any(ch.isdigit() for ch in combined):
        raise AssertionError("报错里没有任何行列数字 ⇒ 读者无法定位")


def test_render_leg_rejects_duplicate_keys_without_pyyaml_too(tmp_path):
    """判据 5：**CI 的真实形态**（`case-truth-check` job 没有 PyYAML）下必须**同样红**。

    只在"有 PyYAML"那侧检测 = 名义上的 fail-closed（该 job 才是渲染腿真正跑的地方）。
    """
    env = _no_pyyaml_env(tmp_path / "nopyyaml")
    combined = _assert_render_rejects(
        tmp_path, _DUP_KEY_BODY, needle="重复键 `namespaces`", env=env, name="dupkey_noPyYAML")
    if "零依赖" in combined and "重复键" not in combined:
        raise AssertionError(f"零依赖后端没走到键异常判定：\n{combined[-500:]}")


# ─────────────────────────────────────────────────────────────────────────────
# 判据 6：两侧判定一致（真库）+ 门禁严于宽松腿（#4265 的机械化）
# ─────────────────────────────────────────────────────────────────────────────
def test_yaml_light_and_pyyaml_verdicts_agree_on_the_real_corpus():
    """判据 6：真库上 `yaml_light` / 标准 YAML / 门禁的判定必须**同极**（不同极即红）。"""
    bad = _corpus_disagreements(CASE_FILES)
    if bad:
        raise AssertionError(
            "同一批源文件上三侧判定不一致（名字, 宽松腿接受, 标准YAML接受, 门禁放行）：\n  "
            + "\n  ".join(map(str, bad))
            + "\n⇒ 判定分歧本身就是 bug：非法的源会被一侧接受、被另一侧拒绝（#4265）")


def test_gate_is_strictly_tighter_than_the_loose_leg(tmp_path):
    """判据 6（#4265 的机械化）：宽松腿吃得下、标准 YAML 拒绝的样本 ⇒ 门禁**必须拒**。"""
    cases_dir = _case_dir(tmp_path, badquote=_BAD_QUOTE_BODY)
    sample = cases_dir / "badquote.yml"
    if not _yaml_light_ok(sample):
        raise AssertionError("样本没被宽松腿吃下 ⇒ 这条判据在本次形态上没有判别力（红证退化）")
    if _pyyaml_ok(sample):
        raise AssertionError("样本被标准 YAML 接受了 ⇒ 它不是 #4265 的形态（夹具已过期）")
    blind = _gate_blindness([sample])
    if blind:
        raise AssertionError(f"门禁放行了标准 YAML 拒绝的文件 ⇒ #4265 原样复发：{blind}")


def test_blinding_the_gate_turns_this_file_red(tmp_path, monkeypatch):
    """判据 6·红证③：把严格判定**单点改瞎**（两侧判定被人为改成一致）⇒ 判据当场变红。

    ⚠️ 变异**先自证生效**（§23 G7）：没生效的注入其"绿"不算证据。
    """
    cases_dir = _case_dir(tmp_path, badquote=_BAD_QUOTE_BODY)
    sample = cases_dir / "badquote.yml"
    original = cases_yaml.strict_error
    if _gate_blindness([sample]):
        raise AssertionError("变异前门禁就已经瞎了 —— 判据本来就没在跑")
    monkeypatch.setattr(cases_yaml, "strict_error", lambda path: None)
    if cases_yaml.strict_error is original:        # ★ 变异自证生效
        raise AssertionError("变异没生效：`strict_error` 仍指向原函数 ⇒ 下面的红不算证据")
    if not _gate_blindness([sample]):
        raise AssertionError("把判定改瞎之后判据**没红** ⇒ 这条判据读的不是 strict_error（空断言）")


def test_both_backends_agree_on_the_real_corpus(tmp_path):
    """判据 6（**CI 的真实配置**）：真库在**零依赖后端**（无 PyYAML = 渲染腿在 CI 走的那条）下的
    判决，必须与后端①（本进程，有 PyYAML）**逐文件一致**。

    ⚠️ 只测后端① = **没测到 CI 上真正跑的那条腿**：`.github/cases_yaml.py` 模块头记着
    `case-truth-check` job **没有 PyYAML**，而"两条腿判决分歧"正是 #5147 / #4265 的病根
    ⇒ 这条判据把"分歧"本身钉住（真库现取 25 文件、0 分歧）。
    """
    import json
    env = _no_pyyaml_env(tmp_path / "no_pyyaml")
    code = ("import sys, json, glob; sys.path.insert(0, '.github'); import cases_yaml as c;"
            "print('BACKEND=' + c.strict_loader_name());"
            "print(json.dumps({f: c.strict_error(f) for f in sorted(glob.glob('.github/cases/*.yml'))},"
            " ensure_ascii=False))")
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT),
                          capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise AssertionError(f"零依赖腿探针跑不起来（不可判，不许当通过读）：{proc.stderr[-300:]}")
    lines = proc.stdout.strip().splitlines()
    if len(lines) < 2 or lines[0].strip() != "BACKEND=<无 PyYAML>":
        raise AssertionError(f"没跑到零依赖后端 ⇒ 本判据会静默空跑：{lines[:1]}")
    zero_dep = json.loads(lines[1])
    if len(zero_dep) != len(CASE_FILES):
        raise AssertionError(
            f"零依赖腿只判了 {len(zero_dep)} 个文件（真库 {len(CASE_FILES)} 个）⇒ 有文件没进判据")
    bad = [(Path(f).name, cases_yaml.strict_error(f), zero_dep[f])
           for f in zero_dep
           if (cases_yaml.strict_error(f) is None) != (zero_dep[f] is None)]
    if bad:
        raise AssertionError(
            "两后端在真库上判决不一致（文件, 后端①, 后端②）—— CI 的渲染腿走的是后端②：\n  "
            + "\n  ".join(map(str, bad)))


def test_registered_backend_divergence_is_still_a_divergence(tmp_path):
    """登记（**未固化**）：`k: v` + 更深一行的 `k2: v2` 上**两个后端判决分歧**。

    实测（本次现取）：后端① `2:5: mapping values are not allowed in this context（标准 YAML 解析失败）`；
    后端② `None` ⇒ CI 的渲染腿（**没有 PyYAML**）会把这种文件**照旧渲染出来**，而判据腿报错
    —— 与 #5147 / #4265 是**同一形态**，只是换了个形状（"假真值"仍有一处开口）。

    **为什么不修（照实）**：补它要让零依赖腿判红这个形态，而该形态的**行级**判据会连带把
    `tests/unit_ci_workflows/test_render_cases_yaml_fail_closed.py` 的
    `NOT_COVERED["tab_indent"]`（制表符缩进让行级缩进失真）**顶成非 None** ⇒ 那条既有登记
    当场变红，而**本包不许改那个文件**（§23.5：改被测对象 = 让别人的红证变空断言）。

    **谁看**：判据面 owner（两条登记必须**一起**改：给零依赖腿补该形态 + 处置 `tab_indent` 登记）。

    **死亡条件**：谁把零依赖腿补上了 ⇒ 本判据当场红，逼他同时处置那两条登记。
    """
    sample = tmp_path / "backend_divergence.yml"
    sample.write_text("k: v\n  k2: v2\n", encoding="utf-8")
    if _pyyaml_ok(sample):
        raise AssertionError("样本被标准 YAML 接受了 ⇒ 这条登记过期（该形态已不构成分歧）")
    env = _no_pyyaml_env(tmp_path / "no_pyyaml")
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.github'); import cases_yaml as c;"
         f"print('VERDICT:', c.strict_error({str(sample)!r}))"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise AssertionError(f"探针跑不起来（不可判，不许当通过读）：{proc.stderr[-300:]}")
    if "VERDICT: None" not in proc.stdout:
        raise AssertionError(
            "零依赖腿**已经**抓到该形态了（好消息）⇒ 请把这条登记从本文件与 `.github/cases_yaml.py` "
            "模块头删掉，并**同时**处置 `NOT_COVERED[\"tab_indent\"]`（同一处改动会让它变红）。"
            f"实测：{proc.stdout.strip()}")


# ─────────────────────────────────────────────────────────────────────────────
# 判据 7：#4291 判据 3② —— 模板断言"源 == 装载"（现取）
# ─────────────────────────────────────────────────────────────────────────────
def _source_assertions(text: str) -> list[str]:
    """源文件里 `reviewer_asserts` 的断言**原文**（inline `expect: v` 与列表两种写法都收）。

    ⚠️ 返回的是**未归一**的原文 —— 归一到"标准 YAML 行内注释口径"的动作在比较处做
    （`_norm_assertion`），否则"被注释截断"这件事会被抽取阶段自己抹掉、看不见。
    """
    out, lines = [], text.split("\n")
    for i, ln in enumerate(lines):
        stripped = ln.lstrip(" ")
        if not stripped.startswith("expect:"):
            continue
        indent, rest = len(ln) - len(stripped), stripped[len("expect:"):].strip()
        if rest:
            out.append(rest)
            continue
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                continue
            ind = len(nxt) - len(nxt.lstrip(" "))
            if ind <= indent or not nxt.strip().startswith("- "):
                break
            out.append(nxt.strip()[2:].strip())
    return out


def _norm_assertion(text: str) -> str:
    """按**标准 YAML 的行内注释口径**归一（` #…` 起注释）。

    复用宽松腿自己的 `_strip_inline_comment`（单一真相源）—— 自己再写一份"看起来一样"的
    剥离规则，就会在"两者不一致"时把断言丢失误报成注释截断（本仓经典假红形态）。
    """
    from yaml_light import _strip_inline_comment
    return str(_strip_inline_comment(text))


#: 判据 7 的参数化集合：**声明了 `expect:`** 的模板（现取；空集合由前提判据拦下）。
TEMPLATES_WITH_EXPECT = [p for p in TEMPLATE_FILES
                         if _source_assertions(p.read_text(encoding="utf-8"))]


def _loaded_assertions(path) -> list[str]:
    """模板**装载后**的断言（走 `yaml_light` = 真实消费口径）。"""
    out = []
    for item in (load_file(str(path)).get("reviewer_asserts") or []):
        if isinstance(item, dict):
            v = item.get("expect")
            if isinstance(v, list):
                out += [str(x) for x in v]
            elif v is not None:
                out.append(str(v))
    return out


@pytest.mark.parametrize("path", TEMPLATES_WITH_EXPECT, ids=[p.name for p in TEMPLATES_WITH_EXPECT])
def test_template_assertion_texts_survive_loading(path: Path):
    """判据 7（#4291 判据 3②）：源里的每条断言原文都必须出现在**装载后**的断言里。

    ⚠️ 这条判据在**修复前必红**：fabric-calc 源 6 条 → 装载 2 条（丢 4）、
    product-sku-stock 源 16 条 → 装载 9 条（丢 7）、ai-chat 源 5 条 → 装载 3 条（丢 2）。

    参数化集合 = **声明了 `expect:` 的模板**（`dashboard-ui` / `frontend-fix` 两条没有断言面，
    对它们本判据不适用 ⇒ 不参数化、也不 `skip`：**空跑与通过必须长得不一样**，
    前提由 `test_assertion_survival_premise` 现取钉住）。
    """
    src = _source_assertions(path.read_text(encoding="utf-8"))
    loaded = _loaded_assertions(path)
    if not src:
        raise AssertionError(f"{path}: 参数化集合与抽取口径不一致（本判据会静默空跑）")
    missing = [x for x in src if _norm_assertion(x) not in loaded]
    if missing:
        raise AssertionError(
            f"{path}: {len(missing)}/{len(src)} 条断言**静默消失**（源有、装载后没有）—— "
            f"#4291 的形态：\n  " + "\n  ".join(m[:110] for m in missing))


def test_assertion_survival_premise():
    """判据 7 的**前提**：断言抽取面不许被整体抽空（否则上面那条参数化会静默全绿）。"""
    with_expect = {p.name for p in TEMPLATE_FILES
                   if _source_assertions(p.read_text(encoding="utf-8"))}
    if len(with_expect) < 20:
        raise AssertionError(
            f"只有 {len(with_expect)} 个模板被抽到 `expect:`（本仓实测 24）⇒ 抽取口径坏了，"
            f"判据 7 会静默空跑")
    for name in ("fabric-calc.yml", "product-sku-stock.yml", "ai-chat.yml"):
        if name not in with_expect:
            raise AssertionError(f"{name} 不在抽取面内 ⇒ #4291 的靶子丢了（判据失去判别力）")


# ─────────────────────────────────────────────────────────────────────────────
# 判据 6（未固化登记）：带死亡条件的缺口台账（现取计数，涨跌都红）
# ─────────────────────────────────────────────────────────────────────────────
#: 扫描面**已知抓不到**的重复键形态（照实登记）。谁补上了 ⇒ 本判据当场红，逼他更新登记。
NOT_COVERED_DUPLICATE: dict[str, str] = {
    "flow_mapping_duplicate_key": 'a:\n  - {k: 1, k: 2}\n',
}


def test_registered_gaps_are_still_gaps():
    """登记表是**有死亡条件**的：现在还抓不到 ⇒ 绿；谁补上了 ⇒ **当场变红**（§17.3 ④）。"""
    newly = {name: sample for name, sample in NOT_COVERED_DUPLICATE.items()
             if cases_yaml.key_anomalies(sample)}
    if newly:
        raise AssertionError(
            f"这些形态**已经**能被键异常扫描抓到了（好消息）：{sorted(newly)} —— 请把"
            f"它们从 `NOT_COVERED_DUPLICATE` 与 `.github/cases_yaml.py` 模块头那张表里移走，"
            f"并补进本文件的注入样本（否则登记表会烂在这里）")


def test_registered_template_gaps_are_still_gaps():
    """两处**已登记但不修**的模板面读数（现取）：读数变了（修好了/恶化了）⇒ **当场变红**。"""
    illegal = [p.name for p in TEMPLATE_FILES if not _pyyaml_ok(p)]
    truncated = 0
    for p in TEMPLATE_FILES:
        raw = _source_assertions(p.read_text(encoding="utf-8"))
        truncated += sum(1 for x in raw if _norm_assertion(x) != x)
    if len(illegal) != _TEMPLATES_NOT_STANDARD_YAML or truncated != _TEMPLATE_ASSERTIONS_COMMENT_TRUNCATED:
        raise AssertionError(
            f"登记过期：模板面读数为「标准 YAML 拒绝 {len(illegal)} 个（登记 "
            f"{_TEMPLATES_NOT_STANDARD_YAML}）/ 断言被行内注释截断 {truncated} 处（登记 "
            f"{_TEMPLATE_ASSERTIONS_COMMENT_TRUNCATED}）」。\n"
            f"⇒ 变少了：把这两条登记从本文件与 PR body 里删掉（不许留过期登记）；"
            f"变多了：**新增**了同类缺口，先查是不是有人又把断言写成了会被吞掉的形态。")


def test_no_pyyaml_registration_matches_the_ci_job(tmp_path):
    """登记面自检：CI 的 `case-truth-check` job **确实**没有 PyYAML（零依赖后端的必要性）。

    判据 = 同目录既有夹具造出的"无 PyYAML"环境里，`cases_yaml` 走的是零依赖后端；
    若哪天该 job 装了 PyYAML，`_no_pyyaml_env` 这条腿就名不副实 ⇒ 红（逼更新本登记与模块头）。
    """
    env = _no_pyyaml_env(tmp_path / "no_pyyaml_probe")
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.github'); import cases_yaml as c;"
         " print('pyyaml' if c.pyyaml_available() else 'zero-dep')"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise AssertionError(
            f"探针跑不起来（判据不可判，不许当通过读）：{proc.stderr[-300:]}")
    if "zero-dep" not in proc.stdout:
        raise AssertionError(
            f"无 PyYAML 环境里后端名不符：{proc.stdout.strip()!r} ⇒ 零依赖腿的登记已过期")