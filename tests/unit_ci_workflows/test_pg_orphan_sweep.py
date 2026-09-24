# case_ids: MC-012
# （沿用 tests/unit_ci_workflows/** 的既有惯例：CI/流程结构类 L0 不变式统一挂 MC-012 ——
#   见 tests/unit_ci_workflows/test_merge_gate.py 的同款声明与 `.github/cases/misc.yml` 的登记。
#   本 PR 不新建用例族。）
"""孤儿 PG 集群（issue #5263）三条判据 —— 夹具 teardown / 只读清点 / dry-run 边界。

## 病灶（issue #5263 实测）

`tests/unit_ci_workflows/**` 的真库判据各自 `initdb` + `pg_ctl start` 起一次性集群；夹具只在
**成功路径**上停库（或被中止）⇒ postmaster 被 `launchd` 收养、数据目录留在 `/tmp` 或 pytest tmp 下
**永不回收**（本机实测 6 个全在、最久 3 天 13 小时、每个集群 ~69MB）。

## 三条判据（逐条对应 issue 的判据表；每条都带**能单独变红**的注入式红证）

| # | 判据 | 落码 | 红证（本文件真跑，不是纸面） |
|---|---|---|---|
| ① | 真库夹具必须在**失败/中止路径**上也停集群（`try/finally` 或 `addfinalizer`，不是只在成功路径 `pg_ctl stop`） | 登记模块**不得**自己拼 `pg_ctl start/stop` 的 argv（AST 判 argv 里的 `"start"`/`"stop"` 字面量）⇒ 起/停只能经收口件；收口件 `start_cluster` 本体必须「失败也停」；夹具的 `yield` 必须被带 `finally` 的 `try`（或 `with`）覆盖 | Ⅰ 去掉某夹具的 `finally` ⇒ **红**；Ⅱ 去掉收口件的 except-stop ⇒ **红**；Ⅲ **行为级**：让一个用例失败 ⇒ 断言**无残留**（真 PG 真跑） |
| ② | **只读清点**入口：列出「ppid==1 且数据目录在 `/tmp` 或 pytest tmp 下」的 `postgres -D`；**无残留必须打印计数 0** | `scripts/pg_orphan_sweep.py`（宿主：`scripts/**` 无同类件 ⇒ 独立入口；分类口径**不复制**，经 importlib 复用收口件） | Ⅳ 受控 `ps` 文本里造孤儿 ⇒ 必列出，且 `ppid≠1` / 非临时区 / 非 postgres 三条**负例**不得列出；Ⅴ 摘掉「计数行总是打印」⇒ 无残留时静默 ⇒ **红**；Ⅵ **真残留**：红证Ⅲ 造出的残留被真 `ps` 判成孤儿 |
| ③ | 默认 **dry-run**，`--apply` 才停；且**不得**停 `ppid≠1` 的进程 | 默认零写操作（替身 `pg_ctl` 的记录文件**不产生**）；`--apply` 逐条复核 `ppid==1` | Ⅶa 去掉收口件的 `ppid==1` ⇒ 在用集群会被**列进孤儿清单**（错分类可见）；Ⅶb 收口件 + 脚本复核两处都去掉 ⇒ 它**真的去停在用集群** |

## ⚠️ 本单实测出的规格前提修正（判据③，必须一并读）

`ppid==1` **不等于**「没在用」：`pg_ctl start` 是 fork-and-exit，postmaster 的父进程**秒级**就变成
launchd（实测：**发起集群的 python 进程仍存活**时，`ps` 里已是 `ppid=1` / 存活 3 秒）。
⇒ 判据③按 issue 原文**逐字实现**（`ppid≠1` 一律不动），但它不足以实现 issue 的「不做」条
（**不动仍然活着的集群**）⇒ 额外加**存活时长闸**：`--apply` 只停存活 ≥ `--min-age`（默认 30 分钟）的
孤儿，低龄的**列出但不动作**（判据③的红证 Ⅷ：把闸调到 0 ⇒ 低龄孤儿会被停）。

判据②③的注入点 = 替身可执行文件（`PG_SWEEP_PS_BIN` / `PG_SWEEP_PG_CTL_BIN` / `PG_SWEEP_FUNNEL`，
沿用 `scripts/merge_gate.py` 的 `MG_GH_BIN` 口径）：**不 mock 被测函数**，而是把 CLI 边界当注入点，
所以「到底停没停、停了谁」在同一条真实进程链上被验证；变异一律打在**源码文本**的**临时副本**上
（避开「判据被自己的文案喂绿」，且绝不改工作树）。
"""
from __future__ import annotations

import ast
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

UNIT_DIR = Path(__file__).resolve().parent          # tests/unit_ci_workflows
TESTS_DIR = UNIT_DIR.parent                         # tests/（合成模块要按它进 sys.path 才能 import 包）
REPO_ROOT = TESTS_DIR.parent
FUNNEL = UNIT_DIR / "pg_cluster.py"
SWEEP_SCRIPT = REPO_ROOT / "scripts" / "pg_orphan_sweep.py"

#: 受控 `ps` 文本（判据②③的夹具）。五行覆盖五种形态：
#: 孤儿（ppid==1 + /tmp + 3 小时）/ 在用（ppid!=1 + /tmp + 4 小时，**只有 ppid 能排除它**）/
#: 低龄孤儿（ppid==1 + /tmp + 1 分钟，判据②要列出、判据③的时长闸要不动它）/
#: 非临时区（ppid==1 + /opt）/ 非 postgres。
PS_ORPHAN = "  1234     1 03:12:44 /usr/local/bin/postgres -D /tmp/pg5263-fake-A/pgdata -k /tmp/s1 -p 5432"
PS_LIVE = "  4321  4242 04:00:00 /usr/local/bin/postgres -D /tmp/pg5263-live-B/pgdata -k /tmp/s2 -p 5433"
PS_FRESH = "  2345     1 00:01:02 /usr/local/bin/postgres -D /tmp/pg5263-young-C/pgdata -k /tmp/s4 -p 5435"
PS_PROD = "  9999     1 00:00:03 /usr/local/bin/postgres -D /opt/migao/prod/pgdata -k /tmp/s3 -p 5434"
PS_UNRELATED = "  7777     1 00:00:01 /usr/bin/python3 -c pass"

#: 计数行原文（红证 Ⅴ 按它做单点变异）。
SUMMARY_PRINT = (
    '    print(f"[pg-orphan-sweep] 孤儿集群 = {len(orphans)}"\n'
    '          f"（扫到 postgres -D 进程 = {len(rows)} 条；ppid!=1（在用，**不动**）= {len(in_use)} 条；"\n'
    '          f"本进程临时区根 = {pg.tmp_base()}）")\n'
)

#: 收口件的「处置前复核 ppid」那一行（红证 Ⅶb 的单点变异点）。
PPID_RECHECK = ("            if row.ppid != 1:            "
                "# 处置前**再核一次**（清点与处置之间父进程可能换了）")

#: 本判据文件自己**不是**夹具宿主（它生成合成模块来驱动判据）⇒ 不参与判据①的逐模块扫描
#: （先例：`tests/unit_ci_workflows/test_realdb_failclosed.py` 的全树扫描同样排除 `SELF`）。
#: ⚠️ 但它生成的合成模块**必须**通过同一条扫描 —— 见 `test_synthetic_module_passes_the_same_scan`
#: （否则「判据自己用的形态」与「它要求别人的形态」可以各走各的）。
SELF = Path(__file__).name


def _load(path: Path, name: str):
    """按**路径**加载模块（不依赖 pytest 的 import 模式；判据要读真值，不是读文案）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _mutate(source: str, pairs: list[tuple[str, str]], where: str) -> str:
    """对**源码文本**做单点变异；每处必须恰好命中 1 次（变异不生效 ⇒ 本红证会退化成空跑）。"""
    for old, new in pairs:
        assert source.count(old) == 1, (
            f"{where}: 变异点命中 {source.count(old)} 次（应为 1）⇒ 本红证会退化成空跑，请同步变异点")
        source = source.replace(old, new, 1)
    return source


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据①（静态）：起/停只许经收口件 + teardown 必须覆盖 yield + 收口件本体「失败也停」
# ══════════════════════════════════════════════════════════════════════════════════════

def _direct_pgctl_argv(source: str, tree) -> list[str]:
    """模块里**直接**拼 `pg_ctl … start/stop` 的调用点（= 该由收口件承担的 argv 拼装）。

    判据是 **argv 里恰为 `"start"` / `"stop"` 的字符串常量**（不是裸子串扫描）：注释 / 文档串里
    提一句 `pg_ctl start` **不算**（本仓 7 个模块的注释里就有）。
    """
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        segment = ast.get_source_segment(source, node) or ""
        if not segment.startswith("subprocess."):
            continue
        literals = {n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        if literals & {"start", "stop"}:
            hits.append(f"L{node.lineno}: {segment.splitlines()[0].strip()}")
    return hits


def _funnel_refs(tree, attr: str) -> int:
    """`pg_cluster.<attr>` 的出现次数（起/停必须经收口件 ⇒ 两个属性都该被引用）。"""
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == attr
        and isinstance(node.value, ast.Name) and node.value.id == "pg_cluster"
    )


def _uncovered_yields(tree) -> list[int]:
    """`yield` 的位置里既不在带 `finally` 的 `try` 内、也不在任何 `with` 内的（teardown 无保证）。"""
    covered: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Try) and node.finalbody) or isinstance(node, ast.With):
            for inner in ast.walk(node):
                if isinstance(inner, (ast.Yield, ast.YieldFrom)):
                    covered.add(id(inner))
    return sorted(
        node.lineno for node in ast.walk(tree)
        if isinstance(node, (ast.Yield, ast.YieldFrom)) and id(node) not in covered
    )


def scan_module(path: Path) -> list[str]:
    """单个真库模块的违规清单（判据①；**纯函数** ⇒ 注入式红证可直接喂变异后的副本）。"""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    problems: list[str] = []
    direct = _direct_pgctl_argv(source, tree)
    if direct:
        problems.append(f"{path.name}: 自己拼 `pg_ctl start/stop` 的 argv（{len(direct)} 处）⇒ "
                        f"起/停必须经收口件 pg_cluster.start_cluster / stop_cluster：{direct[0]}")
    for attr in ("start_cluster", "stop_cluster"):
        if _funnel_refs(tree, attr) == 0:
            problems.append(f"{path.name}: 没有引用收口件的 `pg_cluster.{attr}`（起/停不得自备实现）")
    uncovered = _uncovered_yields(tree)
    if uncovered:
        problems.append(f"{path.name}: 第 {uncovered} 行的 `yield` 不在带 `finally` 的 try（或 with）内 "
                        f"⇒ 用例失败/中止时 teardown 无保证")
    return problems


def _calls_stop_cluster(node) -> bool:
    """`stop_cluster(...)`（本模块内的裸调用）或 `pg_cluster.stop_cluster(...)`。"""
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Name) and node.func.id == "stop_cluster")
        or (isinstance(node.func, ast.Attribute) and node.func.attr == "stop_cluster")
    )


def funnel_start_stop_problems(source: str) -> list[str]:
    """收口件 `start_cluster` 本体必须「失败也停」：有 `try`，且 handler / finalbody 里调 `stop_cluster`。"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "start_cluster":
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Try):
                    continue
                tail = list(inner.finalbody) + [stmt for handler in inner.handlers for stmt in handler.body]
                for stmt in tail:
                    if any(_calls_stop_cluster(call) for call in ast.walk(stmt)):
                        return []
            return ["pg_cluster.start_cluster 本体缺「失败则 stop_cluster」的 try/except —— "
                    "「起来了但后面失败」这一形态会留孤儿（issue #5263）"]
    return ["收口件里找不到 `start_cluster`"]


def test_realdb_modules_route_cluster_lifecycle_through_the_funnel():
    """判据①（静态）：登记模块的起/停只许经收口件，且夹具 `yield` 必须被 teardown 覆盖。"""
    pg = _load(FUNNEL, "_pg_cluster_guard")
    problems: list[str] = []
    for name in sorted(set(pg.REALDB_TEST_MODULES) - {SELF}):
        problems.extend(scan_module(UNIT_DIR / name))
    assert problems == [], (
        "真库模块的集群生命周期脱离了收口件（issue #5263 判据①）：\n  " + "\n  ".join(problems)
    )


def test_synthetic_module_passes_the_same_scan(tmp_path):
    """自证：本判据文件生成的合成模块**也**满足判据①；去掉 teardown 的变异形态**必被判出**。

    没有这条，「判据要求别人怎么写」与「判据自己怎么写」可以各走各的（本单实测踩过：
    新判据文件自身被它的逐模块扫描判红）。
    """
    bins = {"initdb": "/usr/bin/initdb", "pg_ctl": "/usr/bin/pg_ctl", "psql": "/usr/bin/psql"}
    for name in ("good", "bad"):
        (tmp_path / name).mkdir()
    good = _synthetic_module(tmp_path / "good", tmp_path / "good" / "d", tmp_path / "good" / "s",
                             bins=bins, finalizer=True, port=1)
    bad = _synthetic_module(tmp_path / "bad", tmp_path / "bad" / "d", tmp_path / "bad" / "s",
                            bins=bins, finalizer=False, port=1)
    assert scan_module(good) == [], "判据自己生成的合成模块没过判据①（形态不一致）"
    assert scan_module(bad) != [], "去掉 teardown 的合成模块没被判出 ⇒ 判据①的判别力不覆盖合成模块"


def test_funnel_start_cluster_stops_on_failure_paths():
    """判据①（收口件本体）：「起不来 / 起来了但探测失败 / Ctrl-C」都必须先停库再抛。"""
    problems = funnel_start_stop_problems(FUNNEL.read_text(encoding="utf-8"))
    assert problems == [], "\n  ".join(problems)


def test_red_proof__dropping_a_fixture_finally_is_caught(tmp_path):
    """红证 Ⅰ：把某夹具的 `finally` 降级成 `except` ⇒ 判据①**必红**（判据有判别力，不是恒绿）。"""
    source = (UNIT_DIR / "test_cutting_plan_meters_migration.py").read_text(encoding="utf-8")
    mutated = _mutate(source, [(
        "    finally:\n        pg_cluster.stop_cluster(",
        "    except Exception:  # 变异①：teardown 不再保证（finally → except）\n        pg_cluster.stop_cluster(",
    )], "红证Ⅰ")
    path = tmp_path / "test_mutated_fixture.py"
    path.write_text(mutated, encoding="utf-8")
    problems = scan_module(path)
    assert problems != [], "把夹具的 `finally` 去掉后判据仍绿 ⇒ 判据①没有判别力"


def test_red_proof__dropping_the_funnels_failure_stop_is_caught(tmp_path):
    """红证 Ⅱ：把收口件 `start_cluster` 的 except-stop 摘掉 ⇒ 判据①**必红**。"""
    mutated = _mutate(FUNNEL.read_text(encoding="utf-8"), [(
        '    except BaseException:            # 含 KeyboardInterrupt：中止路径也不许留孤儿\n'
        '        stop_cluster(bins["pg_ctl"], datadir)\n'
        '        raise\n',
        '    except BaseException:  # 变异②：不再停集群\n        raise\n',
    )], "红证Ⅱ")
    path = tmp_path / "pg_cluster_mutated.py"
    path.write_text(mutated, encoding="utf-8")
    problems = funnel_start_stop_problems(mutated)
    assert problems != [], "摘掉收口件的失败路径停库后判据仍绿 ⇒ 判据①没有判别力"


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据②③（行为级）：只读清点入口 —— 替身 `ps` / 替身 `pg_ctl` 走**真实进程链**
# ══════════════════════════════════════════════════════════════════════════════════════

def _sh(path: Path) -> str:
    """shell 单引号转义（替身脚本里嵌路径用）。"""
    return "'" + str(path).replace("'", "'\\''") + "'"


def _heredoc(lines: list[str]) -> str:
    return "cat <<'MGEOF'\n" + "".join(line + "\n" for line in lines) + "MGEOF\n"


def _fake_ps(path: Path, lines: list[str], *, flag: Path | None = None,
             flag_lines: list[str] | None = None) -> Path:
    """替身 `ps`：输出受控进程表；给了 `flag` 时**只在哨兵文件存在时**输出 `flag_lines`。

    （哨兵由替身 `pg_ctl` 在 `--apply` 时删掉 ⇒ 「停完复查」能看到计数归零这条正证。）
    """
    body = "#!/bin/sh\n"
    if flag is not None:
        body += f"if [ -f {_sh(flag)} ]; then\n" + _heredoc(flag_lines or []) + "fi\n"
    body += _heredoc(lines)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_pg_ctl(path: Path, record: Path, *, clear: Path | None = None) -> Path:
    """替身 `pg_ctl`：把 argv 追加进 `record`（= 「到底停没停、停了谁」的正证）；可选删哨兵。"""
    body = "#!/bin/sh\n" + f'echo "$*" >> {_sh(record)}\n'
    if clear is not None:
        body += f"rm -f {_sh(clear)}\n"
    path.write_text(body + "exit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _run_sweep(*, script: Path = SWEEP_SCRIPT, ps_bin: Path | None = None,
               pg_ctl_bin: Path | None = None, funnel: Path | None = None,
               apply: bool = False, min_age: int | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if ps_bin is not None:
        env["PG_SWEEP_PS_BIN"] = str(ps_bin)
    if pg_ctl_bin is not None:
        env["PG_SWEEP_PG_CTL_BIN"] = str(pg_ctl_bin)
    if funnel is not None:
        env["PG_SWEEP_FUNNEL"] = str(funnel)
    argv = [sys.executable, str(script)]
    if apply:
        argv.append("--apply")
    if min_age is not None:
        argv += ["--min-age", str(min_age)]
    return subprocess.run(argv, capture_output=True, text=True, env=env, cwd=str(REPO_ROOT))


def test_inventory_lists_orphans_and_excludes_everything_else(tmp_path):
    """判据②正例+负例：孤儿必列出；`ppid!=1` / 非临时区 / 非 postgres **一律不得**列出。"""
    ps_bin = _fake_ps(tmp_path / "ps", [PS_ORPHAN, PS_LIVE, PS_FRESH, PS_PROD, PS_UNRELATED])
    proc = _run_sweep(ps_bin=ps_bin)
    assert proc.returncode == 1, f"有孤儿却非 1：\n{proc.stdout}\n{proc.stderr}"
    for listed in ("/tmp/pg5263-fake-A/pgdata", "/tmp/pg5263-young-C/pgdata"):
        assert listed in proc.stdout, f"孤儿 {listed} 没被列出：\n{proc.stdout}"
    for excluded in ("/tmp/pg5263-live-B/pgdata", "/opt/migao/prod/pgdata"):
        assert excluded not in proc.stdout, (
            f"{excluded} 不该出现在孤儿清单里（负例：ppid!=1 / 非临时区）\n{proc.stdout}")
    assert "孤儿集群 = 2" in proc.stdout, proc.stdout


def test_inventory_prints_a_count_of_zero_instead_of_silence(tmp_path):
    """判据②：**无残留时必须打印计数 0**（静默无输出 = 红 —— 「没扫到」要长得像「没扫到」）。"""
    ps_bin = _fake_ps(tmp_path / "ps", [PS_LIVE, PS_UNRELATED])
    proc = _run_sweep(ps_bin=ps_bin)
    assert proc.returncode == 0, f"无孤儿应返回 0：\n{proc.stdout}\n{proc.stderr}"
    assert "孤儿集群 = 0" in proc.stdout, f"无残留时静默无输出（判据②的红形态）：\n{proc.stdout!r}"
    assert "ppid!=1（在用，**不动**）= 1" in proc.stdout, proc.stdout


def test_red_proof__dropping_the_count_line_is_caught(tmp_path):
    """红证 Ⅴ：把「计数行总是打印」摘成「有孤儿才打印」⇒ 无残留时静默 ⇒ 判据②**必红**。"""
    mutated = _mutate(SWEEP_SCRIPT.read_text(encoding="utf-8"), [(
        SUMMARY_PRINT, "    if orphans:\n" + textwrap.indent(SUMMARY_PRINT, "    "),
    )], "红证Ⅴ")
    script = tmp_path / "pg_orphan_sweep_mutated.py"
    script.write_text(mutated, encoding="utf-8")
    ps_bin = _fake_ps(tmp_path / "ps", [PS_LIVE, PS_UNRELATED])
    proc = _run_sweep(script=script, ps_bin=ps_bin, funnel=FUNNEL)
    assert "孤儿集群 = 0" not in proc.stdout, (
        f"变异后仍打印了计数行 ⇒ 本红证没有判别力：\n{proc.stdout!r}")


def test_dry_run_is_default_and_apply_only_stops_orphans(tmp_path):
    """判据③：默认 dry-run（**零写操作**）；`--apply` 只停 `ppid==1` 的孤儿。"""
    record, flag = tmp_path / "pg-ctl.log", tmp_path / "orphan.flag"
    flag.write_text("up", encoding="utf-8")
    ps_bin = _fake_ps(tmp_path / "ps", [PS_LIVE, PS_UNRELATED], flag=flag, flag_lines=[PS_ORPHAN])
    pg_ctl_bin = _fake_pg_ctl(tmp_path / "pg_ctl", record, clear=flag)

    dry = _run_sweep(ps_bin=ps_bin, pg_ctl_bin=pg_ctl_bin)
    assert dry.returncode == 1, dry.stdout
    assert record.exists() is False, f"dry-run 竟然调了 pg_ctl（判据③要求零写操作）：\n{record.read_text()}"
    assert flag.exists() is True, "dry-run 动了哨兵文件（不该有任何写操作）"

    applied = _run_sweep(ps_bin=ps_bin, pg_ctl_bin=pg_ctl_bin, apply=True)
    assert applied.returncode == 0, f"--apply 后还有残留：\n{applied.stdout}\n{applied.stderr}"
    logged = record.read_text(encoding="utf-8")
    assert "/tmp/pg5263-fake-A/pgdata" in logged, f"--apply 没停孤儿：\n{logged}"
    assert "/tmp/pg5263-live-B/pgdata" not in logged, (
        f"**停了在用（ppid!=1）的集群** —— 误停 = 制造假失败（判据③）：\n{logged}")
    assert "孤儿集群 = 0" in applied.stdout, applied.stdout


def test_apply_leaves_young_orphans_alone(tmp_path):
    """判据③的**边界**（issue「不做」条）：低龄孤儿**列出但不动** —— `ppid==1` 证明不了没在用。"""
    record = tmp_path / "pg-ctl.log"
    ps_bin = _fake_ps(tmp_path / "ps", [PS_FRESH])
    pg_ctl_bin = _fake_pg_ctl(tmp_path / "pg_ctl", record)
    proc = _run_sweep(ps_bin=ps_bin, pg_ctl_bin=pg_ctl_bin, apply=True)
    assert record.exists() is False, (
        f"低龄孤儿（存活 1 分钟）被停了 —— 它可能正被在跑的用例使用：\n{record.read_text()}")
    assert "⏸ 跳过 pid=2345" in proc.stdout, proc.stdout
    assert proc.returncode == 1, f"未处置的孤儿必须仍然计数（不得静默当已清）：\n{proc.stdout}"


def test_red_proof__zeroing_the_min_age_guard_is_caught(tmp_path):
    """红证 Ⅷ：把存活时长闸调到 0 ⇒ 低龄孤儿**真的会被停** ⇒ 那条边界判据有判别力。"""
    mutated = _mutate(SWEEP_SCRIPT.read_text(encoding="utf-8"), [(
        "DEFAULT_MIN_AGE_MINUTES = 30", "DEFAULT_MIN_AGE_MINUTES = 0  # 变异④：撤掉时长闸",
    )], "红证Ⅷ")
    script = tmp_path / "pg_orphan_sweep_noage.py"
    script.write_text(mutated, encoding="utf-8")
    record = tmp_path / "pg-ctl.log"
    ps_bin = _fake_ps(tmp_path / "ps", [PS_FRESH])
    pg_ctl_bin = _fake_pg_ctl(tmp_path / "pg_ctl", record)
    _run_sweep(script=script, ps_bin=ps_bin, pg_ctl_bin=pg_ctl_bin, funnel=FUNNEL, apply=True)
    logged = record.read_text(encoding="utf-8") if record.exists() else ""
    assert "/tmp/pg5263-young-C/pgdata" in logged, (
        f"撤掉时长闸后低龄孤儿仍没被停（本红证没判别力 / 时长闸不是承重的）：\n{logged}")


def test_red_proof__loosening_the_ppid_rule_stops_a_live_cluster(tmp_path):
    """红证 Ⅶ：去掉「ppid 必须是 1」⇒ 在用集群先被**错列**（Ⅶa）、再被**真停**（Ⅶb）。

    两段分开，是为了让**每一层**的承重性各自可见：收口件负责「谁算孤儿」，脚本的处置前复核
    负责「就算分类被放宽也仍然不动 `ppid!=1`」—— 两层都去掉才是「完全失去这道闸」。
    """
    loosed = _mutate(FUNNEL.read_text(encoding="utf-8"), [(
        "        return self.ppid == 1 and is_tmp_datadir(self.datadir)",
        "        return is_tmp_datadir(self.datadir)  # 变异③：不再要求 ppid==1",
    )], "红证Ⅶa")
    funnel = tmp_path / "pg_cluster_loosed.py"
    funnel.write_text(loosed, encoding="utf-8")

    ps_bin = _fake_ps(tmp_path / "ps", [PS_ORPHAN, PS_LIVE, PS_FRESH, PS_UNRELATED])
    mislisted = _run_sweep(ps_bin=ps_bin, funnel=funnel)
    assert "/tmp/pg5263-live-B/pgdata" in mislisted.stdout, (
        f"去掉 ppid==1 之后在用集群仍没被错列 ⇒ 判据③的分类条件不承重（红证Ⅶa 退化）："
        f"\n{mislisted.stdout}")

    record = tmp_path / "pg-ctl.log"
    pg_ctl_bin = _fake_pg_ctl(tmp_path / "pg_ctl", record)
    script = tmp_path / "pg_orphan_sweep_noppid.py"
    script.write_text(_mutate(SWEEP_SCRIPT.read_text(encoding="utf-8"), [(
        PPID_RECHECK, "            if False:  # 变异③b：去掉「处置前复核 ppid」",
    )], "红证Ⅶb"), encoding="utf-8")
    _run_sweep(script=script, ps_bin=ps_bin, pg_ctl_bin=pg_ctl_bin, funnel=funnel, apply=True)
    logged = record.read_text(encoding="utf-8") if record.exists() else ""
    assert "/tmp/pg5263-live-B/pgdata" in logged, (
        f"两层 ppid 闸都去掉后竟仍没去停在用集群 ⇒ 判据③的负例抓不到（红证Ⅶb 退化）：\n{logged}")


# ══════════════════════════════════════════════════════════════════════════════════════
# 判据①②③ 的**真 PG** 行为级证据：失败用例不留残留 + 真残留能被判成孤儿
# ══════════════════════════════════════════════════════════════════════════════════════

def _synthetic_module(work: Path, datadir: Path, sockdir: Path, *, bins: dict,
                      finalizer: bool, port: int) -> Path:
    """合成一个「像真库判据那样起集群」的模块，并**故意失败**（验失败路径的 teardown）。

    `finalizer=False` 时把 teardown 的 `stop_cluster` 换成打印 ⇒ 造出**真残留**（红证 Ⅲ/Ⅵ 用）。

    ⚠️ `datadir` / `sockdir` 由调用方给**短路径**（`/tmp/pg5263-*/…`）：unix socket 路径有
    ~103 字节上限，pytest 的 `tmp_path`（macOS `$TMPDIR/pytest-of-*`）一放就超 —— 本单实测踩过，
    报错形态是「`pg_ctl` 起不来 + 日志里 socket 路径超长」。

    `bins` = 收口夹具 `realdb_binaries` 的**绝对路径**字典（按字面量烘进合成模块 —— 它因此也走同一份
    二进制发现口径，不在合成模块里另起一套）。
    """
    probe = work / "started.marker"
    teardown = ('        pg_cluster.stop_cluster(BINS["pg_ctl"], DATADIR)'
                if finalizer else
                '        print("变异④：teardown 不停集群（红证要的就是这个残留）")')
    source = f'''\
import sys
from pathlib import Path

sys.path.insert(0, {str(TESTS_DIR)!r})
from unit_ci_workflows import pg_cluster

import pytest

DATADIR = Path({str(datadir)!r})
SOCKDIR = Path({str(sockdir)!r})
PROBE = Path({str(probe)!r})
BINS = {bins!r}


@pytest.fixture
def cluster():
    pg_cluster.start_cluster(BINS, DATADIR, sockdir=SOCKDIR, port={port}, log=DATADIR / "pg.log")
    PROBE.write_text("集群起来了", encoding="utf-8")
    try:
        yield DATADIR
    finally:
{teardown}


def test_deliberately_failing(cluster):
    raise AssertionError("故意失败：验「失败路径也停集群」")
'''
    path = work / "test_synthetic_orphan_probe.py"
    path.write_text(source, encoding="utf-8")
    return path


def _run_synthetic(module: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(module), "-q", "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=str(REPO_ROOT))


def _clusters_for(pg, datadir: Path) -> list:
    """真 `ps` 里数据目录 == `datadir` 的 postmaster 行（按**内容**判，不按进程名猜）。"""
    proc = subprocess.run([pg.which("ps") or "ps", *pg.PS_ARGS], capture_output=True, text=True)
    target = os.path.realpath(str(datadir))
    return [row for row in pg.parse_pg_processes(proc.stdout)
            if os.path.realpath(row.datadir) == target]


def _wait_gone(pg, datadir: Path, timeout: float = 20.0) -> list:
    """等残留消失（有界轮询：`-m immediate` 停止是异步的，返回不等于已退干净）。"""
    deadline = time.monotonic() + timeout
    rows = _clusters_for(pg, datadir)
    while rows and time.monotonic() < deadline:
        time.sleep(0.2)
        rows = _clusters_for(pg, datadir)
    return rows


def test_a_failing_case_stops_its_cluster(tmp_path, realdb_binaries):
    """判据①（**行为级**）：让一个用例失败 ⇒ 断言**无残留**（issue 原文的红证口径）。

    走收口夹具 `realdb_binaries`（缺 PG ⇒ CI 判红 / 本机显式 skip 都在它内部决定）。
    """
    pg = _load(FUNNEL, "_pg_cluster_behaviour")
    root = Path(tempfile.mkdtemp(prefix="pg5263-probe-", dir="/tmp"))
    try:
        datadir, sockdir = root / "d", root / "s"
        sockdir.mkdir()
        module = _synthetic_module(tmp_path, datadir, sockdir, bins=realdb_binaries,
                                   finalizer=True, port=_free_port())
        proc = _run_synthetic(module)
        assert proc.returncode != 0, (
            f"合成的失败用例没有失败 ⇒ 本判据没验到「失败路径」：\n{proc.stdout}\n{proc.stderr}")
        assert (tmp_path / "started.marker").exists() is True, (
            f"集群压根没起来 ⇒ 本判据是空断言：\n{proc.stdout}\n{proc.stderr}")
        assert _wait_gone(pg, datadir) == [], (
            f"用例失败后集群仍在 ⇒ 失败路径没停库（issue #5263 判据①）：\n{proc.stdout}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_red_proof__a_real_leftover_is_classified_as_orphan_and_cleaned(tmp_path, realdb_binaries):
    """红证 Ⅲ+Ⅵ：去掉 teardown 的 stop ⇒ 造出**真残留**，它必须被真 `ps` 判成**孤儿**。

    这条同时证明三件事：① 判据①的断言（「无残留」）**有判别力**（去掉 finally 就真的有残留）；
    ② 判据②的分类器在**真残留**（不是喂进去的假文本）上也成立；③ 残留由本判据自己收掉 ——
    **不许**为了取证而给别人留孤儿。
    """
    pg = _load(FUNNEL, "_pg_cluster_behaviour")
    root = Path(tempfile.mkdtemp(prefix="pg5263-leak-", dir="/tmp"))
    try:
        datadir, sockdir = root / "d", root / "s"
        sockdir.mkdir()
        module = _synthetic_module(tmp_path, datadir, sockdir, bins=realdb_binaries,
                                   finalizer=False, port=_free_port())
        proc = _run_synthetic(module)
        assert proc.returncode != 0, f"合成的失败用例没有失败：\n{proc.stdout}\n{proc.stderr}"

        leftovers = _clusters_for(pg, datadir)
        try:
            assert leftovers != [], (
                "去掉夹具 teardown 的 stop 后竟无残留 ⇒ 判据①的「无残留」断言没有判别力"
                f"（本红证退化）：\n{proc.stdout}")
            deadline = time.monotonic() + 20.0
            orphans = pg.orphan_postmasters(leftovers)
            while not orphans and time.monotonic() < deadline:
                time.sleep(0.2)
                leftovers = _clusters_for(pg, datadir)
                orphans = pg.orphan_postmasters(leftovers)
            assert orphans != [], (
                "真残留没被判成孤儿（ppid==1 且数据目录在临时区）⇒ 判据②的分类器在真现场不成立："
                f"{[(r.pid, r.ppid, r.datadir) for r in leftovers]}")
        finally:
            pg.stop_cluster(realdb_binaries["pg_ctl"], datadir)      # 自己造的残留自己收
        assert _wait_gone(pg, datadir) == [], "红证自己留下了孤儿集群 —— 比原病灶更糟"
    finally:
        shutil.rmtree(root, ignore_errors=True)