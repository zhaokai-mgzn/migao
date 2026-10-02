# case_ids: MC-068
"""`docs/wiki/RBAC.md` 里的「新租户种子岗位清单」必须与真值源**逐值相等**（issue #6036 的 F7 类级固化）。

## 这一条要治什么（验收报告 F7 的原文）

验收报告 `acceptance/2026-10-02/new-tenant-multirole/REPORT.md` §四·F7：
`docs/wiki/RBAC.md` 写「新租户注册初始化**五岗**种子（管理员/客服/运营/销售/财务）」，
而实测新租户是 **7 岗** —— 多出 `product_manager` / `knowledge_editor`（由 V137 正式定义）。

#5992 把那一行改成了「七岗」，但**没有任何判据把它钉住** ⇒ 下一次改清单（加岗位 / 删岗位）
时文档会**静默漂移**，而「文档 vs 实测」的差**又一次**只能靠人工验收发现（本仓的经典形态：
「改了一个缺陷却没修」——`AGENTS.md` 铁律 8）。本文件就是那条缺失的判据。

## 口径（逐字，来自本单的验收要求）

- **真值源** = `rbac/manifest.json` 的 `roles.seed` 键集合（单一声明源，见 `rbac/sources.json` 的
  `role-defaults-seed` 面）与 `V137__formalize_legacy_roles.sql`（**渲染自同一清单**，见
  `rbac/sources.json` 的 `sql-role-grants` 面：`derived_from = manifest.roles.*`）。
- **不许手抄一份新清单然后不管**：判据**不认**任何一份手写副本作为真值 —— 它把文档里的清单
  与清单文件**逐个码对账**，且**首行（清单声明行）就是唯一被认的那一行**。
- 不一致 ⇒ **红**，并**具名**报出多/少了哪几个码、中文数字对不对。

## 覆盖不到什么（照实登记）

- 判不了**散文**（`docs/design/rbac-single-source.md`、`RegistrationService` 的注释里的「七岗」）——
  它们不在本判据的语料里。**有意如此**：散文描述可读性，不是声明；把它们也扫进来只会制造假红。
- 判不了「这个岗位**应该**有哪些权限码」（那是 `rbac/readings.json` 的 `roles.seed` 值对账，
  归 `tests/unit_ci_workflows/test_rbac_single_source_manifest.py`）。
- 不查 GitHub / 不联网；纯静态（CI 的 `ci workflow helper unit tests` job 只装 `pytest` + `pyyaml`）。
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "rbac" / "manifest.json"
DOC_PATH = REPO_ROOT / "docs" / "wiki" / "RBAC.md"

#: 文档里的**清单声明行**的唯一锚（`docs/wiki/RBAC.md` 的「岗位（实际生效）」节）。
#: 口径：声明行 = **以本锚开头的那一行**（`MARKER` 是它的前缀，必须逐字出现）。
MARKER = "> 新租户注册初始化"

#: V137 里的**声明行**锚（`-- ` 之后逐字出现；下方正则 `_V137_DECL_RE` 把码集读出来）。
#: 它声明的是「本迁移**正式定义**的岗位码」——**不是**全部种子岗（另外五岗由 V29/V32 + `RegistrationService` 建）。
V137_MARKER = "V137 formalized_roles="

#: 中文数字 → 整数（只收文档里真会用的那几个；收不到的形态判「无法解析 ⇒ 红」，fail-closed）。
CN_DIGITS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

_CN_DIGIT_CLASS = "".join(CN_DIGITS)
_CODE_RE = re.compile(r"`([a-z][a-z0-9_]*)`")
_DECL_RE = re.compile(rf"\*\*([{_CN_DIGIT_CLASS}]+)岗\*\*")


class RoleListDrift(Exception):
    """无法解析文档声明行（fail-closed：解析不了 = 判红，不当『没问题』读）。"""


def parse_doc_seed_roles(doc_text: str) -> tuple[int, list[str]]:
    """取出文档声明行的 **（中文数字, 岗位码列表）**；解析不了 ⇒ `RoleListDrift`。"""
    lines = [ln for ln in doc_text.splitlines() if ln.startswith(MARKER)]
    if not lines:
        raise RoleListDrift(f"文档里找不到清单声明行（前缀 `{MARKER}` 的行）")
    if len(lines) > 1:
        raise RoleListDrift(f"清单声明行有 {len(lines)} 行（口径 = 唯一一行，多写要多处同步 ⇒ 红）")
    all_lines = doc_text.splitlines()
    idx = all_lines.index(lines[0])
    # 声明行允许**折行**：取紧接着的、同属该引用块（仍以 `> ` 起头）的**一行**续行拼成逻辑声明行。
    # 口径 = **最多一行**续行 ⇒ 后半句（V137 / 快照式语义那句）不拼进来（标题右边那行仍是「另一行」）。
    # ⚠️ 取用纪律（见 `docs/wiki/Change-Blast-Radius.md` §16.7）：本判据**只认**这一份文档、这一个锚，
    # 靠 `_CODE_RE` 的 `[a-z][a-z0-9_]*` 形态把散文里的其它反引号词挡在外面。
    line = lines[0]
    if idx + 1 < len(all_lines) and all_lines[idx + 1].startswith(">"):
        line = line + " " + all_lines[idx + 1]

    m = _DECL_RE.search(line)
    if not m:
        raise RoleListDrift("声明行里没有 `**<中文数字>岗**` 形态的岗位数（拼错/漏写 ⇒ 红）")
    numeral = m.group(1)
    if numeral not in CN_DIGITS:
        raise RoleListDrift(f"无法解析的中文数字：{numeral!r}")
    declared = CN_DIGITS[numeral]

    codes = _CODE_RE.findall(line)
    if not codes:
        raise RoleListDrift("声明行里一个岗位码（反引号包住的 code）都没有")
    return declared, codes


def manifest_seed_roles(manifest: dict) -> list[str]:
    """真值源：`manifest.roles.seed` 的键集合（有序，便于比对报错可读）。"""
    return sorted(manifest["roles"]["seed"].keys())


def check_role_list_consistency(manifest: dict, doc_text: str) -> list[str]:
    """纯函数：返回问题清单（空 = 一致）。注入式红证直接拿它的入参做内存变异。"""
    issues: list[str] = []
    seed = manifest_seed_roles(manifest)
    try:
        declared, codes = parse_doc_seed_roles(doc_text)
    except RoleListDrift as e:
        return [f"文档声明行无法解析：{e}"]

    if declared != len(seed):
        issues.append(f"文档写「{declared} 岗」而真值源 `roles.seed` 有 {len(seed)} 个岗位码")

    missing = sorted(set(seed) - set(codes))
    extra = sorted(set(codes) - set(seed))
    if missing:
        issues.append(f"文档清单**漏了**真值源里的岗位码：{missing}")
    if extra:
        issues.append(f"文档清单**多了**真值源里没有的岗位码：{extra}")
    if len(codes) != len(set(codes)):
        dupes = sorted({c for c in codes if codes.count(c) > 1})
        issues.append(f"文档清单里有重复的岗位码：{dupes}")
    return issues


def check_v137_formalized_roles(manifest: dict, v137_text: str) -> list[str]:
    """V137 的**声明**码集（`V137_MARKER` 那行）必须逐值等于它真建的 `roles` 行，且 ⊆ 真值源。

    真值源的另一侧：V137 由 `rbac/generate_migration.py` 从清单渲染（`rbac/sources.json` 的
    `sql-role-grants` 面，`derived_from = manifest.roles.*`）⇒ 它建的码**不允许**跑出清单之外。
    """
    issues: list[str] = []
    seed = set(manifest_seed_roles(manifest))
    declared_match = re.search(rf"{re.escape(V137_MARKER)}([a-z_,]+)", v137_text)
    if not declared_match:
        return ["V137 里找不到声明行（`-- " + V137_MARKER + "<码,码>`）—— 被改写 ⇒ 同批更新迁移与本判据"]
    declared = [c for c in declared_match.group(1).split(",") if c]
    if len(declared) != len(set(declared)):
        issues.append(f"V137 声明行里有重复的岗位码：{sorted({c for c in declared if declared.count(c) > 1})}")

    # `INSERT INTO roles (…) SELECT gen_random_uuid()::text, t.id, '<name>', '<code>', …` 是它的**建行**面。
    built = re.findall(r"SELECT gen_random_uuid\(\)::text, t\.id, '[^']*', '([a-z_]+)'", v137_text)
    if not built:
        issues.append("V137 里解析不到任何建行语句（迁移被改写成别的形态 ⇒ 同批更新本判据）")
        return issues

    if sorted(declared) != sorted(set(built)):
        issues.append(f"V137 声明 {sorted(declared)} ≠ 它真建的 roles 行 {sorted(set(built))}")
    outside = sorted(set(declared) - seed)
    if outside:
        issues.append(f"V137 定义的岗位码不在真值源 `roles.seed` 里：{outside}")
    if len(set(declared)) == len(seed):
        issues.append("V137 声明了**全部**种子岗 —— 它只该定义历史岗位（五岗由 V29/V32 + RegistrationService 建）")
    return issues


# ============================== 判据本体 ==============================

def test_doc_seed_role_list_matches_manifest():
    """F7 的主判据：`docs/wiki/RBAC.md` 的清单 == `rbac/manifest.json#roles.seed`。"""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    doc = DOC_PATH.read_text(encoding="utf-8")
    issues = check_role_list_consistency(manifest, doc)
    assert not issues, "文档岗位清单与真值源不一致（issue #6036 的 F7）：\n" + "\n".join(issues)


def test_v137_formalized_roles_match_manifest():
    """同族：V137（渲染自同一清单）建的 roles 行 == 清单的 `roles.seed`。"""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    v137 = (REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources"
            / "db" / "migration" / "V137__formalize_legacy_roles.sql").read_text(encoding="utf-8")
    issues = check_v137_formalized_roles(manifest, v137)
    assert not issues, "V137 与真值源不一致（issue #6036 的 F7）：\n" + "\n".join(issues)


def test_doc_seed_roles_are_the_manifest_seed_exactly():
    """正向钉住：文档清单**逐值**等于真值源（不是「数量相等」；顺序中立，集合逐值相等）。"""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    doc = DOC_PATH.read_text(encoding="utf-8")
    declared, codes = parse_doc_seed_roles(doc)
    seed = manifest_seed_roles(manifest)
    assert sorted(codes) == seed, f"文档清单 {sorted(codes)} != 真值源 {seed}"
    assert declared == len(seed)


# ============================== 红证（内存变异，判据直接吃变异体）==============================

def _doc_and_manifest() -> tuple[dict, str]:
    return (json.loads(MANIFEST_PATH.read_text(encoding="utf-8")),
            DOC_PATH.read_text(encoding="utf-8"))


def test_redproof_baseline_is_green():
    """红证的对照读数：**不注入**时必须判绿（否则下面每条注入都不可信）。"""
    manifest, doc = _doc_and_manifest()
    assert check_role_list_consistency(manifest, doc) == []


def test_redproof_reverting_to_five_roles_is_red():
    """注入 ①：把声明行改回 F7 的**原始缺陷形态**「五岗」（仅 5 个历史岗位）⇒ 必红且具名。"""
    manifest, doc = _doc_and_manifest()
    drifted = doc.replace(
        "> 新租户注册初始化**七岗**种子",
        "> 新租户注册初始化**五岗**种子",
    ).replace("`product_manager`", "").replace("`knowledge_editor`", "")
    issues = check_role_list_consistency(manifest, drifted)
    assert issues, "把清单改回「五岗」竟然判绿 —— 判据是空断言"
    joined = "\n".join(issues)
    assert "5 岗" in joined and "7 个岗位码" in joined, f"未报出数量差：{joined}"
    assert "product_manager" in joined and "knowledge_editor" in joined, f"未漏码：{joined}"


def test_redproof_adding_a_role_to_manifest_is_red():
    """注入 ②：真值源**新增**一个岗位码而文档没跟 ⇒ 必红（这才是 F7 的真正方向）。"""
    manifest, doc = _doc_and_manifest()
    mutated = copy.deepcopy(manifest)
    mutated["roles"]["seed"]["warehouse_keeper"] = ["dashboard:view"]
    issues = check_role_list_consistency(mutated, doc)
    assert issues, "清单加了岗位而文档没跟却判绿 —— 判据看不到真值源的变化"
    assert "warehouse_keeper" in "\n".join(issues), "\n".join(issues)


def test_redproof_renaming_a_role_code_in_doc_is_red():
    """注入 ③：文档把 `finance` 写错成 `financial` ⇒ 必红（漏一个 + 多一个，逐值口径）。"""
    manifest, doc = _doc_and_manifest()
    drifted = doc.replace("`finance`", "`financial`", 1)
    issues = check_role_list_consistency(manifest, drifted)
    assert issues, "错码竟然判绿"
    joined = "\n".join(issues)
    assert "financial" in joined and "finance" in joined, joined


def test_redproof_unparseable_declaration_is_red():
    """注入 ④（fail-closed）：声明行被删 / 数字写坏 ⇒ 判红，**不得**当成「没问题」。"""
    manifest, doc = _doc_and_manifest()
    for broken in (
        doc.replace("**七岗**", "**若干岗**"),
        doc.replace("**七岗**种子", "岗位种子"),
        doc.replace("`finance`", "").replace("`sales`", ""),  # 漏码（不是解析不了，但同样必红）
    ):
        assert check_role_list_consistency(manifest, broken), "无法解析却判绿（fail-open）"


def test_redproof_missing_declaration_line_is_red():
    """注入 ④b（fail-closed）：整条声明行被删 ⇒ 判红（「找不到声明」不得读成「没问题」）。"""
    manifest, doc = _doc_and_manifest()
    broken = "\n".join(ln for ln in doc.splitlines() if not ln.startswith(MARKER))
    issues = check_role_list_consistency(manifest, broken)
    assert issues and "找不到" in "\n".join(issues), "\n".join(issues)


def test_redproof_duplicate_declaration_lines_are_red():
    """注入 ⑤：同一个清单写两行 ⇒ 判红（多处同步 = 漂移温床）。"""
    manifest, doc = _doc_and_manifest()
    line = next(ln for ln in doc.splitlines() if ln.startswith(MARKER))
    issues = check_role_list_consistency(manifest, doc + "\n" + line + "\n")
    assert issues and "2 行" in "\n".join(issues), "\n".join(issues)


def test_control_only_comment_change_does_not_go_red():
    """对照读数（防判据被自己的文案喂红）：**只改**与声明无关的散文 ⇒ 不红。"""
    manifest, doc = _doc_and_manifest()
    noisy = doc.replace("## 权限模型", "## 权限模型（本行只是注释，与岗位清单无关）")
    assert check_role_list_consistency(manifest, noisy) == []


# ---- V137 那一侧的红证 ----

def test_redproof_v137_missing_a_role_row_is_red():
    """注入 ⑥：V137 少建一个岗位行 ⇒ 必红。"""
    manifest, _ = _doc_and_manifest()
    v137 = (REPO_ROOT / "backend" / "admin-api" / "src" / "main" / "resources"
            / "db" / "migration" / "V137__formalize_legacy_roles.sql").read_text(encoding="utf-8")
    mutated = v137.replace("'knowledge_editor'", "'knowledge_editor_old'")
    issues = check_v137_formalized_roles(manifest, mutated)
    assert issues, "V137 少建一个行却判绿"
    joined = "\n".join(issues)
    assert "knowledge_editor" in joined, joined


def test_redproof_v137_rewritten_shape_is_red():
    """注入 ⑦（fail-closed）：V137 被改成解析不到的形态 ⇒ 红（不是静默通过）。"""
    manifest, _ = _doc_and_manifest()
    issues = check_v137_formalized_roles(manifest, "-- 空迁移\nBEGIN;\nCOMMIT;\n")
    assert issues, "解析不到建行语句却判绿（fail-open）"
