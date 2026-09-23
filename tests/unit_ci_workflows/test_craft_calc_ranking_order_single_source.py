# case_ids: MC-012, OR-032
"""「选优顺序」**单一真值源**守卫（issue #5254）。

## 病灶（本 issue 的形态）

`docs/design/order-auto-derivation.md` §3 自称「本页是单一真值源……不得各自解释口径」，
而它写的是**旧序**（目标键在前）—— 与实现 `curtain_calc.py` 里 `_rank` 的键序、上屏 `warning` 文案、
以及 `test_curtain_calc_derive_plan.py` **同文件**的判据注释**互相矛盾**，而**没有任何东西会因此变红**：
契约页说 A、引擎算 B ⇒ 下一个照契约写代码/写文档的人把漂移再复制一份（本仓反复复发的「第二份口径」）。

用户 2026-09-23 裁定 **甲**：结构 = 「**约束优先 + 目标最省**」（= 字典序多目标：约束键在前、目标键在后）。
本仓落地 = 拼接次数为**硬约束档**，用料 / 接高接宽在**同档内**比，完全并列时收敛到候选表序；
`_rank` 键序、上屏文案、契约页表述三者自此同源。

## 判据（三条，各带注入式红证）

| # | 判据 | 红证（改哪里 ⇒ 这里红） |
|---|---|---|
| C1 | 全仓（除历史记录面）**每一处**顺序表述都是同一份顺序 | 把任一落点写回旧序 |
| C2 | 扫描面**写死**为四个落点，且每处都真的扫到了顺序表述 | 把扫描面缩到只剩契约页 |
| C3 | 契约页的顺序 == `_rank` 源码里键元组的顺序（**同源**） | 改一边不改另一边 |

## 语义锚点（为什么不是「命中某四个字就红」）

顺序表述的形态 = **≥2 个锚点词 + 序标记**（箭头 / 圈码）。只命中**单个**锚点词的句子**不是**顺序表述，
例如「某个具体算例里定高买宽恰好最省料」这种**事实陈述**、候选表的**列名行**、
前端夹具里模仿服务端 `reason` 的字符串 —— 一律不得判红。`NEGATIVE_SAMPLES` 登记这些负例，
并断言它们在「放宽成命中锚点即红」的朴素规则下**会**命中 ⇒ 证明本判据的锚点确实在收窄，
负例不是「碰巧没扫到」。

## 排除面（显式登记，不是留白）

`CHANGELOG.md` 与 `acceptance/**` 是**历史记录**（§9「前几节是当时时点的诚实记录」）。
其中**确有**旧序表述 —— `acceptance/2026-09-23/order-auto-derivation/report.md` 的落点对照表逐字记着
「契约页 = 旧序 / 实现 = 新序」这个**当时的事实**。它们**不回改、也不许被判红**
⇒ 排除是**有载荷的**，`test_exclusion_is_registered_and_load_bearing` 把它钉成断言。

## 本文件自身的纪律

判据不许被**自己的文案**喂绿 / 喂红（§17.3）：本文件里顺序串一律由 `ANCHOR_FORMS` 拼出，
**字面量一个不留** —— `test_guard_file_holds_no_literal_order_claim` 守这一点。
"""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# 顺序表述的**语义锚点**：档位 ⇒ 认得的措辞（措辞可轻微不同 ⇒ 不钉字节）。
# ⚠️ `meters` 只认**强形态**（带上「最少」）：裸「用料」是普通名词，会命中具体算例的事实陈述。
ANCHOR_FORMS = {
    "splice": r"拼接次数最少|拼接最少|拼接次数",
    "meters": r"用料最少",
    "joins": r"接高\s*/\s*接宽|接高接宽",
    "table": r"候选表顺序|候选表序|表序",
}
# 生效顺序（用户 2026-09-23 裁定「甲」）= 契约页表述 = `_rank` 键序 = 上屏文案。
CANONICAL = ("splice", "meters", "joins", "table")

# 四个落点（C2 写死的扫描面）：契约页 / 引擎（键序 + 上屏文案）/ 端点 docstring / 测试模块 docstring。
LANDING_SITES = {
    "contract": "docs/design/order-auto-derivation.md",
    "engine": "backend/ai-agent-service/app/tools/curtain_calc.py",
    "endpoint": "backend/ai-agent-service/app/api/internal.py",
    "tests": "backend/ai-agent-service/tests/test_curtain_calc_derive_plan.py",
}
SCAN_PATHS = tuple(LANDING_SITES.values())
CONTRACT_PATH = LANDING_SITES["contract"]
RANK_PATH = LANDING_SITES["engine"]

# 历史记录面（§9）：不许被判红，也不许回改。
EXCLUDED_PATHS = ("CHANGELOG.md",)
EXCLUDED_PREFIXES = ("acceptance/",)

# 负例（不是顺序表述，**不许判红**）：具体算例的事实陈述 / 前端夹具里模仿服务端 reason 的字符串。
NEGATIVE_SAMPLES = (
    ("backend/ai-agent-service/tests/test_production/test_craft_calc.py", "可行集里用料最少"),
    ("frontend/admin-web/tests/unit/pages/orders-new-plan.test.tsx", "定高买宽单幅可做"),
)

_ORDER_MARK = re.compile(r"→|->|[①②③④]")
_ORDER_CONTEXT = re.compile(r"选优|顺位|排序|优先|次序|其次")


def _anchor_positions(line: str) -> dict:
    """行内命中的锚点键 ⇒ 首次出现位置（未命中 ⇒ 不出现在结果里）。"""
    out = {}
    for key, pattern in ANCHOR_FORMS.items():
        hit = re.search(pattern, line)
        if hit:
            out[key] = hit.start()
    return out


def order_claim(line: str):
    """**顺序表述**的判定本体：≥2 个锚点 + 序标记 ⇒ 返回按出现先后排出的锚点元组，否则 `None`。

    只认「把多个档位排成一条」的形态 —— 单个档位的句子（具体算例的事实陈述、候选表列名）不是顺序表述
    （负例见 `NEGATIVE_SAMPLES`）。
    """
    pos = _anchor_positions(line)
    if len(pos) < 2:
        return None
    if not (_ORDER_MARK.search(line) or _ORDER_CONTEXT.search(line)):
        return None
    return tuple(sorted(pos, key=pos.get))


def _expected(seq) -> tuple:
    """该表述**应当**有的先后（命中集合按生效顺序过滤 —— 允许只写出前几档）。"""
    return tuple(key for key in CANONICAL if key in seq)


def claims_in_text(text: str):
    """逐行扫出顺序表述：`[(行号, 锚点序)]`。"""
    return [(n, seq) for n, line in enumerate(text.splitlines(), 1)
            if (seq := order_claim(line))]


def read_text(rel: str) -> str:
    path = REPO_ROOT / rel
    assert path.is_file(), f"落点文件不存在（路径漂移 ⇒ 判红，而不是静默跳过）：{rel}"
    return path.read_text(encoding="utf-8")


def scan(rel: str):
    """某个落点里的顺序表述。"""
    return claims_in_text(read_text(rel))


def _tracked_files():
    """全仓**已跟踪**文件（`git ls-files`：天然排除 node_modules / .venv / 未跟踪产物）。"""
    proc = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT,
                          capture_output=True, text=True)
    assert proc.returncode == 0, f"`git ls-files` 失败（判据失锚 ⇒ 判红）：{proc.stderr[:200]}"
    return [path for path in proc.stdout.split("\0") if path]


def is_excluded(rel: str) -> bool:
    return rel in EXCLUDED_PATHS or rel.startswith(EXCLUDED_PREFIXES)


@lru_cache(maxsize=None)
def repo_claims(exclude_history: bool = True) -> tuple:
    """全仓顺序表述（默认排除历史记录面）：`((路径, 行号, 锚点序), ...)`。

    三条判据各要一次 ⇒ 缓存（**一次全仓读 ≈7 秒**：`ci workflow helper unit tests` 那个 job 的
    `timeout-minutes` 只有 8 分钟，别把预算花在重复读同一批文件上）。
    """
    out = []
    for rel in _tracked_files():
        if exclude_history and is_excluded(rel):
            continue
        try:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        out.extend((rel, n, seq) for n, seq in claims_in_text(text))
    return tuple(out)


# ── C1：全仓只有一份顺序表述 ──────────────────────────────────────────────────
def test_c1_every_order_claim_states_the_same_order():
    bad = [(rel, n, seq) for rel, n, seq in repo_claims() if seq != _expected(seq)]
    assert not bad, (
        "顺序表述出现了「第二份口径」（issue #5254）：\n"
        + "\n".join(f"  {rel} 第 {n} 行读到 {seq}，应为 {_expected(seq)}"
                    for rel, n, seq in bad)
        + f"\n生效顺序（契约页 / 键序 / 上屏三方同源）= {CANONICAL}"
    )


# ── C2：扫描面写死 + 每处都真扫到 ─────────────────────────────────────────────
def test_c2_scan_surface_covers_all_four_landing_sites():
    assert set(LANDING_SITES) == {"contract", "engine", "endpoint", "tests"}, (
        "落点登记表被改动（issue #5254）：四个落点一个都不许少 ——"
        "「只扫一处」正是本 issue 的病灶"
    )
    found = {rel for rel, _, _ in repo_claims()}
    assert found == set(SCAN_PATHS), (
        "全仓实测带顺序表述的文件 ≠ 扫描面：漏扫的文件里就藏着下一处漂移\n"
        f"  实测 = {sorted(found)}\n  扫描面 = {sorted(SCAN_PATHS)}"
    )
    for rel in SCAN_PATHS:
        assert scan(rel), f"{rel} 没扫到任何顺序表述 —— 漏扫（该处表述被删/被改写形态）"


# ── C3：契约页与 `_rank` 键序**同源** ─────────────────────────────────────────
_RANK_KEY_MARKERS = {
    "splice": r"splice_times",
    "meters": r'\["meters"\]',
    "joins": r"\bjoins\b",
    "table": r"order\[",
}


def rank_key_order() -> tuple:
    """从 `_rank` 的**源码**里取出键元组的先后（不是抄一份常量 —— 抄一份就是第二份口径）。"""
    src = read_text(RANK_PATH)
    body = re.search(r"def _rank\(c: Dict\[str, Any\]\):(.*?)\n    def ", src, re.S)
    assert body, "引擎里找不到 `_rank` 函数（改名/挪走 ⇒ 判据失锚，判红而不是静默跳过）"
    ret = re.search(r"return\s*\((.*?)\)\s*$", body.group(1), re.S | re.M)
    assert ret, "`_rank` 里找不到 `return (...)` 键元组（形态变了 ⇒ 判据失锚，判红）"
    expr = ret.group(1)
    pos = {}
    for key, pattern in _RANK_KEY_MARKERS.items():
        hit = re.search(pattern, expr)
        assert hit, f"`_rank` 的键元组里找不到对应键（判据失锚 ⇒ 判红）：{key} / {expr!r}"
        pos[key] = hit.start()
    return tuple(sorted(pos, key=pos.get))


def test_c3_contract_claim_is_same_source_as_rank_key_order():
    impl = rank_key_order()
    assert impl == CANONICAL, (
        f"`_rank` 的键序与用户裁定（2026-09-23）不一致：实现 {impl} / 生效 {CANONICAL}\n"
        "（改排序键 = 改算例选中的候选 = 改钱 —— 不属本判据的可改范围，须先有用户裁定）"
    )
    contract = {seq for _, seq in scan(CONTRACT_PATH)}
    assert contract == {impl}, (
        "契约页的顺序串与实现的键序**不同源**（改一边没改另一边）：\n"
        f"  契约页 = {sorted(contract)}\n  `_rank` = {impl}\n"
        "契约页是单一真值源 ⇒ 它必须把四档顺序**完整**给出，且与键序逐位相同"
    )


# ── 负例：D 类不许判红，且负例有判别力 ───────────────────────────────────────
def _find_line(rel: str, needle: str):
    for n, line in enumerate(read_text(rel).splitlines(), 1):
        if needle in line:
            return n, line
    raise AssertionError(
        f"负例登记的锚点 {needle!r} 在 {rel} 里找不到 —— 负例已过期，请重新取证（不许留白）"
    )


def test_negative_samples_are_not_order_claims():
    """具体算例的事实陈述 / 前端夹具字符串 ≠ 顺序表述 ⇒ 不许判红（判红 = 假红机器）。"""
    for rel, needle in NEGATIVE_SAMPLES:
        n, line = _find_line(rel, needle)
        assert order_claim(line) is None, (
            f"{rel} 第 {n} 行被误判成顺序表述：{line.strip()[:120]}\n"
            "它是**单个档位**的事实陈述，不是「把多个档位排成一条」的顺序表述"
        )
        assert _anchor_positions(line), (
            f"{rel} 第 {n} 行的负例**没有判别力**：它连一个锚点都不命中 ⇒"
            "「放宽锚点会判红」这件事无法被本断言证伪（负例形同虚设）"
        )


def test_checker_flags_the_superseded_order_shape():
    """判据**不是恒绿**：用锚点表拼出「目标档在前」的旧序形态 ⇒ 必须被判红。"""
    superseded = " → ".join((ANCHOR_FORMS["meters"].split("|")[0],
                            ANCHOR_FORMS["splice"].split("|")[0]))
    seq = order_claim(superseded)
    assert seq == ("meters", "splice"), (
        f"旧序形态没被识别成顺序表述 ⇒ 判据恒绿（空断言）：{superseded!r}"
    )
    assert seq != _expected(seq), f"旧序形态被判成合法 ⇒ C1 对这类表述无效：{seq}"


# ── 排除面：登记 + 有载荷 ────────────────────────────────────────────────────
def test_exclusion_is_registered_and_load_bearing():
    """显式排除历史记录面：排除**不是留白** —— 断言它当前确实挡着东西（且挡的正是旧序）。"""
    excluded = [(rel, n, seq) for rel, n, seq in repo_claims(exclude_history=False)
                if is_excluded(rel)]
    assert excluded, (
        "排除面里一条顺序表述都没有 ⇒ 这条排除是留白；"
        "要么删掉排除项，要么说明历史记录为何不含该表述"
    )
    assert any(seq != _expected(seq) for _, _, seq in excluded), (
        "排除面里没有一处**旧序**表述 ⇒ 本排除当前没有载荷（§9 的历史记录已被改动？）——"
        "若确系有意清理，请在同一个 PR 里显式说明并同步本条断言"
    )


# ── 本文件自身的纪律 ────────────────────────────────────────────────────────
def test_guard_file_holds_no_literal_order_claim():
    """判据不许被**自己的文案**喂绿 / 喂红（§17.3）：本文件不得出现字面量顺序串。"""
    mine = Path(__file__).resolve()
    assert claims_in_text(mine.read_text(encoding="utf-8")) == [], (
        "守卫自己写了字面量顺序串 ⇒ 它会把自己算成「第五个落点」（或被自己的文案喂绿）\n"
        "⇒ 顺序串一律由 `ANCHOR_FORMS` 运行时拼出"
    )
    rel = mine.relative_to(REPO_ROOT).as_posix()
    assert rel in set(_tracked_files()), (
        f"本守卫未被 git 跟踪（{rel}）：全仓扫描看不到它，`claims_in_text` 的自律也没人复核"
    )
