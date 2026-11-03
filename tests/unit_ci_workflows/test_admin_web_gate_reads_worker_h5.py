# case_ids: MC-170
"""门禁触发面必须覆盖**本腿断言真读的跨包面**（issue #6684）。

## 病（实测形态，不是推断）

`pr-check.yml` 的 `admin-web-test` 腿有一条**跨包断言**：
`frontend/admin-web/tests/unit/lib/copy-no-markdown-emphasis.test.ts` 的 `SRC_DIRS` 除本包 `src` 之外
还扫 `../worker-h5/src`（商家可见文案的 markdown 强调必须经渲染器上屏，issue #5194）。
而本腿的路径门控只覆盖 `frontend/admin-web/**` + 自己 ⇒ **纯 worker-h5 的 PR 整段跳过它**：
`#6675`（只改 `frontend/worker-h5/**`）在 PR 上绿、合并后 main 上红（`machine.mjs` 的模板串里带
字面 markdown 强调），红只交给**下一个**碰 admin-web 的 PR —— 归因成本极高，且那时"凶手"早已合并。

⇒ 「门控面声明」与「断言真读的面」脱节，是本仓反复踩的同一族（`test_gate_coverage_and_same_source.py`
的 #4177）。本文件把**这一条腿**的 TS 断言面从**源码现取**，不再靠人工声明（那一层的缺口登记在
`declaration_gate_registry.json` 的 `unfixed` 里：「TS/JS 门禁的断言面自动发现未实装」）。

## 本判据锁什么（每条都能单独变红）

| # | 判据 | 红证（注入式） |
|---|---|---|
| 1 | **读取面现取**：从守卫源码的 `SRC_DIRS` 现取仓内相对目录；每条都必须是**真实存在**的目录，且**至少一条在 `frontend/admin-web` 之外** | 把 `SRC_DIRS` 改名/删掉 ⇒ 红（口径漂移，不许静默空跑）；跨包面被删 ⇒ 红并要求**同一提交**里显式撤掉门禁面（不许悄悄收窄） |
| 2 | **触发面覆盖**（= #6684 的实例判据）：每条跨包读取面都必须被 `Detect admin-web changes` 的**现取谓词**命中 | 把 `frontend/worker-h5/src/` 从谓词里删掉 ⇒ 红并**具名**报出是哪条面 |
| 3 | **登记**：每条跨包读取面必须登记进 `declaration_gate_registry.json` 的 `must_cover` | 删掉登记 ⇒ 红（缺口不许匿名存在） |
| 4 | **负控（原有面不许丢）**：本腿仍必须被自己的模块 `frontend/admin-web` 与**自身定义** `pr-check.yml` 触发 | 删掉任一 ⇒ 红（整条腿永不运行 = 假绿，比红更糟） |
| 5 | **判别力自证**（内存变异，不碰真文件） | 「只覆盖本包」的谓词 ⇒ 判据 2 必红并具名；「只覆盖 worker-h5」的谓词 ⇒ 判据 4 必红；未注入 ⇒ 两条都不报 |
| 6 | **被证伪的声明不得以未标注形态存在**：那句已被 issue #6684 证伪的话若仍出现，其所在注释块必须带「已被证伪」标注 + 单号 | 去掉标注 ⇒ 红；带标注（= 保留"当初为什么这么写"的痕迹）⇒ 不红（对照读数） |
| 7 | **反空跑（教训必须留在原地）**：`Detect admin-web changes` 步的注释必须写明「曾被漏掉的那条面 + 已被证伪 + 单号」 | 只把假话删掉、不留痕迹 ⇒ 红（下一个人会用同一套推理再写一遍） |

## 边界（照实登记，别把本判据读成覆盖面更大的东西）

- 只认守卫里 `const SRC_DIRS = [...]` 这一种声明形态 + `join(process.cwd(), '…')` 这一种构造式
  （该守卫就是这么写的）。别的写法**不是**静默略过：判据 1 会先因「解析不到面 / 面非真实目录」红。
- 只裁 `pr-check.yml::admin-web-test` 这一条腿。其它腿的 TS 断言面仍是**人工声明**
  （`declaration_gate_registry.json` 的 `unfixed` 已登记该缺口）—— 本文件**不**声称覆盖它们。
- 判不了「这条跨包断言本身该不该存在」（那是 issue #5194 的覆盖面问题）。本判据只保证
  **它读了什么 ⇒ 门禁就按什么触发**。
- 判据 6/7 判的是**文本形态**（标注记号 / 被漏掉的面 / 单号在不在），判不了「有没有出现**新**的假断言」——
  新假断言的机械兜底是判据 1~3（声明的面 ⇄ 触发面 ⇄ 断言真读的面）。

判据 = 本文件；一键复算：
`python3 -m pytest tests/unit_ci_workflows/test_admin_web_gate_reads_worker_h5.py -q -s`
"""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW_REL = ".github/workflows/pr-check.yml"
WORKFLOW = REPO / WORKFLOW_REL
JOB = "admin-web-test"
DETECT_STEP = "Detect admin-web changes"
#: 该腿的执行根（`vitest` root / `npm ci` 的 cwd）—— `SRC_DIRS` 里的 `process.cwd()` 就是它。
GUARD_CWD = "frontend/admin-web"
GUARD_REL = "frontend/admin-web/tests/unit/lib/copy-no-markdown-emphasis.test.ts"
REGISTRY = REPO / "tests/unit_ci_workflows/declaration_gate_registry.json"
GATE_ID = "pr-check-admin-web-tests"
#: 负控面：本腿自己的模块 + 本腿自己的定义（原谓词里本来就有的两条，一条都不许丢）。
OWN_PATHS = ("frontend/admin-web", WORKFLOW_REL)

#: `const SRC_DIRS = [ … ]`（守卫的唯一扫描面声明；改名/删除 ⇒ 判据 1 红，不静默空跑）
SRC_DIRS_BLOCK = re.compile(r"const\s+SRC_DIRS\s*=\s*\[(.*?)\]", re.S)
#: `join(process.cwd(), '…')` —— 该守卫把扫描面写成这种构造式；段按 `process.cwd()`（= `GUARD_CWD`）解析。
JOIN_CPWD = re.compile(r"join\(\s*process\.cwd\(\)((?:\s*,\s*'(?:[^'\\]|\\.)*')+)\s*\)")
STR_LIT = re.compile(r"'((?:[^'\\]|\\.)*)'")
#: Detect 步里的 `grep -E '<谓词>'`（**现取**，不从登记册读 —— 登记册只承担「逐字同源」，另有一份判据）
GREP_E = re.compile(r"grep\s+-E\s+'([^']+)'")

#: 已被 issue #6684 证伪的那句原文（**逐字**；判据 6 只在它仍出现时要求带标注）
REFUTED_CLAIM = "不存在「改了仓内别处而本腿该跑」的形态"
#: 标注记号：出现这句原文的注释块必须带它 + 单号（否则后来者仍会照它推理）
REFUTATION_MARKER = "已被证伪"
REFUTATION_ISSUE = "#6684"
#: 曾被漏掉的那条面（判据 7 要求它在门控步的注释里**逐字**出现 —— 教训不许被"整理"掉）
MISSED_FACE = "frontend/worker-h5/src"


# ══════════════════════════════════════════════════════════════════════════════
# 一、现取：守卫的扫描面 / 本腿的触发谓词（全部结构化读，不按文件名猜）
# ══════════════════════════════════════════════════════════════════════════════


def _detect_step_run() -> str:
    """`Detect admin-web changes` 步的 `run` 原文（YAML 结构读，**不**全文 grep —— 注释里提一句不算）。"""
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = (data.get("jobs") or {}).get(JOB, {}).get("steps") or []
    step = next((s for s in steps if s.get("name") == DETECT_STEP), None)
    if step is None:
        raise AssertionError(f"{WORKFLOW_REL} 的 job `{JOB}` 里找不到步骤 `{DETECT_STEP}`（被改名/删除？）")
    run = str(step.get("run") or "")
    assert run, f"步骤 `{DETECT_STEP}` 的 `run` 为空 ⇒ 门控没有实现（判据会在空串上恒真）"
    return run


def live_predicate() -> str:
    """本腿触发谓词的**现取原文**（来自 workflow，不是登记册）。"""
    found = GREP_E.findall(_detect_step_run())
    assert len(found) == 1, (
        f"`{DETECT_STEP}` 里应恰有 1 条 `grep -E '<谓词>'`，现取 {len(found)} 条：{found!r}"
        " —— 门控实现变形 ⇒ 本判据的取数面失效，必须同批校准（不许静默空跑）"
    )
    return found[0]


def scan_dirs() -> set[str]:
    """守卫 `SRC_DIRS` 里的扫描面 → **仓库相对**目录（`process.cwd()` = `GUARD_CWD`）。"""
    text = (REPO / GUARD_REL).read_text(encoding="utf-8")
    block = SRC_DIRS_BLOCK.search(text)
    if block is None:
        raise AssertionError(
            f"`{GUARD_REL}` 里找不到 `const SRC_DIRS = [...]` —— 守卫的扫描面声明变形/被删 ⇒ 本判据取数面失效"
            "（改它的同时必须校准本判据与门禁面；不许让判据静默空跑）"
        )
    out: set[str] = set()
    for call in JOIN_CPWD.finditer(block.group(1)):
        segs = STR_LIT.findall(call.group(1))
        if segs:
            out.add(posixpath.normpath(posixpath.join(GUARD_CWD, *segs)))
    return out


def _gate_entry() -> dict:
    gates = json.loads(REGISTRY.read_text(encoding="utf-8"))["gates"]
    entry = next((g for g in gates if g.get("id") == GATE_ID), None)
    if entry is None:
        raise AssertionError(f"登记册里没有门禁 `{GATE_ID}`（被改名/删除？登记册必须与现取双向相符）")
    return entry


def _covers(predicate: str, path: str) -> bool:
    """该谓词是否覆盖 `path`（目录按 `<path>/__probe__` 探针测；口径与既有判据同款）。"""
    rx = re.compile(predicate)
    return bool(rx.search(path + "/__probe__") or rx.search(path))


def _is_own(path: str) -> bool:
    return path == GUARD_CWD or path.startswith(GUARD_CWD + "/")


def cross_package(dirs: set[str]) -> list[str]:
    """`frontend/admin-web` 之外的读取面（= 本腿只按自己的模块门控时会被漏掉的那些）。"""
    return sorted(d for d in dirs if not _is_own(d))


# ══════════════════════════════════════════════════════════════════════════════
# 二、纯函数判据（红证与判别力自证都喂它，不碰真文件）
# ══════════════════════════════════════════════════════════════════════════════


def coverage_problems(predicate: str, dirs: set[str]) -> list[str]:
    """跨包读取面是否被 `predicate` 覆盖（**空 ⇒ 无问题**，每条问题都具名）。"""
    return [
        f"`{d}` 是本腿断言**真读**的面，但 `{DETECT_STEP}` 的触发谓词不覆盖它 ⇒ 改它不会跑本腿"
        "（#6684 形态：PR 上绿、合并后 main 上红，红只交给下一个改 admin-web 的 PR）"
        for d in cross_package(dirs)
        if not _covers(predicate, d)
    ]


def own_module_problems(predicate: str, own_paths: tuple[str, ...] = OWN_PATHS) -> list[str]:
    """负控：本腿自己的模块 / 自身定义是否仍被触发（丢了 = 整条腿永不运行）。"""
    return [
        f"`{p}` 不再被触发谓词命中 ⇒ 本腿在自己的模块上**永不运行**（假绿，比红更糟）"
        for p in own_paths
        if not _covers(predicate, p)
    ]


def _normalize(text: str) -> str:
    """比较口径：去掉引号形态与空白（`「」` 与 `『』` 是同一句话的两种**转述**写法 —— 实测踩过：
    本判据首版逐字比 `「…」`，而 workflow 里引的是 `『…』` ⇒ 判据在真文件上**恒绿**（空断言））。"""
    return re.sub(r"[\s「」『』]", "", text)


def missing_trace_tokens(run: str) -> list[str]:
    """门控步注释里**缺**的教训记号（空 ⇒ 无问题）。纯函数：判据 7 与它的红证共用。"""
    normalized = _normalize(run)
    return [tok for tok in (MISSED_FACE, REFUTATION_MARKER, REFUTATION_ISSUE) if _normalize(tok) not in normalized]


def unannotated_refutations(lines: list[str]) -> list[int]:
    """出现「被证伪的那句原文」而所在注释块**没有**标注的 1-based 行号（空 ⇒ 无问题）。

    注释块 = 上下连续以 `#` 开头的行；标注 = 块内同时出现 `已被证伪` 与单号。
    """
    needle = _normalize(REFUTED_CLAIM)
    bad: list[int] = []
    for i, line in enumerate(lines):
        if needle not in _normalize(line):
            continue
        start, end = i, i
        while start > 0 and lines[start - 1].lstrip().startswith("#"):
            start -= 1
        while end + 1 < len(lines) and lines[end + 1].lstrip().startswith("#"):
            end += 1
        block = _normalize("\n".join(lines[start : end + 1]))
        if _normalize(REFUTATION_MARKER) not in block or REFUTATION_ISSUE not in block:
            bad.append(i + 1)
    return bad


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据（每条都能单独变红；红证 = 本文档表里的注入方式）
# ══════════════════════════════════════════════════════════════════════════════


def test_scan_face_is_parsed_from_the_guard_source() -> None:
    """判据 1：读取面现取，且面是真实的、含跨包面（反空跑）。"""
    dirs = scan_dirs()
    cross = cross_package(dirs)
    print(f"守卫 `{GUARD_REL}` 的 SRC_DIRS 现取 = {sorted(dirs)}（跨包面 = {cross}）")
    assert dirs, f"`{GUARD_REL}` 的 `SRC_DIRS` 解析出 0 个目录 ⇒ 判据在空集上恒真（空断言）"
    missing = sorted(d for d in dirs if not (REPO / d).is_dir())
    assert not missing, (
        f"`SRC_DIRS` 里的这些面在仓内**不存在**：{missing} ⇒ 要么守卫写错，要么本判据的解析口径漂了"
        f"（守卫以 `{GUARD_CWD}` 为 cwd，`join(process.cwd(), '..', 'worker-h5', 'src')` = `frontend/worker-h5/src`）"
    )
    assert cross, (
        f"`SRC_DIRS` 里已没有任何 `{GUARD_CWD}` 之外的扫描面 —— 本判据的业务对象消失。"
        "若**有意**把跨包面搬走（例如搬到 worker-h5 自己的腿），必须在**同一提交**里："
        f"① 从 `{WORKFLOW_REL}` 的 `{DETECT_STEP}` 谓词删掉该面并同改登记册 "
        "② 删掉本文件（或改写它的对象），③ 在 PR body 写明「覆盖面搬家，不是取消覆盖」"
    )


def test_live_trigger_covers_cross_package_scan_face() -> None:
    """判据 2（= #6684 的实例判据）：跨包读取面必须被**现取谓词**命中。"""
    predicate = live_predicate()
    dirs = scan_dirs()
    print(f"现取谓词 = {predicate!r}")
    print(f"跨包读取面 = {cross_package(dirs)}")
    problems = coverage_problems(predicate, dirs)
    assert not problems, (
        "门控面与断言真读的面脱节（issue #6684）：\n"
        + "\n".join(f"  {p}" for p in problems)
        + f"\n修法：把该面**精确**加进 `{DETECT_STEP}` 的谓词（并同改 "
        "`tests/unit_ci_workflows/declaration_gate_registry.json` 的 `predicate` + `must_cover`）。"
        "\n⛔ 不许改成 workflow 级 `paths:`（required check 会卡 Waiting 且**不会变红**）；"
        "\n⛔ 不许删掉那条跨包断言来换绿。"
    )


def test_cross_package_scan_face_is_registered() -> None:
    """判据 3：跨包读取面必须登记进登记册（缺口不许匿名存在）。"""
    dirs = scan_dirs()
    registered = {str(e.get("path")) for e in _gate_entry().get("must_cover") or []}
    cross = cross_package(dirs)
    print(f"登记册 must_cover = {sorted(registered)}")
    missing = [d for d in cross if d not in registered]
    assert not missing, (
        f"这些跨包读取面没登记进 `{GATE_ID}` 的 `must_cover`：{missing} ⇒ "
        "登记册是「门控真的覆盖它」的唯一声明面；不登记就没人机械核它对不对（#4177 形态）"
    )


def test_leg_still_triggers_on_its_own_module() -> None:
    """判据 4（负控）：原有触发面一条都不许丢（自己模块 + 自身定义）。"""
    predicate = live_predicate()
    problems = own_module_problems(predicate)
    assert not problems, "\n".join(problems) + f"\n现取谓词 = {predicate!r}"


def test_refuted_claim_is_not_left_unannotated() -> None:
    """判据 6：被证伪的那句话若仍在，必须带「已被证伪 + 单号」标注（保留教训，不许冒充事实）。"""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    bad = unannotated_refutations(lines)
    assert not bad, (
        f"`{WORKFLOW_REL}` 第 {bad} 行的注释块里出现**已被 issue #6684 证伪**的断言，却没有 "
        f"`{REFUTATION_MARKER}` + `{REFUTATION_ISSUE}` 标注：\n  {REFUTED_CLAIM}\n"
        "它陈述的事实在仓内已不成立（本腿的跨包断言真读 `frontend/worker-h5/src`）⇒ "
        "要么改写成成立的事实，要么标注为历史并说明「当初为什么这么写 / 为什么被证伪」。"
    )


def test_refutation_trace_is_kept_in_the_gate_comment() -> None:
    """判据 7（反空跑）：门控步的注释必须保留「漏过哪条面 + 已被证伪 + 单号」这三样。

    为什么需要它：判据 6 只在「那句话仍被引用」时才有对象 —— 若有人把整段注释**删干净**
    （= 把教训一起删掉），判据 6 会绿而在空集上恒真。工作单 ① 的原文要求是
    「改写成**成立的事实**并保留『当初为什么这么写』的痕迹，不要简单删」⇒ 这条把它变成机械读数。
    """
    run = _detect_step_run()
    missing = missing_trace_tokens(run)
    assert not missing, (
        f"`{DETECT_STEP}` 步的注释里缺少 {missing} ⇒ 门控面声明既没写清「哪条面曾被漏掉」，"
        "也没写清「为什么被证伪 / 被谁证伪」：只删掉假话而不留痕迹，下一个人会用同一套推理再写一遍"
        "（issue #6684）。注释里必须出现：被漏掉的面、`已被证伪`、issue 号。"
    )


class TestDiscriminatingPower:
    """判据 5：判别力自证（内存变异；**不碰真文件**）。"""

    def test_unmutated_readings_are_clean(self) -> None:
        predicate = live_predicate()
        dirs = scan_dirs()
        assert coverage_problems(predicate, dirs) == []
        assert own_module_problems(predicate) == []

    def test_dropping_the_cross_package_face_turns_the_coverage_judgement_red(self) -> None:
        """红证 ④：把触发集里的 worker-h5 面删掉 ⇒ 判据 2 必红并具名。"""
        dirs = scan_dirs()
        cross = cross_package(dirs)
        assert cross, "没有跨包面 ⇒ 这条红证无从注入（判据 1 本来就会先红）"
        problems = coverage_problems(f"^({GUARD_CWD}/)", dirs)
        assert problems, "「只覆盖本包」的谓词竟然没有任何问题 ⇒ 判据 2 是空断言"
        assert all(d in "\n".join(problems) for d in cross), f"判红必须**具名**每一条面，现取 = {problems}"

    def test_dropping_the_own_module_face_turns_the_negative_control_red(self) -> None:
        """判据 4 的红证：把 admin-web 面删掉 ⇒ 负控必红（整条腿永不运行）。"""
        narrowed = "^(frontend/worker-h5/src/|\\.github/workflows/pr-check\\.yml$)"
        problems = own_module_problems(narrowed)
        assert problems and "frontend/admin-web" in problems[0], f"负控没判红 ⇒ 它不是判据：{problems}"

    def test_unannotated_refutation_is_detectable_in_memory(self) -> None:
        """判据 6 的正控 + 对照：±标注、以及**引号形态不同**的转述，读数都必须正确。

        ⚠️ 引号那一组不是凑数：本判据首版逐字比 `「…」`，而 workflow 里引的是 `『…』`
        ⇒ 在真文件上**恒绿**（空断言）。同一句话的两种转述写法必须都判得出来。
        """
        bare = ["# 触发面说明", f"#    ⇒ {REFUTED_CLAIM}。", "HITS=x"]
        annotated = [
            "# 触发面说明",
            f"#    ⚠️ 此处原文写的是「{REFUTED_CLAIM}」——{REFUTATION_MARKER}（issue {REFUTATION_ISSUE}）",
            "HITS=x",
        ]
        swapped = REFUTED_CLAIM.replace("「", "『").replace("」", "』")
        requoted = ["# 触发面说明", f"#    ⇒ {swapped}。", "HITS=x"]
        assert unannotated_refutations(bare) == [2], "未标注形态必须判红（且具名行号）"
        assert unannotated_refutations(requoted) == [2], "换一套引号的同一句话同样是**未标注**的假断言"
        assert unannotated_refutations(annotated) == [], "带标注形态不得判红（否则教训没法留在原地）"

    def test_trimming_the_trace_from_the_gate_comment_is_detectable(self) -> None:
        """判据 7 的红证：把注释里的「被漏掉的面」整段删掉 ⇒ 必须红（教训不许被"整理"掉）。"""
        run = _detect_step_run()
        assert missing_trace_tokens(run) == [], "真树必须已带齐教训记号（否则判据 7 的真实对象不在）"
        trimmed = run.replace(MISSED_FACE, "（这条面）")
        assert missing_trace_tokens(trimmed) == [MISSED_FACE], f"变异没判红 ⇒ 判据 7 是空断言：{MISSED_FACE}"
