package com.migao.admin.service;

// case_ids: PG-049

import com.migao.admin.exception.BusinessException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * **工艺单值护栏**（用户裁定 2026-09-19）：「每个部位**最多一个**声明工艺的加工项，两个 ⇒ fail-closed」。
 *
 * <h2>为什么必须有这条护栏（不是洁癖）</h2>
 * 路线键的工艺维是**单值**（`production_route_templates` 按 部位×工艺 取主线）。加工项目录里
 * 有 5 个项会**声明**工艺（`processing_items.craft_hint`：打孔/韩折/韩定+S钩/穿杆/平幔），
 * 若一张单里同时勾了「韩折」与「打孔」：
 * <ul>
 *   <li>取价侧按**全部**加工项名算组合键（`韩折+打孔+…`）——那是**另一个组合**，价目里没有 ⇒ 未定价；</li>
 *   <li>路线侧只能取**一个**工艺 ⇒ 实际工序与另一维的意图不符；</li>
 * </ul>
 * ⇒ 同一单**两套口径**（钱按一套、工序按另一套）。故：**两个不同声明 ⇒ 422**，
 * 而不是「静默取第一个」（静默取第一个 = 让商家以为两维都生效了）。
 *
 * <h2>判据的边界（**只认「不同」**）</h2>
 * 同一工艺被多个加工项声明是**合法**的：「韩折」与「韩定+S钩」都声明 `韩褶`
 * （两者是同一打褶方式的两种做法，ERP 名字不同、工艺相同）⇒ 不冲突、取 `韩褶`。
 *
 * <h2>红证（不会红的断言 = 空断言）</h2>
 * 把 {@code craftHintOf} 改回「遇到第一个声明就 return」（即本护栏落地前的实现）
 * ⇒ {@link #twoDifferentDeclarationsFailClosed} 必红（不再抛异常，返回「韩褶」）。
 *
 * <h2>为什么直接测这个静态方法（而不是造整条 generate 桩）</h2>
 * 护栏的判据**只**依赖「快照条目里的加工项声明」，与订单/租户/路线库无关；
 * 走 {@code generate} 需要 7 处桩（订单/明细/工序库/价目/规则/幂等/落库），
 * 桩本身会成为失败来源（同族教训见 `ProcessingOrderRouteSourceTest` 的头部说明）。
 */
@DisplayName("工艺单值护栏：craftHintOf（加工项声明的工艺最多一个）")
class ProcessingOrderCraftGuardTest {

    /** 造一条快照条目：每个加工项一个 `craftHint`（`null` = 该加工项**不声明**工艺）。 */
    private static Map<String, Object> entryWithDeclarations(String... hints) {
        Map<String, Object> entry = new LinkedHashMap<>();
        List<Map<String, Object>> items = new ArrayList<>();
        for (int i = 0; i < hints.length; i++) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", "p-" + (i + 1));
            item.put("name", "加工项" + (i + 1));
            if (hints[i] != null) {
                item.put("craftHint", hints[i]);
            }
            items.add(item);
        }
        entry.put("processingItems", items);
        return entry;
    }

    @Test
    @DisplayName("PG-049 没有 processingItems 键 ⇒ null（该维按缺维处理，不猜）")
    void missingProcessingItemsKeyIsNull() {
        assertThat(ProcessingOrderService.craftHintOf(new LinkedHashMap<>())).isNull();
    }

    @Test
    @DisplayName("PG-049 都不声明工艺 ⇒ null（不是「工艺=空」）")
    void noDeclarationIsNull() {
        assertThat(ProcessingOrderService.craftHintOf(entryWithDeclarations(null, null))).isNull();
    }

    @Test
    @DisplayName("PG-049 恰好一个声明 ⇒ 取它（正常路径）")
    void singleDeclarationIsReturned() {
        assertThat(ProcessingOrderService.craftHintOf(entryWithDeclarations(null, "韩褶", null)))
                .isEqualTo("韩褶");
    }

    @Test
    @DisplayName("PG-049 多个加工项声明**同一个**工艺 ⇒ 不冲突（韩折 与 韩定+S钩 都是韩褶）")
    void sameDeclarationFromSeveralItemsIsNotAConflict() {
        assertThat(ProcessingOrderService.craftHintOf(entryWithDeclarations("韩褶", "韩褶")))
                .as("同一工艺被多个加工项声明是合法的：它们是同一打褶方式的两种做法")
                .isEqualTo("韩褶");
    }

    @Test
    @DisplayName("PG-049 两个**不同**声明 ⇒ 422 fail-closed（不许静默取第一个）")
    void twoDifferentDeclarationsFailClosed() {
        assertThatThrownBy(() ->
                ProcessingOrderService.craftHintOf(entryWithDeclarations("韩褶", "打孔")))
                .isInstanceOf(BusinessException.class)
                .satisfies(thrown -> {
                    BusinessException e = (BusinessException) thrown;
                    assertThat(e.getHttpStatus()).as("必须 422（可行动的业务拒绝，不是 500）").isEqualTo(422);
                    assertThat(e.getCode())
                            .as("复用路线取不到的既有错误码（不新增契约面）")
                            .isEqualTo(ProcessingOrderService.ERR_ROUTING_NOT_FOUND);
                    assertThat(e.getMessage())
                            .as("消息必须**点名**是哪两个工艺 —— 否则商家不知道该取消哪一个")
                            .contains("韩褶").contains("打孔");
                    assertThat(e.getSuggestion())
                            .as("必须给可行动的下一步（只报错不给动作 = 用户只能来问研发）")
                            .isNotNull().contains("取消勾选");
                });
    }
}
