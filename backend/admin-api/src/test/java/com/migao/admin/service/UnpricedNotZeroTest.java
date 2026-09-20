// case_ids: PG-021, PG-039
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingPositionOperation;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionWorkLog;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingPositionOperationMapper;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteSignalMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.when;

/**
 * <b>未定价 ≠ 价 0</b>（issue #4696，P1）—— 实例化侧与读面**同口径**的三态判据。
 *
 * <h2>缺陷原形（主会话实测）</h2>
 * 实例化侧（{@code ProcessingOrderService.buildRoute}）在**矩阵价 NULL** 时回落「工序库行价」
 * （{@code production_operations.unit_price}，V49 DDL 是 {@code NOT NULL DEFAULT 0}）⇒
 * 布料单的 `配料`/`打包` 落库单价 = <b>0 元</b>；而 V88 的读面
 * （{@code GET /operation-layers}）**不回落** ⇒ 判 {@code unpriced}、界面显示「未定价」。
 * ⇒ <b>界面说「未定价」、实际计件 0 元</b>：工人白干且无人知道，且
 * 「没定价」与「价本来就是 0」**不可区分**。
 *
 * <h2>判据（每条独立、注入式可红）</h2>
 * <ol>
 *   <li><b>红证①</b>：矩阵价 NULL ⇒ 实例化 payload 的 {@code unit_price} 必须是 {@code null}
 *       （<b>不得</b>回落工序库行价 0）—— 夹具里 `配料`/`打包` 的工序库行价逐字是 {@code 0.0}
 *       （与 V79 种子同值），故「改前实测」恰好落在 <b>0 元</b> 这个静默形态上；</li>
 *   <li><b>反向护栏</b>：把同一格显式改成 <b>0</b> ⇒ 实例侧给 {@code 0}（定价为 0 元），
 *       与 ① 的 {@code null} <b>可区分</b>（两者同形 ⇒ 必红）；</li>
 *   <li><b>同口径</b>：同一格（`打包`×`布料`，矩阵价 NULL）实例化侧判未定价、
 *       读面 {@code operationLayers} 该行也判 {@code unpriced} 且 {@code price=null}
 *       —— <b>两处必须一致</b>（一侧回落一侧不回落 ⇒ 必红）。</li>
 * </ol>
 *
 * <p>落库侧的「null 不被折成 0」由 {@code ProductionService.parseSpecs} 的
 * {@code bd(..., null)} 承担，其红证在 {@code UnpricedPieceworkReportTest}
 * （报表按 0 计件 ⇒ 必红）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("未定价 ≠ 价 0：实例化侧与读面同口径（issue #4696）")
class UnpricedNotZeroTest {

    private static final Long TENANT = 1L;
    private static final String ORDER_ID = "order-001";

    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private ProcessingItemMapper processingItemMapper;
    @Mock
    private OrderService orderService;
    @Mock
    private ProcessingPositionOperationMapper positionOperationMapper;
    @Mock
    private ProductionWorkLogMapper workLogMapper;
    @Mock
    private ClientRequestIdService clientRequestIdService;
    @Mock
    private ProductionOperationQtyClient productionOperationQtyClient;
    @Mock
    private ProductionOperationMapper productionOperationMapper;
    @Mock
    private ProductionRouteTemplateMapper productionRouteTemplateMapper;
    @Mock
    private ProductionRouteRuleMapper productionRouteRuleMapper;
    @Mock
    private ProductionOperationPositionMapper productionOperationPositionMapper;
    @Mock
    private ProductionCraftMapper productionCraftMapper;
    @Mock
    private ProductionRouteSignalMapper productionRouteSignalMapper;

    private ProcessingOrderService instantiation;
    private ProductionRoutingReadService read;

    /** 部位价目矩阵的**可注入**夹具（默认 = 规范 4 部位；用例可就地改某一格）。 */
    private List<ProductionOperationPosition> priceRows;

    @BeforeEach
    void setUp() {
        TenantContext.setTenantId(TENANT);
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, ProductionOperationPosition.class);
        TableInfoHelper.initTableInfo(assistant, Order.class);

        priceRows = new ArrayList<>(RoutingModelFixture.canonicalPositions(TENANT));

        when(productionRouteTemplateMapper.selectList(any())).thenReturn(List.of(
                RoutingModelFixture.defaultTemplateAllPositions(TENANT),
                RoutingModelFixture.fabricTemplate(TENANT)));
        when(productionRouteRuleMapper.selectList(any())).thenReturn(
                RoutingModelFixture.rulesWithFactors(TENANT));
        when(productionOperationPositionMapper.selectList(any())).thenAnswer(inv -> priceRows);
        when(productionCraftMapper.selectList(any())).thenReturn(List.of(
                RoutingModelFixture.defaultCraft(TENANT, "韩褶")));
        when(productionOperationMapper.selectList(any())).thenReturn(
                RoutingModelFixture.operationEntities(TENANT));

        ProductionOperationQueryService queryService = new ProductionOperationQueryService(
                productionOperationMapper, productionRouteTemplateMapper, productionRouteRuleMapper,
                productionOperationPositionMapper, productionCraftMapper, productionRouteSignalMapper);
        ProductionService productionService = new ProductionService(
                processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, orderItemMapper, clientRequestIdService);
        instantiation = new ProcessingOrderService(
                processingOrderMapper, orderMapper, orderItemMapper, processingItemMapper,
                orderService, new ObjectMapper(), productionService, queryService,
                productionOperationQtyClient);
        read = new ProductionRoutingReadService(productionOperationPositionMapper,
                productionRouteRuleMapper, queryService, processingItemMapper);

        lenient().when(productionOperationQtyClient.resolve(any())).thenAnswer(inv -> {
            List<Map<String, Object>> request = inv.getArgument(0);
            List<ProductionOperationQtyClient.PositionQty> resolved = new ArrayList<>();
            for (Map<String, Object> position : request) {
                Map<String, BigDecimal> qty = new LinkedHashMap<>();
                Map<String, String> source = new LinkedHashMap<>();
                for (Object raw : (List<?>) position.get("operations")) {
                    qty.put(String.valueOf(raw), BigDecimal.ONE);
                    source.put(String.valueOf(raw), "fallback");
                }
                resolved.add(new ProductionOperationQtyClient.PositionQty(
                        (String) position.get("position_name"), qty, source));
            }
            return resolved;
        });

        Order order = Order.builder().id(ORDER_ID).tenantId(TENANT)
                .orderNo("ORD-20260920-0001").status("confirmed")
                .customerName("张三").customerPhone("13800138000").build();
        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(null);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    /** 布料单（{@code processing_info.saleForm = 布料}）的实例化 payload（部位 = 布料，主线 = 配料→打包）。 */
    private List<Map<String, Object>> fabricPayload() {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("colorName", "米白");
        info.put("sellingMethod", "散剪");
        info.put("saleForm", "布料");
        info.put("processingItems", List.of(Map.of("id", "p-1", "name", "工序甲",
                "unitPrice", 3.0, "quantity", 2, "unit", "米")));
        OrderItem item = OrderItem.builder()
                .id("item-1").tenantId(TENANT).orderId(ORDER_ID)
                .productName("遮光布料X").quantity(BigDecimal.valueOf(2))
                .width(new BigDecimal("2.5")).height(new BigDecimal("2.8"))
                .processingInfo(info)
                .build();
        when(orderItemMapper.selectList(any())).thenReturn(List.of(item));

        List<Map<String, Object>> payload = instantiation.derivePositionPayload(ORDER_ID, TENANT);
        assertThat(payload).as("布料单必须落一条部位（否则判据无从谈起）").hasSize(1);
        return payload;
    }

    /** payload 里某个**逻辑工序名**那一步。 */
    private static Map<String, Object> step(List<Map<String, Object>> payload, String logicalName) {
        for (Map<String, Object> position : payload) {
            for (Object raw : (List<?>) position.get("operations")) {
                @SuppressWarnings("unchecked")
                Map<String, Object> op = (Map<String, Object>) raw;
                if (logicalName.equals(op.get("logical_name"))) {
                    return op;
                }
            }
        }
        throw new AssertionError("payload 里没有逻辑工序「" + logicalName + "」");
    }

    /** 把某一格的价就地改成给定值（{@code null} = 未定价）。 */
    private void setCellPrice(String logicalName, String position, String price) {
        for (int i = 0; i < priceRows.size(); i++) {
            ProductionOperationPosition row = priceRows.get(i);
            if (logicalName.equals(row.getLogicalName()) && position.equals(row.getPosition())) {
                priceRows.set(i, ProductionOperationPosition.builder()
                        .id(row.getId()).tenantId(row.getTenantId())
                        .logicalName(row.getLogicalName()).position(row.getPosition())
                        .unitPrice(price == null ? null : new BigDecimal(price))
                        .applicable(row.getApplicable()).status(row.getStatus()).deleted(row.getDeleted())
                        .build());
                return;
            }
        }
        throw new AssertionError("夹具里没有 (" + logicalName + ", " + position + ") 这一格");
    }

    /** 读面 `operationLayers` 的 operations 段里 (逻辑工序, 部位) 那一行。 */
    @SuppressWarnings("unchecked")
    private Map<String, Object> layersOperationRow(String logicalName, String position) {
        Map<String, Object> layers = read.operationLayers(TENANT);
        for (Map<String, Object> row : (List<Map<String, Object>>) layers.get("operations")) {
            if (logicalName.equals(row.get("operation")) && position.equals(row.get("position"))) {
                return row;
            }
        }
        throw new AssertionError("读面 operations 段没有 (" + logicalName + ", " + position + ")");
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> layersDeliveryRow(String logicalName) {
        Map<String, Object> layers = read.operationLayers(TENANT);
        for (Map<String, Object> row : (List<Map<String, Object>>) layers.get("delivery")) {
            if (logicalName.equals(row.get("operation"))) {
                return row;
            }
        }
        throw new AssertionError("读面 delivery 段没有「" + logicalName + "」");
    }

    // ══════════════════════ 红证①：未定价不得回落工序库行价 ══════════════════════

    @Test
    @DisplayName("🔴 红证①：矩阵价 NULL ⇒ 实例化 unit_price 为 null（**不得**回落工序库行价 0 元）")
    void unpricedMatrixCellDoesNotFallBackToCatalogRowPrice() {
        // 夹具事实：`配料`/`打包` 的**工序库行价**逐字是 0.0（与 V79 种子同值：
        // 「unit_price 落 0 不是定价 0，未定价的真载体是部位价目行的 NULL」）⇒
        // 改前这里回落到 0 ⇒ 计件 0 元且与「定价 0」不可区分。
        assertThat(RoutingModelFixture.catalog().get("配料").get("unit_price"))
                .as("夹具自证：工序库行价 = 0（正是那条静默回落的落点）")
                .isEqualTo(new BigDecimal("0.0"));
        assertThat(RoutingModelFixture.catalog().get("打包").get("unit_price"))
                .as("夹具自证：工序库行价 = 0")
                .isEqualTo(new BigDecimal("0.0"));

        List<Map<String, Object>> payload = fabricPayload();

        assertThat((BigDecimal) step(payload, "配料").get("unit_price"))
                .as("布料×配料 的矩阵价是 NULL ⇒ 实例化必须给 null（未定价），**不得**折成 0 元")
                .isNull();
        assertThat(step(payload, "打包").get("unit_price"))
                .as("布料×打包 的矩阵价是 NULL ⇒ 实例化必须给 null（未定价）")
                .isNull();
    }

    // ══════════════════════ 反向护栏：价 0 与未定价必须可区分 ══════════════════════

    @Test
    @DisplayName("反向护栏：同一格显式定价为 **0 元** ⇒ 实例化给 0（≠ null），与「未定价」可区分")
    void pricedZeroIsDistinguishableFromUnpriced() {
        setCellPrice("配料", "布料", "0");

        List<Map<String, Object>> payload = fabricPayload();

        assertThat((BigDecimal) step(payload, "配料").get("unit_price"))
                .as("定价为 0 元 = 有价 ⇒ 落 0；若与「未定价」同形（都 null 或都 0）⇒ 本断言红")
                .isNotNull()
                .isEqualByComparingTo(BigDecimal.ZERO);
        assertThat(step(payload, "打包").get("unit_price"))
                .as("同一次实例化里另一格仍是未定价 ⇒ 两态在同一次响应里可区分")
                .isNull();
    }

    // ══════════════════════ 同口径：实例化侧 == 读面 ══════════════════════

    @Test
    @DisplayName("🔴 同口径：同一格实例化侧与读面给**同一判定**（一侧回落一侧不回落 ⇒ 必红）")
    void instantiationAndReadSideAgreeOnTheSameCell() {
        List<Map<String, Object>> payload = fabricPayload();

        // ① 部位级格（`配料`×`布料`）：读面 operations 段逐字给该格价 ⇒ 与实例化侧**逐字相同**
        Map<String, Object> readCell = layersOperationRow("配料", "布料");
        assertThat(readCell.get("unit_price"))
                .as("读面（V88 起）对 NULL 格给 null")
                .isNull();
        assertThat((BigDecimal) step(payload, "配料").get("unit_price"))
                .as("实例化侧必须与读面同口径：同为 null（改前实例侧回落到 0 ⇒ 红）")
                .isEqualTo(readCell.get("unit_price"));

        // ② 套级格（`打包`）：读面聚合成「一列价」并给出**显式** price_state
        Map<String, Object> readDelivery = layersDeliveryRow("打包");
        assertThat(readDelivery.get("price_state"))
                .as("读面对「有格未定价」判 unpriced")
                .isEqualTo("unpriced");
        assertThat(readDelivery.get("price")).isNull();
        assertThat(step(payload, "打包").get("unit_price"))
                .as("实例化侧对同一格必须给同一判定（未定价 ⇒ 单价 null，不是 0 元）")
                .isEqualTo(readDelivery.get("price"));
    }

    @Test
    @DisplayName("同口径反向护栏：显式定价 0 元 ⇒ 两侧都给 0（**不是** unpriced）")
    void bothSidesAgreeThatZeroIsPriced() {
        setCellPrice("配料", "布料", "0");

        List<Map<String, Object>> payload = fabricPayload();
        Map<String, Object> readCell = layersOperationRow("配料", "布料");

        assertThat((BigDecimal) readCell.get("unit_price")).isNotNull().isEqualByComparingTo(BigDecimal.ZERO);
        assertThat((BigDecimal) step(payload, "配料").get("unit_price"))
                .as("两侧都把「0 元」当**有价**：读面 0 / 实例侧 0 —— 若一侧把它当未定价 ⇒ 红")
                .isNotNull()
                .isEqualByComparingTo(BigDecimal.ZERO);
    }

    /**
     * 未定价的实例读面（加工单工序进度）：{@code unit_price} 必须是 {@code null} + 显式
     * {@code price_state='unpriced'} —— 改前 {@code nz()} 把它折成 0 元 ⇒ 界面显示「¥0.00」，
     * 与「定价为 0」**不可区分**（界面说「未定价」、实际计件 0 元的那条静默差异）。
     */
    @Test
    @DisplayName("🔴 加工单工序进度：未定价实例读面给 null + price_state=unpriced（不折成 ¥0.00）")
    void operationProgressExposesUnpricedInsteadOfZero() {
        ProductionService service = new ProductionService(
                processingOrderMapper, positionOperationMapper, workLogMapper,
                orderMapper, orderItemMapper, clientRequestIdService);

        com.migao.admin.entity.ProcessingOrder po = new com.migao.admin.entity.ProcessingOrder();
        po.setId("po-1");
        po.setTenantId(TENANT);
        po.setOrderId(ORDER_ID);
        po.setStatus("generated");
        po.setDeleted(0);
        when(processingOrderMapper.selectActiveByOrderId(ORDER_ID, TENANT)).thenReturn(po);

        ProcessingPositionOperation unpriced = ProcessingPositionOperation.builder()
                .id("op-1").tenantId(TENANT).processingOrderId("po-1")
                .positionName("布料").seq(1).operationName("配料").groupName("后道").unit("米")
                .qty(new BigDecimal("10")).unitPrice(null).factor(BigDecimal.ONE)
                .isMustFinish(false).isStartMarker(false)
                .status("pending").doneQty(BigDecimal.ZERO).deleted(0).build();
        when(positionOperationMapper.selectList(any())).thenReturn(List.of(unpriced));
        when(workLogMapper.selectList(any())).thenReturn(List.of());

        Map<String, Object> view = service.getOperations(ORDER_ID, TENANT);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> positions = (List<Map<String, Object>>) view.get("positions");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> operations =
                (List<Map<String, Object>>) positions.get(0).get("operations");
        assertThat(operations).hasSize(1);
        assertThat(operations.get(0).get("unit_price"))
                .as("未定价 ⇒ 读面必须是 null（改前 nz() 折成 0 ⇒ 界面显示 ¥0.00，与定价 0 同形）")
                .isNull();
        assertThat(operations.get(0).get("price_state"))
                .as("读面必须显式给三态标记，供界面渲染「未定价」与定价入口")
                .isEqualTo("unpriced");
    }
}
