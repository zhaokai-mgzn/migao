# case_ids: PR-011, PR-019, PR-017, OR-014
"""跨用例「同名商品」污染：**写方不得写共享名** + 前置自断言（issue #3835）。

## 病灶（判定跑 `34908262839`，库级 + 逐轮双证据）

同一 persona 腿内 78 条用例共用一套栈/库、`EVAL_CONCURRENCY=6` 并行。**写类用例造出的
商品名撞上了种子名** ⇒ 它在**运行期**往共享命名空间里多放了一件同名商品，而按名读该商品的
用例（`PP-001`/`PR-017`/`OR-014`…）**没进串行道**（`namespaces` 只对"≥2 条用例声明同一键"
生效 ⇒ 读方不声明就没有任何隔离）：

| 证据 | 原文 |
|---|---|
| 库级（admin-api 日志） | `23:37:45.569 创建商品成功: id=d7d3dd98… name=遮光窗帘` → `23:40:46.327 删除商品成功`；而 `PR-016` 自己的窗口是 `23:35:40 → 23:37:49` ⇒ **副本在写方结束后仍存活 ≈3 分钟** |
| `PR-017` 首跑 | `R1 … product_search(products=2 total=2)` → `ai=搜索到 **2 个**同名「遮光窗帘」` ⇒ `no_success(product_update)` |
| `PP-001` 首跑 | `R1 … product_search(products=2 total=2)` → `ai=搜到两个同名「遮光窗帘」，需要先确认是哪一个` ⇒ `no_success(product_processing_item_manage)` |
| `OR-014` 首跑 | `R1 … product_search(products=2) ; interact(component=choice … options=2)` → `R2 you=遮光窗帘 · ¥100.00/米 · 库存 200`（`auto_respond` 的 choice→首项**选中了副本**）⇒ 6 轮岔路 ⇒ `no_success(order_create)` |
| 重试回落 | 上述三条重试轮 `product_search(products=1 …)` ⇒ 通过；`OR-014` 重试 `pre_clean` 原文「已去重「遮光窗帘」：删 1 件重复，保留种子 `prod_eva…`」正好对应 23:40:46 那次删除 |

**为什么既有防线都治不了这一类**：
· `product_dedupe` 只在**自己起跑前**去重（`pre_clean` 的语义是"尝试边界"），挡不住
  **运行中途**别人造出来的副本；
· **串行化**只防重叠，防不住"写方结束后的残留"（实证：副本比 PR-016 多活了 3 分钟，
  期间起跑的 PR-004/PR-021/CH-007/OR-010/OR-011/OR-028 全部 `products=2`）；
· **`namespaces` 单一声明者 = 零隔离**（`namespace_conflict_groups` 只收 ≥2 条声明的键）
  —— `PR-011` 的 `product_name:夏日清风窗帘` 就是这么"看起来有隔离"的。
⇒ 唯一根治：**写方别去写共享名**（用例自有名 + 只清理自己那个名字）。

## 本文件锁的不变式（每条都有红证）

1. `test_no_create_case_writes_a_seed_product_name`：**建品用例的商品名 ∉ 种子商品名集合**。
   **改前红**（`PR-016` 写「遮光窗帘」= `prod_eval_blackout`；`PR-011` 写「夏日清风窗帘」=
   `prod_eval_summer`；`PR-019` 写「2699系列雪尼尔窗帘面料」= `prod_eval_2699`）。
2. `test_ownership_gaps_match_the_registered_ledger`：除已修的三条外，**存量**的"名字所有权"
   缺口必须与本文件登记的清单**逐条相等**（新增即红、修好未同步清单也红）—— 清单只许缩短
   （同 `.github/case-trust-baseline.json` 的口径）。缺口定义见 `ownership_gaps`。
3. **反向守卫**：前提**真的**不成立时判据必红 —— 撞种子名 / 借用他人声明名 / 建品不声明 /
   清理目标指向别人的名字；外加"用例自有名"的正例（证明判据不是恒红）。
4. `test_read_cases_declare_the_product_count_precondition`：按名定位写对象的读方必须声明
   `precondition[product_count_for_keyword]` ⇒ 前置坏了走
   `precondition_not_applied(declared:…)`（runner 侧），而不是伪装成「agent 不干活」。

## 2026-09-24（#5247 用户裁定「B 端米宝只读化」）：**被测对象退场 ⇒ 判据/夹具改判**

`product_manage(action=create)` 已从 B 端全部 skill 解绑且写 action 从源码删除 ⇒
库内四条建品写方（`PR-008`/`PR-011`/`PR-012`/`PR-019`）全部退役（`expectations` 改判
`direct_reply`、`skip_reason` 带 `#5247`）⇒ 本文件两处"活跃态"判据**没有对象**：
① "已知污染源必须被扫描面认出"（它们不再是建品写方）；② 台账里 `PR-008`/`PR-012` 的
"清理目标不可解"缺口（写商品属性的期望已删 ⇒ 缺口不复现）。另有三条红证的**写工具槽**
用的是已不再是写工具的工具（`customer_manage(action=add_tag)` 等）⇒ 夹具不再被认作写用例、
规则 b2 静默不触发（红证假绿）。**改判口径见各用例 docstring**，共性三条：
① 判据只针对**存活**对象（退役登记必须"名副其实"：条目仍在库 + 带 `#5247` 理由 +
   不再带任何写期望、也不再是建品写方形态）；② 原断言保留为**解退役路径**的条件式守卫；
③ 红证夹具的写工具槽重锚到当前可达的写工具，**缺陷形态逐字保留** —— 判别力由合成夹具承担，
一条未放宽。
> ⚠️ 本批暴露的**判据源盲区**（值得所有"是否写方"判据警惕）：`product_manage` 退出
> `WRITE_TOOLS`（幽灵写工具处置）后，只读 `assertion_taxonomy.write_expectations` 的判据
> **对本代建品写方失明**（塞回 `product_manage(action=create)` 也认不出）⇒ 本文件因此
> 保留**两处**判据源（taxonomy 的写期望 + 本地 `_is_create_case` 的建品写方形态）。

文件末尾两组**零 LLM** 证据：① 用 runner 自己的 `check_expectation` 把"同名 2 件 ⇒ agent
澄清 ⇒ 写工具未调用 ⇒ 判红"这条因果链在纯数据上跑出来（`products=2` 红 / `1` 绿 / `0` 红）；
② `product_count_for_keyword` 的两条判据 + fail-closed 兜底 + 单一真相源。
"""
import importlib.util
import json
import re
import sys
import types
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = REPO_ROOT / ".github" / "cases"
# append（**不是** insert）：只作脚本模式的兜底解析路径，避免遮蔽同名模块（与 conftest 同款理由）。
sys.path.append(str(REPO_ROOT / "tests"))

from unit_ci_workflows._source_parsing import assigned_strings  # noqa: E402  （#5323 收敛：唯一取值口径）

#: runner 源码（`_PRECLEAN_CLEANUP_TYPES` 的真值源）。
RUNNER_SRC = REPO_ROOT / "tests" / "agent_eval" / "local_runner.py"


def _runner_cleanup_types(src: str) -> set:
    """**纯函数**：runner 的 `_PRECLEAN_CLEANUP_TYPES` 集合（唯一取值口径见 `_source_parsing.py`）。

    `#5323` 第 6 条（本轮收口）：旧口径
    `re.search(r"_PRECLEAN_CLEANUP_TYPES\\s*=\\s*frozenset\\(\\{(.*?)\\}\\)")` + 按引号 `findall`
    是在**原文**上取值 ⇒ 注释 / 文档字符串里一句同形文本即被读成集合成员。现口径 = `ast`。
    """
    members = assigned_strings(src, "_PRECLEAN_CLEANUP_TYPES", "tests/agent_eval/local_runner.py")
    assert members, "取不到 runner 的 `_PRECLEAN_CLEANUP_TYPES` 定义（判据锚点漂移了？）"
    return set(members)

#: 种子商品名 = 两个评测栈 seed **实际 INSERT 的商品名**的并集
#: （`tests/agent_eval/fixtures/xiaobu_eval_seed.sql` + `mibao_eval_seed.sql`）。
#: 用**逐条比对**而不是宽正则：本规则判的就是"名字集合的成员关系"。
SEED_PRODUCT_NAMES = (
    "遮光窗帘",                # prod_eval_blackout（小布栈）
    "北欧风窗帘",              # prod_eval_dark_green（小布栈）
    "夏日清风窗帘",            # prod_eval_summer（小布栈）
    "2699系列雪尼尔窗帘面料",  # prod_eval_2699（米宝栈）
)

#: **存量**「名字所有权」缺口登记（issue #3835 扩扫交付物；**只许缩短**）。
#: 判据见 `ownership_gaps`。这些用例的共同点是**不撞种子名**（撞种子名的三条已在本 PR 修掉）
#: ⇒ 危害面是"用例之间同名 / 清理互相误删 / 自身重试前置不等价"（`#3800` 家族），
#: 与"读方首跑前置被污染"（#3835 的病灶）不同族，故**登记不修**、另开跟随单。
REGISTERED_OWNERSHIP_GAPS = {
    # ── 2026-09-24（#5247）**两条存量缺口随被测对象退场**（照实留档，不是放宽）──────────
    # `PR-008` 原登记：「声明了自有名「测试窗帘A」但无 pre_clean ⇒ 重试前置（1 件）与
    #   首跑（0 件）不等价（#3800）」；
    # `PR-012` 原登记：「声明了自有名「测试窗帘」但无 pre_clean ⇒ 同上（#3800）」。
    # 为什么不再复现（原前提被 #5247 证伪）：B 端建品写能力整体下线 ——
    #   `product_manage(action=create)` 已从 B 端全部 skill 解绑、写 action 也从源码删除
    #   ⇒ 两条用例的 `expectations` 改判 `direct_reply`（`skip_reason` 带 #5247）
    #   ⇒ 它们**不再是建品写方**，`ownership_gaps` 的扫描面不再覆盖它们
    #   ⇒ 登记的缺口随对象退场而消失（**不是**缺口被修好 —— 能力已不存在）。
    # 台账按本判据自己的要求（「陈旧条目即红」）收缩；**口径未放宽**：任何**新**的缺口
    # 仍会让 `new == []` 变红；"扫描面如今为空"由
    # `test_the_known_polluters_are_covered_by_the_scan` 的前提自证钉住（防假绿）。
    # PR-014 / PR-015 / PR-020 三条缺口**已随 #4371 商品↔加工项解耦注销**（清单只许缩短）：
    # 它们整条用例都建立在「商品持有加工项」（建品时按适用分类过滤加工项 / 加工项自定义价落库）
    # 之上，解耦后用例已从 cases/product.yml 删除 ⇒ 缺口对象不存在，登记随之移除。
    # 留注释防被当成"漏登记"再塞回来。
    # CH-005 已于 2026-09-18 **真修**（补 namespaces[product_name:星夜] + pre_clean
    # [product_remove 自有名]）⇒ 按「清单只许缩短」从本清单移除（同一处修复顺带清掉
    # CASE-TRUST-NO-SELF-CLEAN 一条存量违规，见 .github/case-trust-baseline.json）。
    # 留注释防被当成"漏登记"再塞回来。
}

#: 「撞种子名」的实例 —— 已修，且**必须**保持修好状态（红证锚点见下）。
#: ⚠️ 2026-09-19（#4371 商品↔加工项解耦）：原三条中的 `PR-016`（「建品流程 - 分类确认后按
#: 适用商品分类过滤/优先推荐加工项」）**整条用例已删除**（其全部语义建立在"商品持有加工项 +
#: 按适用分类过滤"之上）⇒ 本元组收缩到两条。收缩**不降低判别力**：
#: `test_red_proof_pr016_seed_collision_is_caught` 仍用**合成夹具**（不读真实用例库）证明
#: 判据能认出「写种子名 + product_dedupe」这一形态，扫描面本身由
#: `test_no_create_case_writes_a_seed_product_name` 扫**全库**建品用例。
SEED_COLLISION_FIXED = ("PR-011", "PR-019")

#: **#5247 退役的建品写方** = 原「已知污染源」名册的退役去向（值 = 退役理由；**只许缩短**）。
#: 为什么需要它：`test_the_known_polluters_are_covered_by_the_scan` 的原口径是
#: 「已知污染源必须被 `_is_create_case` 认出，否则主判据恒绿空跑」—— #5247 把 B 端建品写
#: 能力整体下线（`product_manage(action=create)` 从全部 B 端 skill 解绑 + 写 action 从源码
#: 删除）⇒ 两条用例的 `expectations` 改判 `direct_reply` ⇒ 它们**不再是建品写方**
#: （`_is_create_case` 对它们本就该返回 False）⇒ 原断言对"活跃态"仍成立、对"退役态"
#: **没有对象**。改判为三问（退役登记名副其实 + 存活建品写方集必须为空 + 解退役路径
#: 扫描面必须重新认出），三问合起来**比原断言更强** —— 见该用例 docstring。
#: **不是放宽、也不是藏身处**：把真写方塞进本登记（留着写期望却登记为"已退役"）会让
#: 该用例的第一问直接变红。
RETIRED_POLLUTERS_5247 = {
    "PR-011": "#5247 建品写能力从 B 端下线 ⇒ 退役（expectations 改判 direct_reply，不再是建品写方）",
    "PR-019": "#5247 建品写能力从 B 端下线 ⇒ 退役（expectations 改判 direct_reply，不再是建品写方）",
}


def _load_runner():
    """导入 `local_runner`（L0 job 只装 pytest+pyyaml → 缺 httpx 时注入最小替身）。"""
    sys.path.insert(0, str(REPO_ROOT / "tests" / "agent_eval"))
    try:
        import httpx  # noqa: F401
    except ImportError:                      # pragma: no cover - 本地 venv 有 httpx
        stub = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                raise RuntimeError("httpx 替身：本文件的单测不得真实发起 HTTP")

        stub.AsyncClient = _AsyncClient
        sys.modules.setdefault("httpx", stub)
    import local_runner
    return local_runner


def _all_cases() -> list:
    out = []
    for f in sorted(CASES_DIR.glob("*.yml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        for c in doc.get("cases") or []:
            c = dict(c)
            c["__file"] = f.name
            out.append(c)
    return out


def _is_create_case(case: dict) -> bool:
    """该用例是否**建商品**（`expectations[].tool == product_manage` 且 `args.action == create`）。"""
    for exp in case.get("expectations") or []:
        if not isinstance(exp, dict):
            continue
        if str(exp.get("tool") or "").strip() != "product_manage":
            continue
        args = exp.get("args") or {}
        if isinstance(args, dict) and str(args.get("action") or "").strip() == "create":
            return True
    return False


def _declared_product_names(case: dict) -> set:
    """用例 `namespaces` 里声明的 `product_name:<X>` 的 `<X>` 集合。"""
    out = set()
    for k in case.get("namespaces") or []:
        s = str(k)
        if s.startswith("product_name:"):
            out.add(s.split(":", 1)[1])
    return out


def _written_product_names(case: dict) -> set:
    """用例**实际写入**的商品名集合 = 声明名 ∪ 结构化载荷里的 `name`。

    为什么必须读载荷：`PR-019` 改前形态正是"**写种子名但不声明**"（名字只出现在
    `auto_fill.name` / 表单 `form_values.name` 里）—— 只看 `namespaces` 会漏掉它，
    而它恰恰是三个已知污染源之一（`migao-acceptance`：判据的扫描面必须覆盖病灶）。
    """
    out = set(_declared_product_names(case))
    af = case.get("auto_fill")
    if isinstance(af, dict) and af.get("name"):
        out.add(str(af["name"]).strip())
    for ui in case.get("user_inputs") or []:
        if not isinstance(ui, dict):
            continue
        blk = ui.get("auto_fill")
        if isinstance(blk, dict):
            if blk.get("name"):
                out.add(str(blk["name"]).strip())
            fv = blk.get("form_values")
            if isinstance(fv, dict) and fv.get("name"):
                out.add(str(fv["name"]).strip())
        ar = ui.get("auto_respond")
        if isinstance(ar, dict) and isinstance(ar.get("form_values"), dict) \
                and ar["form_values"].get("name"):
            out.add(str(ar["form_values"]["name"]).strip())
    return out


def _remove_keywords(case: dict) -> set:
    """用例 `pre_clean` 里 `product_remove` 的点名目标集合。"""
    return {str(s.get("product_keyword") or "")
            for s in (case.get("pre_clean") or [])
            if isinstance(s, dict) and s.get("type") == "product_remove"}


def seed_name_writers(cases: list) -> list:
    """写**种子商品名**的建品用例清单（**纯函数** ⇒ 反向守卫可直接喂合成用例）。"""
    return sorted(str(c.get("id") or "?") for c in cases
                  if _is_create_case(c)
                  and (_written_product_names(c) & set(SEED_PRODUCT_NAMES)))


def ownership_gaps(cases: list) -> dict:
    """建品用例的「名字所有权」缺口 `{case_id: 原因}`（纯函数）。

    判据（**精确名字比对**，不用宽正则）：
      · 必须声明 ≥1 个 `product_name:*`（不声明 ⇒ 争用组不成立 ⇒ 隔离机制对它无效）；
      · 声明的名字必须出现在自己的 `user_inputs` 里（它得真是"我造的那个名字"）；
      · 名字 ∉ 种子商品名集合；
      · 名字不得与**别人声明的名字**互相**子串包含**（`product_remove` 按子串删全部）；
      · `pre_clean` 必须有 `product_remove{自有名}`（把前置复位成「不存在」——
        `product_dedupe` 只留 1 件，不构成"不存在"）。
    """
    declared_all: set = set()
    owner: dict = {}
    for c in cases:
        cid = str(c.get("id") or "?")
        for n in _declared_product_names(c):
            declared_all.add(n)
            owner.setdefault(n, []).append(cid)

    gaps = {}
    for c in cases:
        cid = str(c.get("id") or "?")
        if not _is_create_case(c):
            continue
        names = _declared_product_names(c)
        if not names:
            written = sorted(_written_product_names(c))
            gaps[cid] = ("未声明任何 product_name:*（写方不声明 ⇒ 隔离机制对它无效）"
                         + (f"；实际写入的名字：{written}" if written else ""))
            continue
        inputs = json.dumps(c.get("user_inputs") or [], ensure_ascii=False)
        reasons = []
        for n in sorted(names):
            if n not in inputs:
                reasons.append(f"声明的名字 {n!r} 不在自己的 user_inputs 里")
            if n in SEED_PRODUCT_NAMES:
                reasons.append(f"写**种子商品名** {n!r} ⇒ 运行期造出第二件同名商品（#3835）")
            peers = [o for o in owner.get(n, []) if o != cid]
            if peers:
                reasons.append(f"名字 {n!r} **也被 {peers} 声明** ⇒ 多个写方同名、"
                               f"清理会互相误删（#3800）")
            for other in sorted(declared_all - {n}):
                if n in other or other in n:
                    reasons.append(f"名字 {n!r} 与别人声明的 {other!r} 互相**子串包含**"
                                   f"⇒ `product_remove` 会连带删掉对方的商品（#3800）")
        if not (_remove_keywords(c) & names):
            reasons.append(f"`pre_clean` 未用 `product_remove` 复位自有名 {sorted(names)}"
                           f"（实际：{sorted(_remove_keywords(c)) or '无'}）")
        if reasons:
            gaps[cid] = "；".join(reasons)
    return gaps


class TestWriterOwnsItsProductName:
    def test_no_create_case_writes_a_seed_product_name(self):
        """**主判据**：建品用例的商品名 ∉ 种子商品名集合（#3835 的根治点）。

        改前：`PR-016`（遮光窗帘）/`PR-011`（夏日清风窗帘）/`PR-019`（2699系列雪尼尔窗帘面料）
        ⇒ 红；改后：空 ⇒ 绿。
        """
        bad = seed_name_writers(_all_cases())
        assert bad == [], (
            f"这些建品用例在写**种子商品名** ⇒ 运行期造出第二件同名商品，"
            f"按名读它的用例会岔路判红（#3835）：{bad}")

    def test_the_known_polluters_are_covered_by_the_scan(self):
        """扫描面自证：**已知建品写方**必须被判据覆盖到（否则主判据是空跑）。

        `migao-acceptance`「绿了但没跑」：若 `_is_create_case` 认不出它们，
        主判据恒绿、判别力为 0。

        原口径（#3835）：`PR-011`/`PR-019` 是**存活**污染源 ⇒ 直接断言
        `_is_create_case(by[cid])` 为真（认不出 = 扫描面失效）。

        #5247 证伪的前提：B 端建品写能力整体下线 ⇒ 两条用例的 `expectations` 改判
        `direct_reply`、`skip_reason` 带 `#5247` ⇒ 它们**不再是建品写方**，原断言的活跃态
        对象不存在（`_is_create_case` 对它们本就该返回 False）。改判为三问，全部 fail-closed：
          ① 退役登记**名副其实**：条目仍在库（退役 ≠ 删除）+ 确实带 `#5247` 退役理由 +
             不再带**任何写期望**、也不再是**建品写方形态**。两处判据源**都必须有**：
             `assertion_taxonomy.write_expectations`（当前可达写工具 ⇒ 堵住"塞回
             `order_create`（整工具写；#5302 后 action 级写方已归零） 之类的真写期望"）+ 本地
             `_is_create_case`（**建品写方形态**）—— 只靠前者会漏：`product_manage` 已随
             #5247 退出 `WRITE_TOOLS`（幽灵写工具处置），把
             `{"tool": "product_manage", "args": {"action": "create"}}` 塞回来
             `write_expectations` **认不出来**，而它恰恰是"混进退役登记"最可能的形态；
             ⇒ 堵死"把真写方塞进退役登记蒙混过关"；
          ② 扫描面必须认得**所有当前存活**的建品写方 ⇒ 现存库内存活建品写方集**必须为空**
             （#5247 后建品写只可能来自 B 端）——若某天写方回归/新写方未登记，本条先红，
             逼人回来重新核对扫描面，而不是让主判据在空扫描面上假绿；
          ③ **解退役路径**：把条目的写期望在内存里还原成改前形态，扫描面必须立刻重新认出它
             —— 这正是原断言的判别力，逐字保留为条件式守卫（不动用例库）。
        """
        by = {c["id"]: c for c in _all_cases()}
        tax = _taxonomy()
        # ① 退役登记名副其实
        assert set(RETIRED_POLLUTERS_5247) == set(SEED_COLLISION_FIXED), (
            "退役登记与「已修的种子撞名实例」名册漂移（两处必须同集合，防单一事实源分叉）")
        for cid, why in sorted(RETIRED_POLLUTERS_5247.items()):
            case = by.get(cid)
            assert case, (
                f"{cid} 已从用例库删除 —— 退役只改断言面，条目与理由必须留档（{why}）")
            skip = str(case.get("skip_reason") or "")
            assert "#5247" in skip, (
                f"{cid} 登记为 #5247 退役却未写明理由（{skip[:60]!r}）—— 退役必须可追溯")
            assert not tax.write_expectations(case), (
                f"{cid} 仍在退役登记里却**带着写期望**（{tax.write_expectations(case)}）"
                "⇒ 真写方被塞进退役登记蒙混过关")
            assert not _is_create_case(case), f"{cid} 仍被认作建品写方（退役不彻底）"
        # ② 扫描面必须认得所有**当前存活**的建品写方 ⇒ 该集合必须为空
        live = sorted(cid for cid, c in by.items()
                      if _is_create_case(c) and not str(c.get("skip_reason") or ""))
        assert live == [], (
            "现存库内仍有**存活**的建品写方 —— B 端建品写能力已随 #5247 下线，存活集必须为空；"
            "出现即说明建品写能力回归（或新写方未登记）⇒ 请回到本判据重新核对扫描面与台账，"
            f"不要直接删本条断言：{live}")
        # ③ 解退役路径：改前形态必须被扫描面重新认出（原断言，条件式保留）
        for cid in sorted(RETIRED_POLLUTERS_5247):
            revived = dict(by[cid])
            revived["skip_reason"] = ""
            revived["expectations"] = [{"tool": "product_manage", "args": {"action": "create"}}]
            assert _is_create_case(revived), (
                f"判据认不出这些建品用例（扫描面失效）：['{cid}'] —— 解退役（写期望还原为"
                "改前形态）后仍认不出 ⇒ 主判据 `bad == []` 恒绿、判别力为 0")

    def test_ownership_gaps_match_the_registered_ledger(self):
        """存量缺口必须与登记清单**逐条相等** —— 清单只许缩短（新增即红）。

        这不是"豁免"：任何**新**的所有权缺口都会让本断言红；修好一条却没同步清单也会红
        （防债务僵化，同 `.github/case-trust-baseline.json` 的口径）。

        ⚠️ 2026-09-24（#5247）：台账里 `PR-008`/`PR-012` 两条**已按本条判据自己的要求
        移除**（"这些已登记的缺口已不复现 ⇒ 必须从 `REGISTERED_OWNERSHIP_GAPS` 移除"）——
        它们的缺口建立在"写商品属性的建品流程"上，而 `product_manage(action=create)` 已从
        B 端下线 ⇒ 用例退役、缺口不复现（留档见台账旁的注释）。**口径未放宽**：
        `new == []` / `stale == []` 两条 fail-closed 语义逐字保留，且下面加了**前提自证**，
        让"扫描面如今为空"这件事显式化（否则本判据会在空扫描面上假绿）。
        """
        by = {c["id"]: c for c in _all_cases()}
        live = ownership_gaps(list(by.values()))
        # 前提自证（防「绿了但没跑」）：本判据的**扫描面**（建品写方）已随 #5247 全域退役 ⇒
        # `live` 必为空集。若某天存活建品写方回归，这条前提先红，逼你回来重新登记台账 ——
        # 而不是让下面的 `new == []` 在空扫描面上静默通过。
        assert [cid for cid, c in by.items()
                if _is_create_case(c) and not str(c.get("skip_reason") or "")] == [], (
            "存活建品写方已回归 —— 台账（`REGISTERED_OWNERSHIP_GAPS`）必须重新核对并登记缺口")
        new = sorted(set(live) - set(REGISTERED_OWNERSHIP_GAPS))
        assert new == [], (
            "出现**未登记**的建品用例名字所有权缺口（#3835 / `#3800`）：\n  - "
            + "\n  - ".join(f"{cid}: {live[cid]}" for cid in new))
        stale = sorted(set(REGISTERED_OWNERSHIP_GAPS) - set(live))
        assert stale == [], (
            "这些已登记的缺口已不复现 ⇒ 必须从 REGISTERED_OWNERSHIP_GAPS 移除"
            f"（清单只许缩短，防债务僵化）：{stale}")

    def test_the_fixed_seed_collisions_have_no_ownership_gap(self):
        """已修用例必须**完全干净**（新判据之外的缺口也要覆盖到它们）。"""
        live = ownership_gaps(_all_cases())
        leftover = {cid: live[cid] for cid in SEED_COLLISION_FIXED if cid in live}
        assert leftover == {}, f"已修用例仍有所有权缺口：{leftover}"

    # ── 红证锚点：改前形态必红（逐条覆盖三个已知污染源）──────────────────────
    def test_red_proof_pr016_seed_collision_is_caught(self):
        """把 `PR-016` 的名字与清理目标换回**改前形态** ⇒ 判据必红。"""
        fake = [{"id": "PR-016", "user_inputs": ["录入这个商品，名称遮光窗帘，价格 100"],
                 "namespaces": ["product_name:遮光窗帘"],
                 "pre_clean": [{"type": "product_dedupe", "product_keyword": "遮光窗帘"}],
                 "expectations": [{"tool": "product_manage", "args": {"action": "create"}}]}]
        assert seed_name_writers(fake) == ["PR-016"]
        assert "PR-016" in ownership_gaps(fake)

    def test_red_proof_pr011_is_caught(self):
        """`PR-011` 的改前形态（写种子名 + 清理目标是别人的名字）⇒ 判据必红。"""
        fake = [{"id": "PR-011", "user_inputs": ["名称叫夏日清风窗帘，价格 168"],
                 "namespaces": ["product_name:测试窗帘", "product_name:夏日清风窗帘"],
                 "pre_clean": [{"type": "product_remove", "product_keyword": "测试窗帘"}],
                 "expectations": [{"tool": "product_manage", "args": {"action": "create"}}]}]
        assert seed_name_writers(fake) == ["PR-011"]
        assert "PR-011" in ownership_gaps(fake)

    def test_red_proof_pr019_is_caught(self):
        """`PR-019` 的改前形态（写米宝栈种子名 + `product_dedupe{种子名}`）⇒ 判据必红。"""
        fake = [{"id": "PR-019",
                 "user_inputs": [{"text": "根据这张图片录入商品（色卡图）"}],
                 "auto_fill": {"name": "2699系列雪尼尔窗帘面料", "price": "23.8"},
                 "namespaces": [],
                 "pre_clean": [{"type": "product_dedupe",
                                "product_keyword": "2699系列雪尼尔窗帘面料", "price": 23.8}],
                 "expectations": [{"tool": "product_manage", "args": {"action": "create"}}]}]
        assert seed_name_writers(fake) == ["PR-019"], (
            "PR-019 改前形态是「写种子名但**不声明**」—— 判据必须读结构化载荷里的 name 才认得出来")
        assert "PR-019" in ownership_gaps(fake)

    # ── 反向守卫：前提真的不成立时必须红（防"恒真判据"）──────────────────────
    def test_borrowing_another_cases_name_is_rejected(self):
        """借用**别人声明的名字**（两条写方同名）⇒ 判据必红。"""
        fake = [
            {"id": "FAKE-1", "user_inputs": ["创建商品，名称测试窗帘，价格 100"],
             "namespaces": ["product_name:测试窗帘"],
             "pre_clean": [{"type": "product_remove", "product_keyword": "测试窗帘"}],
             "expectations": [{"tool": "product_manage", "args": {"action": "create"}}]},
            {"id": "FAKE-2", "user_inputs": ["创建商品，名称测试窗帘，价格 200"],
             "namespaces": ["product_name:测试窗帘"],
             "pre_clean": [{"type": "product_remove", "product_keyword": "测试窗帘"}],
             "expectations": [{"tool": "product_manage", "args": {"action": "create"}}]},
        ]
        g = ownership_gaps(fake)
        assert "FAKE-1" in g and "FAKE-2" in g, g

    def test_create_case_without_declaration_is_rejected(self):
        """建品但**不声明**名字 ⇒ 判据必红（「有 namespaces 就有隔离」是错觉）。"""
        fake = [{"id": "FAKE-3", "user_inputs": ["创建商品，名称全新窗帘，价格 100"],
                 "namespaces": [],
                 "expectations": [{"tool": "product_manage", "args": {"action": "create"}}]}]
        g = ownership_gaps(fake)
        assert "未声明任何 product_name" in g["FAKE-3"], g

    def test_cleanup_targeting_someone_elses_name_is_rejected(self):
        """`pre_clean` 去清**别人的名字**（⇒ 复位不了自己的前置）⇒ 判据必红。"""
        fake = [{"id": "FAKE-4", "user_inputs": ["创建商品，名称甲乙丙帘，价格 100"],
                 "namespaces": ["product_name:甲乙丙帘"],
                 "pre_clean": [{"type": "product_remove", "product_keyword": "测试窗帘"}],
                 "expectations": [{"tool": "product_manage", "args": {"action": "create"}}]}]
        g = ownership_gaps(fake)
        assert "未用 `product_remove` 复位自有名" in g["FAKE-4"], g

    def test_case_owned_name_passes(self):
        """**改后绿**的最小正例：自有名 + 声明 + `product_remove{自有名}` ⇒ 无缺口。"""
        fake = [{"id": "FAKE-5", "user_inputs": ["创建商品，名称E2E建品流程样品帘，价格 100"],
                 "namespaces": ["product_name:E2E建品流程样品帘"],
                 "pre_clean": [{"type": "product_remove",
                                "product_keyword": "E2E建品流程样品帘"}],
                 "expectations": [{"tool": "product_manage", "args": {"action": "create"}}]}]
        assert seed_name_writers(fake) == []
        assert ownership_gaps(fake) == {}


def _taxonomy():
    """载入 `.github/assertion_taxonomy.py`（门禁的**单一判据源**）。"""
    spec = importlib.util.spec_from_file_location(
        "assertion_taxonomy", REPO_ROOT / ".github" / "assertion_taxonomy.py")
    tax = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tax)
    return tax


class TestCleanupTargetResolvabilityScope:
    """`CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE` 的**适用域**（#3835 实证修正）。

    命题「点名目标必须在**种子**里可解析」只在**准备型**前置上成立。**清理型**前置删的
    常常是**用例运行期自建**的对象（按设计就不在种子里，且 `_PRECLEAN_CLEANUP_TYPES`
    把"目标不存在"判为**良性 no-op**）⇒ 两类混进同一判据 = 正确修法被永远判红
    （`migao-dev-flow` §19.1「基于错误的真相模型写出的护栏 = 永远红」）。
    实证：本 PR 把三条种子撞名用例改成**用例自有名**后，`product_remove{自有名}`
    就被原判据判红了。
    """

    CODES = "CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE"

    @staticmethod
    def _catalog() -> dict:
        """最小种子目录：只放 1 件种子商品 + 1 个种子员工名（够判可解析性）。"""
        return {"products": {"遮光窗帘"}, "users": {"王五"}, "sys_users": {"王五"},
                "customer_tags": {"VIP2"}}

    def _codes(self, case: dict) -> set:
        tax = _taxonomy()
        return {v["code"] for v in tax.judge_case(case, catalog=self._catalog())}

    def test_case_owned_cleanup_target_is_exempt(self):
        """**改后绿**：清理自有名（名字来自本用例 `namespaces` 声明）⇒ 不判不可解析。

        ⚠️ 2026-09-24（#5247）夹具重锚：写工具槽由 `product_manage(action=create)` 换成
        **当前可达**的写工具 `order_create`（整工具写；#5302 后 action 级写方已归零） —— 否则夹具不被
        `judge_case` 认作写用例、规则 b2 根本不执行 ⇒ 本用例"不判不可解析"恒真（假绿）。
        缺陷形态（`pre_clean` 点名一个种子真值里解析不到的目标）逐字保留。
        """
        case = {
            "id": "FAKE-OWN-1", "title": "（夹具）清自己的产物", "persona": "mibao",
            "user_inputs": ["录入这个商品，名称E2E建品流程样品帘，价格 100"],
            "namespaces": ["product_name:E2E建品流程样品帘"],
            "expectations": [{"tool": "order_create"}],
            "must_succeed": [{"tool": "order_create"}],
            "precondition": [{"type": "product_count_for_keyword", "source": "x", "expect": 0}],
            "pre_clean": [{"type": "product_remove",
                           "product_keyword": "E2E建品流程样品帘"}],
        }
        tax = _taxonomy()
        # 非空跑自证（防同款夹具再次静默失效）：夹具必须**真的**被认作写用例 ——
        # 否则规则 b2 不执行，下面那条"不判不可解析"就是恒真断言（绿了但没跑）。
        assert tax.write_expectations(case), (
            "夹具的写工具槽失效（不在 `WRITE_TOOLS` / `WRITE_TOOL_ACTIONS` 里）⇒ "
            "规则 b2 不会执行，本用例会假绿")
        assert self.CODES not in self._codes(case), "用例自有名的清理目标被误判为不可解析"
        # 非空跑自证：**裸的可解析性判据本身就返回 False** —— 差别完全由豁免产生
        assert tax.resolve_pre_clean_target(
            "product_remove", "product_keyword", "E2E建品流程样品帘", self._catalog()) is False, (
            "夹具选错了（这个目标竟然在种子里可解析）⇒ 本用例证明不了豁免在起作用")
        assert tax.is_case_owned_cleanup_target(
            case, "product_remove", "E2E建品流程样品帘") is True

    def test_unowned_cleanup_target_is_still_blocked(self):
        """**fail-closed**：清理一个**既不在种子、也没被自己声明**的名字 ⇒ 照样判红。

        ⚠️ 2026-09-24（#5247）夹具重锚（**根因**）：原写工具槽 `product_manage(action=create)`
        已从 B 端下线、且不再是 `WRITE_TOOLS` 成员 ⇒ 夹具不被认作写用例 ⇒ 规则 b2 不触发
        ⇒ 本红证**变成假绿**（改判前实测：`assert CODES in set()` 失败）。改用当前可达的写
        工具 `order_create`（整工具写；#5302 后 action 级写方已归零）（C 端单端工具；夹具自带 `persona: mibao`
        只用于压掉 `CASE-TRUST-SINGLE-LEG-NO-PERSONA`）。**缺陷形态逐字保留**：`pre_clean[product_remove]
        .product_keyword = '幽灵商品名'` 既不在种子（`catalog.products = {遮光窗帘}`）
        也不在本用例 `namespaces` 声明里 ⇒ 必须继续判 `CASE-TRUST-PRECLEAN-TARGET-UNRESOLVABLE`。
        """
        case = {
            "id": "FAKE-OWN-2", "title": "（夹具）清别人的名字", "persona": "mibao",
            "user_inputs": ["录一个商品"],
            "namespaces": ["product_name:甲乙丙帘"],
            "expectations": [{"tool": "order_create"}],
            "must_succeed": [{"tool": "order_create"}],
            "precondition": [{"type": "product_count_for_keyword", "source": "x", "expect": 0}],
            "pre_clean": [{"type": "product_remove", "product_keyword": "幽灵商品名"}],
        }
        assert self.CODES in self._codes(case), (
            "既不在种子、也没被本用例声明的清理目标未被判红 —— 豁免范围过宽（假绿）")

    def test_preparation_type_is_not_exempt(self):
        """豁免**只对清理族**生效：准备型即便名字被自己声明，也必须继续核对种子。

        反例锚点：`employee_reactivate{employee_name: 王五}`（准备型）—— 若把它也豁免，
        就把 HR-003 这类正确用例的护栏拆掉了。

        ⚠️ 2026-09-24（#5247）夹具重锚：写工具槽 `employee_manage(action=toggle_status)`
        已随"8 个工具收窄为只读"（写 action 从源码删除）退出 `WRITE_TOOL_ACTIONS` ⇒ 夹具
        不再被认作写用例、规则 b2 不触发（红证假绿）。改用当前可达的写工具
        `order_create`（整工具写；#5302 后 action 级写方已归零）。**缺陷形态逐字保留**：准备型
        `pre_clean[employee_reactivate].employee_name = '李四'` 虽在 `namespaces` 里声明，
        仍必须按种子真值核对（种子里只有「王五」）⇒ 继续判红。
        """
        case = {
            "id": "FAKE-OWN-3", "title": "（夹具）准备型不复位", "persona": "mibao",
            "user_inputs": ["恢复王五"],
            "namespaces": ["employee_name:李四"],
            "expectations": [{"tool": "order_create"}],
            "must_succeed": [{"tool": "order_create"}],
            "precondition": [{"type": "product_count_for_keyword", "source": "x", "expect": 0}],
            "pre_clean": [{"type": "employee_reactivate", "employee_name": "李四"}],
        }
        assert self.CODES in self._codes(case), (
            "准备型的点名目标被这次豁免放过 —— 豁免范围越界（会拆掉 HR-003 的护栏）")

    def test_cu_003_shape_still_blocked(self):
        """历史形态（`CU-003` 的 `VIP2活跃` ∉ 种子标签目录）必须**继续**判红。

        ⚠️ 2026-09-24（#5247）夹具重锚（**根因**）：原写工具槽
        `customer_manage(action=add_tag)` 已随"8 个工具收窄为只读"删除（该工具现只有
        `{list, detail, list_tags}`）⇒ 夹具不被认作写用例、规则 b2 不触发（红证假绿：
        实测 `assert CODES in set()` 失败）。改用当前可达的写工具
        `order_create`（整工具写；#5302 后 action 级写方已归零）。**缺陷形态逐字保留**：`pre_clean`
        `[customer_tag_remove].tag_name = 'VIP2活跃'` 在种子标签目录（`catalog
        .customer_tags = {VIP2}`）里解析不到，且它不在 `namespaces` 声明里（声明的只有
        手机号）⇒ 必须继续判红。
        """
        case = {
            "id": "FAKE-CU-003", "title": "（夹具）CU-003 形态", "persona": "mibao",
            "user_inputs": ["给张三加VIP2活跃标签", "确认"],
            "namespaces": ["customer_phone:13800138000"],
            "expectations": [{"tool": "order_create"}],
            "must_succeed": [{"tool": "order_create"}],
            "precondition": [{"type": "product_count_for_keyword", "source": "x", "expect": 0}],
            "pre_clean": [{"type": "customer_tag_remove", "customer_keyword": "13800138000",
                           "tag_name": "VIP2活跃"}],
        }
        assert self.CODES in self._codes(case), "CU-003 的形态被放过（豁免范围过宽）"

    def test_cleanup_type_set_matches_runner_source(self):
        """`CLEANUP_PRECLEAN_TYPES` 必须与 runner 的 `_PRECLEAN_CLEANUP_TYPES` **同集合**。

        两处漂移会让本判据的适用域静默走偏（runner 把某类型当清理型、门禁当准备型，
        或反之）—— 与 `test_case_trust_gate.py` 锁 marker 一致性的同款做法。
        """
        runner_set = _runner_cleanup_types(RUNNER_SRC.read_text(encoding="utf-8"))
        tax = _taxonomy()
        assert runner_set == set(tax.CLEANUP_PRECLEAN_TYPES), (
            f"清理族集合不一致：runner={sorted(runner_set)} "
            f"taxonomy={sorted(tax.CLEANUP_PRECLEAN_TYPES)}")


class TestReadCasesDeclarePrecondition:
    """按名定位写对象的读方必须声明**可判定的前置**（`migao-dev-flow` §18.4 / 门禁 F 条）。"""

    #: ⚠️ 2026-09-19（#4371 商品↔加工项解耦）：原三条中的 `PP-001`（「加工项选择 - 分页翻页」，
    #: 按名定位「遮光窗帘」再给商品挂加工项）**整条用例已删除**（商品不再持有加工项）
    #: ⇒ 本元组收缩到两条。收缩不降低判别力：判据本身遍历 `READ_CASES` 逐条断前置声明，
    #: 而"读方必须声明前置"这条口径对**其余**按名读的用例仍由门禁 F 条全库生效。
    READ_CASES = ("PR-017", "OR-014")

    def test_read_cases_declare_the_product_count_precondition(self):
        by = {c["id"]: c for c in _all_cases()}
        for cid in self.READ_CASES:
            specs = by[cid].get("precondition") or []
            hits = [s for s in specs if isinstance(s, dict)
                    and s.get("type") == "product_count_for_keyword"
                    and s.get("source") == "遮光窗帘"]
            assert hits, (
                f"{cid} 没有声明「「遮光窗帘」唯一」这一前置 ⇒ 前置被污染时会伪装成"
                f"「agent 不干活」（#3835）：{specs}")
            assert hits[0].get("expect") == 1, (
                f"{cid} 的前置断言缺 `expect: 1`（只有漂移判据会漏掉"
                f"「基线本就不成立」那一格）：{hits[0]}")

    def test_gate_rule_f_accepts_the_declaration(self):
        """新门禁 F 条（`CASE-TRUST-NO-PRECONDITION-ASSERTION`）必须认这个形态。"""
        tax = _taxonomy()
        for cid in self.READ_CASES:
            c = next(x for x in _all_cases() if x["id"] == cid)
            ok, how = tax.declares_precondition(c)
            assert ok, f"{cid} 的 precondition 声明未被门禁认账（{how}）"


# ══════════════════════════════════════════════════════════════════════════════
# 机制红证（零 LLM、零 docker）：**同名 2 件 ⇒ agent 澄清 ⇒ 写工具未调用 ⇒ 判红**
#
# 为什么还要这一组：上面是**静态资产**判据（"名字对不对"），它不证明"名字错了会怎样"。
# 本组用 runner **自己的** `check_expectation` 把因果链跑出来 —— 两条输入的差别**只在**
# "商品库里有 1 件还是 2 件同名"，其余逐字相同；结果一条红一条绿 ⇒ 红/绿**完全由前置
# 决定**，与 agent 能力无关（这就是"判红不可归因于 agent"的可执行证明）。
# 逐轮数据取自判定跑 run 34908262839 的 mibao 腿 trace 原文（见本文件顶部表格）。
# ══════════════════════════════════════════════════════════════════════════════
lr = _load_runner()


def _round(tools, args=None, final_text="", products=None):
    """造一轮 runner 形状的结果（只填 `check_expectation` 真正读的字段）。"""
    calls = [{"name": t, "args": dict((args or {}).get(t) or {}), "success": True}
             for t in tools]
    data = {"products": [{}] * products, "total": products} if products is not None else {}
    return {
        "tool_calls": calls,
        "final_text": final_text,
        "data_by_tool": {"product_search": data} if data else {},
        "__all_tool_names": list(tools),
    }


#: `PP-001` 的首跑（污染）—— `products=2` ⇒ agent 正确地要求澄清 ⇒ 写工具从未执行
POLLUTED_ROUNDS = [
    _round(["product_search", "processing_item_query"], products=2,
           final_text="搜到两个同名「遮光窗帘」，需要先确认是哪一个"),
    _round(["interact"], products=2, final_text="请选择要添加加工项的商品"),
    _round(["interact"], products=2,
           final_text="两个「遮光窗帘」同名，需要您指定操作对象"),
]
#: `PP-001` 的重试（干净）—— `products=1` ⇒ 写工具执行
CLEAN_ROUNDS = [
    _round(["product_search", "processing_item_query"], products=1),
    _round(["interact"], products=1),
    _round(["product_processing_item_manage", "processing_item_query"],
           args={"product_processing_item_manage": {"action": "add"}}, products=1),
]
#: 反向守卫输入：**真的少一件**（`products=0`，商品缺失）—— 也必须红
MISSING_ROUNDS = [
    _round(["product_search"], products=0, final_text="没有找到「遮光窗帘」"),
    _round(["product_search"], products=0, final_text="库里查不到该商品"),
    _round([], products=0, final_text="请确认商品名称"),
]

PP001_EXPECTATIONS = [
    {"tool": "product_processing_item_manage", "args": {"action": "add"}},
    {"tool": "processing_item_query"},
]


def _score(rounds, expectations):
    """复刻 runner 的计分循环（`score = 通过数 / 总数`）。"""
    passed, failed = 0, []
    for exp in expectations:
        exp_txt = exp["tool"] if isinstance(exp, dict) else str(exp)
        exp_args = exp.get("args") if isinstance(exp, dict) else None
        if exp_args is None:
            want = exp_txt
        else:
            # `expectations` 的渲染形态（与 runner 的 `_parse_expectation` 同形）
            want = exp_txt + "(" + ", ".join(f"{k}={v}" for k, v in exp_args.items()) + ")"
        hit = any(lr.check_expectation(r, want)[0] for r in rounds)
        if hit:
            passed += 1
        else:
            failed.append(want)
    return (passed / len(expectations) if expectations else 1.0), failed


class TestPollutionIsWhatMakesTheCaseRed:
    def test_clean_precondition_is_green(self):
        """干净前置（1 件同名）⇒ 绿。"""
        score, failed = _score(CLEAN_ROUNDS, PP001_EXPECTATIONS)
        assert score == 1.0, f"干净前置竟然不绿（夹具写错了？）：{failed}"

    def test_polluted_precondition_is_red_even_though_agent_behaved_correctly(self):
        """**改前能复现**：同名 2 件 ⇒ 红，而 agent 每一轮都合规（要求澄清是**正确行为**）。

        这正是 `#3835` 的判红形态 `no_success(product_processing_item_manage)` ——
        读起来像"agent 不会加加工项"，实际是"harness 没给它一个确定的目标商品"。
        """
        score, failed = _score(POLLUTED_ROUNDS, PP001_EXPECTATIONS)
        clean_score, _ = _score(CLEAN_ROUNDS, PP001_EXPECTATIONS)
        assert len(failed) == 1 and "product_processing_item_manage" in failed[0], (
            f"污染前置下**写工具期望**竟然满足了（夹具或判据失效）：{failed}")
        assert score < clean_score, f"污染与干净的分差为 0，本组红证无判别力：{score}/{clean_score}"

    def test_reverse_guard_missing_product_still_red(self):
        """**反向守卫**：真的**少一件**（商品缺失）也必须红 —— 判据不是"只要不是 2 件就绿"。"""
        score, failed = _score(MISSING_ROUNDS, PP001_EXPECTATIONS)
        assert score == 0.0, f"商品缺失（另一种前置不成立）竟然没判红：{failed}"
        assert any("product_processing_item_manage" in f for f in failed), failed

    def test_the_two_inputs_differ_only_in_the_product_count(self):
        """**判别性自证**：红/绿两次的逐轮差别只在 `products` ⇒ 结论由前置决定。"""
        assert [r["data_by_tool"]["product_search"]["total"] for r in POLLUTED_ROUNDS] == [2, 2, 2]
        assert [r["data_by_tool"]["product_search"]["total"] for r in CLEAN_ROUNDS] == [1, 1, 1]


class TestPreconditionDriftCheckIsFailClosed:
    """`product_count_for_keyword` 的 runner 侧判据（两判据 + fail-closed）。"""

    SPEC = [{"type": "product_count_for_keyword", "source": "遮光窗帘", "expect": 1}]

    def test_declared_type_is_implemented(self):
        assert lr.check_precondition_declared(self.SPEC) == []

    def test_unknown_type_is_still_fail_closed(self):
        """**未实现的 type 仍必须 config_error**（不许为了塞新 type 放宽兜底分支）。"""
        bad = lr.check_precondition_declared([{"type": "no_such_type", "source": "x"}])
        assert bad and "没有实现" in bad[0], bad

    def test_baseline_equals_expect_is_green(self):
        assert lr.check_precondition_drift(
            self.SPEC, {"product_count_for_keyword:遮光窗帘": 1},
            {"product_count_for_keyword:遮光窗帘": 1}) == []

    def test_polluted_baseline_is_red(self):
        """判据 ①：**基线本就不成立**（开跑时已有 2 件）⇒ 红（只看漂移会漏掉这一格）。"""
        issues = lr.check_precondition_drift(
            self.SPEC, {"product_count_for_keyword:遮光窗帘": 2},
            {"product_count_for_keyword:遮光窗帘": 2})
        assert issues and "本就不成立" in issues[0], issues
        assert issues[0].startswith("precondition[product_count_for_keyword]"), issues[0]

    def test_missing_product_is_red(self):
        """判据 ①（另一侧）：真的**少一件**（0 件）也红 —— 那是另一种前置不成立。"""
        issues = lr.check_precondition_drift(
            self.SPEC, {"product_count_for_keyword:遮光窗帘": 0},
            {"product_count_for_keyword:遮光窗帘": 0})
        assert issues and "本就不成立" in issues[0], issues

    def test_mid_run_drift_is_red(self):
        """判据 ②：运行中途被并行用例造出副本（1 → 2）⇒ 红。"""
        issues = lr.check_precondition_drift(
            self.SPEC, {"product_count_for_keyword:遮光窗帘": 1},
            {"product_count_for_keyword:遮光窗帘": 2})
        assert issues and "漂移" in issues[0], issues

    def test_unreadable_probe_does_not_fake_a_verdict(self):
        """取不到读数时**不报**（网络抖动 ≠ 前置不成立）—— 与既有 `order_count_for_phone` 同口径。"""
        assert lr.check_precondition_drift(self.SPEC, {}, {}) == []

    def test_existing_order_count_type_semantics_unchanged(self):
        """回归护栏：`order_count_for_phone` 的判据行为不得因本次改动而变。"""
        spec = [{"type": "order_count_for_phone", "source": "13800138000"}]
        assert lr.check_precondition_declared(spec) == []
        assert lr.check_precondition_drift(
            spec, {"order_count_for_phone:13800138000": 4},
            {"order_count_for_phone:13800138000": 4}) == []
        drift = lr.check_precondition_drift(
            spec, {"order_count_for_phone:13800138000": 4},
            {"order_count_for_phone:13800138000": 5})
        assert drift and "漂移" in drift[0], drift
        assert "手机号" in drift[0], "既有 type 的消息措辞不得退化（可读性回归）"

    def test_failure_signature_separates_precondition_from_behavior(self):
        """前置失败与行为失败必须**分属不同根因原子**（否则归因又混在一起）。"""
        atom = lr._case_issue_atom(
            "precondition[product_count_for_keyword]: 前置在本次运行期间漂移 —— …")
        assert atom == "precondition_not_applied(declared:product_count_for_keyword)", atom
        behavior = lr._case_issue_atom(
            "product_processing_item_manage(action=add) → unmatched expectation")
        assert atom != behavior

    def test_probe_and_cleanups_share_one_query_implementation(self):
        """**单一真相源**：前置探针与两个清理动作必须共用 `_list_products_matching`。"""
        src = (REPO_ROOT / "tests" / "agent_eval" / "local_runner.py").read_text(encoding="utf-8")
        assert re.search(r"async def _list_products_matching\(", src), "共用查询函数不存在"
        assert src.count("_list_products_matching(") >= 4, (
            "`product_remove` / `product_dedupe` / `_probe_product_count` 未共用同一份"
            "「怎么算命中」的定义 ⇒ 会出现「清理按子串、计数按模糊」的口径漂移")


class TestRunnerCleanupTypeParsingIsSyntaxBased:
    """`#5323` 第 6 条成对红证：集合成员只认**代码里**的声明（且主判据照旧会红）。"""

    #: 旧口径会读成成员的三个位置：`#` 注释行 + 模块文档字符串举例 + 真声明（**前两个是陷阱**）。
    COMMENTED = (
        '# _PRECLEAN_CLEANUP_TYPES = frozenset({"ghost_cleanup"})  ← 留档注释（这不是声明）\n'
        '"""示例（说明文字，不是代码）：\n'
        '_PRECLEAN_CLEANUP_TYPES = frozenset({"ghost_cleanup"})\n'
        '"""\n'
        '_PRECLEAN_CLEANUP_TYPES = frozenset({\n'
        '    "product_remove",\n'
        '    "customer_tag_remove",\n'
        '    "employee_remove",\n'
        '})\n'
    )

    def test_comment_and_docstring_are_not_members(self):
        """负例：注释 / 文档字符串里的同形文本 ⇒ **不得**被读成成员（修前此断言必红）。"""
        got = _runner_cleanup_types(self.COMMENTED)
        assert got == {"product_remove", "customer_tag_remove", "employee_remove"}, sorted(got)
        assert "ghost_cleanup" not in got, "只在注释/文档字符串里出现的类型被读成了集合成员"

    def test_real_member_is_read_and_set_drift_still_reds(self):
        """正例（防修过头）：真写在代码里的成员 ⇒ 读到；集合漂移 ⇒ 主判据照旧红。"""
        real = _runner_cleanup_types(self.COMMENTED)
        drifted = _runner_cleanup_types(self.COMMENTED.replace('"customer_tag_remove",\n', ""))
        assert drifted == real - {"customer_tag_remove"}, sorted(drifted)
        assert drifted != real, "真声明的成员删掉后读数不变 ⇒ 判据恒真（空断言）"
        assert drifted != set(_taxonomy().CLEANUP_PRECLEAN_TYPES), (
            "漂移后的集合仍与 taxonomy 相等 ⇒ 主判据的「同集合」判据没有判别力"
        )
