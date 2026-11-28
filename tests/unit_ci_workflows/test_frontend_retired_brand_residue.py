# case_ids: UI-082, UI-018
r"""退役品牌名「米宝」在 `frontend/**` 的**类级**残余守卫（issue #9306）。

## 口径（用户 2026-11-28 裁定，逐字）

> 「C 端也不叫米宝了，C 端现在不提供 agent 形态，只提供技术能力，直接叫**智能客服**」

最新命名：**B 端经营侧 = 黄金策**（agent 形态）；**C 端 = 智能客服**（无 agent 形态）。
「米宝」是**退役品牌名**，不应出现在任何用户可见面。

命名散落在前端 ~58 个文件里（官网文案 / 后台设置 / 组件提示 / 商家小程序 / 冻结测试），
靠人记住「以后别再写米宝」必然复发（`#6525` / `#8881` 就复发过）⇒ 落成判据：
**未登记即红** + 台账**只许缩短** + 扫描面自证（扫不到东西不许算通过）。

## 四条判据

| # | 判什么 | 红的样子 |
|---|---|---|
| 1 | `frontend/**` live 面不得再出现「米宝」（台账登记的除外） | 具名 `文件:行` + 原文 |
| 2 | 台账诚实：每条登记必须仍有命中（空豁免红）+ `frozen_max` 与条数相等 + `why` 有理 + `kind` 合法 | 具名条目 + 复算命令 |
| 3 | 扫描面非空自证：文件数低于下限 ⇒ 红（路径写错 / 扫描被空转，判据等于没跑） | 打印实际文件数 |
| 4 | 红证（注入式，先自证注入生效）：未登记的旧称命中 ⇒ 判据 1 具名红；登记了但已无命中 ⇒ 判据 2 具名红 | 具名条目 |

三态：`0` = 绿；`1` = 红（具名）；本判据零网络、零时钟、零 LLM，**无 `3`**。
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
LEDGER_PATH = Path(__file__).resolve().parent / "frontend_retired_brand_residue_ledger.json"

#: 退役品牌名（本判据唯一扫描目标；技术标识 `mibao` / `xiaobu` 与组件名 `MibaoLogo` 不在此列）
OLD_NAME = "米宝"

#: 扫描面：前端源码 / 测试 / 配置 / 文档（构建产物目录一律不进）
TEXT_SUFFIXES = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".json", ".md", ".mdx", ".css", ".scss", ".html", ".yml", ".yaml",
}
SKIP_DIRS = {"node_modules", ".next", "dist", "out", "coverage", "build", "target", ".turbo"}
#: 扫描面下限：低于它说明路径写错 / 扫描空转（现取 1405 个文件；只许变多，取整到千位留余量）
MIN_SCANNED_FILES = 1000

KINDS = {"compliance_frozen", "negative_anchor"}


def ledger() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def scan_files() -> list[Path]:
    """`frontend/**` 的文件清单（跳过构建产物目录）；排序后返回（红证逐条具名靠它稳定）。"""
    return sorted(
        path
        for path in FRONTEND.rglob("*")
        if path.is_file()
        and path.suffix in TEXT_SUFFIXES
        and not (SKIP_DIRS & set(path.parts))
    )


def rel_path(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def covered(entries: list[dict], rel: str, line: str) -> bool:
    """该行是否被台账**具名**覆盖（`path` 必须相等、`anchor` 必须是行内子串）。"""
    return any(entry["path"] == rel and entry["anchor"] in line for entry in entries)


def violations(rel: str, text: str, entries: list[dict]) -> list[str]:
    """live 面里**未登记**的旧称出现 → 具名清单。纯函数（红证直接喂字符串）。"""
    return [
        f"{rel}:{lineno} · {line.strip()[:100]}"
        for lineno, line in enumerate(text.split("\n"), start=1)
        if OLD_NAME in line and not covered(entries, rel, line)
    ]


def stale_entries(entries: list[dict]) -> list[str]:
    """登记了却**已无命中**的条目（空豁免只许缩短）。纯函数。"""
    cache: dict[str, str] = {}
    stale: list[str] = []
    for entry in entries:
        path = entry["path"]
        if path not in cache:
            cache[path] = (REPO_ROOT / path).read_text(encoding="utf-8")
        if not any(OLD_NAME in line and entry["anchor"] in line for line in cache[path].split("\n")):
            stale.append(f"{path} · {entry['anchor']}")
    return stale


# ── 判据 1：live 面零未登记旧称 ───────────────────────────────────────────────

def test_frontend_live_face_has_no_unregistered_retired_brand():
    entries = ledger()["entries"]
    found: list[str] = []
    for path in scan_files():
        found.extend(violations(rel_path(path), path.read_text(encoding="utf-8", errors="replace"), entries))
    assert found == [], (
        f"frontend live 面仍有 {len(found)} 处未登记的「{OLD_NAME}」（它是**退役品牌名**："
        "B 端 = 黄金策，C 端 = 智能客服）：\n  "
        + "\n  ".join(found)
        + "\n确实是判据锚 / 合规小字的，登记进 tests/unit_ci_workflows/"
        "frontend_retired_brand_residue_ledger.json（只许缩短）。"
    )


# ── 判据 2：台账诚实（空豁免红 + 只许缩短 + 理由在场）─────────────────────────

def test_residue_ledger_is_honest():
    data = ledger()
    entries = data["entries"]
    assert len(entries) == data["frozen_max"], (
        f"台账条数 {len(entries)} ≠ 冻结上限 {data['frozen_max']} —— 只许缩短："
        "删条目的同批必须下调 frozen_max（上调上限 = 扩大豁免，需要评审）"
    )
    for entry in entries:
        assert entry["kind"] in KINDS, f"台账条目的 kind={entry['kind']!r} 不在 {sorted(KINDS)} 内：{entry}"
        assert len(entry["why"].strip()) >= 10, (
            f"台账条目缺理由（≥10 字；写不出理由 = 还没想清为什么要保留）：{entry}"
        )
        assert (REPO_ROOT / entry["path"]).is_file(), f"台账条目的路径不存在（扫描面已变）：{entry['path']}"

    stale = stale_entries(entries)
    assert stale == [], (
        "台账里有登记却已无命中（空豁免只许缩短，删掉这些条目并同批下调 frozen_max）：\n  "
        + "\n  ".join(stale)
    )


# ── 判据 3：扫描面自证（扫不到东西不许算通过）──────────────────────────────────

def test_scan_face_is_not_empty():
    files = scan_files()
    assert len(files) >= MIN_SCANNED_FILES, (
        f"扫描面只有 {len(files)} 个文件（下限 {MIN_SCANNED_FILES}）—— 路径写错或扫描空转，"
        "「零旧称」会是假绿"
    )
    rels = {rel_path(path) for path in files}
    for must in (
        "frontend/admin-web/src/app/(corporate)/page.tsx",
        "frontend/admin-web/tests/unit/pages/corporate-home.test.tsx",
        "frontend/bmini-app/tests/chat-empty-state.test.tsx",
    ):
        assert must in rels, f"扫描面漏了 `{must}` —— 判据扫的不是它声称的那个对象"


# ── 判据 4：红证（注入式，先自证注入生效）─────────────────────────────────────

def test_red_proof_unregistered_old_name_is_named():
    """注入一条旧称 ⇒ 判据 1 的纯函数**具名红**；补一条台账条目 ⇒ 转绿（判据不是恒真）。"""
    rel = "frontend/admin-web/src/app/(corporate)/page.tsx"
    text = "        顾客咨询直接找米宝。\n"
    found = violations(rel, text, ledger()["entries"])
    assert len(found) == 1 and found[0].startswith(f"{rel}:1"), f"未登记的旧称没被具名抓住：{found}"

    clever = [{"path": rel, "anchor": "顾客咨询直接找米宝", "kind": "negative_anchor", "why": "红证用临时条目"}]
    assert violations(rel, text, clever) == [], "登记后应转绿（否则不是按台账判定）"
    assert violations("frontend/bmini-app/README.md", text, clever) == [
        f"frontend/bmini-app/README.md:1 · 顾客咨询直接找米宝。"
    ], "换了路径仍须红（`path` 必须参与判定）"


def test_red_proof_stale_entry_is_named():
    """注入一条**已无命中**的台账条目 ⇒ 判据 2 的纯函数具名点名（空豁免不许蒙过）。"""
    entry = {
        "path": "frontend/bmini-app/README.md",
        "anchor": "这一串在文件里根本不存在（红证）",
        "kind": "negative_anchor",
        "why": "红证用临时条目：登记了却无命中必须被判红",
    }
    stale = stale_entries([entry])
    assert stale == ["frontend/bmini-app/README.md · 这一串在文件里根本不存在（红证）"], stale
