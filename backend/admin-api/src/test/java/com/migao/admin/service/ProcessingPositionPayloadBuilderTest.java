// case_ids: MC-245
package com.migao.admin.service;

import com.migao.admin.service.ProductionOperationQtyClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;

/**
 * {@link ProcessingPositionPayloadBuilder}（issue #8725 第二档切出来的「部位 payload」单元）的定点判据。
 *
 * <p>它钉的是**部位计数口径**：配布边行并入同樘窗的主布部位（否则一扇窗被算成两扇：
 * 褶数 / 开数 / 幅数 / 工序 / 计件全部翻倍）、空快照不造部位、逐工序的 qty / qty_source
 * 必须来自算料客户端（不落 0、不拿订单数量顶替）。</p>
 */
@DisplayName("部位 payload 单元：樘窗绑组 / 空快照 / qty 来源（issue #8725 切片）")
class ProcessingPositionPayloadBuilderTest {

    private static final Long TENANT = 1L;

    private ProductionOperationQueryService query;
    private ProductionOperationQtyClient qtyClient;
    private ProcessingPositionPayloadBuilder builder;

    @BeforeEach
    void setUp() {
        query = mock(ProductionOperationQueryService.class);
        qtyClient = mock(ProductionOperationQtyClient.class);
        builder = new ProcessingPositionPayloadBuilder(query, qtyClient);
        lenient().when(query.routeTemplateFor(eq(TENANT), anyString()))
                .thenAnswer(inv -> {
                    String position = inv.getArgument(1);
                    return "布帘".equals(position) || "纱帘".equals(position)
                            ? RoutingModelFixture.defaultTemplate(TENANT) : null;
                });
        lenient().when(query.defaultRouteTemplate(TENANT))
                .thenReturn(RoutingModelFixture.defaultTemplate(TENANT));
        lenient().when(query.routeRules(TENANT))
                .thenReturn(RoutingModelFixture.rulesWithFactors(TENANT));
        lenient().when(query.operationPositions(TENANT))
                .thenReturn(RoutingModelFixture.canonicalPositions(TENANT));
        lenient().when(query.operationsByName(TENANT))
                .thenReturn(RoutingModelFixture.catalog());
        lenient().when(query.defaultCraft(TENANT)).thenReturn("韩褶");
        lenient().when(query.normalizeOperationName(anyString()))
                .thenAnswer(inv -> RoutingModelFixture.logicalName(inv.getArgument(0)));
        lenient().when(query.variantNameOf(anyString(), any(), any()))
                .thenAnswer(inv -> RoutingModelFixture.variantNameOf(
                        inv.getArgument(0), inv.getArgument(1), inv.getArgument(2)));
        lenient().when(query.routeSignals(TENANT)).thenReturn(List.of());
        stubQtyOne();
    }

    /** 算料桩：每道工序给 `1 / fallback`（本判据钉的是**键在不在、值从哪来**，不是算法）。 */
    private void stubQtyOne() {
        lenient().when(qtyClient.resolve(any())).thenAnswer(inv -> {
            List<Map<String, Object>> request = inv.getArgument(0);
            List<ProductionOperationQtyClient.PositionQty> resolved = new ArrayList<>();
            for (Map<String, Object> position : request) {
                Map<String, BigDecimal> qty = new LinkedHashMap<>();
                Map<String, String> source = new LinkedHashMap<>();
                for (Object raw : (List<?>) position.get("operations")) {
                    qty.put(String.valueOf(raw), BigDecimal.ONE);
                    source.put(String.valueOf(raw), "calc");
                }
                resolved.add(new ProductionOperationQtyClient.PositionQty(
                        (String) position.get("position_name"), qty, source));
            }
            return resolved;
        });
    }

    private static Map<String, Object> row(String itemId, String productName, String curtainType,
                                           String craftLineId, String componentRole) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("itemId", itemId);
        entry.put("productName", productName);
        entry.put("colorName", "米白");
        entry.put("curtainType", curtainType);
        entry.put("craft", "韩褶");
        entry.put("processingItems", List.of(Map.of("id", "p-" + itemId, "name", "韩褶")));
        if (craftLineId != null) {
            entry.put("craftLineId", craftLineId);
        }
        if (componentRole != null) {
            entry.put("componentRole", componentRole);
        }
        return entry;
    }

    @Test
    @DisplayName("同一樘窗的配布边行并入主布部位 ⇒ 一扇窗 = 一个部位（否则工序 / 计件全部翻倍）")
    void edgeRowIsAbsorbedIntoTheWindowGroup() {
        List<Map<String, Object>> snapshot = List.of(
                row("item-1", "遮光帘A", "布帘", "line-1", null),
                row("item-2", "配布边A", "布帘", "line-1", "配布边"));

        ProcessingPositionPayloadBuilder.PositionPayload payload =
                builder.buildPositionPayload(snapshot, TENANT);

        assertThat(payload.positions()).hasSize(1);
        assertThat(payload.positions().get(0).get("position_name")).isEqualTo("遮光帘A 米白");
        assertThat(payload.positions().get(0).get("order_item_id")).isEqualTo("item-1");
    }

    @Test
    @DisplayName("配布边行**自带**未成组（同组没有主布行）⇒ 它自己成部位（不静默丢窗）")
    void loneEdgeRowKeepsItsOwnPosition() {
        List<Map<String, Object>> snapshot = List.of(
                row("item-9", "配布边B", "布帘", "line-9", "配布边"));

        ProcessingPositionPayloadBuilder.PositionPayload payload =
                builder.buildPositionPayload(snapshot, TENANT);

        assertThat(payload.positions()).hasSize(1);
        assertThat(payload.positions().get(0).get("order_item_id")).isEqualTo("item-9");
    }

    @Test
    @DisplayName("空快照 ⇒ 零部位且路线三元组全 null（不造默认值）")
    void emptySnapshotYieldsEmptyPayload() {
        ProcessingPositionPayloadBuilder.PositionPayload payload =
                builder.buildPositionPayload(List.of(), TENANT);

        assertThat(payload.positions()).isEmpty();
        assertThat(payload.routeKey()).isNull();
        assertThat(payload.routeRequestedKey()).isNull();
        assertThat(payload.routeSource()).isNull();
    }

    @Test
    @DisplayName("逐工序 qty / qty_source 取自算料客户端（不落 0、不拿订单数量顶替）")
    void qtyAndSourceComeFromTheCalcClient() {
        List<Map<String, Object>> snapshot = List.of(row("item-1", "遮光帘A", "布帘", null, null));

        ProcessingPositionPayloadBuilder.PositionPayload payload =
                builder.buildPositionPayload(snapshot, TENANT);

        assertThat(payload.positions()).hasSize(1);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> operations =
                (List<Map<String, Object>>) payload.positions().get(0).get("operations");
        assertThat(operations).isNotEmpty();
        assertThat(operations).allSatisfy(op -> {
            assertThat(op.get("qty")).isEqualTo(BigDecimal.ONE);
            assertThat(op.get("qty_source")).isEqualTo("calc");
        });
        // 序号必须从 1 起连续（页面/纸面按 seq 排）
        for (int i = 0; i < operations.size(); i++) {
            assertThat(operations.get(i).get("seq")).isEqualTo(i + 1);
        }
    }

    @Test
    @DisplayName("路线三元组来自部位解析结果（route_key = 模板名，route_requested_key = 部位×工艺）")
    void routeTripleComesFromTheResolver() {
        List<Map<String, Object>> snapshot = List.of(row("item-1", "遮光帘A", "布帘", null, null));

        ProcessingPositionPayloadBuilder.PositionPayload payload =
                builder.buildPositionPayload(snapshot, TENANT);

        assertThat(payload.routeKey()).isEqualTo(RoutingModelFixture.TEMPLATE_NAME);
        assertThat(payload.routeRequestedKey()).isEqualTo("布帘×韩褶");
        assertThat(payload.routeSource()).isEqualTo("direct");
    }
}
