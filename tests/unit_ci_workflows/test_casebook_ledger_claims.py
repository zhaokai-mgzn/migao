# case_ids: MC-028
"""用例文本里的「台账读数」必须等于**现取** —— 陈旧计数文本进不来。

## 病根（本单实测：一个真实例 + 一类形态）

`.github/cases/misc.yml` 的 **MC-028**（固化单）`data_checks` 的覆盖边界行写着
「`kind=action` 的 4 条**靠人执行**」，而承载它的台账
`tests/unit_ci_workflows/dev_mode_failure_modes_ledger.json` 里 `kind=action` 的条目
**现取 9 条**（#5707 本单落地时的读数）；同一条用例的 `merge_log` 还写着
「13 条具名，含 3 条未守护缺口」（同一时点：`ci_findings` **16** 条、`state=gap` **2** 条）。
⇒ **读数与它声称的对象脱钩**（`FM-A5` / `FM-R1` 的**用例库面**）：读这条用例的人拿到旧数，
而**没有任何东西会因此变红** —— 用例文本是自由文本，台账改不动它，
台账条目涨到 10 条、`FM-E18` 落地都不会碰到它。同类形态的**另一处**
（技能 §19 的索引行，`FM-E1`~旧端点的范围写法）已具名登记在台账 `NS-4`，**不在本判据射程**。

## 本文件锁什么（四条判据，逐条都有能单独变红的负向夹具）

| # | 判据 | 取法（结构化，**不读散文**） | 红证 |
|---|---|---|---|
| 1 | **记号存在**：用例文本里每一处 `FM-<族><序号>` 必须在台账对应表里真实存在 | 正则取记号 + 按族分派（A~D→`entries` · E→`ci_findings` · R→`relay_entries`） | 注入一个台账里不存在的记号 ⇒ 红 |
| 2 | **范围端点 == 现取 min/max**：`FM-<族><i>`~`FM-<族><j>` 的两个端点必须等于该表 id 的现取最小/最大 | 与判据 1 同一个正则 + 台账现取 | 把端点写成旧值（少一个号）⇒ 红 |
| 3 | **键绑定计数 == 现取，且未登记即红**：`kind=<v>` / `state=<v>` 附近紧跟的「N 条」必须等于现取；**每一处命中都必须在策展表 `CLAIMS` 里登记**（未登记 ⇒ 红，报文给可行动出口） | 策展表（同 `test_agent_permission_parity.py` 判据 13 的 `COMMENT_CLAIMS` 口径：逐条登记「锚 + 口径 + 为什么」） | 把现取 9 写成 4 ⇒ 红；注入一处未登记的键绑定计数 ⇒ 红 |
| 4 | **锚唯一**：每条登记声明的锚在文件里**恰好命中一次** | 逐条 `finditer` 计数 | 删掉该锚（或复制一份）⇒ 红 |

**fail-closed**：语料为空 / 策展表为空 ⇒ **非空违规**（不许「没东西可判 ⇒ 绿」）。
**射程元判据**：`CASEBOOK_ROOT` / `CASEBOOK_SUFFIXES` 的声明必须等于判据**实际枚举**的语料集
（语料里出现未声明后缀的文件、或声明被收窄 ⇒ 红）。

## 明确的边界（**不要**把本守卫读成覆盖面更大的东西）

逐条登记在 `UNCOVERED_FORMS`（`form` / `reason` / `owner` / `issue` / `restart_when` / `out_of_corpus`），
**只许缩短**（条数 ≤ `UNCOVERED_FORMS_FROZEN`，上限写在本文件里 ⇒ 数据文件改不动它）。
`restart_when` 写的是「什么条件下这一条**不再成立**」，**不是**「以后要补的待办」。

## 有意不做（照实登记，**不是**「已覆盖」）

- **不扫自然语言计数**（「N 条」「N 处」「N 个」这类叙述句）：`FM-A11` 的反面 ——
  26 个用例文件里这类句子大量存在，按它扫会**噪声淹掉判据**（同 `COMMENT_CLAIMS` 的边界口径）。
  真要覆盖，出口是**逐条登记**（`CLAIMS`），不是放宽正则；
- **只判「文本里的数与台账现取是不是同一个值」**：台账本身对不对是台账自己的事
  （`test_dev_mode_failure_modes.py` 的边界已登记「只保证有承载体、不保证承载体是对的」）；
- **不碰生成物**：`tests/agent_eval/eval_cases.py` 与 `docs/testing/mibao-verification-cases.md`
  由 `scripts/generated_artifacts_freshness.py`（0/1/3）保证 ≡ 源 —— 源改准、重渲染即同步
  （**手改生成物**会被它判红，两边不重复判）；
- 本判据**不改任何门禁的通过条件、不新增豁免**。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_REL = "tests/unit_ci_workflows/dev_mode_failure_modes_ledger.json"

#: 射程声明（**冻结**）：语料 = `.github/cases/**` 下的这些后缀（`README.md` 也在内 —— 它同样人读）。
CASEBOOK_ROOT = ".github/cases"
CASEBOOK_SUFFIXES = (".yml", ".md")
CASEBOOK_EXCLUDE_DIRS: tuple[str, ...] = ()

#: 三种**结构化**形态（声明即射程：要加形态，先改这里 + 补未覆盖面登记）。
#: ⚠️ 三条都只认**带记号 / 带键绑定 / 带 `~` 范围**的读数 —— 自然语言计数刻意不在面内（见 docstring）。
MARK_RE = re.compile(r"\bFM-([A-Z])(\d+)\b")
#: 范围写法在用例文本里通常带反引号（`` `FM-R1`~`FM-R7` ``）⇒ 记号与 `~` 之间允许反引号 / 空白。
RANGE_RE = re.compile(r"\bFM-([A-Z])(\d+)\b[`\s]*[~～][`\s]*FM-([A-Z])(\d+)\b")
KEY_COUNT_RE = re.compile(r"`(kind|state)=([A-Za-z_]+)`[^\n]{0,32}?([0-9]+)\s*条")
#: 用例块边界（把命中归到某条用例上，报错才**具名**到用例）。
CASE_HEAD_RE = re.compile(r"^\s*-\s*id:\s*(MC-\d+)\s*$", re.MULTILINE)

#: 记号族 → 台账表（`entries` 一个表覆盖 A~D 四个族）。
FAMILY_TO_LIST = {
    "A": "entries", "B": "entries", "C": "entries", "D": "entries",
    "E": "ci_findings", "R": "relay_entries",
}
#: 台账表 → 它的族字母（`mark-absent` 面反查用）。
LIST_TO_FAMILIES = {
    "entries": ("A", "B", "C", "D"), "ci_findings": ("E",), "relay_entries": ("R",),
}

#: 中文数字（**只给策展表的锚用**，不做全文扫描）：`FM-R4`/`FM-R7` 两条 …… 这类写法要能被登记。
CN_NUMERALS = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _as_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return CN_NUMERALS.get(token)


# ──────────────────────────────────────────────────────────────────────────────
# 策展表：**每一处关于台账的计数声明都要登记**（未登记 ⇒ 判据 3 红）
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Claim:
    """一条**已登记**的用例文本读数：`pattern` 的捕获组 = 文本里写的数；`face` = 现取口径。"""
    file: str          # 相对 `.github/cases` 的路径
    case_id: str       # 归属用例（人读定位用；判据会核它在文件里存在）
    pattern: str       # 正则：**恰好一个捕获组**，捕获文本里写的那个数
    face: str          # 见 `FACES`
    arg: tuple         # face 的参数
    why: str           # 这处读数在说什么（给下一个人看的口径）


#: face 名 → (必现「见证串」, 现取函数)。见证串保证**登记没有说谎**：
#: 一条声称是 `state-count` 的登记，锚里必须真的出现 `` `state=<那个值>` ``。
FACES: dict[str, tuple[str, Callable[[dict, tuple], int]]] = {
    "kind-count":  ("kind=", lambda led, arg: _count(led, arg[0], "kind", arg[1])),
    "state-count": ("state=", lambda led, arg: _count(led, arg[0], "state", arg[1])),
    "list-count":  ("条", lambda led, arg: len(_ids(led, arg[0]))),
}


def _ids(ledger: dict, key: str) -> list[str]:
    return [str(e.get("id")) for e in (ledger.get(key) or [])]


def _count(ledger: dict, key: str, field: str, value: str) -> int:
    return sum(1 for e in (ledger.get(key) or []) if e.get(field) == value)


CLAIMS: tuple[Claim, ...] = (
    Claim(
        file="misc.yml", case_id="MC-028",
        pattern=r"`kind=action` 的\s*\*{0,2}\s*(?:现取\s*)?([0-9]+|两|二)\s*条",
        face="kind-count", arg=("entries", "action"),
        why="覆盖边界行里「靠人执行」的那批条目数 —— 台账 `entries` 里 `kind=action` 的条数（现取）",
    ),
    Claim(
        file="misc.yml", case_id="MC-028",
        pattern=r"现取\s*([0-9]+)\s*条（`FM-E1`",
        face="list-count", arg=("ci_findings",),
        why="CI 面（清单 E）的条目数 —— 台账 `ci_findings` 的现取条数",
    ),
    Claim(
        file="misc.yml", case_id="MC-028",
        pattern=r"其中\s*`state=gap`\s*([0-9]+)\s*条",
        face="state-count", arg=("ci_findings", "gap"),
        why="CI 面里 `state=gap`（未守护）的现取条数 —— 它就是清零靶子本身",
    ),
    Claim(
        file="misc.yml", case_id="MC-038",
        pattern=r"`FM-R4`/`FM-R7`/`FM-R9`/`FM-R10`/`FM-R11`/`FM-R12`/`FM-R13`\s*(七|7)\s*条\s*`kind=action`",
        face="kind-count", arg=("relay_entries", "action"),
        why="§26 面「靠人执行」的那批条目数（由 2 条长到 6 条见台账 `PD-5`、再长到 7 条见 `PD-7`）—— 台账 `relay_entries` 里 `kind=action` 的条数（现取）",
    ),
)

#: 「记号必须**不存在**」这一面的登记（`FM-E6` 缺号：NS-1 的那条纪律没找到 durable 证据 ⇒ 未入册）。
#: 形态：`pattern` 捕获序号，`arg` = 台账表 —— 该表里**不得**存在这个号。
MARK_ABSENT_CLAIMS: tuple[Claim, ...] = (
    Claim(
        file="misc.yml", case_id="MC-028",
        pattern=r"`FM-E([0-9]+)`\s*缺号",
        face="mark-absent", arg=("ci_findings",),
        why="清单 E 的缺号事实（`FM-E6` 从未入册）—— 写成「缺号」就必须真的缺，补上即红",
    ),
)

#: 未覆盖面登记（**只许缩短**）：每条 `out_of_corpus` 是一个**面外**路径前缀，
#: 判据会核「本判据的语料确实不在它下面」（声明与事实自洽，`FM-A12` 的写法）。
UNCOVERED_FORMS: tuple[dict, ...] = (
    {
        "form": "自由文本计数（既无 `FM-` 记号、也无 `kind=`/`state=` 键绑定、也无 `~` 范围）",
        "reason": "自然语言计数与叙述句在文本层不可区分：26 个用例文件里「N 条」「N 处」大量存在，"
                  "按它扫会噪声淹掉判据（同 `COMMENT_CLAIMS` 的边界口径）。本单的实例 = MC-028 "
                  "`merge_log` 里的「13 条具名，含 3 条未守护缺口」（现取 16 / 2），"
                  "已按「历史记录 + 前向指针」口径处理，未做机械守卫。",
        "owner": "用例库线",
        "issue": "#5707",
        "restart_when": "出现「把这类读数改成由台账**渲染**（而不是手打）」的承载体时（渲染物可逐字比对）。",
        "out_of_corpus": "",
    },
    {
        "form": "中文数字计数（「两条」「三处」……）—— 除 `CLAIMS` 里已登记的条目外",
        "reason": "与上一条同因（中文数字在散文里更常见）；已登记的条目走 `CN_NUMERALS` 逐条核",
        "owner": "用例库线",
        "issue": "#5707",
        "restart_when": "需要覆盖某处中文数字读数时，按策展表**逐条登记**（MC-038 那处即示范）。",
        "out_of_corpus": "",
    },
    {
        "form": "`.github/cases/**` 之外的同类文本（`docs/**` · 源码注释 · 技能里**未被判据 19 覆盖的**节）",
        "reason": "本判据射程 = 用例库。🔴 **技能 §19 索引行这一半已销账**（#5707 同批）：它现在由 "
                  "`tests/unit_ci_workflows/test_dev_mode_failure_modes.py::test_live_index_readings_equal_the_ledger`"
                  "（判据 19）按**现取**逐值钉住（端点 ≡ 该族 id 的现取 min/max · 计数走 `INDEX_CLAIMS` 策展表 · 未登记即红），"
                  "覆盖面登记在技能 §19.3 —— 两边**不重复判**；剩下的 `docs/**` 与源码注释仍在面外（具名登记在台账 `NS-4`）。",
        "owner": "研发模式（预设）线 / 文档线",
        "issue": "#5707",
        "restart_when": "出现「`docs/**` 的同类读数也由现取钉住」的承载体时（判据 19 的射程扩到该面，或另立同款判据）。",
        "out_of_corpus": ".agent-presets/",
    },
    {
        "form": "生成物里的同族陈旧（`tests/agent_eval/eval_cases.py` · `docs/testing/mibao-verification-cases.md`）",
        "reason": "生成物**不独立判**：`scripts/generated_artifacts_freshness.py`（0/1/3）已保证它 ≡ `.github/cases/**` 的源"
                  "（源改准 + 重渲染 ⇒ 同步；手改生成物它判红）⇒ 两边不重复判。",
        "owner": "用例库线（生成物机具）",
        "issue": "#5707",
        "restart_when": "生成物若改为**不再逐字转发** `data_checks`，则本判据的覆盖不再传递到它，须重新评估。",
        "out_of_corpus": "tests/agent_eval/",
    },
)
#: 未覆盖面条数的**现取上限**（冻结在本文件里 ⇒ 数据文件改不动它；只许缩短）。
UNCOVERED_FORMS_FROZEN = 4


# ──────────────────────────────────────────────────────────────────────────────
# 语料层（射程声明 == 实际枚举；两处实现相互独立）
# ──────────────────────────────────────────────────────────────────────────────

def _walk_all_files(root: Path) -> list[str]:
    """`.github/cases/**` 下的**全部**文件（不带后缀过滤）—— 射程元判据的对照面。"""
    out: list[str] = []
    base = root / CASEBOOK_ROOT
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in CASEBOOK_EXCLUDE_DIRS)
        for name in sorted(filenames):
            out.append((Path(dirpath) / name).relative_to(base).as_posix())
    return sorted(out)


def casebook_paths(root: Path | None = None) -> list[str]:
    """按**冻结的后缀声明**枚举语料（判据实际读的那一份）。"""
    root = root or REPO_ROOT
    return sorted(p for p in _walk_all_files(root) if p.endswith(CASEBOOK_SUFFIXES))


def real_case_texts(root: Path | None = None) -> dict[str, str]:
    """真语料：`{相对 `.github/cases` 的路径: 文本}`。"""
    root = root or REPO_ROOT
    return {p: (root / CASEBOOK_ROOT / p).read_text(encoding="utf-8") for p in casebook_paths(root)}


def load_ledger(root: Path | None = None) -> dict:
    """台账（缺文件 ⇒ fail-closed，**不是**静默跳过）。"""
    root = root or REPO_ROOT
    path = root / LEDGER_REL
    if not path.is_file():
        raise AssertionError(f"台账不存在：{LEDGER_REL} —— 本判据 fail-closed（缺台账 = 读数无真值源）")
    return json.loads(path.read_text(encoding="utf-8"))


def case_at(text: str, pos: int) -> str:
    """命中位置所在的用例号（取它之前最近的 `- id:` 行）—— 报错要**具名到用例**。"""
    found = "（未定位到用例）"
    for m in CASE_HEAD_RE.finditer(text, 0, pos):
        found = m.group(1)
    return found


# ──────────────────────────────────────────────────────────────────────────────
# 判据层（**纯函数吃文本**：红证在内存里构造坏形态，不改磁盘）
# ──────────────────────────────────────────────────────────────────────────────

def _claim_hits(text: str, claim: Claim) -> list[re.Match]:
    return list(re.finditer(claim.pattern, text))


def _witness_of(claim: Claim) -> str:
    if claim.face in FACES:
        prefix, _ = FACES[claim.face]
        return f"{prefix}{claim.arg[1]}" if prefix != "条" else "条"
    return "缺号"


def problems(
    case_texts: Mapping[str, str],
    ledger: dict,
    claims: tuple[Claim, ...] = CLAIMS,
    absent_claims: tuple[Claim, ...] = MARK_ABSENT_CLAIMS,
) -> list[str]:
    """把「用例文本」与「台账现取」对照，返回违规清单（空 = 绿）。"""
    bad: list[str] = []
    if not case_texts:
        return ["语料为空 ⇒ 本判据恒绿（fail-closed：不许『没东西可判 ⇒ 绿』）"]
    if not claims and not absent_claims:
        return ["策展表为空 ⇒ 本判据恒绿（fail-closed）"]

    # ── 判据 3/4：策展表逐条核（锚唯一 + 数 == 现取）+ mark-absent 面 ──
    for claim in claims + absent_claims:
        text = case_texts.get(claim.file)
        if text is None:
            bad.append(f"[{claim.case_id}] 登记的语料文件不在射程内：{claim.file}")
            continue
        if claim.case_id and claim.case_id not in text:
            bad.append(f"[{claim.case_id}] 该用例号在 {claim.file} 里不存在（登记指向了不存在的用例）")
        hits = _claim_hits(text, claim)
        if len(hits) != 1:
            bad.append(
                f"[{claim.case_id}] 锚必须**恰好命中一次**，实得 {len(hits)} 次："
                f"pattern={claim.pattern!r}（删掉该读数行 / 复制一份 ⇒ 红）"
            )
            continue
        token = hits[0].group(1)
        got = _as_int(token)
        if got is None:
            bad.append(f"[{claim.case_id}] 捕获到的数无法解析：{token!r}")
            continue
        if claim.face == "mark-absent":
            key = claim.arg[0]
            families = LIST_TO_FAMILIES.get(key, ())
            present = [i for f in families for i in _ids(ledger, key) if i.startswith(f"FM-{f}{got}")]
            if present:
                bad.append(
                    f"[{claim.case_id}] 文本声称 `FM-{families[0] if families else '?'}{got}` **缺号**，"
                    f"而台账 `{key}` 里它**在册**：{present} ⇒ 该读数已陈旧（销账时同批删掉这句）"
                )
            continue
        expected = FACES[claim.face][1](ledger, claim.arg)
        if got != expected:
            bad.append(
                f"[{claim.case_id}] **计数与现取脱钩**：文本写 {got}，台账现取 {expected}"
                f"（口径 = `{claim.arg[0]}` 的 {claim.face}）⇒ 改准文本，或改登记的口径"
            )

    # ── 判据 1/2/3：普查（记号存在 / 范围端点 / 键绑定计数已登记） ──
    ledger_ids: dict[str, list[str]] = {
        "entries": _ids(ledger, "entries"),
        "ci_findings": _ids(ledger, "ci_findings"),
        "relay_entries": _ids(ledger, "relay_entries"),
    }
    for rel, text in sorted(case_texts.items()):
        file_claims = [c for c in claims if c.file == rel]
        spans = [(m.start(), m.end()) for c in file_claims for m in _claim_hits(text, c)]
        #: 「缺号」声明是**有意点名一个不存在的号**（`FM-E6` 从未入册）⇒ 它所在的那一段豁免判据 1
        #: （豁免面本身由 `MARK_ABSENT_CLAIMS` 反向判：那个号真被补进台账 ⇒ 红）。
        absent_spans = [(m.start(), m.end()) for c in absent_claims if c.file == rel
                        for m in _claim_hits(text, c)]
        for m in MARK_RE.finditer(text):
            if any(s <= m.start() and m.end() <= e for s, e in absent_spans):
                continue
            family, num = m.group(1), int(m.group(2))
            key = FAMILY_TO_LIST.get(family)
            if key is None:
                bad.append(
                    f"[{case_at(text, m.start())}] 记号 `{m.group(0)}` 的族字母 `{family}` 不在声明的族里"
                    f"（A~D→`entries` · E→`ci_findings` · R→`relay_entries`）⇒ 新族要先改 `FAMILY_TO_LIST`"
                )
                continue
            if m.group(0) not in ledger_ids[key]:
                bad.append(
                    f"[{case_at(text, m.start())}] 记号 `{m.group(0)}` 在台账 `{key}` 里**不存在**"
                    f"（现取最小/最大 = {_endpoints(ledger_ids[key])}）⇒ 陈旧引用（`FM-A5`），改准或销账"
                )
        for m in RANGE_RE.finditer(text):
            fam_a, lo, fam_b, hi = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
            key = FAMILY_TO_LIST.get(fam_a)
            if key is None or fam_a != fam_b:
                bad.append(f"[{case_at(text, m.start())}] 范围 `{m.group(0)}` 跨族 / 族字母未知 ⇒ 无法对照现取")
                continue
            got = (lo, hi)
            expected = _endpoints(ledger_ids[key])
            if got != expected:
                bad.append(
                    f"[{case_at(text, m.start())}] **范围端点与现取脱钩**：文本写 {got[0]}~{got[1]}，"
                    f"台账 `{key}` 现取 {expected[0]}~{expected[1]} ⇒ 改准端点（这一处正是 `FM-R1` 的用例库面）"
                )
        for m in KEY_COUNT_RE.finditer(text):
            if any(not (m.end() <= s or m.start() >= e) for s, e in spans):
                continue
            bad.append(
                f"[{case_at(text, m.start())}] **未登记的台账计数声明**：{m.group(0)!r}"
                f"（`{m.group(1)}={m.group(2)}` 与 {m.group(3)} 条绑定）⇒ "
                f"出口二选一：① 按现取改准；② 在 `CLAIMS` 里登记（锚 + 口径 + why）"
            )
    return bad


def _endpoints(ids: list[str]) -> tuple[int, int] | tuple[None, None]:
    nums = sorted(int(re.search(r"(\d+)$", i).group(1)) for i in ids if re.search(r"(\d+)$", i))
    if not nums:
        return (None, None)
    return (nums[0], nums[-1])


# ──────────────────────────────────────────────────────────────────────────────
# 判据（真语料 + 注入式红证；全部**内存构造**）
# ──────────────────────────────────────────────────────────────────────────────

MISC = "misc.yml"


def _real() -> tuple[dict[str, str], dict]:
    return real_case_texts(), load_ledger()


def test_real_casebook_matches_the_ledger_readings():
    """承重判据：真实用例库里的台账读数 == 台账现取（四条判据一起走）。"""
    texts, ledger = _real()
    assert problems(texts, ledger) == []


def test_mutation_is_really_read():
    """自证：内存变异**真的被读到**（否则下面所有红证都是空断言）。"""
    texts, _ = _real()
    mutated = dict(texts)
    mutated[MISC] = mutated[MISC].replace("data_checks:", "data_checks:  # 变异被读到了", 1)
    assert mutated[MISC] != texts[MISC]
    assert "变异被读到了" in mutated[MISC]
    # 变异确实进了判据的取数路径：计数面照旧可解析（只改注释 ⇒ 读数不变，见下一条对照）
    assert len(KEY_COUNT_RE.findall(mutated[MISC])) == len(KEY_COUNT_RE.findall(texts[MISC]))


def test_only_adding_a_comment_is_not_red():
    """对照读数：只加一条注释 ⇒ **不红**（判据读的是结构化形态，不是散文噪声）。"""
    texts, ledger = _real()
    mutated = dict(texts)
    mutated[MISC] = mutated[MISC] + "\n# 注释：本行没有任何读数，不该被读成声明\n"
    assert problems(mutated, ledger) == []


def test_stale_count_is_red():
    """判据 3 红证：把现取数改小 1（模拟陈旧文本）⇒ 必红，且报文给出两个数。"""
    texts, ledger = _real()
    hit = _claim_hits(texts[MISC], CLAIMS[0])[0]
    written = _as_int(hit.group(1))
    stale = str(written - 1)
    mutated = dict(texts)
    mutated[MISC] = texts[MISC][: hit.start(1)] + stale + texts[MISC][hit.end(1):]
    got = problems(mutated, ledger)
    assert got and any("计数与现取脱钩" in p and stale in p for p in got), got


def test_anchor_deleted_is_red():
    """判据 4 红证：把该读数行的**全部出现**删掉 ⇒ 必红（销账必须显式）。"""
    texts, ledger = _real()
    hit = _claim_hits(texts[MISC], CLAIMS[0])[0]
    mutated = dict(texts)
    mutated[MISC] = texts[MISC][: hit.start()] + texts[MISC][hit.end():]
    got = problems(mutated, ledger)
    assert got and any("恰好命中一次" in p for p in got), got


def test_anchor_duplicated_is_red():
    """判据 4 红证：锚出现两次（两处读数互相打架）⇒ 必红。"""
    texts, ledger = _real()
    hit = _claim_hits(texts[MISC], CLAIMS[0])[0]
    mutated = dict(texts)
    mutated[MISC] = texts[MISC] + "\n# " + hit.group(0) + "\n"
    got = problems(mutated, ledger)
    assert got and any("恰好命中一次" in p for p in got), got


def test_unregistered_key_count_is_red():
    """判据 3 红证：注入一处**未登记**的键绑定计数 ⇒ 必红（出口 = 改准或登记）。"""
    texts, ledger = _real()
    specimen = "`state=guarded` 的 " + "3" + " 条"
    mutated = dict(texts)
    mutated[MISC] = texts[MISC] + "\n# 注入：" + specimen + "\n"
    got = problems(mutated, ledger)
    assert got and any("未登记的台账计数声明" in p for p in got), got


def test_phantom_mark_is_red():
    """判据 1 红证：注入一个台账里不存在的记号 ⇒ 必红（陈旧引用）。"""
    texts, ledger = _real()
    specimen = "FM-E" + "99"
    mutated = dict(texts)
    mutated[MISC] = texts[MISC] + "\n# 注入：" + specimen + "\n"
    got = problems(mutated, ledger)
    assert got and any("在台账 `ci_findings` 里**不存在**" in p for p in got), got


def test_stale_range_endpoint_is_red():
    """判据 2 红证：范围端点写成旧值（少一个号）⇒ 必红。"""
    texts, ledger = _real()
    hi = _endpoints([str(e.get("id")) for e in ledger["ci_findings"]])[1]
    specimen = "`FM-E1`~`FM-E" + str(hi - 1) + "`"
    mutated = dict(texts)
    mutated[MISC] = texts[MISC] + "\n# 注入：" + specimen + "\n"
    got = problems(mutated, ledger)
    assert got and any("范围端点与现取脱钩" in p for p in got), got


def test_absent_mark_claim_is_two_way():
    """`mark-absent` 面两个方向都判：把缺号的那个号**补进台账** ⇒ 该读数立刻陈旧 ⇒ 红。"""
    texts, ledger = _real()
    hit = _claim_hits(texts[MISC], MARK_ABSENT_CLAIMS[0])[0]
    num = _as_int(hit.group(1))
    mutated_ledger = json.loads(json.dumps(ledger))
    mutated_ledger["ci_findings"].append({"id": f"FM-E{num}", "state": "registered"})
    got = problems(texts, mutated_ledger)
    assert got and any("缺号" in p and "在册" in p for p in got), got


def test_empty_corpus_is_red():
    """fail-closed：空语料 ⇒ 红（不许「没东西可判 ⇒ 绿」）。"""
    _, ledger = _real()
    assert problems({}, ledger) != []


def test_empty_claims_is_red():
    """fail-closed：策展表被清空 ⇒ 红。"""
    texts, ledger = _real()
    assert problems(texts, ledger, claims=(), absent_claims=()) != []


def test_scope_declaration_matches_actual_walk():
    """射程元判据：**声明 == 实际** —— 语料里出现未声明后缀的文件 ⇒ 红（收窄/漏面都要先改声明）。"""
    declared = set(casebook_paths())
    actual = set(_walk_all_files(REPO_ROOT))
    assert declared, "语料枚举为空（根/后缀声明被改坏）⇒ fail-closed"
    assert declared == actual, (
        f"射程声明与实际不符：未进射程的文件 = {sorted(actual - declared)}（新后缀须先在 "
        f"`CASEBOOK_SUFFIXES` 声明）；声明了却不存在 = {sorted(declared - actual)}"
    )


def test_claim_entries_are_witnessed_and_wellformed():
    """策展表自检：承诺的口径必须被**锚里的见证串**佐证（登记不许说谎）+ 恰好一个捕获组。"""
    bad: list[str] = []
    for claim in CLAIMS + MARK_ABSENT_CLAIMS:
        witness = _witness_of(claim)
        if witness not in claim.pattern:
            bad.append(f"[{claim.case_id}] {claim.face} 的登记缺少见证串 {witness!r}：{claim.pattern!r}")
        groups = re.compile(claim.pattern).groups
        if groups != 1:
            bad.append(f"[{claim.case_id}] 捕获组必须恰好 1 个，实得 {groups}：{claim.pattern!r}")
        if claim.face != "mark-absent" and claim.face not in FACES:
            bad.append(f"[{claim.case_id}] face 未定义：{claim.face!r}")
        if not claim.why.strip():
            bad.append(f"[{claim.case_id}] 登记没有 why（下一个人看不出这处读数在说什么）")
    assert bad == []


def test_uncovered_forms_registered_and_frozen():
    """覆盖面登记：非空 + 每条五要素齐 + **只许缩短**（上限冻结在本文件里）+ 面外路径自洽。"""
    assert UNCOVERED_FORMS, "未覆盖面登记为空 = 声称覆盖一切（红）"
    assert len(UNCOVERED_FORMS) <= UNCOVERED_FORMS_FROZEN, (
        f"未覆盖面条数 {len(UNCOVERED_FORMS)} > 冻结上限 {UNCOVERED_FORMS_FROZEN} ⇒ 只许缩短"
        "（新增面必须公开抬一次上限，让它在 diff 里可见）"
    )
    bad = [
        f"未覆盖面第 {i + 1} 条缺字段：{sorted({'form', 'reason', 'owner', 'issue', 'restart_when', 'out_of_corpus'} - set(f))}"
        for i, f in enumerate(UNCOVERED_FORMS)
        if {"form", "reason", "owner", "issue", "restart_when", "out_of_corpus"} - set(f)
    ]
    assert bad == []
    corpus_files = casebook_paths()
    leaked = [
        (f["out_of_corpus"], p) for f in UNCOVERED_FORMS if f["out_of_corpus"]
        for p in corpus_files if p.startswith(f["out_of_corpus"])
    ]
    assert leaked == [], (
        f"登记为「面外」的路径其实在射程内（声明与事实脱钩）：{leaked} ⇒ "
        "要么把它移出 `UNCOVERED_FORMS`（已覆盖），要么收窄射程前先想清楚"
    )
