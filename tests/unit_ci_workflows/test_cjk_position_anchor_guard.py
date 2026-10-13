# case_ids: MC-092
r"""「把**中文/注释级文案**当**结构位置**」的类级元守卫（issue #6802；同族 issue #5323）。

## 病根（一类缺陷，不是一个缺陷）

`tests/unit_ci_workflows/test_dev_db_whitelist_one_command.py::preflight_ordering_ok` 曾用
`text.find("启动 admin-api")` 取**文本首现**当「启动行的位置」。2026-10-13 合并 main 时，另一个块
（`#6790` 的 ai-agent 配置块）的**注释**里写了同一句话，比真启动行更靠前 ⇒ 判据判红、且报错把归因
指成「你顺序写错了」（真因 = 注释里出现了一个词）。

- 与 `#5323`「把原文当代码读」同族，形态从「引号取值」变成「**位置取值**」；
- 判红给出**错误归因**，诊断成本转嫁给下一个人；
- **负控缺失**：没有「注释里写同一句话 ⇒ 判定不变」这条该有的负控，所以这个脆弱点第一次暴露就是误伤。

## 本判据判什么

**检出形态（机械口径，AST、不看散文）**：`.find/.index/.rfind/.rindex(<字符串字面量>)` 满足

1. 字面量含**中日韩/制表符/全角**字符（`CJK_RE`）—— 即「文案级」锚而不是代码符号；**且**
2. 该调用的结果被用于**位置语义**：切片端（`x[a:b]`）、顺序比较（`<` / `>` / `<=` / `>=`，**排除** `x < 0`
   这类存在性形态）、`sorted(..., key=…)`、或**先落到变量/参数再当上述位置用**（dataflow —— `#6802` 现场
   正是这一形态：`launch = text.find("启动 admin-api")` 之后 `… < launch`）。

⇒ 每条命中**必须**在 `tests/unit_ci_workflows/cjk_position_anchor_ledger.json` 登记并带 `reason`；
**未登记即红**（`test_detected_sites_equal_ledger`），**台账只许缩短**（`test_ledger_is_frozen_and_well_formed` 钉住
现取条数 = `frozen_max_sites`）。登记条目的 `reason` 必须给出**现取证据**（该锚在语料里出现几次 / 是否落在注释行）。

**有意不改形态的那一类**（本包只登记、不改）：拿**输出/YAML 步名/Markdown 标题/用例真相串**当位置 ——
那些对象的真值面就是文本本身（子进程 stdout、workflow 步名、文档章标题），没有比它更「结构」的锚；
它们的风险面是「将来有人在**同一语料**里加注释引用同一句」，故登记并把现取出现次数写进 `reason`。

## 判据（本文件）

| # | 判什么 | 会怎么红 |
|---|---|---|
| 1 | **台账复算（全射程普查）**：检出集 ↔ 登记集**双向相等**（同一文件同一锚算两次） | 新写一处「中文锚 + 位置语义」⇒ 具名报出该处；改掉一个锚 ⇒ 旧条目变 stale ⇒ 红 |
| 2 | **台账不许空转**：每条须有 `file` / `anchor` / `kind` / `reason`（≥ 20 字，且含现取证据） | 空台账 / 空 reason / 只写「有意如此」⇒ 红 |
| 3 | **只许缩短**：条数 ≤ `FROZEN_MAX_SITES`（= 台账 `frozen_max_sites`，两处必须一致） | 加条目「消红」而不改大冻结数 ⇒ 红 |
| 4 | **判别力自证（内存注入）**：脆弱片段（cmp / slice / sorted / dataflow）必红；**代码符号锚**（ASCII）不红；**仅存在性判断**（`x.find(…) < 0`）不红；**只改注释 ⇒ 检出集不变** | 守卫退化成恒绿 / 被自己的说明文字喂红 ⇒ 红 |
| 5 | **射程自证（基线制）**：台账文件必在扫描集；**未提交的新文件**（`git ls-files --others`）立刻进扫描集并被检出 | 新文件漏扫（判据恒绿）⇒ 红 |

## 边界（照实登记，§19.1）

- **射程 = 基线制**：`scanned_files()` = 台账那一批 ∪ **本 PR 改动/新增**的 `test_*.py`（未提交 + 未跟踪 +
  `origin/main..HEAD`）。⇒ 判据 1（台账复算）是**全射程普查**（不受基线影响），判据 5 才是真实工作口径；
  理由：存量 42 处是**已上线**的位置锚，它们在**没被改到**时不为本包产生噪声，被改到就必红。
  `.git` 不可用 / 没有 `origin/main` 时基线退化为空集（**假绿方向**，不误伤）—— 台账那一批仍由判据 1 逐条复算。
- 只覆盖**单行字符串字面量**锚：`"".join([...])` 拼出来的锚、模块常量传入的锚**看不见**（假绿方向，不误伤）；
  其中「常量锚」由 `tests/unit_ci_workflows/test_guard_parsing_is_comment_aware.py` 的同族口径另管。
- **未覆盖（如实登记）**：`list.index("中文")`（4 处：YAML 步名/工艺步骤）、`re.search` 的 `.start()`、
  字典键 —— 它们的锚同样是文案，但本判据只裁**字符串方法**这一族（那 4 处是 workflow 步名，取值面是 YAML 结构，
  改法不是「换成代码符号」，本包**不改**它们）。
- 本文件**不自扫**（它自己的说明文字里满是中文锚）。
- 不改任何门禁的通过条件、不新增豁免。
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_CI_DIR = REPO_ROOT / "tests" / "unit_ci_workflows"
LEDGER_PATH = UNIT_CI_DIR / "cjk_position_anchor_ledger.json"

#: 「文案级」字符：中日韩统一表意文字 + 全角标点 + 制表符 + 常见状态符号（✓/✗/❌/✅/⚠）
CJK_RE = re.compile(
    r'[\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef\u2500-\u257f\u2713\u2717\u274c\u2705\u26a0]'
)
FINDER_METHODS = ("find", "index", "rfind", "rindex")

#: 冻结上限（现取读数 = 台账现有条目数；**只许缩短**，加条目必须同时改大这个数 = 在 diff 里显式可见）
FROZEN_MAX_SITES = 42


# ── 检出器（AST，机械口径）──────────────────────────────────────────────────

def _cjk_literal_anchor(node: ast.AST) -> str | None:
    """该表达式是「含中日韩字符的字符串字面量」⇒ 返回该字面量，否则 None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and CJK_RE.search(node.value):
        return node.value
    return None


def _finder_calls(node: ast.AST) -> list:
    """子树里所有 `x.find/.index/.rfind/.rindex("…中日韩…")` 调用（后序便于按行号排序）。"""
    found = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if not (isinstance(f, ast.Attribute) and f.attr in FINDER_METHODS and n.args):
            continue
        anchor = _cjk_literal_anchor(n.args[0])
        if anchor is not None:
            found.append((n, anchor))
    return found


def _is_existence_comparator(node: ast.AST) -> bool:
    """`x < 0` / `x >= 0` / `x == -1` 这类**只问存在性**的比较端（不是位置比较）。"""
    if isinstance(node, ast.Constant):
        return node.value is None or isinstance(node.value, (bool, int, float, str))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, (int, float))
    return False


def _position_uses(tree: ast.AST) -> set:
    """返回「位置语义」表达式的 `id()` 集合：切片两端 / 顺序比较两端 / `sorted` 的实参。

    另外收集「被位置语义用到的变量名」—— 位置值常先落到变量再比较（`launch = text.find(…)`），
    只看节点 `id()` 会漏掉 dataflow（实测漏过一版），故按**名**再兜一层。
    """
    uses = set()
    names = set()

    def mark(node):
        if node is not None:
            uses.add(id(node))
            if isinstance(node, ast.Name):
                names.add(node.id)

    for n in ast.walk(tree):
        if isinstance(n, ast.Slice):
            mark(n.lower)
            mark(n.upper)
        elif isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(
                n.ops[0], (ast.Lt, ast.Gt, ast.LtE, ast.GtE)):
            # 存在性形态（`x < 0` / `x >= 0`）不算位置比较 —— 它只问「在不在」
            compared = [n.left] + list(n.comparators)
            if any(_is_existence_comparator(c) for c in compared):
                continue
            for c in compared:
                mark(c)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "sorted":
            for kw in n.keywords:            # `key=` / `cmp=` 的**整棵子树**（常在 lambda 里）
                for sub in ast.walk(kw.value):
                    mark(sub if not isinstance(sub, ast.Call) else sub)
            for a in n.args:
                mark(a)
    return uses, names


def detected_sites_in_source(src: str, file_label: str) -> list:
    """`src` 里的命中逐条（`(file, anchor, verdict, line, source_line)`，按出现顺序）。

    `verdict` 是**机械判定**：`slice`（切片端）/ `cmp`（顺序比较端）/ `sorted`（sorted 键）/
    `dataflow`（先落到变量 / 再当位置用）。解析不了 ⇒ 抛（调用方 fail-closed）。
    """
    tree = ast.parse(src)
    lines = src.split("\n")
    uses, use_names = _position_uses(tree)
    hits = []
    for node, anchor in _finder_calls(tree):
        verdict = ""
        if id(node) in uses:
            verdict = _verdict_for(tree, node) or "pos"
        else:
            parent = next((p for p in ast.walk(tree)
                           if isinstance(p, ast.Assign) and p.value is node), None)
            targets = [t.id for t in getattr(parent, "targets", []) if isinstance(t, ast.Name)]
            if targets and any(t in use_names for t in targets):
                verdict = "dataflow"
        if verdict:
            src_line = lines[node.lineno - 1].strip()
            hits.append((file_label, anchor, verdict, node.lineno, src_line))
    return hits


def _verdict_for(tree: ast.AST, node: ast.AST) -> str:
    """该 finder 调用是被**哪种**位置语义用到的。"""
    for n in ast.walk(tree):
        if isinstance(n, ast.Slice) and any(x is node for x in (n.lower, n.upper)):
            return "slice"
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "sorted":
            for kw in n.keywords:
                for sub in ast.walk(kw.value):
                    if sub is node:
                        return "sorted"
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(
                n.ops[0], (ast.Lt, ast.Gt, ast.LtE, ast.GtE)):
            if any(x is node for x in [n.left] + list(n.comparators)):
                return "cmp"
    return ""


def detected_sites() -> list:
    """射程 = `scanned_files()`（**基线制**：只裁**本包/本 PR 会碰的文件** + 台账那一批）。"""
    hits = []
    for path in scanned_files():
        hits.extend(detected_sites_in_source(
            path.read_text(encoding="utf-8"),
            str(path.relative_to(REPO_ROOT)),
        ))
    return hits


def detected_all_sites() -> list:
    """**全射程普查**（不看基线）：`tests/unit_ci_workflows/test_*.py` 全扫、**本文件不自扫**。

    用途 = 台账复算（`test_detected_sites_equal_ledger`）：**新写**的位置锚（哪怕还没提交）也会被它抓住。
    """
    hits = []
    for path in sorted(UNIT_CI_DIR.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        hits.extend(detected_sites_in_source(
            path.read_text(encoding="utf-8"),
            str(path.relative_to(REPO_ROOT)),
        ))
    return hits


def _git(*argv: str) -> str | None:
    """只读 git 调用（取不到 ⇒ None；调用方 fail-closed）。"""
    try:
        proc = subprocess.run(["git", "-C", str(REPO_ROOT), *argv],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _fresh_files() -> set:
    """**本 PR 会碰的** `tests/unit_ci_workflows/**` 文件（未提交 + 未跟踪 + `origin/main..HEAD` 改动的并集）。

    未跟踪（`--others --exclude-standard`）也算 —— 否则「新建但还没 `git add` 的脆弱文件」会静默漏扫
    （实测：没有这条时新文件不进扫描集）。取不到 git（非仓库 / 无 `origin/main`）⇒ 显式打印。
    """
    fresh = set()
    ok = False
    for argv in (("diff", "--name-only", "origin/main...HEAD", "--", "tests/unit_ci_workflows"),
                 ("diff", "--name-only", "--", "tests/unit_ci_workflows"),
                 ("ls-files", "--others", "--exclude-standard", "--", "tests/unit_ci_workflows")):
        out = _git(*argv)
        if out is None:
            continue
        ok = True
        fresh |= {l.strip() for l in out.splitlines() if l.strip()}
    if not ok:
        print("[cjk-anchor-guard] ⚠️ git 不可用（非仓库？）⇒ 本判据**看不到**未登记的新文件", flush=True)
    return fresh


def scanned_files() -> list:
    """扫哪些文件（**基线制**，与 `#5323` 同族口径）：

    = 台账登记过的文件（存量**只许缩短**：改用结构锚 ⇒ 条目消失 ⇒ 该文件基本退出扫描集）
      ∪ **本 PR 会碰的**新文件/改动文件（未提交 + 未跟踪 + `origin/main..HEAD`）。

    ⇒ ① 「提交一个带新位置锚的文件」必红；② 本包**不会**因为并发包 B 新建的文件而误红
    （B 的文件不在 A 的改动集里）；③ 别人**改到**某个已上线的位置锚 ⇒ 仍在射程内 ⇒ 红。
    ⚠️ 边界（如实登记）：`.git` 不可用或 CI 检出没有 `origin/main` 时，`_fresh_files()` 退化为空集，
    此时判据只覆盖台账那一批（**假绿方向**，不误伤）；台账那一批本身由
    `test_detected_sites_equal_ledger`（全射程普查）逐条复算，故台账腐坏仍会红。
    """
    ledger_files = {REPO_ROOT / f for f, _a, _k, _r in registered_sites()}
    allowed = {UNIT_CI_DIR / f.name for f in (UNIT_CI_DIR.glob("test_*.py"))
               if f.name != Path(__file__).name}
    scan = sorted((ledger_files | {REPO_ROOT / p for p in _fresh_files()}) & allowed)
    print(f"[cjk-anchor-guard] 扫描集 = {len(scan)} 个文件"
          f"（台账 {len(ledger_files)} + 本 PR 改动 {len(_fresh_files())}，差集已算）", flush=True)
    return scan


def registered_sites() -> list:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return [(s["file"], s["anchor"], s.get("kind", ""), s.get("reason", "")) for s in ledger["sites"]]


def ledger_frozen_max() -> int:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))["frozen_max_sites"]


# ── 判据 ────────────────────────────────────────────────────────────────────

def test_detected_sites_equal_ledger():
    """**台账复算（现取，不受基线影响）**：全射程普查 `tests/unit_ci_workflows/test_*.py`，
    检出集 ↔ 登记集**双向相等**（多重集）。

    ⚠️ 这条是「台账没腐坏」的复算：任何**新写**的位置锚（未提交也算）都会让它判红 —— 逐条给出文件与锚，
    出口可行动（改结构锚 / 登记并给现取证据）。**改动一个锚**同样判红（旧条目变 stale）。
    """
    detected = [(f, a) for f, a, _v, _ln, _s in detected_all_sites()]
    registered = [(f, a) for f, a, _kind, _reason in registered_sites()]
    assert registered, "台账为空 ⇒ 本判据会空转成绿：请登记或修掉命中的位置锚（fail-closed）"
    missing = [d for d in detected if d not in registered]
    stale = [r for r in registered if r not in detected]
    assert not missing, (
        "未登记的「中文/注释级文案当结构位置」（issue #6802 同族）：\n  "
        + "\n  ".join(f"{f} :: {a!r}" for f, a in missing)
        + "\n⇒ 出口①：改成**结构性锚**（代码符号 / `backend/admin-api` + `mvnw spring-boot:run` 这类"
          "**代码面**特征，注释行不算）；出口②：在 tests/unit_ci_workflows/cjk_position_anchor_ledger.json "
          "登记并写**现取证据**（该锚在语料里出现几次 / 是否落在注释行）。"
    )
    assert not stale, (
        "台账登记了**已不存在/已改动**的锚（台账只许缩短）：\n  "
        + "\n  ".join(f"{f} :: {a!r}" for f, a in stale)
    )


def test_scan_scope_is_ledger_plus_change_set():
    """**基线制射程自证**：台账文件都在扫描集里（⇒ 存量仍被复算），未登记且未改动的文件不在。

    ⇒ 证明本判据**不是**恒绿空转（台账文件真被扫、真被检出），也**不会**被并发包新建的文件误红。
    """
    names = {p.name for p in scanned_files()}
    ledger_names = {Path(f).name for f, _a, _k, _r in registered_sites()}
    assert ledger_names <= names, f"台账文件缺席扫描集：{sorted(ledger_names - names)}"
    assert Path(__file__).name not in names, "本判据文件不自扫（它自己的说明文字里满是中文锚）"
    for f, a, _k, _r in registered_sites():
        src = (REPO_ROOT / f).read_text(encoding="utf-8")
        hits = [x for _ff, x, _v, _l, _s in detected_sites_in_source(src, f)]
        assert a in hits, f"台账登记的锚在文件里检不出来（台账已腐坏）：{f} :: {a!r}"


def test_scan_scope_picks_up_fresh_file():
    """`_fresh_files()` 真的来自 git：**未提交**的新文件立刻进扫描集 ⇒ 台账复算会把它判红。"""
    probe = UNIT_CI_DIR / "test_cjk_anchor_probe.py"
    probe.write_text(
        'def ok(text):\n'
        '    return text.find("mvnw spring-boot:run") < text.find("启动 admin-api")\n',
        encoding="utf-8",
    )
    try:
        names = {p.name for p in scanned_files()}
        assert probe.name in names, f"未提交的新文件必须进扫描集（现取：{sorted(names)}）"
        hits = [a for _f, a, _v, _l, _s in detected_sites_in_source(
            probe.read_text(encoding="utf-8"), probe.name)]
        assert hits == ["启动 admin-api"], hits
        detected = [(f, a) for f, a, _v, _l, _s in detected_sites()]
        assert (str(probe.relative_to(REPO_ROOT)), "启动 admin-api") in detected, (
            "扫描集里的新文件必须被检出（注入自证）"
        )
        registered = [(f, a) for f, a, _k, _r in registered_sites()]
        assert (str(probe.relative_to(REPO_ROOT)), "启动 admin-api") not in registered, (
            "（注入自证）这个锚**没有**登记 ⇒ 台账复算会把它判红"
        )
    finally:
        probe.unlink(missing_ok=True)


def test_ledger_is_frozen_and_well_formed():
    """每条须有 `file`/`anchor`/`kind`/`reason`（现取证据），条数 ≤ 冻结上限（**只许缩短**）。"""
    entries = registered_sites()
    assert ledger_frozen_max() == FROZEN_MAX_SITES, (
        f"台账 `frozen_max_sites`（{ledger_frozen_max()}）≠ 判据里的 `FROZEN_MAX_SITES`（{FROZEN_MAX_SITES}）—— "
        "两处必须一起改（改大 = 在 diff 里显式可见）"
    )
    assert len(entries) <= FROZEN_MAX_SITES, (
        f"台账条数 {len(entries)} > 冻结上限 {FROZEN_MAX_SITES}（只许缩短）—— "
        "新增条目必须同时改大 FROZEN_MAX_SITES（= 在 diff 里显式可见），且 PR body 说明为什么它不能改成结构锚"
    )
    for f, a, kind, reason in entries:
        assert f.startswith("tests/unit_ci_workflows/") and a.strip(), f"条目形态不完整：{f!r} / {a!r}"
        assert kind in ("prose-output", "structural-code", "neg-control"), f"未知 kind：{kind!r}（{f}）"
        assert len(reason) >= 20, f"reason 太短（等于没给现取证据）：{f} :: {a!r}"
    keys = [(f, a) for f, a, _k, _r in entries]
    assert keys, "台账清空 ⇒ 判据 1 会直接红（fail-closed；这里再钉一次）"
    # 注：`(file, anchor)` **允许重复**（同一锚在同一文件的多个位置各自登记）——
    # 判据 1 用的是**多重集**相等，重复恰恰是「条数只许缩短」的计数锚点。


def test_detector_discriminates_shapes():
    """判别力自证：脆弱形态必红；**代码符号锚** / **仅存在性判断** 不红；`sorted` 算位置语义。"""
    vulnerable = (
        'def ok(text):\n'
        '    """说明文字里的 启动 admin-api 不算位置。"""\n'
        '    return text.find("mvnw spring-boot:run") < text.find("启动 admin-api")\n'
    )
    hits = detected_sites_in_source(vulnerable, "mem.py")
    assert sorted(a for _f, a, _v, _l, _s in hits) == ["启动 admin-api"], hits

    # 对照①：**代码符号锚**（ASCII）不算 —— 结构锚正是要鼓励的形态
    code_anchor = (
        'def ok(text):\n'
        '    return text.find("mvnw spring-boot:run") < text.find("跑冒烟 spec")\n'
    )
    assert [a for _f, a, _v, _l, _s in detected_sites_in_source(code_anchor, "mem.py")] == ["跑冒烟 spec"], \
        "只该报中文那一侧（ASCII 结构锚不报）"

    # 对照②：**仅存在性判断**（`< 0` / `>= 0`）不是位置语义 ⇒ 不报
    existence = (
        'def ok(text):\n'
        '    return text.find("启动 admin-api") < 0\n'
    )
    assert detected_sites_in_source(existence, "mem.py") == [], "存在性判断不取位置，不应报"

    # 对照③：切片两端取的是**位置** ⇒ 两端的中文锚都要报
    slicey = (
        'def ok(text):\n'
        '    return text[text.find("# ── 1.5 云 dev DB 预检"):text.find("# ── 2. 起栈")]\n'
    )
    assert sorted(a for _f, a, _v, _l, _s in detected_sites_in_source(slicey, "mem.py")) == \
        ["# ── 1.5 云 dev DB 预检", "# ── 2. 起栈"], "切片两端的位置锚必须都报"

    # 对照④：`sorted` 的键也是位置语义
    sorty = (
        'def ok(items, text):\n'
        '    return sorted(items, key=lambda s: text.find("值守面（超时未部署 ⇒ 判红 + 开/清值守 issue）"))\n'
    )
    assert len(detected_sites_in_source(sorty, "mem.py")) == 1, "sorted 的键里的中文锚必须报"

    # 对照⑤：**dataflow** —— 位置先落到变量、再比较（`#6802` 现场的形态）也必须报
    flow = (
        'def ok(text):\n'
        '    launch = text.find("启动 admin-api")\n'
        '    return text.find(text[10:20]) < launch\n'
    )
    assert [a for _f, a, _v, _l, _s in detected_sites_in_source(flow, "mem.py")] == ["启动 admin-api"], \
        "先落到变量的位置锚必须报（那是 #6802 的真实形态）"

    # 对照⑥：只改注释 ⇒ 检出集**不变**（判据不许被自己的说明文字喂红）
    mutated = vulnerable.replace("说明文字里的 启动 admin-api 不算位置。", "说明文字改写了：启动 admin-api 仍是注释。")
    assert [a for _f, a, _v, _l, _s in detected_sites_in_source(mutated, "mem.py")] == \
           [a for _f, a, _v, _l, _s in hits], "只改注释不得改变检出集"


def test_registered_reasons_carry_live_evidence():
    """登记条目必须给**现取证据**：`reason` 里点出出现次数或「注释行」——不许只写「有意如此」。"""
    for f, a, _kind, reason in registered_sites():
        assert ("次" in reason or "注释" in reason or "行" in reason), (
            f"reason 没有现取证据（出现次数 / 注释行读数）：{f} :: {a!r}"
        )
