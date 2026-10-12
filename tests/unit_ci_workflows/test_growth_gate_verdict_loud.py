# case_ids: MC-061
"""`growth_gate` 的**判定收尾行**（issue #6774）—— 复用**既有** `--exit-on-block` 作 fail-closed 出口。

## 病灶（本批实证，代价 = 一轮 CI + 一次返工）

包内自查**不允许**跑全量 `verify-all.sh gate`（§27 机器级重活锁；D 口径 = 全量只在批次集成跑一次）
⇒ 包内**只能**直接调 `.github/growth_gate.py`，而它 `blocker_count = 1` 时**退出码仍是 0**
（默认语义：判定只在 `--json-file` 的 `blocker_count` 字段里，CI 的 `pr-check.yml` 正是读 JSON）。
实测：PR #6768 据 `exit 0` 报了「通过」，被 CI 的 `QA Growth Gate` 抓红（job 114625907544）。
⇒ 判定必须**自己出声**：只读最后几行的人也要能拿到真判定。

## 本文件锁什么（每条都能单独变红）

| # | 判据 | 坏形态 ⇒ 红 |
|---|---|---|
| 1 | 有 blocker ⇒ stdout **末段**是判定行，含 `BLOCKERS=<n>` 与数字 | 收尾行被摘掉 / 数字打错 ⇒ 红 |
| 2 | ⚠️ **默认语义不变**（机械锁）：不加开关时 `blocker_count ≥ 1` 仍 **exit 0** | 顺手改成「有 blocker 就非零」⇒ 红（CI 语义被改） |
| 3 | **既有** `--exit-on-block` 双向对照：≥1 ⇒ 非 0；= 0 ⇒ 0 | 开关只单向 / 恒非零 / 恒零 ⇒ 红 |
| 4 | 0 blocker ⇒ 打 ✅ 行，且默认退出码 0 | 只在有 blocker 时打印 ⇒ 红 |
| 5 | 判定行里的数字 == JSON 的 `blocker_count`（**单一数据源**，防双源漂移） | 行的数字与 JSON 各说各话 ⇒ 红 |
| 6 | 端到端**真语料我证**：临时注入一个缺测的生产文件 ⇒ 真跑 `--check-cases` 出现判定行且数字正确；清掉 ⇒ 变 ✅ | 判据 1 只在内存桩上成立（假绿）⇒ 红 |
| 7 | 注入式红证：把收尾行摘掉（从 stdout **内存变异**）⇒ 判据 1 的断言当场红 | 判据 1 是空断言 ⇒ 红 |
| 8 | `CLEAN_FILES` 是**读**来的（== `test_growth_gate_blast_radius.py::HIT_FILES`），且每条路径真在仓内 | 被改回手抄字面量 / 出处为空 / 路径不存在（对照臂空跑）⇒ 红 |

## 边界（照实登记，§19.1）

- 判**接线与语义**（行在不在、数字对不对、退出码对不对），判不了「人有没有真去读那一行」；
- **不改**任何 blocker 的触发条件、**不加**豁免、**不动** `pr-check.yml`（判据 2 就是这条的机械锁）；
- **不新造开关**（issue #6774 的返工口径，铁律 5 复用先于最小实现）：fail-closed 出口 = **既有**
  `--exit-on-block`（`origin/main` 就有，全仓零调用方）；issue 原文提议的 `--fail-on-blocker`
  **已作废**，本文件不引用它（防以后有人照 issue 原文再来加第二个）；
- **定点判据的选取集教训（本单 CI 实测，job 114634842129）**：按**名字前缀**挑同名文件
  （`test_growth_gate_*.py`）会漏掉**别的文件名**下、却会读到你新增文件的类级守卫
  （本单 = `test_gate_coverage_and_same_source.py` 的判据 9，它扫的是面内**所有**文件的
  「注释块 + 模块级字面量集合声明」）⇒ 挑集合时先
  `grep -rl "<你的文件名或符号>" tests/unit_ci_workflows/*.py` 把「会读到你的」守卫一并纳入。
  本文件据此把 `CLEAN_FILES` 的第二份拷贝删掉（改成**读**那一侧）+ 本注释不带「同源/一致」类措辞；
- 预设仓那半边的纪律（「门禁类判据必须读判定字段，不许用退出码判定」写进 `migao-dev-flow`）
  属**另一个仓**，不在本包射程（issue #6774 的边界节）。
"""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PY = REPO_ROOT / ".github" / "growth_gate.py"

#: 「只看最后几行」的人拿到真判定的**唯一出口**（issue #6774 判据 1 的形态）。
#: ⚠️ 判据按**结构**断言（`BLOCKERS=<数字>` + `blocker_count` 字样 + 在末段），
#: 不整行钉死文案 —— 文案可以演进，但「末段有判定行且带数字」这条契约不许丢。
VERDICT_RE = re.compile(r"BLOCKERS=(\d+)")
#: 收尾行必须自报这个字段名（CI 的真值字段），否则读者仍不知道判定该读哪里。
FIELD_NAME = "blocker_count"

#: 真实存在的生产文件，其配套测试在仓内**存在** ⇒ 零 blocker（判据 3/4 的对照臂）。
#: ⚠️ **本文件不写第二份路径拷贝**（初版抄了一份字面量 + 一句「同源口径」注释）—— 那种
#: 「注释里的承诺」没有判据承担：删掉任一侧都不会红（`#5007①` 的形态，实测被 CI 的
#: `test_gate_coverage_and_same_source.py::test_same_source_claims_have_criteria` 判红，job 114634842129）。
#: ⇒ 清单**只从** `.github/scripts` 之外的那一处现有定义读（`test_growth_gate_blast_radius.py`），
#: 结构上不存在会漂的第二份；本注释**刻意不带**「同源 / 一致 / 单一份实现」这类措辞（带了就
#: 会被那台守卫收成「承诺」，从而要求登记判据 —— 那是给**两份实现**用的通道，本处不是两份）。
#: 判据 8（`test_clean_files_come_from_the_blast_radius_module_and_exist`）另钉住「清单是**读**来的
#: 且每条路径真在仓内」。
BLAST_RADIUS_TEST_PY = REPO_ROOT / "tests" / "unit_ci_workflows" / "test_growth_gate_blast_radius.py"


def _load_blast_radius_hit_files():
    """从 `test_growth_gate_blast_radius.py` 现取 `HIT_FILES`（直接读那一侧，不抄字面量）。"""
    spec = importlib.util.spec_from_file_location("blast_radius_hit_files_under_test",
                                                  BLAST_RADIUS_TEST_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.HIT_FILES)


#: 零 blocker 的对照臂（判据 3/4）—— 唯一来源 = 上面那个模块的 `HIT_FILES`。
CLEAN_FILES = _load_blast_radius_hit_files()


def _load_gate():
    """从 `.github/growth_gate.py` 加载被测模块（与既有守卫同一加载法）。"""
    spec = importlib.util.spec_from_file_location("growth_gate_verdict_under_test", GATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_gate(files, json_file, extra=()):
    """在**子进程**里真跑 `growth_gate.py`（拿真退出码；不经任何管道）。

    为什么必须子进程：#6774 的病根正是**退出码**语义 ⇒ 只有真进程的 `returncode` 才是被测对象。
    """
    cmd = [sys.executable, str(GATE_PY), "--repo-root", str(REPO_ROOT),
           "--files", *files,
           "--tech-stack", ".github/tech-stack.yml",
           "--exemptions", ".github/qa-exemptions.yml",
           "--check-cases", ".github/cases",
           "--json", "--json-file", str(json_file),
           *extra]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    return proc


def _last_nonempty_lines(out, n=3):
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return lines[-n:]


def _verdict_line(out):
    """取 stdout **末段**（最后 3 个非空行）里的判定行；取不到 ⇒ None。"""
    hits = [ln for ln in _last_nonempty_lines(out, 3) if VERDICT_RE.search(ln)]
    return hits[-1] if hits else None


def _missing_test_production_file():
    """现取一个**磁盘上不存在**、但真落在 tech-stack 规则射程内的生产文件路径。

    为什么现取而不写死：写死的路径一旦被人补上配套测试（或文件被删），判据 6 会静默失效。
    本函数只读 `.github/tech-stack.yml` 的规则（`classify_file` 的**同一份**规则源）。
    """
    gate = _load_gate()
    tech, err = gate._load_yaml(str(REPO_ROOT / ".github" / "tech-stack.yml"))
    assert not err, f"规则源读取失败 ⇒ 判据无法自证（先修 tech-stack.yml）：{err}"
    modules = tech.get("modules") or []
    test_commands = tech.get("test_commands") or {}
    errors = []
    rules = gate.compile_rules(modules, test_commands, errors)
    assert not errors and rules, f"规则源退化（{errors}）⇒ 缺测门禁整条失效，判据先红"

    import yaml  # 仓内既装依赖（tech-stack 解析同源）

    ex_path = REPO_ROOT / ".github" / "qa-exemptions.yml"
    ex = yaml.safe_load(ex_path.read_text(encoding="utf8")) or {}
    exemptions = ex.get("exemptions") or []

    for i in range(1, 400):
        candidate = f"frontend/admin-web/src/lib/zzz-verdict-loud-probe-{i}.ts"
        if (REPO_ROOT / candidate).exists():
            continue
        res = gate.classify_file(candidate, rules, exemptions, str(REPO_ROOT))
        if res.get("kind") == "block":
            return candidate, res
    raise AssertionError("找不到任何「规则射程内 + 缺配套测试」的生产文件路径 ⇒ 判据 6 无法自证")


# ── 判据 1 + 5：有 blocker ⇒ 末段有判定行，且数字与 JSON 同源 ──

def test_blocked_input_prints_verdict_line_with_matching_number(tmp_path):
    probe, res = _missing_test_production_file()
    missing_test = (REPO_ROOT / probe)
    missing_test.write_text("export const zzzVerdictLoudProbe = 1;\n", encoding="utf8")
    try:
        json_file = tmp_path / "r.json"
        proc = _run_gate([probe], json_file)
        payload = json.loads(json_file.read_text(encoding="utf8"))
        assert payload["blocker_count"] >= 1, (
            f"端到端红证的前置不成立：这个文件本应触发缺测 blocker（分类读数 = {res}）"
            f"⇒ 下面的判定行断言是空真")
        line = _verdict_line(proc.stdout)
        assert line, (
            "🔴 有 blocker 时 stdout 末段**没有**判定行 —— #6774 的病根原样复发"
            f"（只看最后几行的人仍拿不到判定）\n--- 末段 ---\n"
            + "\n".join(_last_nonempty_lines(proc.stdout, 3)))
        assert f"BLOCKERS={payload['blocker_count']}" in line, (
            f"判定行里的数字与 JSON 的 blocker_count 不一致（双源漂移）：行={line!r} "
            f"JSON={payload['blocker_count']}")
        assert FIELD_NAME in line, (
            f"判定行必须自报「判定读哪个字段」（逐字含 {FIELD_NAME}），实得：{line!r}")
        assert proc.returncode == 0, (
            "🔴 默认语义不许变：不给 --exit-on-block 时 blocker ≥ 1 仍须 exit 0"
            f"（CI 读 JSON 判定），实得 returncode={proc.returncode}")
    finally:
        missing_test.unlink()


# ── 判据 7：注入式红证 —— 把判定行摘掉 ⇒ 判据 1 的断言当场红 ──

def test_removing_the_verdict_line_makes_the_assertion_red(tmp_path):
    """判据 1 的**判别力自证**：在内存里删掉那一行 ⇒ 同一断言必须失败。

    为什么不可省：只证「行出现」不排除它来自别处（或断言本身写宽了）⇒ 那是空断言。
    """
    probe, _ = _missing_test_production_file()
    missing_test = REPO_ROOT / probe
    missing_test.write_text("export const zzzVerdictLoudProbe = 1;\n", encoding="utf8")
    try:
        json_file = tmp_path / "r.json"
        proc = _run_gate([probe], json_file)
        real_line = _verdict_line(proc.stdout)
        assert real_line, "前置：真跑必须先有判定行（否则本条红证测的是别的东西）"
        mutated = "\n".join(ln for ln in proc.stdout.splitlines() if ln != real_line)
        assert _verdict_line(mutated) is None, (
            "摘掉判定行后仍能取到判定行 ⇒ 判据 1 的取行逻辑认错了对象（假绿）")
        with_assertion = _verdict_line(proc.stdout)
        assert (with_assertion is not None) != (_verdict_line(mutated) is not None), (
            "判别力自证失败：删与不删得到同一结论 ⇒ 判据 1 是空断言")
    finally:
        missing_test.unlink()


# ── 判据 2 + 3：**既有** `--exit-on-block` 双向对照 + 默认语义的机械锁 ──

def test_exit_on_block_switch_is_bidirectional(tmp_path):
    probe, _res = _missing_test_production_file()
    missing_test = REPO_ROOT / probe
    missing_test.write_text("export const zzzVerdictLoudProbe = 1;\n", encoding="utf8")
    try:
        # ① 默认关：blocker ≥ 1 ⇒ exit 0（判据 2 的机械锁：这就是「不许顺手改 CI 语义」）
        default = _run_gate([probe], tmp_path / "default.json")
        blocked = _run_gate([probe], tmp_path / "blocked.json", extra=["--exit-on-block"])
        # 先读**退出码**，再读 JSON：开关若没接线，argparse 当场 rc=2 且不写 JSON ⇒
        # 反过来读会变成 FileNotFoundError（把「开关不存在」误报成「文件没写出来」）。
        assert default.returncode == 0, (
            f"🔴 默认语义变了：不给开关时 blocker ≥ 1 必须仍 exit 0，实得 {default.returncode}")
        assert blocked.returncode != 0, (
            f"🔴 --exit-on-block 没生效：blocker ≥ 1 时应非 0，实得 {blocked.returncode}"
            f"\n--- stderr ---\n{blocked.stderr[-800:]}")
        p_default = json.loads((tmp_path / "default.json").read_text(encoding="utf8"))
        p_blocked = json.loads((tmp_path / "blocked.json").read_text(encoding="utf8"))
        assert p_default["blocker_count"] >= 1 and p_blocked["blocker_count"] >= 1, (
            "前置：两条都必须真有 blocker（否则下面的对照无意义）")
        assert blocked.returncode == 1, (
            f"非零的具体形态钉在 1（便于调用方区分「判定阻塞」与「脚本崩了 = 2」），"
            f"实得 {blocked.returncode}")
        assert _verdict_line(blocked.stdout), "加开关后判定行仍须在（两态都要能读到判定）"
        assert "--exit-on-block" in _verdict_line(blocked.stdout), (
            "加开关时判定行要写明「想 fail-closed 该加哪个开关」，实得："
            f"{_verdict_line(blocked.stdout)!r}")

        # ② 0 blocker ⇒ 加开关也必须 exit 0（反向对照，防「恒非零」）
        clean_switched = _run_gate(CLEAN_FILES, tmp_path / "clean-switched.json",
                                   extra=["--exit-on-block"])
        clean_default = _run_gate(CLEAN_FILES, tmp_path / "clean-default.json")
        p_clean = json.loads((tmp_path / "clean-switched.json").read_text(encoding="utf8"))
        assert p_clean["blocker_count"] == 0, (
            f"前置：这组文件本应零 blocker，实得 {p_clean['blocker_count']}（{p_clean['blockers']}）")
        assert clean_switched.returncode == 0, (
            f"🔴 --exit-on-block 在 0 blocker 时必须 exit 0，实得 {clean_switched.returncode}")
        assert clean_default.returncode == 0, "0 blocker + 默认档同样须 exit 0"
    finally:
        missing_test.unlink()


# ── 判据 4：0 blocker ⇒ ✅ 行 ──

def test_clean_input_prints_pass_line(tmp_path):
    proc = _run_gate(CLEAN_FILES, tmp_path / "clean.json")
    payload = json.loads((tmp_path / "clean.json").read_text(encoding="utf8"))
    assert payload["blocker_count"] == 0, f"前置不成立：{payload['blockers']}"
    line = _verdict_line(proc.stdout)
    assert line, (
        "0 blocker 时也要出声（否则「没有判定行」会被读成「没跑到」）\n--- 末段 ---\n"
        + "\n".join(_last_nonempty_lines(proc.stdout, 3)))
    assert "BLOCKERS=0" in line, f"✅ 档的判定行数字必须是 0，实得：{line!r}"
    assert FIELD_NAME in line, f"✅ 档同样要自报判定字段名，实得：{line!r}"
    assert "❌" not in line, f"✅ 档不许带 ❌ 形态（否则读者读成阻塞），实得：{line!r}"
    assert proc.returncode == 0


# ── 判据 6：端到端真语料我证 —— 沿用 `--check-cases` 的 CI 同参数 ──

def test_end_to_end_with_real_corpus_check_cases(tmp_path):
    """与 issue #6774 的复现命令同参数（`--check-cases .github/cases`），真进程真退出码。"""
    probe, _ = _missing_test_production_file()
    missing_test = REPO_ROOT / probe
    json_file = tmp_path / "ci-like.json"
    try:
        missing_test.write_text("export const zzzVerdictLoudProbe = 1;\n", encoding="utf8")
        blocked = _run_gate([probe], json_file)
        p = json.loads(json_file.read_text(encoding="utf8"))
        assert p["blocker_count"] >= 1, "注入生效自证：缺测必须被判成 blocker（否则红证是空跑）"
        assert re.search(rf"BLOCKERS={p['blocker_count']}\b", blocked.stdout), (
            f"CI 同参数下未打判定行（blocker_count={p['blocker_count']}）\n"
            f"--- 末段 ---\n" + "\n".join(_last_nonempty_lines(blocked.stdout, 3)))
        assert blocked.returncode == 0, "默认档仍 exit 0（CI 按 JSON 判定）"
    finally:
        missing_test.unlink()

    clean_json = tmp_path / "after.json"
    after = _run_gate(CLEAN_FILES, clean_json)
    p_clean = json.loads(clean_json.read_text(encoding="utf8"))
    assert p_clean["blocker_count"] == 0 and "BLOCKERS=0" in after.stdout, (
        "清掉注入文件后必须变成 ✅ 档（判据 6 的另一半：注入与还原的读数都要在）")


# ── 判据 8：对照臂自身不能空跑（清单**真读到了**那一侧，且路径真在仓内）──

def test_clean_files_come_from_the_blast_radius_module_and_exist():
    """`CLEAN_FILES` 是**读到的**（不是本文件抄的），且每一条都真在仓内。

    ## 为什么需要这一条（CI 判红实测，job 114634842129）

    初版把这份路径清单**抄**成第二份字面量、并在注释里声称与
    `test_growth_gate_blast_radius.py::HIT_FILES` 一致 ⇒ 被类级守卫
    `test_gate_coverage_and_same_source.py::test_same_source_claims_have_criteria`（判据 9）
    判红：承诺写在注释里，删掉任一侧实现都不会红（`#5007①` 的形态）。
    ⇒ 本文件的出口 = **不写第二份**：清单只在 `CLEAN_FILES = _load_blast_radius_hit_files()`
    一处取用（结构上不可能漂）；本条再钉住两件事：① 读数**非空且真来自那一侧**（不是本文件的
    字面量、也不是空列表）；② 每条路径在仓内**存在**（否则判据 3/4 的对照臂退化成「拿不存在的
    文件跑门禁」= 空跑）。

    ## 判别力（怎么红）

    - 把 `CLEAN_FILES` 改回手抄字面量 ⇒ 与 `_load_blast_radius_hit_files()` 的读数不再相等 ⇒ 红；
    - 那一侧的 `HIT_FILES` 改成空 / 指向不存在的路径 ⇒ 红（两条断言各管一头）。
    """
    live = _load_blast_radius_hit_files()
    assert live, f"从 {BLAST_RADIUS_TEST_PY.name} 取到的 HIT_FILES 为空 ⇒ 对照臂无对象（红）"
    assert CLEAN_FILES == live, (
        "CLEAN_FILES 不是该模块 `HIT_FILES` 的读数（被改回手抄字面量了？）——\n"
        f"  CLEAN_FILES = {CLEAN_FILES}\n  HIT_FILES   = {live}")
    missing = [f for f in live if not (REPO_ROOT / f).is_file()]
    assert not missing, (
        f"清单里的路径在仓内不存在 ⇒ 判据 3/4 的对照臂变成空跑：{missing}")

