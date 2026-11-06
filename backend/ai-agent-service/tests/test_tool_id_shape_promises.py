"""
类级元守卫：工具描述里承诺的「入参形态」必须在实现里真的有对应处理（issue #8783 的同族防线）。

## 病（#8783 的形态，不是推演）

`product_detail` 的描述写「product_id **支持名称/序号/UUID**」，而 `execute()` 把入参原样拼进
`GET /api/admin/products/{id}` ⇒ 传商品名必 `NOT_FOUND`。解析器
（`backend/ai-agent-service/app/utils/id_resolver.py` 的 `resolve_product_id()`）早写好了，
**生产代码零调用** —— 描述没错，实现没跟上。

## 本判据锁什么

扫 `backend/ai-agent-service/app/tools/*.py` 的**工具描述文本**：
出现了「入参形态承诺」锚点（`支持名称/序号` / `名称/序号/UUID`）的模块，
**同一个模块里**必须有解析器调用（`resolve_product_id(` / `id_resolver`）。
没有 ⇒ **判红并具名**（谁承诺了、缺什么）。

## 为什么这条是「类级」而不是又一个实例判据

实例判据只能证明 `product_detail` 这一处好了；本判据让**同类**（描述承诺了名称解析、
实现却没接线）**进不来**：新工具抄这段描述而不接线 ⇒ 当场红。

⚠️ 它同时**反向**守住「不许只改描述当修好」：把 `product_detail` 的描述里那句承诺删掉来「消红」，
本判据的扫描面自证会当场红（`product_detail.py` 必须在命中面里）。

## 豁免台账（只许缩短，不许静默）

`EXEMPT_KNOWN_GAPS` = **同族未修**的工具「承诺了名称/序号/UUID，实现里却没有解析器调用」。
台账里每条都会**双向**校验：既承诺、又没解析，才是合法豁免；一旦修好（有解析器）或
改了描述（不再承诺）⇒ **必须删掉台账条目，否则判红**。⇒ 「没修」这件事**可见且会缩小**。

**现取：台账为空** —— 最后两条（`product_update` / `sku_update` 这两个**写**工具）已由
issue #8788 接线。⚠️ 写工具接的是**严格**解析器 `resolve_unique_product_id()`（只接受唯一
确定的结果）；只读那个 `resolve_product_id()` 允许「模糊命中取第一条」，写在写路径上会重新
长出"猜"的分支 ⇒ 判据见 `backend/ai-agent-service/tests/test_write_path_id_resolution.py` 的
`TestNoGuessIsStructural::test_write_tools_use_the_strict_resolver_only`。

## 边界（照实登记）

只判「描述承诺 vs 是否有解析器调用」这一条**静态**事实；不判解析器本身对不对
（那由 `backend/ai-agent-service/tests/test_product_detail_id_resolution.py` 与
`backend/ai-agent-service/tests/test_id_resolver.py` 负责），也不判模型会不会照描述调用。
"""
# case_ids: MC-250

from pathlib import Path

import pytest


TOOLS_DIR = Path(__file__).resolve().parents[1] / "app" / "tools"

# 「入参形态承诺」锚点：只收**明确的形态清单**，不收「支持」这类宽词（宽词会把散文判红）。
PROMISE_ANCHORS = ("支持名称/序号", "名称/序号/UUID")

# 解析器标记：出现任一 = 该模块真的有解析动作（不是只在注释里提一句）。
RESOLVER_MARKERS = ("resolve_product_id(", "id_resolver")

# 同族未修台账（只许缩短）。**现取为空**：issue #8788 已把最后两条（两个**写**工具）接线。
EXEMPT_KNOWN_GAPS: dict = {}


def _promises_name_resolution(source: str) -> bool:
    """该模块的文本是否承诺了「名称/序号/UUID」这类入参形态。"""
    return any(anchor in source for anchor in PROMISE_ANCHORS)


def _has_resolver(source: str) -> bool:
    """该模块是否真的调用了解析器（文本层，注释里提一句不算 —— 见 `_strip_comment_lines`）。"""
    code = "\n".join(
        line for line in source.splitlines()
        if not line.lstrip().startswith("#")
    )
    return any(marker in code for marker in RESOLVER_MARKERS)


def _find_unwired_promises(sources: dict, exempt=EXEMPT_KNOWN_GAPS) -> list:
    """→ 承诺了但没接线的模块名（已豁免的除外），保持输入顺序。"""
    return [
        name for name, source in sources.items()
        if _promises_name_resolution(source) and not _has_resolver(source) and name not in exempt
    ]


def _tool_sources(directory: Path) -> dict:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(directory.glob("*.py"))}


@pytest.fixture(scope="module")
def tool_sources():
    return _tool_sources(TOOLS_DIR)


class TestScanSurfaceIsReal:
    """扫描面自证（fail-closed）：扫不到东西时「零违规」是假绿。"""

    def test_promise_anchors_hit_a_nonempty_surface(self, tool_sources):
        promising = sorted(n for n, s in tool_sources.items() if _promises_name_resolution(s))

        # 扫描面自证：全库至少 3 个模块写着这句承诺（product_detail + 台账里那 2 个）
        assert len(promising) >= 3, f"入参形态承诺的扫描面退化了（命中 {promising}）"
        # 本单修的那个**必须**在命中面里 —— 反证「把描述删掉来消红」会被当场抓住
        assert "product_detail.py" in promising, "product_detail 不再承诺「名称/序号/UUID」？先把承诺改回来（不许降承诺）"
        # 断言锚点本身不是空转（每个锚点都要有命中）
        for anchor in PROMISE_ANCHORS:
            assert any(anchor in s for s in tool_sources.values()), f"锚点 {anchor!r} 全库零命中 ⇒ 判据失明"


class TestNoUnwiredPromises:
    """类级判据本体：承诺了名称解析却没接线 ⇒ 具名判红。"""

    def test_no_unregistered_promise_without_resolver(self, tool_sources):
        unwired = _find_unwired_promises(tool_sources)

        assert unwired == [], (
            "这些工具的**描述承诺**了「名称/序号/UUID」，实现里却没有解析器调用："
            f"{unwired} ⇒ 照 #8783 的修法接线（或把《已核实的缺口》登记进 EXEMPT_KNOWN_GAPS 并写明重启条件）"
        )

    def test_fixed_tool_is_not_exempt_and_does_resolve(self, tool_sources):
        source = tool_sources["product_detail.py"]

        assert "product_detail.py" not in EXEMPT_KNOWN_GAPS, "本单修好的工具不许留在豁免台账里"
        assert "await resolve_product_id(" in source, "product_detail 必须在 execute 里真的 await 解析器"
        assert _has_resolver(source)

    def test_write_tools_are_no_longer_exempt_and_do_resolve(self, tool_sources):
        """#8788 销账后的**永久**判据：两个写工具必须真的接线，且不许重新登记豁免。

        写路径比只读面多一条硬约束：接的必须是**严格**解析器。只读那个
        `resolve_product_id()` 允许「名称模糊命中取第一条」⇒ 写在写路径上 = 改错商品。
        """
        for name in ("product_update.py", "sku_update.py"):
            source = tool_sources[name]
            assert name not in EXEMPT_KNOWN_GAPS, f"{name} 已修好期，不许重新登记豁免（只许缩短）"
            assert "await resolve_unique_product_id(" in source, (
                f"{name} 必须在 execute 里 await **严格**解析器（写路径不接受模糊取第一条）")
            assert _has_resolver(source)

    def test_exempt_ledger_only_shrinks(self, tool_sources):
        """台账双向校验：既承诺又没解析才算合法豁免；修好/改描述后必须删条目。"""
        for name, reason in EXEMPT_KNOWN_GAPS.items():
            assert name in tool_sources, f"豁免台账里的 {name} 已不存在 ⇒ 删掉该条目（只许缩短）"
            source = tool_sources[name]
            assert _promises_name_resolution(source), (
                f"{name} 已不再承诺入参形态（或已接线）⇒ 从 EXEMPT_KNOWN_GAPS 删掉（只许缩短）：{reason}"
            )
            assert not _has_resolver(source), (
                f"{name} 已接线解析器 ⇒ 从 EXEMPT_KNOWN_GAPS 删掉（只许缩短）：{reason}"
            )


class TestDetectorHasTeeth:
    """判别力自证（正控 / 负控各实跑）：保证「不红」不是来自判据失明。"""

    def test_positive_control_unwired_promise_is_flagged(self):
        sources = {
            "fake_tool.py": (
                'description = "【参数】需要 product_id（支持名称/序号/UUID）。"\n'
                'response = await client.get(f"/api/admin/products/{product_id}")\n'
            ),
        }

        assert _find_unwired_promises(sources, exempt={}) == ["fake_tool.py"]

    def test_negative_control_wired_promise_is_not_flagged(self):
        sources = {
            "fake_tool.py": (
                'description = "【参数】需要 product_id（支持名称/序号/UUID）。"\n'
                'resolved = await resolve_product_id(product_id, tenant_id, client)\n'
            ),
        }

        assert _find_unwired_promises(sources, exempt={}) == []

    def test_negative_control_tool_without_promise_is_not_flagged(self):
        sources = {
            "fake_tool.py": 'description = "【参数】需要 product_id（UUID）。"\n',
        }

        assert _find_unwired_promises(sources, exempt={}) == []

    def test_resolver_mentioned_only_in_comment_is_not_counted(self):
        """注释里提一句解析器不算「接线」—— 否则「写了但没调用」正是 #8783 的原病。"""
        sources = {
            "fake_tool.py": (
                'description = "【参数】需要 product_id（支持名称/序号/UUID）。"\n'
                '# TODO: 以后用 resolve_product_id( 接线\n'
            ),
        }

        assert _find_unwired_promises(sources, exempt={}) == ["fake_tool.py"]
