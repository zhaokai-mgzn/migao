# case_ids: UI-054
"""「配置就绪度」判据**单一真值**守卫（issue #6573）。

## 病根（本仓实测过一次，且**没有任何东西会变红**）

`frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx` 的就绪度注释里逐字记着：
**同一个概念两个载体** ⇒ 同一屏出现两个互相矛盾的数（用户截图实证：「工序库 40 道 · 已完成」与
「29 道工序 · 11 道没定价」并存，issue #5858）。

issue #6573 把「还缺什么、下一步去哪」的判据抽成**一个**模块
（`frontend/admin-web/src/lib/config-readiness.ts`），跨页主线（`/settings/params`）与页内五步
（`/production/routings`）**都调它**。**但**「都调它」这件事在 #6573 之前**没有判据看着**：
只要有人在 `routings` 页里写回一行 `state={x ? 'done' : 'todo'}`，两个载体就又分叉了，
而测试可能两处各自全绿 —— 这正是 `migao-dev-flow` §19 的「不会红的判据」形态。

## 判据（类级；治「同类再长回来」）

1. 判据模块存在，且**导出**了这几个纯判据（`judgeOperationsStep` / `judgeBaseRoutesStep` /
   `judgeDefaultRouteStep` / `judgeFeeCombinationsStep` / `judgeConfigSourceStep`）
   —— 名字被删/改名 ⇒ 红（下游页面会当场编译失败，这里先给一条可归因的红）。
2. 两个消费方（`production/routings/page.tsx` 与 `settings/params/page.tsx`）**都**从
   `@/lib/config-readiness` 引入判据。
3. 两个消费方**都不得**再持有自己的三态定义或就地三元判据
   （`type ReadinessState =` / `? 'done' : 'todo'` / `? 'todo' : 'done'`）—— 这就是「第二个载体」的机械形态。
4. **红证**：把上面三条的判据函数喂一段**坏的**源码，必须报出问题（否则「扫了但扫不出」与
   「根本没扫」在测试里长得一模一样 —— 空断言）。

## 边界（如实登记，不粉饰）

- 它只扫**这两个已知消费方**；将来第三个页面自己写一份就绪度口径，**本判据看不见它**
  （覆盖面写死在 `CONSUMERS` 里 —— 这是「策展清单」不是全仓扫描）。
- 它判的是「**没有第二份实现**」，**不**判判据本身的正确性（那是 `config-readiness` 的单测 +
  `frontend/admin-web/tests/unit/pages/settings-params.test.tsx` 的活）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_WEB = REPO_ROOT / "frontend" / "admin-web" / "src"

#: 判据模块（单一真值）：判据与三态类型的**唯一**定义处。
READINESS_MODULE = ADMIN_WEB / "lib" / "config-readiness.ts"

#: 已知消费方（**策展清单**：新增消费方要显式加进来，否则本判据看不见它）。
CONSUMERS: tuple[Path, ...] = (
    ADMIN_WEB / "app" / "(dashboard)" / "production" / "routings" / "page.tsx",
    ADMIN_WEB / "app" / "(dashboard)" / "settings" / "params" / "page.tsx",
)

#: 必须由判据模块导出的纯判据（改名/删除 ⇒ 红，逼人来这里登记）。
REQUIRED_JUDGES: tuple[str, ...] = (
    "judgeOperationsStep",
    "judgeBaseRoutesStep",
    "judgeDefaultRouteStep",
    "judgeFeeCombinationsStep",
    "judgeConfigSourceStep",
)

#: 「第二个载体」的机械形态：就地三态定义 / 就地三元判据。
_LOCAL_STATE_TYPE_RE = re.compile(r"type\s+ReadinessState\s*=")
_INLINE_TERNARY_RE = re.compile(r"\?\s*'(?:done|todo|unknown)'\s*:\s*'(?:done|todo|unknown)'")


def problems_readiness_single_source(
    module_text: str,
    consumer_texts: dict[str, str],
) -> list[str]:
    """判据的**纯函数**形态（红证要在不碰磁盘的前提下注入坏样本，故不读文件）。"""
    out: list[str] = []

    missing = [name for name in REQUIRED_JUDGES if f"export function {name}" not in module_text]
    if missing:
        out.append(
            f"判据模块 `frontend/admin-web/src/lib/config-readiness.ts` 不再导出 {missing} ⇒ "
            "消费方要么编译不过、要么各自发明一份（单一真值被拆）"
        )

    for path, text in consumer_texts.items():
        if "@/lib/config-readiness" not in text:
            out.append(
                f"{path} 没有从 `@/lib/config-readiness` 引入判据 ⇒ 它要么自己判、要么根本没判"
            )
            continue
        if _LOCAL_STATE_TYPE_RE.search(text):
            out.append(
                f"{path} 又定义了本地的 `type ReadinessState =` ⇒ 第二份三态口径长回来了"
                "（#5858 的「同屏两个矛盾的数」就是这么来的）"
            )
        hits = _INLINE_TERNARY_RE.findall(text)
        if hits:
            out.append(
                f"{path} 出现就地三元判据 {hits} ⇒ 该步的「配没配」绕过了单一真值模块"
                "（判据只许写在 `frontend/admin-web/src/lib/config-readiness.ts`）"
            )
    return out


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def test_readiness_judgement_has_exactly_one_home() -> None:
    """判据 1~3：单一真值存在、两个消费方都调它、都不自带第二份。"""
    assert READINESS_MODULE.is_file(), (
        f"判据模块不存在：{_relative(READINESS_MODULE)}（路径漂移 ⇒ 红，不得静默跳过）"
    )
    consumer_texts = {}
    for path in CONSUMERS:
        assert path.is_file(), f"登记的消费方不存在：{_relative(path)}（路径漂移 ⇒ 红）"
        consumer_texts[_relative(path)] = path.read_text(encoding="utf-8")

    problems = problems_readiness_single_source(
        READINESS_MODULE.read_text(encoding="utf-8"), consumer_texts
    )
    assert problems == [], "配置就绪度判据的单一真值被破坏：\n" + "\n".join(f"  · {p}" for p in problems)


def test_readiness_guard_can_go_red() -> None:
    """判据 4（**红证**）：注入坏样本必须被报出来 —— 否则本判据是空断言。

    三种坏样本各注入一次（缺导出 / 没接线 / 自带第二份），**逐条断言它真的会红**。
    """
    good_module = "\n".join(f"export function {n}(...)" for n in REQUIRED_JUDGES)
    good_consumer = "import { judgeConfigSourceStep } from '@/lib/config-readiness'"
    assert problems_readiness_single_source(good_module, {"a.tsx": good_consumer}) == []

    missing_export = problems_readiness_single_source(
        good_module.replace("export function judgeConfigSourceStep(...)", ""),
        {"a.tsx": good_consumer},
    )
    assert missing_export, "删掉一个判据导出竟没被判出来 ⇒ 判据 1 是空断言"

    not_wired = problems_readiness_single_source(good_module, {"a.tsx": "const x = 1"})
    assert not_wired, "消费方完全不接线竟没被判出来 ⇒ 判据 2 是空断言"

    second_copy = problems_readiness_single_source(
        good_module,
        {
            "a.tsx": good_consumer
            + "\ntype ReadinessState = 'done' | 'todo' | 'unknown'"
            + "\nconst s = ok ? 'done' : 'todo'"
        },
    )
    # 两条独立形态各报一条（本地类型 + 就地三元）—— 少报一条就说明有一条判据没生效
    assert len(second_copy) == 2, f"第二种载体没有被完整判出（实得 {second_copy}）"