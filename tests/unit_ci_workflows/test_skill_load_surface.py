# case_ids: MC-052
"""技能**加载面**只放「执行时需要」的东西：沿革必须外置（`<skill>/CHANGELOG.md`），**不得回流** `SKILL.md`。

## 病（会静默发生，且没有任何东西会因此变红）

| 事实 | 现取读数（2026-10-01，可复算） |
|---|---|
| 加载一个技能 = 把**整份** `SKILL.md` 放进上下文 | 加载器只取 frontmatter 的 `name` + `description`，调用时 `content = parsed.body.trim()`（整份正文）|
| 改动前 `migao-dev-flow/SKILL.md` | **329,631 字符**，其中沿革 = **98,219 字符 = 29.8%**（主体 = 正文 `## 版本沿革` 节，1122 条目行 / 96,269 字符；**另有 1 条散落在 §27 尾部**） |
| 沿革是什么 | **纯历史记录**（v1.1 → v1.94.0 的逐版变更说明）—— **执行流程时零需要** |
| 后果 | **每次加载技能都付一次历史账**；而「沿革该放哪」过去**没有任何判据** ⇒ 它还会长回去 |
| 🔴 **本判据写好后当场跑真实语料** | **命中 1 条**：`- v1.91.0（…）` 整条沿革**散落在 `SKILL.md` §27 尾部**（沿革节里 v1.92.0 与 v1.90.0 之间缺的正是它）⇒ 它抓的**不是假想形态**；同 PR 已把该条并入 `CHANGELOG.md` |
| 🔴 **独立验收 agent（只读复算）又抓到第 4 处** | `SKILL.md` 的 frontmatter **`description`** 仍写着「变更沿革已**迁至正文**「版本沿革」节」——**换了措辞**（「迁至」而非「写进」）⇒ 逃过了按字面替换的口径同步；而 `description` **正是每次会话注入的技能目录文案**（比正文更早、更贵）。**判据 6 就是为这一族加的** |

沿革之所以曾经在正文里，是 frontmatter `description` YAML 纯标量陷阱的绕行（v1.21 实证：2666 字符解析只剩 192）——
**绕行方向对，落点错**：不该从 frontmatter 挪进加载面，应该**挪出加载面**。
⇒ 2026-10-01（issue #5853）：沿革移到**同目录** `CHANGELOG.md`，`SKILL.md` 只留指针。本判据锁住这个形态。

## 判据

| # | 判据 | 变红的形态 |
|---|---|---|
| 1 | 语料非空（fail-closed） | 找不到任何 `skills/*/SKILL.md` ⇒ 红（「没东西可判」不是通过） |
| 2 | 🔴 **加载面不得含沿革**（牙齿） | 加载面出现沿革**节标题**（`## 版本沿革（…`）或沿革**条目行**（`- vN.N.N（…`）⇒ 红 |
| 3 | **外置 ≠ 删除** | 登记的技能缺同目录 `CHANGELOG.md`、或它不含任何 `- vN` 条目 ⇒ 红 |
| 4 | **指针在位** | 登记的技能 `SKILL.md` 里没有指向 `CHANGELOG.md` 的指针行 ⇒ 红 |
| 5 | **判别力自证**（内存构造） | 含节/条目 ⇒ 红；只含指针 ⇒ 不红；只提「沿革」二字 ⇒ 不红 |
| 6 | 🔴 **加载面不得含「旧落点」口径**（**换了措辞也算**） | 加载面出现「沿革 …（写进 / 迁至 / 移至 / 放进 / 放入 / 放在）… 正文」⇒ 红（第 4 处副本正是这个形态：措辞一换，按字面替换的同步就漏） |

**「加载面」的准确定义**（由 `load_surface_text()` 实现）：真正进上下文的两部分 = frontmatter 的 `name` / `description` 值 **＋** 正文；
**不含** frontmatter 里的 YAML 注释 —— 注释不进上下文 ⇒ 允许在那里留「此前写…」的历史说明，判据不误伤（判据 5 的第 ⑧⑨ 例就是这组对照）。

## 🔴 S4（issue #6020，2026-10-02）改判：预设内容已迁出业务仓

本判据判的是**预设内容**（两个技能的 `SKILL.md` / `CHANGELOG.md`），而 S4 之后业务仓**不再承载**
`.agent-presets/**` ⇒ 语料来源改为「**预设仓镜像**优先、否则 git 基线」：

- **预设仓镜像**：`$MIGAO_PRESET_MIRROR`（默认 `~/.migao-dev-preset-anchor`）—— 那是**权威源**；
- **git 基线**：`origin/main` → `origin/main~1` → `HEAD` 里**第一个真读得到**该路径的
  （合并前 `origin/main` 还带着它；合并后退到父提交。⚠️ CI 的 `pull_request` 检出是**浅克隆**，
  `origin/main~1` 可能**根本不解析** —— 实测本 PR 第一轮 CI 就红在这上面 ⇒ 不能钉死单个 ref）。
- 都取不到 ⇒ **红**（不是 skip：`pytest.skip` 会污染 helper-leg 的 skip 冻结读数，
  而「判不了」也不该长得像「没东西可判」）。

**职责归属**：内容侧的**常驻**守卫在**预设仓 CI**（`.github/workflows/preset-guards.yml`）；
本判据留在业务仓是因为它同时是用例 `MC-052` 点名的**机器证据**（`traces.tests`），
且「加载面不许回流沿革」这条纪律的**消费方**仍是本仓（技能在这里被加载）。

## 不判（如实登记边界，§19.1）

- **不设体积上限**：设了会挡住**正常的纪律新增**（加载面本来就该随纪律增长）；
- **正文里支撑纪律的实证叙述不动**：它们是**纪律的判据来源**，不是可外置的叙述（与沿革不同族）；
- **判不了**「沿革内容是否完整 / 该不该有条目 / 写得好不好」——那是人的事；
- **判据 6 是「字面形态」判据**：换一套完全不重叠的措辞（英文 / 「历史记在正文里」）仍在射程外 ——
  射程随**新形态出现**而扩；**别把「判据绿」读成「口径已同步」**（这正是本轮独立验收给出的教训）；
- **本节不改任何门禁的通过条件、不新增豁免。**
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 预设内容在**业务仓基线**里的前缀（S4 前的位置）。
PRESET_BASELINE_PREFIX = ".agent-presets/migao/"
#: 读预设内容的 git 基线候选（按序取第一个**真读得到**的；理由见文件头 S4 段）。
PRESET_BASELINE_REFS = ("origin/main", "origin/main~1", "HEAD")
#: 本机预设仓镜像（= 权威源）。
PRESET_MIRROR = Path(os.environ.get("MIGAO_PRESET_MIRROR") or (Path.home() / "migao-dev-preset-anchor"))


def resolve_skills_root() -> Path:
    """→ 装着**当前预设**的那个 `skills/` 目录（镜像优先，其次 git 基线 ⇒ 落到临时目录）。

    取不到 ⇒ 抛错（**fail-closed**：这不是「无对象可判」，是「语料漂了」）。
    """
    if (PRESET_MIRROR / "skills").is_dir():
        return PRESET_MIRROR / "skills"
    for ref in PRESET_BASELINE_REFS:
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-tree", "-r", "--name-only", ref],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            continue
        rels = [x for x in proc.stdout.splitlines()
                if x.startswith(PRESET_BASELINE_PREFIX + "skills/")]
        if not rels:
            continue
        out = Path(tempfile.mkdtemp(prefix="migao-skill-corpus-"))
        for rel in rels:
            blob = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "show", f"{ref}:{rel}"],
                capture_output=True, text=True,
            )
            if blob.returncode != 0:
                continue
            dst = out / Path(rel).relative_to(PRESET_BASELINE_PREFIX)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(blob.stdout, encoding="utf-8")
        if sorted(out.glob("skills/*/SKILL.md")):
            return out / "skills"
    raise AssertionError(
        "任何来源都取不到预设语料（`skills/*/SKILL.md`）—— S4 / issue #6020 后预设住在**预设仓**：\n"
        f"  · 本机镜像：{PRESET_MIRROR}（建镜像见 AGENTS.md「开发环境准备」）\n"
        f"  · git 基线候选：{list(PRESET_BASELINE_REFS)}（都不含 `{PRESET_BASELINE_PREFIX}skills/`）"
    )

#: 冻结：这些技能的沿革**已外置**，此表**只许增加**（新技能外置后请登记进来）。
EXTERNALIZED_SKILLS_FROZEN = ("migao-acceptance", "migao-dev-flow")

#: 沿革**节标题**（真节：`## 版本沿革（v1.1 → …）`）。外置后的指针行 `## 版本沿革 → 见…` **不算**。
LOG_SECTION_RE = re.compile(r"^##[ \t]*版本沿革[ \t]*[（(]", re.M)
#: 沿革**条目行**：`- v1.94.0（2026-09-30 …` / `- v1.1（AI Native …`。
LOG_ENTRY_RE = re.compile(r"^-[ \t]*v\d+\.\d+(?:\.\d+)?[ \t]*[（(]", re.M)
#: 指针行（外置后的合法形态）：`## 版本沿革 → 见同目录 \`CHANGELOG.md\``。
POINTER_RE = re.compile(r"^##[ \t]*版本沿革[^\n]*CHANGELOG\.md", re.M)
#: **旧落点**口径：沿革**写回正文**。刻意收动词族（写进/迁至/移至/放进/放入/放在）——
#: 独立验收抓到的第 4 处副本用的就是另一个动词（「迁至」），按单一字面同步必然漏。
LEGACY_HOME_RE = re.compile(r"沿革[^\n。；]{0,24}(?:写进|迁至|移至|放进|放入|放在)[^\n。；]{0,12}正文")

def skill_files() -> list[Path]:
    """现取：当前预设的技能文件清单（收集期**不**求值 —— 语料漂了要在**用例里**红，不是收集期炸）。"""
    return sorted(resolve_skills_root().glob("*/SKILL.md"))


def _skill_id(path: Path) -> str:
    return path.parent.name


def _skill_params() -> list:
    return [pytest.param(p, id=_skill_id(p)) for p in skill_files()]


def load_surface_text(skill_md_text: str) -> str:
    """**真正进上下文**的那部分：frontmatter 的 `name` / `description` 值 + 正文（**不含 YAML 注释**）。

    为什么不直接拿整份文件扫：frontmatter 里**刻意**留着「此前写『写进正文 …』」的历史说明（YAML 注释），
    它**不进上下文** ⇒ 扫整份文件会**误伤**它（假红），却**漏掉** `description` 里换措辞的副本（假绿）——
    后者正是本轮独立验收抓到的形态。
    """
    if not skill_md_text.startswith("---\n"):
        return skill_md_text
    _, raw, body = skill_md_text.split("---\n", 2)
    data = yaml.safe_load(raw) or {}
    head = "\n".join(str(data.get(key, "")) for key in ("name", "description"))
    return f"{head}\n{body}"


def load_surface_problems(text: str) -> list[str]:
    """纯函数（红证直接调它，**不碰真实文件**）：加载面里**不该有**的沿革形态。"""
    return [f"沿革节标题：{m.group(0).strip()}" for m in LOG_SECTION_RE.finditer(text)] + [
        f"沿革条目行：{m.group(0).strip()}" for m in LOG_ENTRY_RE.finditer(text)
    ]


def legacy_home_problems(text: str) -> list[str]:
    """纯函数：加载面里**不该有**的「旧落点」口径（沿革写回正文）。"""
    return [f"旧落点口径：{m.group(0).strip()}" for m in LEGACY_HOME_RE.finditer(text)]


def test_corpus_nonempty() -> None:
    """判据 1：语料非空（fail-closed）。"""
    assert skill_files(), "找不到任何 `skills/*/SKILL.md`（语料缺失 ⇒ 不可判定，不得退化成通过）"


@pytest.mark.parametrize("skill_md", _skill_params())
def test_load_surface_has_no_version_log(skill_md: Path) -> None:
    """判据 2（牙齿）：加载面不得含沿革 —— **回流即红**。"""
    problems = load_surface_problems(load_surface_text(skill_md.read_text(encoding="utf-8")))
    assert not problems, (
        f"{skill_md.parent.name} 的**加载面**里出现了沿革"
        "（加载本技能 = 为它付一次上下文；沿革执行流程时零需要）：\n  "
        + "\n  ".join(problems)
        + "\n出口（可行动）：把沿革写进**同目录** `CHANGELOG.md`（倒序，最新在上），本文件只留指针一行 —— "
        "形态见 migao-dev-flow v1.95.0 / issue #5853。"
    )


@pytest.mark.parametrize("skill_md", _skill_params())
def test_load_surface_has_no_legacy_home_wording(skill_md: Path) -> None:
    """判据 6：**换了措辞的「旧落点」副本**同样判红（独立验收抓到的第 4 处副本形态）。

    为什么单列一条：判据 2 只认两种字面形态，而口径副本会**换动词**（「迁至」vs「写进」）——
    按字面替换的同步必然漏一个，且漏的那个常常就在 `description`（每次会话都注入）。
    """
    problems = legacy_home_problems(load_surface_text(skill_md.read_text(encoding="utf-8")))
    assert not problems, (
        f"{skill_md.parent.name} 的**加载面**里还写着「沿革 … 写回正文」的旧落点口径"
        "（沿革 v1.95.0 起已移出加载面）：\n  "
        + "\n  ".join(problems)
        + "\n出口（可行动）：改成指向**同目录** `CHANGELOG.md`；历史说明请写进 YAML 注释（注释不进上下文，不算加载面）。"
    )


@pytest.mark.parametrize("name", EXTERNALIZED_SKILLS_FROZEN)
def test_externalized_log_exists_and_pointer_in_place(name: str) -> None:
    """判据 3 + 4：**外置 ≠ 删除** —— 沿革文件必须在且非空，指针必须在位。"""
    root = resolve_skills_root()
    skill_md = root / name / "SKILL.md"
    changelog = root / name / "CHANGELOG.md"
    assert skill_md.is_file(), f"{name}/SKILL.md 不存在（登记的技能被删了？登记表只许增加，删技能请同 PR 改登记）"
    assert changelog.is_file(), (
        f"{name}：登记的沿革文件 `{changelog}` **不存在** —— "
        "外置 ≠ 删除：沿革是「这条纪律为什么存在」的唯一出处，删掉即无法回溯"
    )
    body = changelog.read_text(encoding="utf-8")
    assert re.search(r"^-[ \t]*v\d+\.\d+", body, re.M), (
        f"{name}/CHANGELOG.md 里没有任何 `- vN.N` 沿革条目（被清空了？）—— 外置 ≠ 删内容"
    )
    assert POINTER_RE.search(skill_md.read_text(encoding="utf-8")), (
        f"{name}/SKILL.md 缺少指向 `CHANGELOG.md` 的**指针** —— 读者/agent 会以为沿革不存在，"
        "于是「这条纪律为什么存在」变得不可达"
    )


def test_discriminating_power_in_memory() -> None:
    """判据 5：判别力自证（**内存构造**，不读真实文件 —— 摘掉牙齿的改法必须当场变红）。

    ⚠️ 本函数**只证明判据函数有判别力**，证明不了「它接在真文件上」——
    接线证据见 PR #5854：`git archive` 出真实目录树、注入后具名判红、未注入的同一棵树判绿（双向对照）。
    """
    # ① 含沿革节（真节，带版本范围）⇒ 红
    assert load_surface_problems("## 版本沿革（v1.1 → v1.94.0）\n- v1.94.0（2026-09-30 某变更）：…\n")
    # ② 只含沿革条目、无节标题 ⇒ 同样红（**半搬半留**是最可能的回流形态）
    assert load_surface_problems("前言\n- v1.94.0（2026-09-30 某变更）：…\n")
    # ③ 外置后的合法形态：只有指针 ⇒ **不红**
    assert not load_surface_problems("## 版本沿革 → 见同目录 `CHANGELOG.md`\n\n> 约定：不回流本文件。\n")
    # ④ 对照：正文里提「沿革」二字 / 改叙述 ⇒ **不红**（否则判据会误伤正常行文）
    assert not load_surface_problems("⚠️ 口径沿革（**别照抄中间态**）：2026-09-18 后是「3 条 → 1 条」。\n")
    # ⑤⑥ 旧落点口径的**两个动词变体**都红（判据 6 的牙齿）
    assert legacy_home_problems("**变更沿革已迁至正文「版本沿革」节**（frontmatter 只放简短摘要）。")
    assert legacy_home_problems("变更沿革写进正文 `## 版本沿革` 节。")
    # ⑦ 新口径 ⇒ 不红（对照）
    assert not legacy_home_problems("**变更沿革在同目录 `CHANGELOG.md`**（v1.95.0 起移出加载面）。")
    # ⑧⑨ **加载面定义**的判别力：同样的文字，在 YAML 注释里不红、进了 description 就红
    commented = "---\nname: x\n# 此前写「变更沿革写进正文 `## 版本沿革` 节」\ndescription: 摘要\n---\n正文\n"
    assert not legacy_home_problems(load_surface_text(commented)), "YAML 注释不进上下文 ⇒ 不该红（假红对照）"
    in_desc = "---\nname: x\ndescription: 变更沿革写进正文 `## 版本沿革` 节\n---\n正文\n"
    assert legacy_home_problems(load_surface_text(in_desc)), "同样的文字进了 description ⇒ 必须红（假绿对照）"


def test_readings_printed(capsys: pytest.CaptureFixture[str]) -> None:
    """读数**现取**打印（§23 G8：只报与负载无关的工作量，不报挂钟）。

    「加载面」= `load_surface_text()` 的长度（这才是每次加载真正进上下文的字符数）；
    整份文件的字符数会**高估**（含 YAML 注释）。
    """
    for skill_md in skill_files():
        changelog = skill_md.parent / "CHANGELOG.md"
        surface = len(load_surface_text(skill_md.read_text(encoding="utf-8")))
        file_chars = len(skill_md.read_text(encoding="utf-8"))
        archived = len(changelog.read_text(encoding="utf-8")) if changelog.is_file() else 0
        print(
            f"📊 {skill_md.parent.name}：**加载面** {surface:,} 字符（文件 {file_chars:,}）· "
            f"沿革（不在加载面）{archived:,} 字符"
        )
