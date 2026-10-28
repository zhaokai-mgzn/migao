// case_ids: PG-045
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.CuttingHeightConfig;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.mapper.CuttingHeightConfigMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import com.migao.admin.mapper.TenantParamAuditMapper;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
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
import static org.mockito.Mockito.when;

/**
 * 机台裁高读面：**部位（帘种）的空值口径**（issue #7993，2026-10-28 一体机现场实证）。
 *
 * <p>下单面按 issue #4521「**主帘缺省即布帘 ⇒ 不写** {@code curtainType}」把布帘这个默认值**刻意留空**；
 * 读面若把空值当「缺部位」，则**每一张布帘单都算不出裁高**（真机：订单详情正常、裁高区报「缺少 position」）。</p>
 *
 * <p>三条判据（每条都能红）：</p>
 * <ol>
 *   <li><b>空值 + 成品帘 ⇒ 按「布帘」补回并**参与命中**</b>：部位限定为「布帘」的增量项要能命中
 *       （红证：不补 ⇒ {@code missing} 含 {@code position}、裁高为 null）；</li>
 *   <li><b>空值 + 布料 ⇒ **不**补</b>：卖布行没有部位语义，仍如实报缺
 *       （红证：无差别补「布帘」⇒ 布料单被算出一个裁高）；</li>
 *   <li><b>显式值零回归</b>：{@code 纱帘} 原样透传，部位限定为「布帘」的项**不命中**
 *       （红证：把显式值也覆盖成布帘 ⇒ 会多算 0.08）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class WorkerCuttingHeightDefaultPositionTest {

    private static final Long TENANT = 46L;
    private static final String ORDER_ID = "order-7993";
    private static final String ITEM_ID = "it-7993";
    private static final String TOKEN = "DEFAULT1";

    @Mock
    private ProductionScanService productionScanService;
    @Mock
    private CuttingHeightConfigMapper cuttingHeightConfigMapper;
    @Mock
    private OrderItemMapper orderItemMapper;
    @Mock
    private OrderMapper orderMapper;
    @Mock
    private ProcessingOrderMapper processingOrderMapper;
    @Mock
    private ProcessingOrderSetMapper processingOrderSetMapper;
    @Mock
    private ProductAttributeMapper productAttributeMapper;

    private WorkerCuttingHeightService service;

    @BeforeEach
    void setUp() {
        CuttingHeightConfigService configService = new CuttingHeightConfigService(cuttingHeightConfigMapper,
                new TenantParamAuditService(org.mockito.Mockito.mock(TenantParamAuditMapper.class),
                        new SimpleMeterRegistry(), new ObjectMapper()));
        service = new WorkerCuttingHeightService(productionScanService, configService, orderItemMapper,
                orderMapper, processingOrderMapper, processingOrderSetMapper, productAttributeMapper);
        when(orderMapper.selectOne(any())).thenReturn(Order.builder()
                .id(ORDER_ID).tenantId(TENANT).orderNo("SO20261028001").customerName("现场客户").build());
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(
                ProcessingOrder.builder().id("po-1").tenantId(TENANT).orderId(ORDER_ID).build()));
        when(processingOrderSetMapper.selectCount(any())).thenReturn(1L);
        when(productAttributeMapper.selectList(any())).thenReturn(List.of());
    }

    @Test
    @DisplayName("① 部位为空 + 成品帘 ⇒ 补回「布帘」，部位限定项能命中，裁高算得出来")
    void blankPositionDefaultsToClothForCurtainLine() {
        stub(positionView(null), orderLine(null, Map.of("saleForm", "成品帘", "specialOptions", List.of("包布折"))));

        Map<String, Object> position = firstPosition(service.read(TOKEN, TENANT));

        assertThat(position.get("position_kind")).isEqualTo("布帘");
        assertThat(position.get("missing")).isEqualTo(List.of());
        assertThat((BigDecimal) position.get("cutting_height")).isEqualByComparingTo("2.530");
        assertThat(hitsOf(position)).extracting(h -> h.get("name")).containsExactly("包布折");
    }

    @SuppressWarnings("unchecked")
    @Test
    @DisplayName("② 部位为空 + 布料行 ⇒ 不补「布帘」，仍如实报缺 position（卖布没有部位语义）")
    void blankPositionStaysMissingForFabricLine() {
        stub(positionView(null), orderLine(null, Map.of("saleForm", "布料")));

        Map<String, Object> position = firstPosition(service.read(TOKEN, TENANT));

        assertThat(position.get("position_kind")).isNull();
        assertThat((List<Object>) position.get("missing")).contains("position");
        assertThat(position.get("cutting_height")).isNull();
    }

    @Test
    @DisplayName("③ 显式部位（纱帘）零回归：原样透传，布帘限定项**不**命中")
    void explicitPositionIsNotOverridden() {
        stub(positionView("纱帘"), orderLine("纱帘", Map.of("saleForm", "成品帘", "specialOptions", List.of("包布折"))));

        Map<String, Object> position = firstPosition(service.read(TOKEN, TENANT));

        assertThat(position.get("position_kind")).isEqualTo("纱帘");
        assertThat(hitsOf(position)).isEmpty();
        assertThat((BigDecimal) position.get("cutting_height")).isEqualByComparingTo("2.450");
    }

    // ────────────────────────────── fixtures ──────────────────────────────

    private void stub(Map<String, Object> view, List<OrderItem> items) {
        when(productionScanService.resolve(TOKEN, null, TENANT)).thenReturn(view);
        when(orderItemMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(items);
        when(cuttingHeightConfigMapper.selectActiveByTenant(TENANT)).thenReturn(config());
    }

    private static Map<String, Object> positionView(String positionKind) {
        Map<String, Object> scanned = new LinkedHashMap<>();
        scanned.put("order_item_id", ITEM_ID);
        scanned.put("position_kind", positionKind);
        scanned.put("position_name", "主卧");
        Map<String, Object> overview = new LinkedHashMap<>();
        overview.put("positions", List.of(scanned));
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("granularity", "set_position");
        view.put("order_id", ORDER_ID);
        view.put("processing_order_no", "JG-20261028-0001");
        view.put("set_no", "1");
        view.put("set_index", 1);
        view.put("position", scanned);
        view.put("set_overview", overview);
        view.put("needs_selection", List.of());
        return view;
    }

    private static List<OrderItem> orderLine(String curtainType, Map<String, Object> processingInfo) {
        OrderItem item = new OrderItem();
        item.setId(ITEM_ID);
        item.setTenantId(TENANT);
        item.setOrderId(ORDER_ID);
        item.setProductId("p-7993");
        item.setProductName("奶油风纯色遮光窗帘");
        item.setWidth(new BigDecimal("3.000"));
        item.setHeight(new BigDecimal("2.450"));
        item.setCraft("韩褶");
        item.setCurtainType(curtainType);
        item.setOpenCount(2);
        item.setCuttingMode("定高买宽");
        item.setFullness(new BigDecimal("2.0"));
        item.setProcessingInfo(processingInfo);
        List<OrderItem> items = new ArrayList<>();
        items.add(item);
        return items;
    }

    /** 只有一条「布帘 + 包布折 +0.08」——用来证明默认部位能参与命中。 */
    private static CuttingHeightConfig config() {
        Map<String, Object> hit = new LinkedHashMap<>();
        hit.put("trigger_kind", "option");
        hit.put("trigger_value", "包布折");
        hit.put("position", "布帘");
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("key", "baobuzhe");
        item.put("name", "包布折");
        item.put("value", new BigDecimal("0.08"));
        item.put("direction", "add");
        item.put("height_join", false);
        item.put("hit", hit);
        item.put("hit_expr", null);
        item.put("enabled", true);
        item.put("order", 10);
        List<Map<String, Object>> items = new ArrayList<>();
        items.add(item);
        return CuttingHeightConfig.builder()
                .tenantId(TENANT)
                .items(items)
                .rounding(Map.of("mode", "half_up", "digits", 3))
                .build();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> firstPosition(Map<String, Object> out) {
        return ((List<Map<String, Object>>) out.get("positions")).get(0);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> hitsOf(Map<String, Object> position) {
        return (List<Map<String, Object>>) position.get("hits");
    }
}
