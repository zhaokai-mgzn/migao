# case_ids: MC-027
r"""**M4：文档与注释里的「可复算命令」必须指涉**存在的**路径**（跟踪单 issue #5699 的 P1；
设计真值源 `docs/design/rbac-single-source.md` 的 §5.2 机制 M4，源自该文件 §1.4 的实例 6）。

## 病根（为什么它比「两份分叉」更危险）

`V124` / `V125` / `V129` 三个**已发布迁移**的文件头都写着同一句「可复算判据」：

    ``grep -c "INSERT INTO permissions" docs/sql/schema.sql`` ⇒ 0

而 `docs/sql/schema.sql` **不存在**（真身已迁到建库脚本 `backend/admin-api/src/main/resources/db/init/schema.sql`）。
实跑该命令 = `No such file or directory` + **exit 2** + 打印 **0** ⇒
「**读不到 ⇒ 0 ⇒ 判据成立**」把**空断言**伪装成绿灯，**永远不会红**（设计 §1.4 实例 6 的实测）。

⇒ 前五条实例是「两份分叉，没有判据会报」；这第六条是「**判据读的是一个不存在的对象**」。
本文件修的是**这一类句子**，不是那三条实例（那三条住在禁改的迁移里 ⇒ 走台账出口 ②）。

## 判据

| # | 判据 | 红证 |
|---|---|---|
| 1 | **失效路径未登记即红**（具名：文件 + 目标路径 + 命令原文 + 该路径实跑 exit 2 的读数） | 造一条指向不存在路径的命令 ⇒ 必红（含**真语料**上「台账置空 ⇒ 三条迁移具名报出」） |
| 2 | **台账只许缩短 + 条目活着** | 加一条 ⇒ 超上限必红；条目已不再命中 ⇒ 陈旧红 |
| 3 | **射程元判据**：声明（`CORPUS`）== 判据实际枚举的语料集 | 收窄声明 ⇒ 必红 |
| 4 | **未覆盖面台账只许缩短** | 加面 ⇒ 超上限必红；缺 reason/owner/issue ⇒ 红 |

## 覆盖面（**覆盖不到什么** —— 设计 §5.3 的 M4 边界，逐条落地）

- **识别形态 = 「反引号内的命令词 + 仓库相对路径字面量」** ⇒ ① 不写反引号、不写仓库相对路径的
  复算命令（例如只说「见建库脚本」）**扫不到**；② **裸文件名引用**（没有目录前缀、且句尾带行号
  的那种写法）不在射程 —— 本判据只认「含 `/` 的仓库相对路径」；
- 🔴 **M4 不判「那条命令的输出对不对」** —— 它只判**路径存在**。路径存在而命令本身写错
  （例如 `grep` 的模式打错）仍是盲区；
- 🔴 **本判据不区分「引用」与「使用」**：文档里**引用**一条坏命令当**证据**（例如设计 §1.4 实例 6
  逐字引用了那条命令作为病灶标本）与**真的在用它**，在文本上**不可区分** ⇒ 这类只能进台账并写明
  `kind=quoted-specimen`（同族教训：内容扫描式机制对「引用」与「使用」一视同仁）；
- **语料边界**：本判据的语料是**声明式**的（`CORPUS`），其余面（Java/Python/TS 的注释、
  `.github/workflows/**` 的 YAML）**不在面内** ⇒ 逐条登记在 `UNCOVERED_FACES`（只许缩短）。
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_CI_DIR = REPO_ROOT / "tests" / "unit_ci_workflows"
LEDGER_PATH = UNIT_CI_DIR / "recomputable_path_ledger.json"
if str(UNIT_CI_DIR) not in sys.path:
    sys.path.insert(0, str(UNIT_CI_DIR))

#: SQL 的**同一对正则**（唯一实现点在 `_sql_schema`；不在这里另起一把尺子）。
from _sql_schema import _SQL_BLOCK_COMMENT_RE, _SQL_LINE_COMMENT_RE  # noqa: E402

#: 语料（结构化声明；`test_corpus_declaration_equals_actual_scan` 把「声称」与「实扫」互相钉住）。
CORPUS = (
    {"root": "docs", "glob": "*.md", "mode": "full", "label": "文档（全文本）"},
    {
        "root": "backend/admin-api/src/main/resources",
        "glob": "*.sql",
        "mode": "sql-comments",
        "label": "已发布迁移（只扫注释；正文本文件不承载可复算判据）",
    },
)
EXCLUDE_DIRS = (
    ".git", "node_modules", ".venv", "venv", "site-packages", ".next", "dist", "build",
    "coverage", "__pycache__", "archive",
)

#: 「命令词」（设计 §5.2 的识别形态：`grep` / `python3 -c` / `pytest` / `sha256` 等）。
RECOMPUTABLE_CMDS = (
    "grep", "rg", "python3", "python", "pytest", "sha256sum", "shasum", "bash", "sh",
    "node", "npx", "cat", "wc", "sed", "awk", "jq", "find",
)
_CMD_RE = re.compile(r"(?:^|[\s;&|(])(" + "|".join(RECOMPUTABLE_CMDS) + r")\s")
_EXT_ALT = "tsx|ts|md|py|sql|java|json|sh|yml|yaml|txt"
_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./~-])((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.(?:" + _EXT_ALT + r"))(?![A-Za-z0-9_])"
)

#: 失效路径台账的上限（**只许缩短**：等于落地时的现取条数；放宽必须改本判据，diff 里看得见）。
STALE_PATH_CAP = 8

#: 未覆盖面台账（只许缩短）：M4 的语料**之外**的面，照实登记而不是假装覆盖。
UNCOVERED_FACES: tuple[dict[str, str], ...] = (
    {
        "face": "backend/**/*.java · **/*.py · frontend/**/*.ts(x) 的注释里的可复算命令",
        "reason": "语料只声明了文档与迁移注释；其余代码注释面的坏路径今天无判据（假绿方向）",
        "owner": "RBAC 跟踪单 #5699 的后续阶段（M4 扩面需先量存量）",
        "issue": "#5699",
    },
    {
        "face": ".github/workflows/**/*.yml 与 scripts/** 里的可复算命令",
        "reason": "同上：语料未声明；把工作流 YAML 纳入面会牵动 workflow 改动（超出 P1 范围）",
        "owner": "RBAC 跟踪单 #5699 的后续阶段",
        "issue": "#5699",
    },
    {
        "face": "不带反引号 / 不带仓库相对路径字面量的复算命令（例如「见建库脚本」）",
        "reason": "识别形态是「反引号 + 命令词 + 路径字面量」⇒ 散文式的指路扫不到（设计 §5.3 已登记）",
        "owner": "无机械出口（设计 §5.3 明示这一类只能靠人复核）",
        "issue": "#5699",
    },
    {
        "face": "命令本身写错（路径存在但 grep 模式 / 参数错）",
        "reason": "M4 只判**路径存在**，不判命令输出对不对（设计 §5.3 逐字登记了这一边界）",
        "owner": "无机械出口（同上）",
        "issue": "#5699",
    },
)
UNCOVERED_FACE_CAP = 4


# ══════════════════════════════════════════════════════════════════════════════
# 一、扫描（纯函数：输入 {相对路径: 文本} ⇒ 失效路径命中清单）
# ══════════════════════════════════════════════════════════════════════════════


def sql_comments(text: str) -> str:
    """SQL 的**注释文本**（复用 `_sql_schema` 的同一对正则；块注释 + `--` 行注释）。"""
    found = [m.group(0) for rx in (_SQL_BLOCK_COMMENT_RE, _SQL_LINE_COMMENT_RE) for m in rx.finditer(text)]
    return "\n".join(found)


def inline_snippets(text: str) -> list[str]:
    """反引号内的**行内片段**（单反引号、不跨行）—— 设计 §5.2 的识别形态。"""
    return [m.group(1) for m in re.finditer(r"`([^`\n]+)`", text)]


def stale_path_hits(files: dict[str, str], exists=None) -> list[dict]:
    """**纯函数**：`{仓库相对路径: 文本}` ⇒ `[{file, target, snippet}, …]`（目标路径不存在者）。

    注入式红证就是把**内存里构造的**文本喂进来（不依赖改磁盘 —— 改磁盘的变异可能不被读到）。
    """
    probe = exists if exists is not None else (lambda rel: (REPO_ROOT / rel).exists())
    mode_by_suffix = {".md": "full", ".sql": "sql-comments"}
    out: list[dict] = []
    for rel in sorted(files):
        mode = mode_by_suffix.get(Path(rel).suffix)
        assert mode, f"语料里出现未登记扩展名 {rel!r} ⇒ 扫描口径不明 ⇒ 红（fail-closed）"
        text = files[rel] if mode == "full" else sql_comments(files[rel])
        for snippet in inline_snippets(text):
            if not _CMD_RE.search(snippet):
                continue
            for m in _PATH_RE.finditer(snippet):
                target = m.group(1)
                if probe(target):
                    continue
                out.append({"file": rel, "target": target, "snippet": snippet.strip()[:160]})
    return out


def corpus_files(corpus=CORPUS) -> set[str]:
    """按**声明**枚举语料（`os.walk` 剪枝；剪枝发生在下降之前）。"""
    out: set[str] = set()
    for entry in corpus:
        base = REPO_ROOT / entry["root"]
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in set(EXCLUDE_DIRS))
            for name in sorted(filenames):
                if Path(name).match(entry["glob"]):
                    out.add((Path(dirpath) / name).resolve().relative_to(REPO_ROOT.resolve()).as_posix())
    return out


def scanned_corpus() -> set[str]:
    """判据**实际**读入的语料（与被测实现分离的第二个枚举器：`rglob`）。"""
    out: set[str] = set()
    for entry in CORPUS:
        for p in (REPO_ROOT / entry["root"]).rglob(entry["glob"]):
            if set(EXCLUDE_DIRS) & set(p.parts) or not p.is_file():
                continue
            out.add(p.resolve().relative_to(REPO_ROOT.resolve()).as_posix())
    return out


@lru_cache(maxsize=1)
def read_corpus() -> dict[str, str]:
    """读入语料全文（未命中者也在内 ⇒ 新鲜度/判别力自证有材料）。缓存：多条判据共用同一次读盘。"""
    return {rel: (REPO_ROOT / rel).read_text(encoding="utf-8") for rel in sorted(scanned_corpus())}


@lru_cache(maxsize=1)
def repo_stale_hits() -> tuple[dict, ...]:
    """仓库当前语料上的失效路径命中（缓存）。"""
    return tuple(stale_path_hits(read_corpus()))


# ══════════════════════════════════════════════════════════════════════════════
# 二、判据本体（纯函数）
# ══════════════════════════════════════════════════════════════════════════════


def unregistered_stale_paths(hits: list[dict], ledger: dict) -> list[str]:
    """**未登记即红**（具名：文件 + 目标 + 命令原文 + 真身路径提示）。"""
    registered = {(e["file"], e["target"]) for e in ledger["entries"]}
    out: list[str] = []
    for h in hits:
        if (h["file"], h["target"]) in registered:
            continue
        out.append(
            f"「可复算命令」指向**不存在**的路径：{h['target']}\n"
            f"      @ {h['file']} :: `{h['snippet']}`\n"
            "      出口（真可行动）：① 把命令改成**真身路径**（该文件允许改时）；"
            "② 若住在禁改的已发布迁移里 ⇒ 登记进 recomputable_path_ledger.json"
            "（写清 true_path / reason / owner / issue）"
        )
    return out


def stale_ledger_entries(hits: list[dict], ledger: dict) -> list[str]:
    """台账条目**活着**（不再命中 ⇒ 陈旧 ⇒ 销账；台账只许缩短）。"""
    present = {(h["file"], h["target"]) for h in hits}
    out: list[str] = []
    for e in ledger["entries"]:
        if (e["file"], e["target"]) not in present:
            out.append(f"陈旧台账条目：{e['file']} → {e['target']}（已不再命中 ⇒ 销账）")
        for key in ("kind", "true_path", "reason", "owner", "issue"):
            if not e.get(key):
                out.append(f"台账条目缺 {key!r}（必须写清真身路径与「谁看」）：{e}")
    if len(ledger["entries"]) > STALE_PATH_CAP:
        out.append(
            f"台账 {len(ledger['entries'])} 条 > 上限 {STALE_PATH_CAP} 条"
            "（只许缩短；要放宽必须显式改本判据的 STALE_PATH_CAP，diff 里看得见）"
        )
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 三、判据
# ══════════════════════════════════════════════════════════════════════════════


def test_no_unregistered_stale_recomputable_paths():
    """**M4 主判据**：文档与迁移注释里的「可复算命令」指涉的路径**必须存在**（未登记即红，具名）。"""
    hits = list(repo_stale_hits())
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    print(f"M4 现取失效路径命中 {len(hits)} 处；台账 {len(ledger['entries'])} 条")
    for h in hits:
        print(f"  · {h['target']}\n      @ {h['file']} :: `{h['snippet']}`")
    problems = unregistered_stale_paths(hits, ledger) + stale_ledger_entries(hits, ledger)
    assert problems == [], "「可复算命令」坐标不合规：\n" + "\n".join(f"  · {p}" for p in problems)


def test_corpus_declaration_equals_actual_scan():
    """**射程元判据**：声明的语料集 == 判据实际读入的语料集（收窄射程 ⇒ 必红）。"""
    declared, actual = corpus_files(), scanned_corpus()
    assert declared, "语料枚举为空 ⇒ 判据在空集上恒真（fail-closed）"
    assert declared == actual, (
        "M4 声称的语料 != 实际扫描集：\n"
        f"  声称有而实际没扫 = {sorted(declared - actual)[:6]}\n"
        f"  实际扫了而没声称 = {sorted(actual - declared)[:6]}"
    )


def test_uncovered_face_ledger_only_shrinks_and_stays_live():
    """未覆盖面台账（只许缩短）：条数 ≤ 上限，每条须有 face/reason/owner/issue。"""
    problems: list[str] = []
    if len(UNCOVERED_FACES) > UNCOVERED_FACE_CAP:
        problems.append(f"未覆盖面 {len(UNCOVERED_FACES)} 条 > 上限 {UNCOVERED_FACE_CAP} 条（只许缩短）")
    for face in UNCOVERED_FACES:
        for key in ("face", "reason", "owner", "issue"):
            if not face.get(key):
                problems.append(f"未覆盖面条目缺 {key!r}：{face}")
    assert problems == [], "未覆盖面台账不合规：\n" + "\n".join(f"  · {p}" for p in problems)


# ══════════════════════════════════════════════════════════════════════════════
# 四、注入式红证（**当场在内存里构造坏形态**，变异体直接作为判据入参）
# ══════════════════════════════════════════════════════════════════════════════


def test_three_migration_specimens_are_named_when_ledger_is_empty():
    """🔴 **现成靶子**（设计 §1.4 实例 6）：台账**置空**时，三条已发布迁移必须被**具名**报出。

    这是「M4 对这三处具名报红」的机械证据 —— 用**真语料**、只把台账换成内存里的空台账
    （不改磁盘上的台账文件）。同时给出**对照读数**：真台账下这三条**不**报红（出口 ② 生效）。
    """
    hits = list(repo_stale_hits())
    empty = {"entries": []}
    problems = unregistered_stale_paths(hits, empty)
    for specimen in (
        "backend/admin-api/src/main/resources/db/migration/V124__backfill_read_permissions.sql",
        "backend/admin-api/src/main/resources/db/migration/V125__backfill_write_permissions.sql",
        "backend/admin-api/src/main/resources/db/migration/V129__backfill_domain_read_permissions.sql",
    ):
        assert any(specimen in p for p in problems), (
            f"台账置空后 {specimen} 没被具名报出 ⇒ M4 对这三处是空断言：{problems}"
        )
    assert len(problems) >= 3, f"台账置空后命中数不足（现取 {len(problems)} 条）"
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    assert unregistered_stale_paths(hits, ledger) == [], "真台账下这三条应已登记（出口 ②）"


def test_detection_red_proofs_and_controls():
    """判别力自证 + 对照读数（**只改注释 / 指向存在的路径**必须**不红**）。

    - 坏形态 A：行内命令指向不存在的路径 ⇒ 命中且**具名**；
    - 坏形态 B：同一句写进 `.sql` 的**代码**里（不是注释）⇒ 命中（本判据扫的是注释 + 文档，
      这里用 `.md` 语料保证口径一致 ⇒ 改走 A 的语料）；
    - 对照 ①：命令指向**存在**的路径 ⇒ **不**命中；
    - 对照 ②：同一句写在**非反引号**的散文里 ⇒ **不**命中（识别形态 = 反引号）；
    - 对照 ③：`~/.cache/x.py` / `/opt/deploy.sh` 这类**非仓库相对**路径 ⇒ **不**命中。
    """
    bad = {"docs/zz_probe.md": '实跑：`grep -c "INSERT INTO permissions" docs/sql/nope.sql` ⇒ 0\n'}
    hits = stale_path_hits(bad)
    assert [h["target"] for h in hits] == ["docs/sql/nope.sql"], f"坏形态没被抓到：{hits}"
    assert "docs/zz_probe.md" in unregistered_stale_paths(hits, {"entries": []})[0], "命中没具名到文件"

    good = {"docs/zz_probe.md": "实跑：`grep -c x docs/design/rbac-single-source.md` ⇒ 1\n"}
    assert stale_path_hits(good) == [], "指向**存在**的路径却判红 ⇒ 误伤（对照读数失败）"

    prose = {"docs/zz_probe.md": "实跑：grep -c x docs/sql/nope.sql ⇒ 0（没有反引号）\n"}
    assert stale_path_hits(prose) == [], "不带反引号的散文被当命令 ⇒ 识别形态写宽了（对照读数失败）"

    external = {"docs/zz_probe.md": "`bash /opt/migao-deploy/deploy.sh`；`cat ~/Library/Caches/a.py`\n"}
    assert stale_path_hits(external) == [], "非仓库相对路径被当仓库路径 ⇒ 误伤（对照读数失败）"

    only_comments = {
        "backend/admin-api/src/main/resources/db/migration/V999__probe.sql":
            "-- 判据：`grep -c x docs/sql/nope.sql` ⇒ 0\nSELECT 1;\n",
    }
    assert [h["target"] for h in stale_path_hits(only_comments)] == ["docs/sql/nope.sql"], (
        "迁移注释里的失效路径没被读到（`.sql` 的注释模式失效）"
    )
    code_only = {
        "backend/admin-api/src/main/resources/db/migration/V999__probe.sql":
            "SELECT '`grep -c x docs/sql/nope.sql`';\n",
    }
    assert stale_path_hits(code_only) == [], (
        "`.sql` 的**代码**里的字符串被当注释读 ⇒ 口径写宽了（对照读数失败）"
    )


def test_stale_ledger_entry_is_red_and_pruning_is_green():
    """台账两个方向都判（**各自单独变红**）：

    ① **陈旧**：台账里挂一条已不命中的条目 ⇒ 必红（销账后 ⇒ 绿，对照）；
    ② **销账过度**：把一条**仍在命中**的条目删掉 ⇒ 那些命中变「未登记」⇒ 必红。
    """
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    hits = list(repo_stale_hits())
    assert stale_ledger_entries(hits, ledger) == [], "落地态台账有陈旧/缺字段问题（前提不成立）"

    ghost = copy.deepcopy(ledger)
    ghost["entries"] = ghost["entries"] + [{
        "file": "docs/zz_ghost.md", "target": "docs/zz_ghost.sql", "kind": "quoted-specimen",
        "true_path": "（无）", "reason": "红证注入", "owner": "红证", "issue": "#5699",
    }]
    assert any("zz_ghost" in p and "陈旧台账条目" in p for p in stale_ledger_entries(hits, ghost)), (
        "陈旧条目没被具名报出"
    )

    trimmed = copy.deepcopy(ledger)
    trimmed["entries"] = [e for e in trimmed["entries"] if e["target"] != "docs/sql/schema.sql"]
    unreg = unregistered_stale_paths(hits, trimmed)
    assert unreg, "把仍在命中的条目删掉后竟无「未登记」⇒ 台账不是承重判据"
    assert stale_ledger_entries(hits, trimmed) == [], "销账本身不该被报成陈旧（对照读数）"
