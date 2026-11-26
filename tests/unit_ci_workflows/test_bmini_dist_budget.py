# case_ids: MC-342
r"""B 端小程序**包体预算**判据（微信口径，单一来源）+ 类级元守卫（issue #8979 / #8981）。

## 病（两条读数打架，而闸门是"假绿"）

| # | 形态 | 当时为什么没红 |
|---|---|---|
| 1 | **两把尺子**：`deploy/scripts/bmini-assert-dist.sh` 写死 `2097152 × 90% = 1887436`，判据文件再抄一遍 ⇒ 闸门与判据说不上是同一件事 | 两个数各改各的，没有任何判据会比另一份更红 |
| 2 | **闸门判的不是微信口径**：#8981 记的是「dist 1,459,140 ↔ 微信后台 2,079,753（≈×1.425）」⇒ 闸门全绿、上传照样爆 | 判据只认 dist 字节；而 `2,079,753` 这个读数**在本仓与部署机上找不到可复算的产物**（见下） |

## 口径之所以改成「等价」而不是「×1.425」（本文件锁的就是这件事）

2026-11-23 部署机实测（`ssh migao-deploy`，`~/prod/migao-bmini-main`，HEAD = `origin/release` `f78dff52c`）：

| 读数 | 值 | 怎么取的 |
|---|---|---|
| `frontend/bmini-app/dist` 字节合计 | **1,465,245** | `find dist -type f -exec cat {} + \| wc -c` |
| 开发者工具上传后报的 `TOTAL` | **1,461,748** | `scripts/bmini-experience.sh all --version 1.0.2 --env prod` 的输出 |

比值 **0.998** ⇒ **两套口径等价**（dist 字节略大于上传读数，用 dist 判是**偏严**方向）。
复核过的旁证：`~/migao-bmini-experience/dist.bak-11222310`（11-22 23:10 备份的**生产域**产物）
字节合计 1,459,203，与 #8981 记的 dist 1,459,140 只差 63 字节（同一份产物的两次读数）。

而 `2,079,753` 这个数：部署机上四份产物（1,459,203 / 1,465,247 / 1,840,656 / 1,465,245）都量不出它，
devtool 日志里也没有留下带该数字的回执 ⇒ 本文件把它登记为**不可复现读数**，
**不**据此叠折算系数（叠了会把闸门错误收紧到 ≈1.47MB，制造假红）。

⇒ 判据 = **dist 字节**，与微信口径等价（比值由 `calibration` 台账现算，0.97~1.03 之外即红）。

## 本文件锁什么（每条都能单独变红）

| # | 判据 | 红证（本文件实跑） |
|---|---|---|
| 1 | **主包**按预算判：`dist − 分包 ≤ 上限 − 余量`；常量**只**来自 `deploy/scripts/bmini-dist-budget.json` | 主包顶到预算 +1 字节 ⇒ 退 1，且输出**具名**「主包 / 超多少字节 / 怎么复算」 |
| 2 | **分包各自判** ≤ 单包上限（不折进主包） | 某分包 = 上限 +1 ⇒ 退 1 且**点名那个分包**；分包在限内 ⇒ 主包判据不受它影响 |
| 3 | **总包** ≤ 总包上限（主包 + 全部分包） | 多个分包合计越线（每个都在限内）⇒ 退 1 且点名「总包」 |
| 4 | **余量地板**（#8979 的 ≥300KB）：预算里的预留 ≥ 300KB，且**最近一次真实产物**按预算判完仍留 ≥300KB | 改小预留 / 改大台账读数 ⇒ 红 |
| 5 | **口径等价**（不许回流 ×1.425）：台账里每条 `dist ↔ TOTAL` 比值必须落在 0.97~1.03，且带出处；脚本输出不得再有 ×1.425 折算读数 | 把 1.425 塞回台账 ⇒ 红；脚本重新打印折算读数 ⇒ 红 |
| 6 | **类级元守卫（单一来源）**：任何执行载体里出现第二份上限常量 ⇒ 红；豁免台账每条必须仍命中（失效即红 ⇒ 只许缩短） | 在任意脚本里写死 `上限字节` ⇒ 红；台账留一条失效豁免 ⇒ 红 |

## 边界（照实登记）

- 判的是**本仓 dist 的字节**，不是微信后台的包体读数 —— 但两者**等价比值**由判据 5 现算、**可复算**；
  真正的发布包只在部署机构建 + 上传（用户 2026-11-23 裁定），本仓的构建只作**度量**。
- 判不了「产物能不能跑起来」（要真机 / 模拟器），也判不了微信后台的「服务器域名」白名单。
- 分包（[#8979](https://github.com/zhaokai-mgzn/migao/issues/8979)）**本 PR 未拆**：实测主包余量
  631,901 字节（≥300KB）⇒ 按「不为拆分而拆分」降级为「只钉判据 + 留重启条件」；
  判据 2/3 已按 `subPackages` 实现并有用例覆盖 ⇒ 真要拆的那天不必再改尺子。
"""
from __future__ import annotations

import ast
import json
import os
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bmini_dist import (  # noqa: E402  （判据面唯一一份预算读取口 / 夹具）
    ASSERT_SCRIPT,
    BUDGET,
    BUDGET_JSON,
    CAP_BYTES,
    MAIN_LIMIT_BYTES,
    REPO_ROOT,
    RESERVE_BYTES,
    TOTAL_CAP_BYTES,
    build_dist,
    load_budget,
    pad_dist_to,
    run_assert,
    tree_bytes,
)

CASE_IDS = "MC-342"
#: #8979 要求的「拆完主包应留 ≥300KB 余量」——300KB = 300 × 1024 字节（**不是** 300,000）。
FLOOR_BYTES = 300 * 1024
#: 判据 5 的等价容差：实测 0.998（11-23）。超出这个带 ⇒ 说明口径真的分叉了，必须重新取证。
RATIO_LOW, RATIO_HIGH = 0.97, 1.03
#: 元守卫扫描的**非 shell** 执行载体（文档 / 用例 yml 是散文，不进扫描面；预算文件本身是唯一来源，按路径排除）。
CARRIER_PATTERNS = (
    "deploy/scripts/*.py",
    "scripts/*.py",
    ".github/workflows/*.yml",
    "tests/unit_ci_workflows/*.py",
    "tests/unit_ci_workflows/*.json",
    "frontend/bmini-app/config/*.ts",
    "frontend/bmini-app/scripts/*.mjs",
)
#: `.sh` 语料的剪枝（与 `test_guard_scope_declaration.py` 冻结值逐字一致 —— 收窄射程要改那边）。
SHELL_CORPUS_EXCLUDE_DIRS = (
    ".git", "node_modules", ".venv", "venv", "site-packages", ".next", "dist", "build", "coverage",
)
#: 结构化射程声明（issue #5284 的类级判据要求；台账 `guard_scope_ledger.json` 里的 declaration 必须
#: 与它**逐字相同**，且必须等于下面 `scanned_shell_carriers()` 实际枚举出来的集合）。
GUARD_SCOPE = {
    "roots": ["."],
    "glob": "*.sh",
    "exclude_dirs": list(SHELL_CORPUS_EXCLUDE_DIRS),
    "enumerator": "scanned_shell_carriers",
    "uncovered_faces": [],
}


def scanned_shell_carriers() -> set[Path]:
    """本模块**实际**扫描的 `.sh` 载体（射程的真身，全仓 + 标准剪枝）。

    为什么收全仓而不是只扫 `deploy/scripts` + `scripts`：这份元守卫的判据是「上限常量只许住在
    预算文件」—— 只要有一份 shell 在仓库里另抄了一个上限，闸门就有第二把尺子。射程写窄等于
    把「新加一份 shell」这条路留空（#5284 的形态）。
    """
    out: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in SHELL_CORPUS_EXCLUDE_DIRS)
        for name in sorted(filenames):
            if name.endswith(".sh"):
                out.add(Path(dirpath) / name)
    return out
ALLOWLIST = Path(__file__).resolve().parent / "bmini_dist_budget_allowlist.json"


# ── 判据 1：主包预算（常量来自单一来源）──────────────────────────────────────
def test_main_package_budget_is_enforced_and_attributable(tmp_path: Path):
    """主包：顶到预算 ⇒ 恰好 300KB 余量 ⇒ 绿；再多 1 字节 ⇒ 红且**可归因**。

    边界语义 = 「主包 + 预留 ≤ 上限」⇒ 恰好等于预算仍是绿（#8979 要的是 **≥**300KB 余量）。
    """
    assert MAIN_LIMIT_BYTES == CAP_BYTES - RESERVE_BYTES  # 自证：预算是导出的，不是另写的

    at_limit = pad_dist_to(build_dist(tmp_path / "green"), MAIN_LIMIT_BYTES)
    assert tree_bytes(at_limit) == MAIN_LIMIT_BYTES  # 自证夹具真的到了预算线
    green = run_assert(at_limit, "test")
    assert green.returncode == 0, green.stdout + green.stderr
    assert "❌" not in green.stdout, green.stdout

    over = pad_dist_to(build_dist(tmp_path / "red"), MAIN_LIMIT_BYTES + 1)
    proc = run_assert(over, "test")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = proc.stdout
    # 可归因三件：哪个包 / 超多少字节 / 怎么复算
    assert "主包" in out
    assert "超" in out and "1 字节" in out, out
    assert str(BUDGET_JSON.relative_to(REPO_ROOT)) in out, "没给出常量出处（复算无从下手）"
    assert str(ASSERT_SCRIPT.relative_to(REPO_ROOT)) in out, "没给出复算命令"


# ── 判据 2：分包各自判（不折进主包）──────────────────────────────────────────
def test_subpackage_is_judged_separately_from_the_main_package(tmp_path: Path):
    """分包：`app.json` 的 `subPackages[].root` 覆盖的字节**不算主包**，各自判 ≤ 单包上限。"""
    pkg = "pkg-admin"
    # 主包很小、分包恰好 = 上限 ⇒ 绿（若把分包折进主包，这一份的「主包」就会是一条红读数）
    green = build_dist(tmp_path / "green", sub_packages=(pkg,), sub_bytes={pkg: CAP_BYTES})
    assert tree_bytes(green) > CAP_BYTES  # 自证：合计已越过单包上限，拆开判才绿
    proc = run_assert(green, "test")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert pkg in proc.stdout, "分包读数没打出来（判据不可见）"

    # 分包 = 上限 +1 ⇒ 红，且**点名那个分包**（不是笼统「主包超了」）
    red = build_dist(tmp_path / "red", sub_packages=(pkg,), sub_bytes={pkg: CAP_BYTES + 1})
    assert tree_bytes(red) > CAP_BYTES
    proc = run_assert(red, "test")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "分包" in proc.stdout and pkg in proc.stdout
    assert "主包" in proc.stdout  # 主包读数仍在（红的是分包，不许把它说成主包）


# ── 判据 3：总包上限 ─────────────────────────────────────────────────────────
def test_total_package_budget_caps_the_sum(tmp_path: Path):
    """总包：每个分包都在单包上限内，但合计越过总包上限 ⇒ 红，且点名「总包」。"""
    count = TOTAL_CAP_BYTES // CAP_BYTES + 1  # 刚好越线的分包个数
    pkgs = tuple(f"pkg-{i}" for i in range(count))
    per = CAP_BYTES - 1024  # 每个都在单包上限内
    dist = build_dist(
        tmp_path / "dist", sub_packages=pkgs, sub_bytes={p: per for p in pkgs}
    )
    assert tree_bytes(dist) > TOTAL_CAP_BYTES  # 自证：合计真的越线
    proc = run_assert(dist, "test")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "总包" in proc.stdout
    assert str(TOTAL_CAP_BYTES) in proc.stdout.replace(",", ""), "没打印总包上限（读数不可复算）"


# ── 判据 4：余量地板（#8979 的 ≥300KB）──────────────────────────────────────
def test_reserve_floor_meets_8979_and_the_last_real_reading():
    """余量地板：预算里的预留 ≥ 300KB，且**最近一次真实产物**按预算判完仍留 ≥300KB。

    `calibration` 里的 `distBytes` 是**现取的实测读数**（带日期与出处）。改了它 / 改了预留
    而实际留不出 300KB ⇒ 红 —— 这就是「#8979 余量 ≥300KB」的可执行形态（不需要在本机重建产物）。
    """
    assert RESERVE_BYTES >= FLOOR_BYTES, (
        f"主包预留 {RESERVE_BYTES} 字节 < #8979 的 300KB 地板 {FLOOR_BYTES} 字节"
    )
    latest = max(BUDGET["calibration"], key=lambda row: row["date"])
    headroom = CAP_BYTES - latest["distBytes"]
    assert headroom >= FLOOR_BYTES, (
        f"最近一次实测产物 {latest['date']}：dist {latest['distBytes']} 字节 ⇒ 余量 "
        f"{headroom} 字节 < 300KB（{FLOOR_BYTES}）⇒ #8979 的分包必须重启（判据已就绪）"
    )
    assert latest["distBytes"] <= MAIN_LIMIT_BYTES, "实测读数已经越过预算线（闸门该红了）"


# ── 判据 5：口径等价（不许把 ×1.425 叠回来）──────────────────────────────────
def test_calibration_proves_dist_and_wechat_readings_are_equivalent(tmp_path: Path):
    """口径等价：台账每条 `dist ↔ TOTAL` 的比值必须落在 0.97~1.03，且带出处（日期 + 怎么取的）。"""
    rows = BUDGET["calibration"]
    assert rows, "calibration 台账为空 ⇒ 「等价」这个结论没有任何证据"
    for row in rows:
        for key in ("date", "distBytes", "wechatBytes", "source"):
            assert key in row, f"calibration 条目缺 {key}（读数不可复算/不可追溯）：{row}"
        ratio = row["wechatBytes"] / row["distBytes"]
        assert RATIO_LOW <= ratio <= RATIO_HIGH, (
            f"{row['date']} 的 dist {row['distBytes']} ↔ 微信 {row['wechatBytes']} 比值 {ratio:.4f} "
            f"落在 {RATIO_LOW}~{RATIO_HIGH} 之外 ⇒ 口径真的分叉了，别改这个判据，去重新取证"
        )
    latest = max(rows, key=lambda r: r["date"])
    # 脚本要把出处打出来（读数可见）；且**不许**再打印按 ×1.425 折算的假读数
    dist = build_dist(tmp_path / "dist")
    proc = run_assert(dist, "test")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert latest["date"] in proc.stdout, "脚本没交代口径的实测出处"
    assert str(latest["wechatBytes"]) in proc.stdout.replace(",", ""), "脚本没打印微信口径读数"
    assert "1.425" not in proc.stdout, "按 ×1.425 折算的假读数回流了（它凭空算出 9,170 字节余量）"


# ── 判据 6：类级元守卫（单一来源 + 豁免台账只许缩短）─────────────────────────
def _carrier_files() -> list[Path]:
    files: set[Path] = scanned_shell_carriers()  # `.sh` = 全仓射程（结构化声明见 GUARD_SCOPE）
    for pattern in CARRIER_PATTERNS:
        files.update(p for p in REPO_ROOT.glob(pattern) if p.is_file())
    files.discard(BUDGET_JSON)  # 唯一来源本身
    # 本文件是「什么算第二把尺子」的**定义处**（禁用集合就在上面那几行）⇒ 不是被约束对象。
    files.discard(Path(__file__).resolve())
    return sorted(files)


def _code_position_hits() -> list[tuple[str, str]]:
    """执行载体在**代码位置**出现的「第二把尺子」。

    🔴 只算代码位置（`.py` 走 `ast`，跳过注释与文档字符串；脚本 / workflow / ts 只剥整行注释）——
    **不是**放宽：判据与文档里引用历史读数（`2,079,753` / `×1.425` 之类）恰恰是应该留下的证据；
    这里要抓的是**会参与判定的那个常量**（旧实现 `CAP_BYTES=2097152` 就是这么写死的）。
    """
    # 上限常量（第二把尺子）+ 历史折算比的**常数形态**（1425 千分数 / 1.425 浮点）。
    # 为什么要连折算比一起禁：`.github/…` 与脚本里只要再写一次 `×1.425`，闸门就会被悄悄收紧
    # 到 ≈1.47MB（#8981 实测 SQL）：删掉一行不算固化，**写不回来**才算。
    forbidden_strings = {str(CAP_BYTES), str(CAP_BYTES * 90 // 100), str(TOTAL_CAP_BYTES), "1425"}
    forbidden_numbers = {CAP_BYTES, CAP_BYTES * 90 // 100, TOTAL_CAP_BYTES, 1425, 1.425}
    hits: list[tuple[str, str]] = []
    for path in _carrier_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        found: set[str] = set()
        if path.suffix == ".py":
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                tree = ast.parse(text)
            docstrings: set[int] = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    body = getattr(node, "body", [])
                    first = body[0] if body else None
                    if (
                        isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)
                    ):
                        docstrings.add(id(first.value))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or id(node) in docstrings:
                    continue
                value = node.value
                if isinstance(value, str):
                    found.update(tok for tok in forbidden_strings if tok in value)
                elif isinstance(value, (int, float)) and value in forbidden_numbers:
                    found.add(str(value))
        else:
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("//"):
                    continue
                found.update(tok for tok in (forbidden_strings | {"1.425"}) if tok in line)
        hits.extend((str(path.relative_to(REPO_ROOT)), token) for token in sorted(found))
    return hits


def test_no_second_ruler_and_the_allowlist_only_shrinks():
    """类级元守卫：任何执行载体里出现上限常量 ⇒ 红；豁免台账每条必须仍命中。

    为什么必须扫「载体」而不是只看脚本：本缺陷（#8981）的形态就是**判据文件**自己抄了一遍常量，
    于是脚本被改宽时判据跟着假绿。扫描面 = 真会被执行的东西（脚本 / workflow / 判据 / 前端 config）。
    """
    assert BUDGET["wechatPackageCapBytes"] == CAP_BYTES  # 自证：读到的就是唯一来源
    allow = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    entries = [(row["path"], row["literal"]) for row in allow.get("entries", [])]

    hits = _code_position_hits()
    unexpected = [h for h in hits if h not in entries]
    assert not unexpected, (
        "出现第二把尺子（上限常量只许住在 deploy/scripts/bmini-dist-budget.json）：\n  "
        + "\n  ".join(f"{path}: {literal}" for path, literal in unexpected)
        + f"\n改法：从 {BUDGET_JSON.relative_to(REPO_ROOT)} 读（判据用 tests/unit_ci_workflows/_bmini_dist.py）"
    )

    live = set(hits)
    stale = [e for e in entries if e not in live]
    assert not stale, (
        "豁免台账里有失效条目（它已经不再命中 ⇒ 白名单只许缩短，删掉它）：\n  "
        + "\n  ".join(f"{path}: {literal}" for path, literal in stale)
    )


def test_single_source_is_really_the_only_reader_of_the_numbers():
    """反证：把预算文件换成一份**改了上限**的副本 ⇒ 判据侧读数必须跟着变（不是另存了一份）。"""
    tweaked = json.loads(BUDGET_JSON.read_text(encoding="utf-8"))
    tweaked["wechatPackageCapBytes"] = CAP_BYTES + 4096
    copy = BUDGET_JSON.parent / "bmini-dist-budget.__probe__.json"
    try:
        copy.write_text(json.dumps(tweaked), encoding="utf-8")
        reloaded = load_budget(copy)
        assert reloaded["wechatPackageCapBytes"] == CAP_BYTES + 4096
        assert reloaded["wechatTotalCapBytes"] == TOTAL_CAP_BYTES  # 其余键原样带过来
    finally:
        copy.unlink(missing_ok=True)
    with pytest.raises(FileNotFoundError):
        load_budget(BUDGET_JSON.parent / "does-not-exist.json")
