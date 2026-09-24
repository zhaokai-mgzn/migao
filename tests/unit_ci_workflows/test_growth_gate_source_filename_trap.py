# case_ids: MC-012
"""门禁陷阱入册 + 常驻判据：**源码文件名**含 `test` / `spec` 会被 `QA Growth Gate` 判成测试文件（issue #4376）。

## 病灶（实测，不是理论）

`.github/growth_gate.py::_is_test_file()`（**「哪些文件算测试文件」的单一事实源**，issue #4077）的判定是
「扩展名 ∈ {`.py`,`.java`,`.ts`,`.tsx`} **+ 文件名正则 `(test|spec)` 命中（忽略大小写）**」——
**不看目录、不看文件在干什么**。⇒ 新增**源码**文件若起名 `craft-spec.ts`，会被判成测试文件：

① G5 用例追溯（`case_trace_check`）要求它声明 `case_ids:`（新增判「未关联行为用例」、修改判「未声明」）；
② 弱断言扫描（`--check-weak`）把它按测试文件扫。

而**在源码里补 `case_ids:` 就是假声明**（`migao-dev-flow` §2.2 硬约束 B：声明 = 用例 ↔ 测试的关联，
源码补声明 = 让门禁以为有对应用例，实际没有）⇒ **两条路都是错的，只能改名**。
实证来源：包 3（#4355 / PR #4368）新增 `craft-spec.ts` 被门禁要求声明 `case_ids`，多花一个 commit 改名。

## 判据（各带注入式红证）

| # | 判据 | 红证 |
|---|---|---|
| 1 | 陷阱**可复现**（对**真实现**断言）：`_is_test_file("…/craft-spec.ts")` 为真、改名 `craft-display.ts` 为假 | 把真实现里的 `spec` 去掉 ⇒ 必红 |
| 2 | **存量普查入册**：全仓「非测试目录 + 文件名命中 `(test\|spec)` + 代码扩展名」⊆ `SOURCE_NAME_CENSUS` | 新建 `…/src/lib/craft-spec.ts` ⇒ 必红（指名报出 + 给改名出口） |
| 3 | 台账**只许缩短** + 每条带 `reason`/`owner`/`disposition` | 往台账加一条 ⇒ 必红 |
| 4 | 台账条目**活着**：每条都**真的**命中 `_is_test_file`（不是陈旧登记） | 把某条换成不命中的名字 ⇒ 必红 |

## 存量与处置（照实登记，§19.1）

现取存量 **1 个**：`frontend/admin-web/vitest.config.ts` —— `vitest` 里就含 `test` 子串。
它是 vitest 的**约定配置文件名**（改名要同步改所有工具链调用，属独立决定），
故按「**登记 + 只许缩短**」处置，并在台账里写清 owner 与 disposition；
**不做**的是「给它补 `case_ids:`」（那是假声明，且本判据的出口明写不许走这条路）。
"""
import importlib.util
import re
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GROWTH_GATE = REPO_ROOT / ".github" / "growth_gate.py"

#: 与判据实现同源的扩展名集合（`.github/growth_gate.py::TEST_FILE_EXTS`）。
CODE_EXTS = (".py", ".java", ".ts", ".tsx")
#: 与 `_is_test_file()` 同源的文件名正则。
NAME_RX_SRC = r"(test|spec)"
#: 普查剪枝（依赖树 / 构建产物 / VCS —— 都不是本仓源码）。
CENSUS_EXCLUDE_DIRS = (
    ".git", "node_modules", ".venv", "venv", "site-packages", ".next", "dist", "build", "coverage",
)

#: **存量台账（只许缩短）**：非测试目录里文件名命中 `(test|spec)` 的源码文件 → 处置。
#: 每条必须有 `reason` / `owner` / `disposition`；新增命中 ⇒ 判据必红（出口 = **改名**，不是补 `case_ids`）。
SOURCE_NAME_CENSUS = {
    "frontend/admin-web/vitest.config.ts": {
        "reason": "`vitest` 含 `test` 子串 ⇒ 按文件名正则命中；它是 vitest 的**约定配置文件名**",
        "owner": "前端工具链（改动它的人 = 触及该 PR 的作者）",
        "disposition": "登记并只许缩短；**不**补 case_ids（源码/配置补声明 = 假声明，违反 §2.2 硬约束 B）",
    },
}


def _load_growth_gate():
    spec = importlib.util.spec_from_file_location("_growth_gate_for_trap", GROWTH_GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _is_test_dir(parts: tuple[str, ...]) -> bool:
    """测试目录的形态（与 growth_gate 的 `is_auto_pass` 同口径：段名以 `test` 开头）。"""
    return any(p == "tests" or p == "__tests__" or p == "spec" or p.startswith("test") for p in parts)


def census_source_files(root: Path = REPO_ROOT) -> set[str]:
    """全仓「**非**测试目录 + 文件名命中 `(test|spec)` + 代码扩展名」的源码文件集（现取）。

    用 `os.walk` 手动剪枝：剪枝发生在**下降之前**（耗时不取决于依赖树形状，§23 G8）。
    """
    mod = _load_growth_gate()
    import re as _re
    rx = _re.compile(NAME_RX_SRC, _re.I)
    out: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in CENSUS_EXCLUDE_DIRS)
        for name in sorted(filenames):
            if not name.endswith(CODE_EXTS):
                continue
            if name in ("conftest.py", "conftest.ts"):
                continue
            if not rx.search(name):
                continue
            rel = (Path(dirpath) / name).resolve().relative_to(root.resolve())
            if _is_test_dir(rel.parts[:-1]):
                continue
            # 与门禁**真实现**对齐：只有它判成测试文件的才算命中（本判据不另写一套判定）。
            if mod._is_test_file(rel.as_posix()):
                out.add(rel.as_posix())
    return out


def test_trap_is_reproducible_on_real_implementation():
    """判据 1：陷阱对**真实现**成立 —— 源码文件名里的 `spec`/`test` 就是会被当成测试文件。

    红证：把 `.github/growth_gate.py` 的判定改掉（例如去掉 `spec`）⇒ 必红
    （那时「改名」这条纪律的**前提**就不成立了，本判据正是把它钉住）。
    另半条：目录形态（`tests/**`）只是**同一种**命中面，不是全部 —— `frontend/.../src/**` 里一样命中。
    """
    mod = _load_growth_gate()
    for trapped in (
        "frontend/admin-web/src/lib/craft-spec.ts",
        "frontend/admin-web/src/lib/craftSpec.ts",
        "backend/ai-agent-service/app/production/routing_test.py",
        "backend/admin-api/src/main/java/com/migao/admin/FooSpec.java",
        "tests/unit_ci_workflows/test_anything.py",  # 目录形态（已知的那一种）
    ):
        assert mod._is_test_file(trapped), f"门禁不再把「{trapped}」当测试文件 ⇒ 本判据的前提已变（改判而非静默）"
    for safe in (
        "frontend/admin-web/src/lib/craft-display.ts",
        "frontend/admin-web/src/lib/craft-fields.ts",
        "frontend/admin-web/src/lib/craft-map.ts",
        "frontend/admin-web/src/lib/platform.mts",  # 扩展名不在面内 ⇒ 也不命中
    ):
        assert not mod._is_test_file(safe), f"「{safe}」被判成测试文件 ⇒ 改名这条出口不再可靠"


def test_source_filename_census_is_ledgered_and_only_shrinks():
    """判据 2+3：全仓普查 ⊆ 台账（**未登记即红**），且台账**只许缩短**、每条要有人看。

    红证（本机可复算）：`echo 'export const x = 1' > frontend/admin-web/src/lib/craft-spec.ts`
    ⇒ 本测试必红并**指名**该文件；出口 = **改名**（`*-display.ts` / `*-fields.ts` / `*-map.ts`）。
    ⛔ 出口**不是**在源码里补 `case_ids:` —— 那是假声明（`migao-dev-flow` §2.2 硬约束 B）。
    """
    found = census_source_files()
    registered = set(SOURCE_NAME_CENSUS)
    unregistered = sorted(found - registered)
    assert unregistered == [], (
        f"这些**源码**文件的文件名命中了 `{NAME_RX_SRC}` ⇒ `QA Growth Gate` 会把它们当测试文件"
        f"（要求声明 case_ids：新增判「未关联行为用例」、修改判「未声明」）—— 现取未登记 {len(unregistered)} 个：\n"
        + "\n".join(f"    {f}" for f in unregistered)
        + "\n  出口（真可行动）：**改名**（如 `craft-display.ts` / `craft-fields.ts` / `craft-map.ts`）；"
          "**不要**在源码里补 `case_ids:`（假声明，违反 §2.2 硬约束 B）；"
          "确需保留的（如工具链约定文件名）逐条登记进 `SOURCE_NAME_CENSUS` 并写 reason/owner/disposition。"
    )
    stale = sorted(registered - found)
    assert stale == [], f"这些台账条目已是陈旧登记（文件已不在普查集里）：{stale} —— 删除条目（只许缩短）"
    missing_meta = sorted(
        f for f, meta in SOURCE_NAME_CENSUS.items()
        if not all(meta.get(k) for k in ("reason", "owner", "disposition"))
    )
    assert missing_meta == [], f"台账条目缺 reason/owner/disposition（必须写清「谁看、怎么处置」）：{missing_meta}"


def test_census_entries_are_live_not_stale_registrations():
    """判据 4：台账条目**活着** —— 每条都必须**真的**命中门禁判定（防「登记了就不管」）。

    红证：把台账里那条的路径换成一个不命中的名字（如 `…/vitest.config.mts`，扩展名不在面内）⇒ 必红。
    """
    mod = _load_growth_gate()
    dead = sorted(p for p in SOURCE_NAME_CENSUS if not mod._is_test_file(p))
    assert dead == [], (
        f"这些台账条目已不再命中门禁判定（陈旧登记，应销账）：{dead}"
    )
    assert SOURCE_NAME_CENSUS, "台账为空 ⇒ 判据 2 的「⊆ 台账」恒真（fail-closed：要么普查失效，要么台账被清空）"


def test_census_detector_flags_new_source_file_on_mutated_tree(tmp_path):
    """判据 2 的**判别力自证**（造在临时目录，不碰真仓库）：新增 `craft-spec.ts` ⇒ 普查必须抓到。

    负例：同样放在该目录但**改名**后的 `craft-display.ts` ⇒ 必须零命中（否则「改名」这条出口是假的）。
    """
    (tmp_path / "src" / "lib").mkdir(parents=True)
    trapped = tmp_path / "src" / "lib" / "craft-spec.ts"
    trapped.write_text("export const x = 1\n", encoding="utf-8")
    found = census_source_files(tmp_path)
    assert found == {"src/lib/craft-spec.ts"}, f"普查没抓到新增的源码陷阱文件：{found}"
    trapped.rename(tmp_path / "src" / "lib" / "craft-display.ts")
    assert census_source_files(tmp_path) == set(), "改名后仍被判为命中 ⇒ 台账的出口（改名）不可靠"
    nested = tmp_path / "src" / "lib" / "tests" / "craft-spec.ts"
    nested.parent.mkdir(parents=True)
    nested.write_text("export const y = 2\n", encoding="utf-8")
    assert census_source_files(tmp_path) == set(), "测试目录内的文件不属于「源码文件名陷阱」这一面"


# ══════════════════════════════════════════════════════════════════════════════
# 同源声明的**执行面**（#5007①；#5415 的常驻判据 `test_same_source_claims_have_criteria` 要求）
# ══════════════════════════════════════════════════════════════════════════════
def test_code_exts_match_growth_gate_implementation():
    """`CODE_EXTS` 必须与 `.github/growth_gate.py::TEST_FILE_EXTS` **逐项同序相等**。

    为什么必须有这条（#5007① 的形态：承诺写在注释里，删一侧实现不会红）：模块头注释声称
    「与判据实现同源」，而在本判据落地前**没有任何判据承担它** —— 谁把实现侧的
    `TEST_FILE_EXTS` 改一处、这里不动，本文件照样全绿。⇒ 本判据从**实现源码**读出该集合，
    再与本文件的 `CODE_EXTS` 逐项同序比对（真值从源里读，不写死第二份清单）。
    """
    src = GROWTH_GATE.read_text(encoding="utf-8")
    m = re.search(r"^TEST_FILE_EXTS\s*=\s*\(([^)]*)\)", src, re.M)
    assert m, (
        "`.github/growth_gate.py` 里读不到 `TEST_FILE_EXTS`（同源判据必须能读到真值）："
        "若它被改名或改成非字面量集合，请同步本判据与模块头注释"
    )
    impl = tuple(re.findall(r"[\"']([^\"']+)[\"']", m.group(1)))
    assert impl, f"`TEST_FILE_EXTS` 里没解析出任何扩展名（现取 {m.group(1)!r}）⇒ 判据会静默空跑"
    assert impl == CODE_EXTS, (
        f"扩展名集合已**不同源**：实现 {impl} vs 本文件 {CODE_EXTS} —— "
        "两侧必须同序逐项相等（该同源声明由本判据承担，登记在 declaration_gate_registry.json）"
    )
