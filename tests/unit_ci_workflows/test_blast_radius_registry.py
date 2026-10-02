# case_ids: MC-061
"""**变更射程 → 必跑具名判据** 的注册表守卫（issue #5970）。

## 为什么有它（实证）

2026-10-02 这批并行开发给每个包下的硬约束是「**不跑全量套件**」，结果四条 PR
（#5961 / #5963 / #5965 / #5967）共 **17 条红**，形态完全相同 ——
**判据只存在于全量单测里，窄跑看不见**（清单见 `.github/scripts/blast_radius.py` 的 docstring）。

口径（逐字，提示与文档共用）：

> **「窄集」必须由「变更的射程」反推** —— 改了工具源码 ⇒ **所有扫工具源码的 meta 面都在射程内**；
> 不是靠回忆清单。

## 本文件判什么（四条各自会红，互不掩盖）

| # | 判据 | 坏形态 ⇒ 红 |
|---|---|---|
| 1 | 每个**登记的面**都能被仓内某个真实文件命中 | 加了一个永远匹配不到的面 ⇒ 提示**永远沉默**（比没有提示更坏：它看起来像「已覆盖」） |
| 2 | 每条探针的**具名判据文件真在仓里**（从命令里解析出仓内路径） | 凭印象写一个不存在的测试文件 ⇒ 人照着跑得到 `no tests ran` |
| 3 | 文档**逐面镜像**注册表（锚点 ↔ 表行 ↔ 具名判据） | 文档少一面 / 多一面 / 命令与文件对不上 ⇒ 两处各漂各的 |
| 4 | 反面锚：**没有面在文档里找不到**、**没有命令是占位符** | 「见 §15.7」那类不可执行文本被当成命令写进探针 |

边界（照实登记）：本文件判**注册表自身**的结构事实，判不了「某次改动的语义射程」
（如改了工具**行为**而没改文件路径）；也判不了「人有没有真去跑」。
"""
import importlib.util
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / ".github" / "scripts" / "blast_radius.py"
DOC_PATH = REPO_ROOT / "docs" / "wiki" / "Change-Blast-Radius.md"

#: `docs/wiki/Change-Blast-Radius.md` 的表行锚（显式 `path::` 前缀包住，避免裸文件名被 Case Trust 规则 G 判红）
ANCHOR_RE = re.compile(r"<code>([a-z][a-z0-9-]*)</code>")

#: 探针里的仓内路径解析：`pytest` 的**测试文件参数**相对 `cwd` 解析（`cwd` 由命令的 `cd` 前缀给出），
#: `source` 字段则相对仓根。两种基准都要核 —— 本 bundle 的第一硬要求就是「不许凭印象写」。
_CMD_PATH_RE = re.compile(r"[\w./$()-]*\.(?:py|ts|tsx|json|sh|sql|yml)")

_SKIP_DIRS = {".git", "node_modules", ".next", "dist", "build", "coverage",
              "__pycache__", ".venv", ".mypy_cache", ".pytest_cache"}


def _load_module():
    spec = importlib.util.spec_from_file_location("blast_radius_under_test", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _repo_files():
    """仓内全部文件（仓内相对 posix 路径）—— 跳过重目录，只用于「面是否可达」。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), REPO_ROOT).replace(os.sep, "/")
            out.append(rel)
    return out


def _unresolved_paths(probe):
    """探针里**解析不到**的仓内路径（`[]` = 全部落地）。

    解析基准三条（各自独立，覆盖三类写法）：
    ① `judgement` → 相对探针的 `cwd`（`pytest <file>` 的语义）；
    ② `source` → 相对仓根（`.sh` / `.py` 实现体的语义）；
    ③ 命令里其它路径 token → 依次试 `cwd` / 命令自己的 `cd` 目标 / 仓根
       （`cd .github && python3 render_cases.py` 属第三类）。
    """
    bases = [REPO_ROOT / probe.cwd]
    cd_target = re.search(r"\bcd\s+([\w./-]+)\s*&&", probe.command)
    if cd_target:
        bases.append(REPO_ROOT / cd_target.group(1))
    bases.append(REPO_ROOT)

    bad = []
    if probe.judgement and not (REPO_ROOT / probe.cwd / probe.judgement).exists():
        bad.append(f"{probe.cwd}/{probe.judgement}")
    if probe.source and not (REPO_ROOT / probe.source).exists():
        bad.append(probe.source)
    if not probe.judgement and not probe.source:
        bad.append(f"（探针无 judgement/source 任一声明：{probe.command}）")
    # 命令里出现的其它仓内路径也一并核（防止「命令改了、声明没改」）
    for token in _CMD_PATH_RE.findall(probe.command):
        if token in (probe.judgement, probe.source):
            continue
        if any((base / token).exists() for base in bases):
            continue
        bad.append(f"{token}（命令里出现、三个基准都解析不到）")
    return bad


# ── 判据 1：每个面都能被仓内某个真实文件命中（否则提示永远沉默）──

def test_every_face_is_reachable_by_some_path():
    mod = _load_module()
    files = _repo_files()
    silent = []
    for entry in mod.FACES:
        hit = any(mod._matches(f, pat) for f in files for pat in entry["paths"])
        if not hit:
            silent.append(f"{entry['face']} → {entry['paths']}")
    assert silent == [], (
        "下列射程面**匹配不到任何仓内文件** ⇒ growth_gate 的射程提示会永远沉默"
        "（看起来像「已覆盖」，比没有提示更坏）：\n  " + "\n  ".join(silent))


def test_every_face_has_a_why_and_unique_name():
    mod = _load_module()
    names = [e["face"] for e in mod.FACES]
    assert len(names) == len(set(names)), f"面名重复：{names}"
    blank = [e["face"] for e in mod.FACES if not (e.get("why") or "").strip()]
    assert blank == [], f"下列面缺 `why`（提示里会打印成空行）：{blank}"


# ── 判据 2：每条探针的具名判据文件真在仓里（不许凭印象写）──

def test_every_probe_points_at_a_real_file():
    mod = _load_module()
    table = mod.probes_by_face(str(REPO_ROOT))
    missing, total = [], 0
    for face, probes in table.items():
        assert probes, f"面 {face} 零探针（提示会说「欠登记面」却不给任何命令）"
        for p in probes:
            total += 1
            for bad in _unresolved_paths(p):
                missing.append(f"{face} · {p.check} → `{bad}`（命令：{p.command}）")
    assert total >= len(table), "探针清单少于面数 ⇒ 判据 2 在本语料上空转"
    assert missing == [], (
        "下列探针声明/命令指向**仓内不存在**的路径 ⇒ 照着跑会得到 `no tests ran`"
        "（不是缺失面，是假命令）：\n  " + "\n  ".join(missing))


def test_no_probe_command_is_a_placeholder():
    """命令必须是**可复制的 shell**，不许是自然语言（判据 2 的补充面）。"""
    mod = _load_module()
    bad = []
    for face, probes in mod.probes_by_face(str(REPO_ROOT)).items():
        for p in probes:
            cmd = p.command.strip()
            if cmd.startswith("见 ") or "见 migao-dev-flow" in cmd or cmd.endswith("）"):
                bad.append(f"{face} · {p.check} → `{cmd}`")
    assert bad == [], (
        "下列探针的命令**不是可复制的 shell**（人复制不了 ⇒ 提示白给）：\n  " + "\n  ".join(bad))


# ── 判据 3：文档逐面镜像注册表（锚点 ↔ 表行 ↔ 具名判据）──

def _doc_text():
    assert DOC_PATH.exists(), f"人读镜像缺失：{DOC_PATH.relative_to(REPO_ROOT)}"
    return DOC_PATH.read_text(encoding="utf8")


def test_doc_mirrors_every_face_exactly_once():
    mod = _load_module()
    text = _doc_text()
    anchors = ANCHOR_RE.findall(text)
    faces = [e["face"] for e in mod.FACES]
    missing = [f for f in faces if anchors.count(f) != 1]
    assert missing == [], (
        f"文档 `{DOC_PATH.relative_to(REPO_ROOT)}` 里下列面名的 `<code>…</code>` 锚不是**恰好一处**"
        f"（少一处 ⇒ 该面在文档里不可定位；多一处 ⇒ 两行说同一面）：{missing}\n"
        f"现取锚点集合：{sorted(set(anchors))}")
    extra = sorted(set(anchors) - set(faces))
    assert extra == [], (
        f"文档里有注册表**没有**的面锚（文档在描述一个不存在的射程面）：{extra}")


def test_doc_lists_the_named_judgement_of_every_probe():
    mod = _load_module()
    text = _doc_text()
    missing = []
    for face, probes in mod.probes_by_face(str(REPO_ROOT)).items():
        for p in probes:
            if p.judgement and p.judgement not in text:
                missing.append(f"{face} · `{p.judgement}`")
            if p.source and p.source not in text:
                missing.append(f"{face} · `{p.source}`")
    assert missing == [], (
        "下列具名判据/命令实现**没有出现在文档表里** ⇒ 提示给了命令、文档没给（两处各说各话）：\n  "
        + "\n  ".join(missing))


# ── 判据 4：提示形态（非阻塞段的逐字首行 + 无命中时空串）──

def test_hint_header_and_blocker_free_wording():
    mod = _load_module()
    hits = mod.hit_faces(["backend/ai-agent-service/app/tools/order_query.py"])
    hint = mod.render_hint(hits, str(REPO_ROOT))
    assert hint.startswith("\n## ⚠️ 变更射程提示（非阻塞，不计入 blocker）"), \
        "提示首行形态变了（判据与消费方按此解析）"
    assert "非阻塞" in hint and "blocker_count` 语义不变" in hint, "必须逐字声明不改 blocker 语义"
    assert "「窄集」必须由「变更的射程」反推" in hint, "必须逐字带上口径"
    assert "Change-Blast-Radius.md" in hint, "必须指向人读镜像"


def test_hint_is_empty_without_hits():
    mod = _load_module()
    assert mod.render_hint([], str(REPO_ROOT)) == "", "无命中必须返回空串（不许打印空标题）"
    assert mod.hit_faces(["README.md", "docs/wiki/INDEX.md"]) == [], \
        "无关文件不该命中任何射程面（否则提示变成噪音，人就不看了）"


def test_tool_source_hits_the_tool_face():
    """反面锚：**改了工具源码 ⇒ 工具面必被命中**（口径的机械表达）。"""
    mod = _load_module()
    faces = [h["face"] for h in mod.hit_faces(
        ["backend/ai-agent-service/app/tools/inventory_query.py"])]
    assert faces == ["tool"], f"工具源码应且只应命中 tool 面，现取：{faces}"
