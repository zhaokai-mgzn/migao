# case_ids: MC-012
r"""**全量套件的入口台账**（issue #5814 的类级元守卫）：会拉起全量 `tests/unit_ci_workflows` 的入口，
必须①**已登记**②**接了机器级准入锁**（未登记即红）。

## 治的形态（2026-09-30 14:24 CST 现场，三份并发里的两份与 runner 无关）

三份同样的全量套件同时跑在 8 核开发机上：自托管 runner 的 CI job（现已停用）、本会话一个
subagent、**另一个会话**一个 subagent（`migao-wt/orders-new-batch5`）；外加 6 个 `node (vitest)`
孤儿（PPID=1）烧了 28 分钟。`load average` 一度 45.44。
⇒ 类级病 = **同一台机器上的重活没有并发准入**。实例修法 = `scripts/machine-heavy-lock.sh` +
`verify-all.sh` 的 `gate` 档接线；本判据是**类级元守卫**：将来有人再加一个全量入口却忘了接锁，
**当场红**（而不是等下一次机器被打瘫）。

## 判定（四条，都能单独变红）

| # | 断言 | 回归时会怎么红 |
|---|---|---|
| 1 | 台账是**唯一真相源**：语料普查现取到的「会拉起全量套件的载体」集合 == 台账登记集合（双向，无遗漏、无幽灵条目） | 新增一个 `pytest … tests/unit_ci_workflows` 的载体却没登记 ⇒ 红；登记了一条实际不存在的载体 ⇒ 红 |
| 2 | 每条 `lock=required` 的条目，其 `invocation` 必须**逐字**出现在载体文件里 | 台账给不存在的保护盖章（条目指向别处）⇒ 红 |
| 3 | 每条 `lock=required` 的条目必须**同时**有 `acquire` 与 `release`（EXIT trap 形态也算） | 只加 `acquire` 不释放 ⇒ 死锁；只加 `release` ⇒ 没拿过锁 ⇒ 红 |
| 4 | 「未登记即红」的**注入式红证**：内存构造一个未登记的新载体 ⇒ 判红；只改注释 ⇒ **不红**（对照读数） | 判据写死成「读真台账就绿」⇒ 红证跑不出来 |

## 边界（照实登记，§19.1）

- 只认**载体文件里逐字写出**的 pytest 调用这一形态：`$(…)` / 变量拼接 / 由别的脚本算出来的
  目标、以及用别的运行器（vitest / jest / playwright）拉起**同一批 Python 判据**的形态**不在面内**
  （假绿方向，不会误伤）；
- **`invocation` 的形式在台账里写明**：`required` 条目写命令关键片段（不是全行），只验「该片段在载体里」；
- 台账的工具文件（本判据自己 / 两个 `.json`）**不进语料**（"引用"不等于"调用"——扫它们只会造出
  幻影条目）；
- 本判据**不保证**接入的锁真的生效（那是 `test_machine_heavy_lock.py` 的事）。
- 🔻 **「直连整目录」那一路的旧读数「盖不到」已作废**（issue #6019）：套件自带 acquire/release，
  载体 = `tests/unit_ci_workflows/conftest.py`，在台账里是 `surface=suite-internal`（**不在**语料面内
  —— 语料普查按设计跳过 `tests/unit_ci_workflows/**`）⇒ 由 `TestSuiteInternalEntries` **单独**裁
  （文件存在 / 同时有 acquire 与 release / `required` / 有 why），**语料面的双向相等一字未放宽**。
"""

from __future__ import annotations

import json
import pathlib
import re
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
LEDGER_REL = "tests/unit_ci_workflows/heavy_entry_ledger.json"
LOCK_SCRIPT_REL = "scripts/machine-heavy-lock.sh"
VERIFY_REL = "verify-all.sh"

#: 语料 = 可能**自己发起**全量套件的载体（documentation 不算：引用 ≠ 调用）。
CORPUS_SUFFIXES = (".sh", ".py", ".yml", ".yaml")
SKIP_PREFIXES = ("tests/unit_ci_workflows/", "docs/", "acceptance/", ".agents/", ".github/cases/")
#: 台账自己的工具面（引用"全量套件"是它的工作内容，不是它去拉起）
TOOL_FILES = {LEDGER_REL, "tests/unit_ci_workflows/heavy_entry_ledger.json",
              "tests/unit_ci_workflows/test_heavy_suite_entry_ledger.py"}

#: 现取形态：`pytest` + 全量目标目录（**整目录**，不是某个子文件）**同行**共现，
#: 允许中间夹 pytest 选项（`-q` / `--tb=short` / `-p no:cacheprovider` …）。
#: 有意**不**追 `$(…)` / 变量拼接 —— 那一类在成员集合里长得像"不调用"，属**假绿方向**（登记在边界）。
INVOCATION_RE = re.compile(
    r"pytest[\"']?[ \t]+(?:--?[A-Za-z][\w-]*[ \t]+)*tests/unit_ci_workflows(?![A-Za-z0-9_/.-])"
)
#: 「散文引用」标记：行内含反引号（`` ` ``）⇒ 该行整行不算调用 —— 本仓写说明时惯用反引号包命令
#: （`scripts/post_merge_verify.py` 的模块 docstring 就逐字提到那条命令，而它实际只跑**选中的子集**）。
#: 取舍的**代价**（假绿方向，不会误伤）：把真调用写在反引号里（如 `` `pytest tests/unit_ci_workflows` ``）
#: 会漏 —— 登记在台账的 coverage_boundary。


def _comments_stripped(text: str) -> str:
    """剥掉整行注释（`#` 起）—— 说明文字里的调用不算调用（对照读数靠它）。"""
    return "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith("#"))


def _invocations_in(text: str) -> list[str]:
    """一行里**真的**在发起全量套件的调用（散文行整行排除）。"""
    out: list[str] = []
    for line in _comments_stripped(text).split("\n"):
        if "`" in line:
            continue
        out.extend(m.group(0) for m in INVOCATION_RE.finditer(line))
    return out


def _corpus_files() -> list[str]:
    """语料 = `git ls-files` 里后缀命中且不在跳过面的文件（用 git 保证与 CI 同一份树）。"""
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True
    )
    files = []
    for rel in proc.stdout.split("\n"):
        rel = rel.strip()
        if not rel or not rel.endswith(CORPUS_SUFFIXES):
            continue
        if rel.startswith(SKIP_PREFIXES) or rel in TOOL_FILES:
            continue
        files.append(rel)
    return sorted(files)


def _scan_corpus(extra: dict[str, str] | None = None) -> dict[str, list[str]]:
    """载体 → 命中的调用行（**语料普查的单一实现**，判据 1/2 与注入式红证共用）。

    `extra` = **内存构造**的注入载体（`{相对路径: 文本}`）—— 红证走这里，
    **绝不往共享检出里写文件**（写文件会让同一台机器上的其它会话/并行判据看到一个假载体）。
    """
    hits: dict[str, list[str]] = {}
    for rel, text in (extra or {}).items():
        found = _invocations_in(text)
        if found:
            hits[rel] = found
    for rel in _corpus_files():
        path = REPO / rel
        if not path.is_file():
            continue
        found = _invocations_in(path.read_text(encoding="utf-8", errors="ignore"))
        if found:
            hits[rel] = found
    return hits


def _load_ledger() -> dict:
    return json.loads((REPO / LEDGER_REL).read_text(encoding="utf-8"))


#: `surface=suite-internal` ⇒ 载体在 `tests/unit_ci_workflows/**` 里（**不在**语料面内）：
#: 语料普查按设计跳过那个前缀（`coverage_boundary` 逐字写着）。这一类的判据是**单独**的一组
#: （`TestSuiteInternalEntries`），**不**参与「语料集合 ⇄ 台账集合」双向相等 —— 那是「容纳新类别」
#: 的形态，**不是**放宽原不变量：语料面的双向相等一字未动（issue #6019）。
SUITE_INTERNAL = "suite-internal"


def _corpus_entries(led: dict | None = None) -> list[dict]:
    """台账里 `surface=corpus` 的条目（缺 `surface` ⇒ 按 corpus 读，兼容存量写法）。"""
    led = _load_ledger() if led is None else led
    return [e for e in led["entries"] if e.get("surface", "corpus") == "corpus"]


def _suite_internal_entries(led: dict | None = None) -> list[dict]:
    """台账里 `surface=suite-internal` 的条目（载体在 `tests/unit_ci_workflows/**` 内）。"""
    led = _load_ledger() if led is None else led
    return [e for e in led["entries"] if e.get("surface") == SUITE_INTERNAL]


def _suite_internal_problems(led: dict) -> list[str]:
    """**suite-internal 类别的判定本体**（纯函数：判据与注入式红证调同一份实现）。

    这一类别要单独成立的四条（每条都能单独变红）：

    | # | 不变式 | 回归时会怎么红 |
    |---|---|---|
    | ① | 载体路径**必须**落在 `tests/unit_ci_workflows/**` 内 | 借这一类把别处的载体塞进「语料面外」逃避双向相等 ⇒ 红 |
    | ② | 载体文件**真实存在** | 登记一条幽灵 suite-internal 载体 ⇒ 红（= 给不存在的保护盖章） |
    | ③ | 文件里**同时**有 acquire 与 release（都通过 `machine-heavy-lock.sh`） | 删掉 acquire ⇒ 准入不生效；删掉 release ⇒ 一次异常退出就死锁 |
    | ④ | `lock=required` 且写明 why（`note`/`reason` ≥10 字） | 静默登记（没说为什么这一类要特判）⇒ 红 |
    """
    bad: list[str] = []
    for e in _suite_internal_entries(led):
        rel = str(e.get("path", ""))
        path = REPO / rel
        if not rel.startswith("tests/unit_ci_workflows/"):
            bad.append(
                f"{rel}：`surface=suite-internal` 的载体必须落在 `tests/unit_ci_workflows/**` 内"
                "（否则就是把别处的载体塞进「语料面外」逃避双向相等）"
            )
            continue
        if not path.is_file():
            bad.append(f"{rel}：台账登记了 suite-internal 载体，但**文件不存在**（幽灵条目）")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        has_acquire = "machine-heavy-lock.sh" in text and "acquire" in text
        has_release = bool(re.search(
            r"machine-heavy-lock\.sh[^\n]*release|release[^\n]*machine-heavy-lock\.sh"
            r"|trap[^\n]*release", text))
        if not has_acquire:
            bad.append(f"{rel}：suite-internal 载体只登记了锁却**没有** acquire —— 准入不生效")
        if not has_release:
            bad.append(
                f"{rel}：suite-internal 载体有 acquire 但**没有** release —— 一次异常退出就死锁"
            )
        if e.get("lock") != "required":
            bad.append(f"{rel}：suite-internal 载体必须 `lock=required`（现值 {e.get('lock')!r}）")
        if len(str(e.get("note") or e.get("reason") or "").strip()) < 10:
            bad.append(f"{rel}：suite-internal 载体必须写明为什么要有这一类（`note`/`reason` ≥10 字）")
    return bad


# ── ① 台账 == 语料普查（未登记即红 / 幽灵条目即红）──────────────────────────────

class TestLedgerIsTheSingleSourceOfTruth:
    def test_ledger_exists_and_is_wellformed(self):
        assert (REPO / LEDGER_REL).is_file(), f"台账缺失：{LEDGER_REL}（未登记即红）"
        led = _load_ledger()
        assert led.get("entries"), "台账 entries 为空 —— 「未登记即红」会退化成空断言"

    def test_registered_set_equals_scanned_set(self):
        """双向：现取到的载体集合 == 台账**语料面**登记集合（漏登记 ⇒ 红；幽灵条目 ⇒ 红）。

        ⚠️ 比的是 `surface=corpus` 那一条（issue #6019 新增 `suite-internal` 类别）——
        语料普查按设计跳过 `tests/unit_ci_workflows/**`，所以 suite-internal 载体**必须**由
        `TestSuiteInternalEntries` 单独裁。**原不变量一字未放宽**：这里仍是双向逐项相等。
        """
        led = _load_ledger()
        registered = {e["path"] for e in _corpus_entries(led)}
        scanned = set(_scan_corpus())
        missing = sorted(scanned - registered)
        phantom = sorted(registered - scanned)
        assert not missing, (
            "以下载体**会拉起全量 tests/unit_ci_workflows 却没登记**在 "
            f"{LEDGER_REL}（未登记即红；登记时同时接上机器级准入锁）："
            + "\n  - " + "\n  - ".join(missing)
            + f"\n复算：python3 -m pytest {LEDGER_REL.replace('heavy_entry_ledger.json', 'test_heavy_suite_entry_ledger.py')} -q -s"
        )
        assert not phantom, (
            f"{LEDGER_REL} 里有**幽灵条目**（登记了实际不存在的载体，= 给不存在的保护盖章）："
            + "\n  - " + "\n  - ".join(phantom)
        )

    def test_invocation_literal_is_really_in_the_carrier(self):
        """判据 2：`required` 条目的 invocation 必须逐字出现在载体里（防「盖章式台账」）。"""
        bad = []
        for e in _corpus_entries():
            if e.get("lock") != "required":
                continue
            text = (REPO / e["path"]).read_text(encoding="utf-8", errors="ignore")
            if e["invocation"] not in text:
                bad.append(f"{e['path']}：台账写的 invocation={e['invocation']!r} 不在文件里")
        assert not bad, "台账条目与载体脱钩：\n  - " + "\n  - ".join(bad)

    def test_required_entries_acquire_and_release(self):
        """判据 3：接了锁的入口必须**同时**有 acquire 与 release（EXIT trap 也算释放面）。"""
        bad = []
        for e in _corpus_entries():
            if e.get("lock") != "required":
                continue
            text = (REPO / e["path"]).read_text(encoding="utf-8", errors="ignore")
            has_acquire = "machine-heavy-lock.sh" in text and "acquire" in text
            has_release = bool(re.search(r"machine-heavy-lock\.sh[^\n]*release|trap[^\n]*release", text))
            if not has_acquire:
                bad.append(f"{e['path']}：只登记了锁却**没有** acquire —— 准入不生效")
            if not has_release:
                bad.append(f"{e['path']}：有 acquire 但**没有** release / EXIT trap —— 一次异常退出就死锁")
        assert not bad, "\n  - ".join(bad)

    def test_exemption_cannot_contradict_the_carrier(self):
        """**声明 ⇄ 现取 双向**：声明 `lock=exempt` 的载体里不得**真的**有 acquire。

        否则就是「给不存在的豁免盖章」的反面 —— 有人把一个已经接了锁的入口改判成豁免，
        台账与事实脱钩（本单要求的「只许缩短 / 改判要能被现场读数反驳」）。
        """
        bad = []
        for e in _corpus_entries():
            if e.get("lock") != "exempt":
                continue
            text = (REPO / e["path"]).read_text(encoding="utf-8", errors="ignore")
            if "machine-heavy-lock.sh" in text and "acquire" in text:
                bad.append(f"{e['path']}：声明 exempt 却真的接了 acquire（改判与事实矛盾）")
        assert not bad, "\n  - ".join(bad)

    def test_ci_only_entries_are_explicitly_exempt_with_reason(self):
        """`lock=exempt` 的条目必须写明**为什么**可以豁免（不许静默豁免）。"""
        bad = [
            e["path"] for e in _corpus_entries()
            if e.get("lock") == "exempt" and len(str(e.get("reason", "")).strip()) < 10
        ]
        assert not bad, "以下条目声明豁免却没说理由（静默豁免 = 台账失效）：\n  - " + "\n  - ".join(bad)


# ── ⑤ `surface=suite-internal`（issue #6019）：语料面**外**的载体单独裁 ────────────────

class TestSuiteInternalEntries:
    """**直连整目录**的套件自带准入（`tests/unit_ci_workflows/conftest.py`）那一类。

    为什么要有这一类而不是把它塞进语料面：载体在 `tests/unit_ci_workflows/**` 里，而语料普查
    按设计跳过该前缀（`coverage_boundary` 逐字写着）⇒ 塞进去只会造出「幽灵条目」（判据 1 红）。
    ⇒ 单独一类 + **单独**判据（本类，四条各自能单独变红），语料面的双向相等保持不动。
    """

    def test_the_class_is_not_empty(self):
        """这一类必须有条目 —— 否则「单独判据」自己退化成空断言（fail-closed）。"""
        entries = _suite_internal_entries()
        assert entries, (
            f"{LEDGER_REL} 里没有 `surface={SUITE_INTERNAL}` 条目："
            "直连整目录 `pytest tests/unit_ci_workflows` 又没有锁了（issue #6019）"
        )

    def test_suite_internal_entries_are_wellformed(self):
        """判据 ①②③④：路径在语料面外 / 文件存在 / acquire 与 release 都在 / `required` + why。"""
        problems = _suite_internal_problems(_load_ledger())
        assert problems == [], "suite-internal 载体的单独判据判红：\n  - " + "\n  - ".join(problems)

    def test_suite_internal_paths_are_not_in_the_corpus_face(self):
        """它们**必须**在语料面外（否则上面的双向相等会当场变红 = 台账与普查口径打架）。"""
        inside = sorted(
            e["path"] for e in _suite_internal_entries() if e["path"] in set(_scan_corpus())
        )
        assert not inside, (
            "以下 `surface=suite-internal` 载体**同时**落进了语料普查面 ⇒ 两个口径打架"
            "（它们应当是 `tests/unit_ci_workflows/**` 里的文件）："
            + "\n  - " + "\n  - ".join(inside)
        )

    def test_deleting_acquire_or_release_turns_red(self):
        """**注入式红证**（内存构造台账 + 真文件文本的变异体）⇒ 判别力自证。

        拿**真** `conftest.py` 的文本，在内存里把 acquire / release 各改名一处，再过
        `_suite_internal_problems`。判据若只是「读真文件就绿」，这几种坏形态都判不出来。
        对照读数 = 同一份**真**文件（**未变异**）必须零问题（它自身满篇注释与说明文字）。
        """
        real = _load_ledger()
        assert _suite_internal_problems(real) == [], "前置：真台账必须自洽（对照读数）"
        carrier = next(e["path"] for e in _suite_internal_entries())
        text = (REPO / carrier).read_text(encoding="utf-8")

        def _with(variant_text: str) -> dict:
            """把真台账的 suite-internal 载体换成变异体（**内存里**，落一个 tmp 文件供读）。"""
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                             encoding="utf-8") as tmp:
                tmp.write(variant_text)
            mutated = json.loads(json.dumps(real))
            for e in mutated["entries"]:
                if e.get("surface") == SUITE_INTERNAL:
                    e["path"] = tmp.name     # 绝对路径 ⇒ 跳过「必须落在 tests/…」那条，专测 ③
            return mutated

        # ① 把 acquire 调用改名 ⇒ 必须红
        no_acquire = text.replace("acquire_suite_lock", "acquire_suite_lock_renamed")
        assert no_acquire != text and "acquire" in no_acquire, "变异未生效（注入没落到真文本上）"
        assert _suite_internal_problems(_with(no_acquire)), (
            "把 acquire 调用改名后判据仍绿 ⇒ 判据看不出「准入不生效」（空断言）"
        )
        # ② 把 release 调用改名 ⇒ 必须红
        no_release = text.replace("release_suite_lock", "release_suite_lock_renamed")
        assert no_release != text, "变异未生效"
        assert _suite_internal_problems(_with(no_release)), (
            "把 release 调用改名后判据仍绿 ⇒ 判据看不出「一次异常退出就死锁」（空断言）"
        )
        # ③ 幽灵载体 ⇒ 必须红
        phantom = json.loads(json.dumps(real))
        phantom["entries"].append(
            {"path": "tests/unit_ci_workflows/zz-nonexistent.py", "surface": SUITE_INTERNAL,
             "lock": "required", "note": "内存构造的幽灵 suite-internal 载体（红证用）"}
        )
        assert _suite_internal_problems(phantom), "幽灵 suite-internal 载体没有被判红（空断言）"
        # ④ 把这一类整个挪出 `tests/unit_ci_workflows/**` ⇒ 必须红（否则可借它逃避双向相等）
        outside = json.loads(json.dumps(real))
        for e in outside["entries"]:
            if e.get("surface") == SUITE_INTERNAL:
                e["path"] = "scripts/zz-injected-outside.py"
        assert _suite_internal_problems(outside), (
            "把 suite-internal 载体挪到语料面外（非 `tests/unit_ci_workflows/**`）却没判红 ⇒ 空断言"
        )


# ── ④ 注入式红证（会红）+ 对照读数（只改注释 ⇒ 不红）──────────────────────────

class TestInjectionRedProofs:
    """全部**内存构造**：拿真语料当基线 → 构造变异体 → 断言坏形态读数 ≠ 基线读数。"""

    def test_unregistered_new_carrier_turns_red(self):
        """注入一个**未登记**的新载体（**内存构造**，不落盘）⇒ 现取集合必须比登记集合多出它。"""
        ledger = _load_ledger()
        registered = {e["path"] for e in _corpus_entries(ledger)}
        scanned = set(_scan_corpus())
        assert scanned == registered, "前置：基线必须自洽（否则下面的注入读数没有意义）"

        fake = "scripts/zz-injected-heavy.sh"
        injected = {fake: "#!/usr/bin/env bash\npython3 -m pytest tests/unit_ci_workflows -q\n"}
        after = set(_scan_corpus(extra=injected))
        missing = sorted(after - registered)
        assert missing == [fake], (
            "注入的未登记载体没有被语料普查看见 ⇒ 判据 1 的射程有洞："
            f"实得 {missing}"
        )
        assert after != scanned, "变异未生效（读数与基线相同）⇒ 空断言"

    def test_comment_only_change_does_not_turn_red(self):
        """对照读数：把同一句调用**写进注释**（`#` 起）⇒ **不**被当成调用（不红）。"""
        text = "#!/usr/bin/env bash\n# python3 -m pytest tests/unit_ci_workflows -q\n"
        assert not _invocations_in(text), (
            "只改注释（把调用写进 `#` 注释）却仍被算作调用 —— 判据会把说明文字误判成入口"
        )
        prose = "> 说明：`python3 -m pytest tests/unit_ci_workflows -q`\n"
        assert not _invocations_in(prose), "散文行（行首为 `>` 外包裹的反引号）被误判成调用"
        # 反向自证：同一句去掉散文包装 ⇒ 必须被看见（防上一条恒真）
        assert _invocations_in("> 说明：python3 -m pytest tests/unit_ci_workflows -q\n"), (
            "不带散文包装的同一句也没被看见 ⇒ 上面那条断言恒真（空断言）"
        )
        live = "#!/usr/bin/env bash\npython3 -m pytest tests/unit_ci_workflows -q\n"
        assert _invocations_in(live), "真调用没被看见 ⇒ 判据恒绿（空断言）"


def installed_baseline(scanned: set[str]) -> set[str]:
    """基线读数（**内存里**的那一份，供「变异真被读到」自证）。"""
    return set(scanned)
