# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI / 仓库结构类 L0 不变式统一挂 MC-012 ——
#   本判据与本目录 `test_gate_coverage_and_same_source.py` / `test_case_prose_test_names.py` 同族：
#   守的是「仓库这个**台账**与源码实际状态是否一致」，不新造用例族、不改任何既有门禁的通过条件。）
r"""存量「已臃肿」的**只许向下**棘轮（issue #8166）。

## 病（一类缺陷，不是一个缺陷）

仓库有《最少代码》（docs/wiki/Code-Minimalism.md）管「**怎么**写少」，但**没有机制管「已经写多了」**：
没有任何东西会在一行行往上长的时候变红。2026-10-30 现取（origin/main `456e0632a`）：
`backend/admin-api/src/main` + `backend/ai-agent-service/app` + `frontend/*/src` 共 **1369** 个源文件
/ **298460** 行，其中 **12** 个文件已越过 **2000** 行（最大 **6913** 行），另有 **46** 个在 800–2000 行。
没有棘轮 ⇒ 删下去半年就长回来（近 400 提交里 CHANGELOG 改 210 次、生成物改 182 次即证据）。

## 真值源（判据**读**它，不重新计算阈值）

| 文件 | 回答什么 |
|---|---|
| `tests/unit_ci_workflows/loc_freeze_ledger.json` | 存量 **>2000 行**的文件冻结清单：`{path, lines, frozen_at}` + `thresholds{freeze,new_file}` + `frozen_count_max`（条数上限）。**逐条行数只许下降、条数只许减少**；冻结清单**被清空 ⇒ 红**（fail-closed） |
| `tests/unit_ci_workflows/loc_ratchet_exemptions.json` | 存量**已越 800 线**文件的登记册（含已冻结的那一档，现取 **58** 条）：`{path, reason, date}` × N + `declared_count`（条数**现取**，判据里不硬编码）。台账为空**合法**；**已不存在的文件 / 已跌破 800 线 ⇒ 红**（只许缩短） |

## 判据（每条都能单独变红；红证见 `test_discriminating_power_*`）

| # | 判据 | 变红的形态 |
|---|---|---|
| 1 | **冻结文件行数上涨 ⇒ 红** | 报 `path` + 现值 + 冻结值 + 增量 + 可复制命令（`wc -l <path>` / `git show origin/main:<path> \| wc -l`）——追加**一行**就红 |
| 2 | **冻结清单条数只许减少** | 现取条数 > `frozen_count_max` ⇒ 红（往清单里塞新文件不是出口）；删条目 ⇒ 绿；清空 ⇒ 红（判据 4） |
| 3 | **新增源码文件 ≥800 行且未登记 ⇒ 红** | 源码面（`backend/admin-api/src/main/**/*.java`、`backend/ai-agent-service/app/**/*.py`、`frontend/*/src/**/*.ts{,x}`）里任何 **≥800 行**、既不在冻结清单也不在豁免台账的文件 ⇒ 红；登记豁免（带 `reason` + `date` + 同步 `declared_count`）⇒ 绿 |
| 4 | **豁免台账只许缩短** | 豁免条目指向**已不存在**的文件 ⇒ 红（销账即删）；文件已**跌破 800 线** ⇒ 红（本表是存量上限，不是永久白名单）；`declared_count` 与现取条数不符 ⇒ 红 |
| 5 | **冻结清单被清空 ⇒ 红**（fail-closed） | `frozen: []` ⇒ 红（「没东西可判」不是通过）；台账缺失 / JSON 坏 / 扫描面为空 ⇒ 同样红 |
| 6 | **阈值只许收紧** | 台账 `thresholds` 被放宽（`freeze > 2000` 或 `new_file > 800`）⇒ 红；判据侧另有镜像常量 `FREEZE_THRESHOLD_MIRROR` / `NEW_FILE_THRESHOLD_MIRROR` ⇒ 放宽要同时改两处且数字变大（diff 里看得见） |
| 7 | **删条目 ⇒ 绿**（只许缩短的方向自证） | 把某条冻结项从清单里删掉（其文件仍在扫描面、仍在豁免登记册）⇒ **不红**；**同时**把豁免登记也删掉 ⇒ 红（≥800 未登记）——两个方向都钉住 |
| 8 | **判别力自证（临时目录，真文件真台账）** | 四个坏形态各自判红：① 往冻结文件**追加一行** ② 新建 **900** 行文件 ③ 清空冻结清单 ④ 豁免指向幽灵文件；另有全量真扫描一个 `< 10 秒` 的读数 |

## 边界（照实登记，**不是**「已全覆盖」）

- **不自动改代码**：判红只给出口（拆分 / 下沉复用件 / 显式登记 + 理由），删除与拆分由人做；
- **存量 800–2000 行的文件继续增长不在本判据面内**（本判据只拦「新增文件 ≥800」与「已冻结文件每一行的增长」，
  以及「跌破 800 未销账」）；这条缺口**没有**被登记成「已覆盖」——它是本单刻意的射程（issue #8166 的门槛口径），
  将来若要把存量 800+ 文件也逐行钉住，应另开单（会把一次 `+1` 行改动读到红，与本单的成本口径不同）；
- **判的是行数，不是复杂度**：一行 400 字符的压缩代码与 400 行清晰代码同权；行数只是**代理指标**；
- **扫描面是白名单目录**，只含三个源码根；`tests/` / `acceptance/` / `node_modules` / `.venv` / `target` /
  `__pycache__` / `.next` / 生成物后缀（`.d.ts` / `*.gen.ts` / `*.generated.*` / `*.min.*`）**不在面内**，
  且 `test_scan_surface_excludes_generated_and_tests` 逐条自证（扫进去 = 红）；
- **与 `verify-all.sh` 的关系**：随 `tests/unit_ci_workflows` 常规执行，**不新增 required check**，
  也不改任何既有门禁的通过条件（本单只新增 1 个判据 + 2 个数据文件）；
- 行数口径与 `wc -l` **逐字一致**（数 `\n`），所以报错里的复算命令是可执行的、读数可直接对照。
"""
from __future__ import annotations

import json
import re
import shlex
import tempfile
import time
from pathlib import Path
from typing import Mapping, Sequence

REPO = Path(__file__).resolve().parents[2]
LEDGER_PATH = Path(__file__).with_name("loc_freeze_ledger.json")
EXEMPTIONS_PATH = Path(__file__).with_name("loc_ratchet_exemptions.json")

#: 阈值**镜像**（真值源仍是台账的 `thresholds`；这里是「不许静默放宽」的第二把锁）。
FREEZE_THRESHOLD_MIRROR = 2000
NEW_FILE_THRESHOLD_MIRROR = 800

#: 冻结清单**条数上限**的镜像（「条数只许减少」：删条目 ⇒ 绿；加条目 ⇒ 红，除非同批显式抬高本上限）。
FROZEN_COUNT_MAX_MIRROR = 12

#: 源码面（**白名单**目录）—— 扫描只认这三处，不遍历 `tests/` / `acceptance/` / 依赖树。
SCAN_ROOTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("backend/admin-api/src/main", (".java",)),
    ("backend/ai-agent-service/app", (".py",)),
    ("frontend/*/src", (".ts", ".tsx")),
)

#: 目录级剪枝（任何一段命中即跳过；依赖 / 构建产物 / 缓存）。
EXCLUDED_DIR_NAMES = frozenset({
    "node_modules", ".venv", "venv", "target", "__pycache__", ".next", "dist", "build",
    "coverage", ".turbo", ".git", "generated",
})

#: 生成物后缀（**不是**手写源码；现取 0 命中，登记在这里是为了将来生成物长到 800 行也不误判）。
GENERATED_SUFFIXES = (".d.ts", ".gen.ts", ".generated.ts", ".min.ts", ".min.tsx", ".bundle.ts")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_THRESHOLDS = {"freeze": FREEZE_THRESHOLD_MIRROR, "new_file": NEW_FILE_THRESHOLD_MIRROR}

#: 报错里给「可复制命令」时用的台账路径（相对仓库根，`git show origin/main:<path>` 可直接跑）。
LEDGER_REL = "tests/unit_ci_workflows/loc_freeze_ledger.json"
EXEMPTIONS_REL = "tests/unit_ci_workflows/loc_ratchet_exemptions.json"


# ══════════════════════════════════════════════════════════════════════════════════════
# 扫描面（快：只走 git 跟踪的白名单目录，1369 个文件 ≈ 0.3 秒；**不**遍历 tests/acceptance/依赖）
# ══════════════════════════════════════════════════════════════════════════════════════


def _wc_l(path: Path) -> int:
    """与 `wc -l` **逐字一致**的行数（数 `\\n`；末行无换行不算一行）。"""
    return path.read_bytes().count(b"\n")


def scan_source_files(
    repo: Path,
    scan_roots: Sequence[tuple[str, tuple[str, ...]]] = SCAN_ROOTS,
) -> dict[str, int]:
    """扫描源码面 → `{仓库相对路径: 行数}`。**扫描面为空 ⇒ 抛错**（fail-closed，不是「没东西可判」）。"""
    files: dict[str, int] = {}
    roots_seen = 0
    for pattern, suffixes in scan_roots:
        for root in sorted(repo.glob(pattern)):
            if not root.is_dir():
                continue
            roots_seen += 1
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(repo).as_posix()
                if any(part in EXCLUDED_DIR_NAMES for part in rel.split("/")):
                    continue
                name = path.name
                if not name.endswith(suffixes) or name.endswith(GENERATED_SUFFIXES):
                    continue
                files[rel] = _wc_l(path)
    if roots_seen == 0:
        raise AssertionError(
            "源码面**一个根都没解析到**（fail-closed）：SCAN_ROOTS 的 glob 全部落空 ⇒ "
            "本判据无从判起，不许静默通过。复算：git ls-files | grep -E 'src/main|ai-agent-service/app|/src/'"
        )
    if not files:
        raise AssertionError(
            "源码面扫描到 **0 个文件**（fail-closed）：目录改名 / 扩展名口径漂移都会长成这样。"
            "复算：git ls-files | wc -l"
        )
    return files


def read_json(path: Path) -> dict:
    """读台账；缺失 / 坏 JSON / 顶层不是对象 ⇒ 抛错（fail-closed，不是「无需登记」）。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AssertionError(f"台账不存在：{path} —— 本判据 fail-closed（缺台账 = 棘轮无人管）") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"台账不是合法 JSON：{path} —— {exc}") from exc
    if not isinstance(data, dict):
        raise AssertionError(f"台账顶层必须是对象：{path} —— 现取 {type(data).__name__}")
    return data


# ══════════════════════════════════════════════════════════════════════════════════════
# 判定本体（纯函数：喂内存 / 临时目录夹具也能跑 —— 判别力自证与真语料共用**同一份**逻辑）
# ══════════════════════════════════════════════════════════════════════════════════════


def _thresholds(thresholds: Mapping[str, object] | None) -> tuple[int, int]:
    merged = dict(DEFAULT_THRESHOLDS)
    merged.update(dict(thresholds or {}))
    return int(merged["freeze"]), int(merged["new_file"])


def violations(
    files: Mapping[str, int],
    frozen: Sequence[Mapping[str, object]],
    exemptions: Sequence[Mapping[str, object]],
    *,
    declared_exemptions: int | None,
    frozen_count_max: int | None,
    thresholds: Mapping[str, object] | None = None,
) -> list[str]:
    """判定本体：返回**违规清单**（空列表 = 绿）。每条违规都必须**可归因 + 可复算**。"""
    freeze_line, new_line = _thresholds(thresholds)
    out: list[str] = []

    if freeze_line > FREEZE_THRESHOLD_MIRROR or new_line > NEW_FILE_THRESHOLD_MIRROR:
        out.append(
            f"阈值只许收紧、不许放宽：台账 freeze={freeze_line} / new_file={new_line}，"
            f"镜像上限 {FREEZE_THRESHOLD_MIRROR} / {NEW_FILE_THRESHOLD_MIRROR} —— "
            f"把阈值调大不会让任何东西变干净，只会让棘轮失效。复算：git show origin/main:{LEDGER_REL}"
        )

    if not files:
        out.append(
            "扫描面为空（fail-closed）：没有可判的源文件 ≠ 通过。复算：git ls-files | wc -l"
        )
        return out

    if not frozen:
        out.append(
            "冻结清单被清空（fail-closed）：`frozen: []` 让判据恒绿 ⇒ 红。要缩短就**删条目**"
            f"（并同步台账本身），不是把清单清空。复算：git show origin/main:{LEDGER_REL} | head -40"
        )

    if frozen_count_max is None:
        out.append(
            f"冻结清单缺 frozen_count_max：条数上限必须落在台账里（判据不硬编码「只许减少」的数值）。"
            f"复算：git show origin/main:{LEDGER_REL}"
        )
    elif len(frozen) > int(frozen_count_max):
        out.append(
            f"冻结清单条数上涨：现取 {len(frozen)} 条 > 上限 {frozen_count_max}（条数**只许减少**）。"
            f"要冻结新文件必须同批剔除等量的旧条目并显式抬高 frozen_count_max（两处数字都要变大，diff 里看得见）。"
            f"复算：python3 -c \"import json;d=json.load(open('{LEDGER_REL}'));print(len(d['frozen']),d['frozen_count_max'])\""
        )

    frozen_paths: set[str] = set()
    for entry in frozen:
        path = str(entry.get("path") or "")
        lines = entry.get("lines")
        frozen_at = str(entry.get("frozen_at") or "")
        if not path or not isinstance(lines, int) or isinstance(lines, bool) or not DATE_RE.match(frozen_at):
            out.append(
                f"冻结条目形状非法：{entry!r} —— 需要 path(非空) + lines(int) + frozen_at(YYYY-MM-DD)。"
                f"复算：git show origin/main:{LEDGER_REL}"
            )
            continue
        if path in frozen_paths:
            out.append(f"冻结清单重复登记：{path} —— 一条文件只能有一行冻结值（否则改哪条都说不清）")
        frozen_paths.add(path)
        if path not in files:
            out.append(
                f"冻结条目已不在扫描面：{path}（文件已删 / 改名 / 移出源码面）⇒ 从冻结清单删除该条"
                f"（只许缩短；幽灵条目不许留着）。复算：git ls-files {shlex.quote(path)}"
            )
            continue
        current = int(files[path])
        if current > lines:
            out.append(
                f"冻结文件行数上涨：{path} 冻结值 {lines} → 现值 {current}（+{current - lines}）。"
                f"修法：把新增部分拆到新文件 / 下沉到复用件，回到 ≤ {lines} 行；"
                f"确实要抬高冻结值必须显式改台账（diff 里看得见，且属单独裁定）。"
                f"复算：wc -l {shlex.quote(path)}；基线：git show origin/main:{shlex.quote(path)} | wc -l"
            )

    exempt_paths: set[str] = set()
    for entry in exemptions:
        path = str(entry.get("path") or "")
        reason = str(entry.get("reason") or "").strip()
        date = str(entry.get("date") or "")
        if not path or not reason or not DATE_RE.match(date):
            out.append(
                f"豁免条目形状非法：{entry!r} —— 需要 path(非空) + reason(非空) + date(YYYY-MM-DD)。"
                f"复算：git show origin/main:{EXEMPTIONS_REL}"
            )
            if path:
                exempt_paths.add(path)
            continue
        if path in exempt_paths:
            out.append(f"豁免台账重复登记：{path} —— 条数就是存量上限，重复登记会虚增上限")
        exempt_paths.add(path)
        if path not in files:
            out.append(
                f"豁免里出现已不存在的文件：{path} ⇒ 销账（只许缩短）。"
                f"复算：git ls-files {shlex.quote(path)}"
            )
            continue
        if int(files[path]) < new_line:
            out.append(
                f"豁免已失效：{path} 现值 {int(files[path])} 行 < {new_line} 线 ⇒ 从豁免台账删除该条"
                f"（只许缩短；本表是存量上限，不是永久白名单）。复算：wc -l {shlex.quote(path)}"
            )

    if declared_exemptions is None:
        out.append(
            f"豁免台账缺 declared_count：条数必须**现取**（读台账），不许在判据里硬编码，"
            f"也不许让台账与声明脱钩。复算：git show origin/main:{EXEMPTIONS_REL}"
        )
    elif int(declared_exemptions) != len(exemptions):
        out.append(
            f"豁免台账条数不符：declared_count={declared_exemptions} ≠ 现取 {len(exemptions)} 条 —— "
            f"增删条目必须同步该字段（一处改动 = diff 里看得见）。复算：python3 -c "
            f"\"import json;d=json.load(open('{EXEMPTIONS_REL}'));print(d['declared_count'],len(d['exemptions']))\""
        )

    for path, lines in sorted(files.items()):
        if lines < new_line or path in frozen_paths or path in exempt_paths:
            continue
        where = (
            f"（现值已过 {freeze_line} 冻结线 ⇒ 只能拆到 < {new_line} 行；冻结清单条数只许减少，"
            f"确要冻结必须同批剔除等量旧条目并显式抬高 frozen_count_max）"
            if lines > freeze_line
            else f"（{new_line}–{freeze_line} 行 ⇒ 进 loc_ratchet_exemptions.json + 同步 declared_count + reason/date）"
        )
        out.append(
            f"未登记的源码大文件：{path} 现值 {lines} 行 ≥ {new_line} ⇒ 未登记即红。"
            f"修法：拆到 < {new_line} 行再提交，或显式登记{where}。"
            f"复算：wc -l {shlex.quote(path)}"
        )

    return out


def report(
    files: Mapping[str, int],
    frozen: Sequence[Mapping[str, object]],
    exemptions: Sequence[Mapping[str, object]],
    thresholds: Mapping[str, object] | None = None,
) -> str:
    """报告型打印：规模 / top 10 / 距阈值余量（绿的时候也让人看得见离红线有多近）。"""
    freeze_line, new_line = _thresholds(thresholds)
    total = sum(int(v) for v in files.values())
    frozen_paths = {str(e.get("path")) for e in frozen}
    exempt_paths = {str(e.get("path")) for e in exemptions}
    top = sorted(files.items(), key=lambda kv: (-int(kv[1]), kv[0]))[:10]
    biggest = max((int(e.get("lines") or 0) for e in frozen), default=0)
    lines = [
        f"[loc-ratchet] 源码面：{len(files)} 个文件 / {total} 行"
        f"（白名单根 = {' · '.join(p for p, _ in SCAN_ROOTS)}）",
        f"[loc-ratchet] 冻结清单：{len(frozen)} 条（> {freeze_line} 行），现取最大 {biggest} 行；"
        f"豁免台账：{len(exemptions)} 条（{new_line}–{freeze_line} 行）",
        f"[loc-ratchet] top 10（行数 · 距 {freeze_line} 线 · 登记）：",
    ]
    for idx, (path, count) in enumerate(top, 1):
        state = "冻结" if path in frozen_paths else ("豁免" if path in exempt_paths else "**未登记**")
        lines.append(
            f"  {idx:>2}. {int(count):>6} 行 · {int(count) - freeze_line:+6d} · {state:>8} · {path}"
        )
    return "\n".join(lines)


def collect(
    repo: Path,
    ledger_path: Path,
    exemptions_path: Path,
    scan_roots: Sequence[tuple[str, tuple[str, ...]]] = SCAN_ROOTS,
) -> tuple[list[str], dict[str, int], dict, dict]:
    """端到端（真目录 + 真台账文件）→ (违规, 文件表, 台账, 豁免台账)。判别力自证用临时目录走同一条路。"""
    files = scan_source_files(repo, scan_roots)
    ledger = read_json(ledger_path)
    ledger_ex = read_json(exemptions_path)
    found = violations(
        files,
        ledger.get("frozen") or [],
        ledger_ex.get("exemptions") or [],
        declared_exemptions=ledger_ex.get("declared_count"),
        frozen_count_max=ledger.get("frozen_count_max"),
        thresholds=ledger.get("thresholds"),
    )
    return found, files, ledger, ledger_ex


# ══════════════════════════════════════════════════════════════════════════════════════
# 真语料：基线必须绿（origin/main 现状 = 基线，不是失败态）
# ══════════════════════════════════════════════════════════════════════════════════════


def test_seed_is_green_and_printed():
    """真语料基线：现取扫描 + 真台账 ⇒ 0 条违规，并打印规模 / top 10 / 余量。"""
    found, files, ledger, ledger_ex = collect(REPO, LEDGER_PATH, EXEMPTIONS_PATH)
    frozen = ledger["frozen"]
    frozen_paths = {str(e["path"]) for e in frozen}
    freeze_line, new_line = _thresholds(ledger.get("thresholds"))

    print(report(files, frozen, ledger_ex["exemptions"], ledger.get("thresholds")))
    assert found == [], "真语料基线必须绿（origin/main 现状 = 基线）：\n" + "\n".join(found)

    # 种子自证（1）：台账阈值 == 镜像；> 冻结线的文件**全部**在冻结清单里（种子的口径真的被用上了）。
    assert freeze_line == FREEZE_THRESHOLD_MIRROR and new_line == NEW_FILE_THRESHOLD_MIRROR, (
        f"台账阈值与镜像不一致：freeze={freeze_line} / new_file={new_line}"
    )
    assert ledger.get("frozen_count_max") == FROZEN_COUNT_MAX_MIRROR, (
        f"冻结清单条数上限与镜像不一致：{ledger.get('frozen_count_max')} ≠ {FROZEN_COUNT_MAX_MIRROR}"
    )
    assert len(frozen) <= FROZEN_COUNT_MAX_MIRROR, "冻结清单条数只许减少"

    # 种子自证（2）：每条冻结值都真的 > 冻结线；现值 ≤ 冻结值（只许下降）。
    assert all(int(e["lines"]) > freeze_line for e in frozen), "冻结条目的 lines 必须在冻结线之上"
    assert all(files.get(str(e["path"]), 0) <= int(e["lines"]) for e in frozen)
    # 种子自证（3）：豁免台账逐条带 reason/date，且 declared_count 就是现取条数。
    assert ledger_ex["declared_count"] == len(ledger_ex["exemptions"]) > 0


def test_scan_surface_excludes_generated_and_tests():
    """扫描面自证：只白名单三个源码根；`tests/` / `acceptance/` / 依赖 / 生成物后缀一个都不进。"""
    files = scan_source_files(REPO)
    assert len(files) > 1000, f"源码面文件数异常偏少（现取 {len(files)}）—— 扫描口径可能被改窄"
    bad = [
        rel for rel in files
        if rel.startswith(("tests/", "acceptance/", "docs/", "scripts/"))
        or "/node_modules/" in f"/{rel}"
        or any(part in EXCLUDED_DIR_NAMES for part in rel.split("/"))
        or rel.endswith(GENERATED_SUFFIXES)
    ]
    assert bad == [], "扫描面混入非源码/生成物：\n" + "\n".join(sorted(bad)[:20])
    allowed = (
        "backend/admin-api/src/main/",
        "backend/ai-agent-service/app/",
        "frontend/",
    )
    assert all(rel.startswith(allowed) for rel in files)


def test_scan_is_under_ten_seconds():
    """判据要快：一次全量扫描（真语料）< 10 秒（实测 ≈0.3 秒，留足余量）。"""
    started = time.monotonic()
    files = scan_source_files(REPO)
    elapsed = time.monotonic() - started
    assert files, "扫描面为空（fail-closed）"
    assert elapsed < 10.0, f"源码面扫描耗时 {elapsed:.1f}s ≥ 10s —— 判据必须保持秒级"


# ══════════════════════════════════════════════════════════════════════════════════════
# 内存判据：每条坏形态各判红（绿不是默认态）
# ══════════════════════════════════════════════════════════════════════════════════════


def _frozen(path: str, lines: int, at: str = "2026-10-30") -> dict:
    return {"path": path, "lines": lines, "frozen_at": at}


def _exempt(path: str, reason: str = "存量 800–2000 行；本单不拆", date: str = "2026-10-30") -> dict:
    return {"path": path, "reason": reason, "date": date}


def test_frozen_growth_of_one_line_is_red():
    """追加**一行**就红：报文必须带 path + 现值 + 冻结值 + 可复制命令。"""
    files = {"a/Big.java": 2101}
    found = violations(
        files, [_frozen("a/Big.java", 2100)], [_exempt("a/Big.java")],
        declared_exemptions=1, frozen_count_max=10,
    )
    assert len(found) == 1 and "a/Big.java" in found[0], found
    assert "2100" in found[0] and "2101" in found[0] and "+1" in found[0], found[0]
    assert "wc -l" in found[0] and "git show origin/main:" in found[0], found[0]


def test_removing_a_frozen_entry_is_green_but_also_dropping_its_registration_is_red():
    """删条目 ⇒ 绿（只许缩短方向正确）；同时把豁免登记也删 ⇒ 红（≥800 未登记）。"""
    files = {"a/Big.java": 3000, "a/Other.java": 2100}
    both = [_frozen("a/Big.java", 3000), _frozen("a/Other.java", 2100)]
    exemptions = [_exempt("a/Big.java"), _exempt("a/Other.java")]
    assert violations(files, both, exemptions, declared_exemptions=2, frozen_count_max=10) == []

    shortened = [_frozen("a/Other.java", 2100)]  # 删掉一条冻结项（只许缩短）
    assert violations(files, shortened, exemptions, declared_exemptions=2, frozen_count_max=10) == [], (
        "删条目本身不许判红 —— 「只许缩短」的方向必须被自证"
    )

    laundered = violations(files, shortened, [_exempt("a/Other.java")], declared_exemptions=1, frozen_count_max=10)
    assert len(laundered) == 1 and "a/Big.java" in laundered[0], laundered
    assert "未登记" in laundered[0], laundered[0]


def test_growing_the_freeze_ledger_count_is_red():
    """冻结清单**条数**只许减少：现取 3 条 > 上限 2 ⇒ 红（往清单里塞新文件不是出口）。"""
    files = {"a/One.java": 2100, "a/Two.java": 2200, "a/Three.java": 2300}
    frozen = [_frozen("a/One.java", 2100), _frozen("a/Two.java", 2200), _frozen("a/Three.java", 2300)]
    exemptions = [_exempt(p) for p in files]
    found = violations(files, frozen, exemptions, declared_exemptions=3, frozen_count_max=2)
    assert len(found) == 1 and "冻结清单条数上涨" in found[0] and "2" in found[0], found

    # 删一条（条数下降）⇒ 绿；`frozen_count_max` 仍是 2（上限不动）。
    assert violations(files, frozen[:2], exemptions, declared_exemptions=3, frozen_count_max=2) == []


def test_cleared_freeze_ledger_is_red_fail_closed():
    """冻结清单被清空 ⇒ 红（fail-closed：没东西可判不是通过）。"""
    files = {"a/Big.java": 3000}
    found = violations(files, [], [_exempt("a/Big.java")], declared_exemptions=1, frozen_count_max=10)
    assert len(found) == 1 and "清空" in found[0] and "fail-closed" in found[0], found


def test_new_nine_hundred_line_file_is_red_then_registration_turns_it_green():
    """新建 900 行源码文件 ⇒ 红；登记豁免（reason + date + declared_count）⇒ 绿。"""
    files = {"a/Frozen.java": 2100, "a/New.tsx": 900}
    frozen = [_frozen("a/Frozen.java", 2100)]
    exemptions = [_exempt("a/Frozen.java")]

    found = violations(files, frozen, exemptions, declared_exemptions=1, frozen_count_max=10)
    assert len(found) == 1 and "a/New.tsx" in found[0] and "900" in found[0], found
    assert "800" in found[0] and "wc -l" in found[0], found[0]

    registered = exemptions + [_exempt("a/New.tsx", "新页面首版；拆分排期见 #8166")]
    assert violations(files, frozen, registered, declared_exemptions=2, frozen_count_max=10) == []

    # 只加条目、不同步 declared_count ⇒ 红（条数必须现取，一处改动即红）。
    mismatched = violations(files, frozen, registered, declared_exemptions=1, frozen_count_max=10)
    assert len(mismatched) == 1 and "declared_count" in mismatched[0], mismatched


def test_exemption_for_a_deleted_file_and_for_a_shrunk_file_are_both_red():
    """豁免里出现已不存在的文件 ⇒ 红；文件跌破 800 线而未销账 ⇒ 红（只许缩短）。"""
    files = {"a/Frozen.java": 2100, "a/Small.ts": 799}
    found = violations(
        files,
        [_frozen("a/Frozen.java", 2100)],
        [_exempt("a/Frozen.java"), _exempt("a/Gone.ts"), _exempt("a/Small.ts")],
        declared_exemptions=3, frozen_count_max=10,
    )
    text = "\n".join(found)
    assert "a/Gone.ts" in text and "已不存在" in text, text
    assert "a/Small.ts" in text and "799" in text and "已失效" in text, text


def test_empty_exemptions_is_legal():
    """台账为空**合法**（判据不许因「豁免 0 条」判红）；只要没有 ≥800 的未登记文件就是绿。"""
    files = {"a/Frozen.java": 2100, "a/Small.ts": 120}
    assert violations(files, [_frozen("a/Frozen.java", 2100)], [], declared_exemptions=0, frozen_count_max=10) == []


def test_malformed_entries_are_red():
    """台账形状（冻结条目 / 豁免条目 / 阈值）坏掉 ⇒ 红，不许静默跳过。"""
    files = {"a/Frozen.java": 2100}
    shape = violations(
        files,
        [{"path": "a/Frozen.java", "lines": "2100", "frozen_at": "2026-10-30"}],
        [{"path": "a/Frozen.java", "date": "2026-10-30"}],
        declared_exemptions=1, frozen_count_max=10,
    )
    assert any("冻结条目形状非法" in v for v in shape), shape
    assert any("豁免条目形状非法" in v for v in shape), shape

    bad_date = violations(
        files, [_frozen("a/Frozen.java", 2100)],
        [{"path": "a/Frozen.java", "reason": "r", "date": "2026/10/30"}],
        declared_exemptions=1, frozen_count_max=10,
    )
    assert any("形状非法" in v for v in bad_date), bad_date

    missing_count = violations(files, [_frozen("a/Frozen.java", 2100)], [_exempt("a/Frozen.java")],
                               declared_exemptions=None, frozen_count_max=10)
    assert len(missing_count) == 1 and "declared_count" in missing_count[0], missing_count


def test_thresholds_come_from_the_ledger_and_may_not_be_relaxed():
    """阈值是台账真值源（收紧会立刻生效），但**放宽** ⇒ 红。"""
    files = {"a/Mid.ts": 150, "a/Frozen.java": 2100}
    frozen = [_frozen("a/Frozen.java", 2100)]

    # 收紧阈值 ⇒ 150 行也算「大文件」⇒ 立刻红（证明读的是台账，不是写死的 800）。
    tightened = violations(files, frozen, [_exempt("a/Frozen.java")],
                           declared_exemptions=1, frozen_count_max=10, thresholds={"freeze": 2000, "new_file": 100})
    assert len(tightened) == 1 and "a/Mid.ts" in tightened[0], tightened

    relaxed = violations(files, frozen, [_exempt("a/Frozen.java")],
                         declared_exemptions=1, frozen_count_max=10, thresholds={"freeze": 5000, "new_file": 5000})
    assert any("阈值只许收紧" in v for v in relaxed), relaxed


# ══════════════════════════════════════════════════════════════════════════════════════
# 判别力自证：四个坏形态在**临时目录**（真文件 + 真台账）里各自判红
# ══════════════════════════════════════════════════════════════════════════════════════


_FIXTURE_ROOTS = (("src", (".java", ".ts")),)


def _write_lines(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"// line {i}\n" for i in range(count)), encoding="utf-8")


def _fixture(tmp: Path, files: dict[str, int], frozen: list[dict], exemptions: list[dict],
             declared: int | None = None, thresholds: dict | None = None) -> tuple[Path, Path, Path]:
    repo = tmp / "repo"
    for rel, count in files.items():
        _write_lines(repo / rel, count)
    ledger = {
        "schema": "loc-freeze-ledger/v1",
        "thresholds": thresholds or dict(DEFAULT_THRESHOLDS),
        "frozen_count_max": len(frozen),
        "frozen": frozen,
    }
    ex = {
        "schema": "loc-ratchet-exemptions/v1",
        "declared_count": len(exemptions) if declared is None else declared,
        "exemptions": exemptions,
    }
    ledger_path = tmp / "loc_freeze_ledger.json"
    ex_path = tmp / "loc_ratchet_exemptions.json"
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    ex_path.write_text(json.dumps(ex, ensure_ascii=False), encoding="utf-8")
    return repo, ledger_path, ex_path


def test_discriminating_power_of_frozen_growth_in_a_temp_repo():
    """坏形态 ①：往冻结文件**追加一行**（真文件、真台账）⇒ 红。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        repo, ledger, ex = _fixture(
            tmp, {"src/Big.java": 2100}, [_frozen("src/Big.java", 2100)], [_exempt("src/Big.java")],
        )
        found, _, _, _ = collect(repo, ledger, ex, _FIXTURE_ROOTS)
        assert found == [], found  # 先自证基线在临时仓里也是绿的

        _write_lines(repo / "src/Big.java", 2101)  # 追加 1 行
        found, _, _, _ = collect(repo, ledger, ex, _FIXTURE_ROOTS)
        assert len(found) == 1 and "src/Big.java" in found[0] and "+1" in found[0], found


def test_discriminating_power_of_a_new_900_line_file_in_a_temp_repo():
    """坏形态 ②：新建 **900** 行源码文件且未登记 ⇒ 红；登记（reason + date）⇒ 绿。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        repo, ledger, ex = _fixture(
            tmp, {"src/Big.java": 2100}, [_frozen("src/Big.java", 2100)], [_exempt("src/Big.java")],
        )
        _write_lines(repo / "src/Fresh.ts", 900)
        found, _, _, _ = collect(repo, ledger, ex, _FIXTURE_ROOTS)
        assert len(found) == 1 and "src/Fresh.ts" in found[0] and "900" in found[0], found

        ex.write_text(json.dumps({
            "schema": "loc-ratchet-exemptions/v1",
            "declared_count": 2,
            "exemptions": [_exempt("src/Big.java"), _exempt("src/Fresh.ts", "首版；拆分排期 #8166")],
        }, ensure_ascii=False), encoding="utf-8")
        found, _, _, _ = collect(repo, ledger, ex, _FIXTURE_ROOTS)
        assert found == [], found


def test_discriminating_power_of_a_cleared_ledger_in_a_temp_repo():
    """坏形态 ③：冻结清单被清空 ⇒ 红（fail-closed）。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        repo, ledger, ex = _fixture(
            tmp, {"src/Big.java": 2100}, [], [_exempt("src/Big.java")],
        )
        found, _, _, _ = collect(repo, ledger, ex, _FIXTURE_ROOTS)
        assert len(found) == 1 and "清空" in found[0], found


def test_discriminating_power_of_a_ghost_exemption_in_a_temp_repo():
    """坏形态 ④：豁免指向**已不存在**的文件 ⇒ 红（只许缩短；也防止台账拿幽灵条目虚增上限）。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        repo, ledger, ex = _fixture(
            tmp, {"src/Big.java": 2100},
            [_frozen("src/Big.java", 2100)],
            [_exempt("src/Big.java"), _exempt("src/Ghost.java", "已删除，未销账")],
        )
        found, _, _, _ = collect(repo, ledger, ex, _FIXTURE_ROOTS)
        assert len(found) == 1 and "src/Ghost.java" in found[0] and "已不存在" in found[0], found


def test_missing_ledger_file_fails_closed():
    """缺台账 ⇒ 抛错（fail-closed），不是「无需登记」的绿。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        repo, ledger, ex = _fixture(
            tmp, {"src/Big.java": 2100}, [_frozen("src/Big.java", 2100)], [_exempt("src/Big.java")],
        )
        ledger.unlink()
        try:
            collect(repo, ledger, ex, _FIXTURE_ROOTS)
        except AssertionError as exc:
            assert "台账不存在" in str(exc), str(exc)
        else:  # pragma: no cover - 真出现即红
            raise AssertionError("缺台账却静默通过（fail-open）")
