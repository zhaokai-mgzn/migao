// case_ids: PG-045
package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.CuttingHeightConfig;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProcessingOrder;
import com.migao.admin.entity.ProductAttribute;
import com.migao.admin.exception.BusinessException;
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
import org.mockito.ArgumentCaptor;
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
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 一体机裁高读面（母单 #5161；设计 {@code docs/design/cutting-height-config-and-terminal.md} §2.5/§2.6）。
 *
 * <p>本类钉住「扫一次码 ⇒ 一屏」这条链上的**六个会重开的判据**（每条都能红）：</p>
 * <ol>
 *   <li><b>一次扫码出详情与裁高值</b>：码 ⇒ （套 × 部位）⇒ 逐部位详情（宽高/工艺/加工类型/开数/褶倍/
 *       用料/部位备注/品牌）+ {@code base}/{@code cutting_height}；红证：详情键少一个 / 裁高不出现 ⇒ 红；</li>
 *   <li><b>命中口径逐字取自订单行</b>：四类触发（特殊选项 / 安装工艺 / 加工项 / 是否定型）+ 部位限定
 *       **全部**由订单行取值命中；红证：本层把 {@code special_options} 写死成空表 ⇒ 红；</li>
 *   <li><b>未配置取值（「画线」形态）不计入且显式报出</b>：它在 {@code misses}（{@code unresolved}）
 *       —— **不按 0 算**；红证：按 0 计入合计 ⇒ 红；</li>
 *   <li><b>取整三位小数</b>：{@code 3.0275 → 3.028}（half_up，scale=3）+ {@code rounding.digits=3}；
 *       红证：改成两位 / 截断 ⇒ 红；</li>
 *   <li><b>缺成品高 ⇒ 显式报缺、不算</b>（{@code missing=["finished_height"]} + 裁高为 null）；
 *       红证：按 0 算出一个数 ⇒ 红；</li>
 *   <li><b>旧码（到加工单级）⇒ 显式拒绝</b>，绝不默认取第 1 个部位 —— 取错部位 = 给机器一个错的裁高。</li>
 * </ol>
 *
 * <p>🔴 <b>本读面不写机器</b>：源码面守卫在 {@code WorkerProductionCuttingHeightTest}（同一 case_id 的另一半）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("WorkerCuttingHeightService 一体机裁高读面（母单 #5161）")
class WorkerCuttingHeightServiceTest {

    private static final Long TENANT = 7L;
    private static final String ORDER_ID = "order-1";

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
        // **真** CuttingHeightConfigService（命中与取整的唯一实现）+ mock mapper（配置行由用例给）
        CuttingHeightConfigService configService = new CuttingHeightConfigService(cuttingHeightConfigMapper,
                new TenantParamAuditService(org.mockito.Mockito.mock(TenantParamAuditMapper.class),
                        new SimpleMeterRegistry(), new ObjectMapper()));
        service = new WorkerCuttingHeightService(productionScanService, configService, orderItemMapper,
                orderMapper, processingOrderMapper, processingOrderSetMapper, productAttributeMapper);
    }

    // ────────────────────────── ① 扫一次码 ⇒ 一屏 ──────────────────────────

    @Test
    @DisplayName("① 扫一次部位级码 ⇒ 详情（宽高/工艺/加工类型/开数/褶倍/用料/备注/品牌）+ 裁高值")
    void scanResolvesOneScreenWithDetailAndCuttingHeight() {
        stubScan(setPositionView());
        stubOrderLine(items());
        when(orderMapper.selectOne(any())).thenReturn(Order.builder()
                .id(ORDER_ID).tenantId(TENANT).orderNo("SO20260929001").customerName("张女士").build());
        when(processingOrderMapper.selectList(any())).thenReturn(List.of(
                ProcessingOrder.builder().id("po-1").tenantId(TENANT).orderId(ORDER_ID).build()));
        when(processingOrderSetMapper.selectCount(any())).thenReturn(3L);
        when(productAttributeMapper.selectList(any())).thenReturn(List.of(
                ProductAttribute.builder().tenantId(TENANT).productId("p-cloth").attrKey("brand").attrValue("观星台").build()));
        when(cuttingHeightConfigMapper.selectActiveByTenant(TENANT)).thenReturn(storedConfig());

        Map<String, Object> out = service.read("7K3M9QP2", TENANT);

        assertThat(out.get("granularity")).isEqualTo("set_position");
        @SuppressWarnings("unchecked")
        Map<String, Object> header = (Map<String, Object>) out.get("order");
        assertThat(header.get("order_no")).isEqualTo("SO20260929001");
        assertThat(header.get("customer_name")).isEqualTo("张女士");
        assertThat(header.get("set_no")).isEqualTo("1");
        assertThat(header.get("set_count")).isEqualTo(3L);

        List<Map<String, Object>> positions = positionsOf(out);
        assertThat(positions).extracting(p -> p.get("position_kind")).containsExactly("布帘", "纱帘");
        Map<String, Object> cloth = positions.get(0);
        assertThat(cloth.get("scanned")).isEqualTo(true);
        assertThat(cloth.get("brand")).isEqualTo("观星台");
        assertThat(cloth.get("product_name")).isEqualTo("全遮光布窗帘");
        assertThat(cloth.get("width")).isEqualTo(new BigDecimal("3.500"));
        assertThat(cloth.get("height")).isEqualTo(new BigDecimal("2.700"));
        assertThat(cloth.get("craft")).isEqualTo("韩褶");
        assertThat(cloth.get("curtain_type")).isEqualTo("布帘");
        assertThat(cloth.get("open_count")).isEqualTo(2);
        assertThat(cloth.get("cutting_mode")).isEqualTo("定高买宽");
        assertThat(cloth.get("fullness")).isEqualTo(new BigDecimal("2.0"));
        assertThat(cloth.get("position_remark")).isEqualTo("左窗");
        assertThat(cloth.get("fabric_meters")).isEqualTo(new BigDecimal("8.10"));
        assertThat((BigDecimal) cloth.get("base")).isEqualByComparingTo("2.700");
        assertThat((BigDecimal) cloth.get("cutting_height")).isEqualByComparingTo("3.028");
        assertThat(cloth.get("missing")).isEqualTo(List.of());
    }

    // ────────────────────────── ② 命中口径逐字取自订单行 ──────────────────────────

    @Test
    @DisplayName("② 四类触发（选项/工艺/加工项/定型）+ 部位限定**全部**由订单行取值命中")
    void hitsAreDerivedVerbatimFromTheOrderLine() {
        stubScan(setPositionView());
        stubOrderLine(items());
        when(cuttingHeightConfigMapper.selectActiveByTenant(TENANT)).thenReturn(storedConfig());

        List<Map<String, Object>> clothHits = hitsOf(service.read("7K3M9QP2", TENANT), 0);

        assertThat(clothHits).extracting(h -> h.get("key"))
                .containsExactly("jiaxian", "butie", "jiagao", "baobian");
        // 部位限定：纱帘的项不得出现在布帘行里（忽略 hit.position 就会多出 shahe）
        assertThat(clothHits).extracting(h -> h.get("key")).doesNotContain("shahe");
        assertThat(clothHits).extracting(h -> h.get("value"))
                .containsExactly(new BigDecimal("0.0625"), new BigDecimal("0.015"),
                        new BigDecimal("0.2"), new BigDecimal("0.05"));
    }

    @Test
    @DisplayName("②′ 交给预览的取值**逐字**来自订单行（本层不重算、不写死）")
    void previewReceivesTheOrderLineValuesVerbatim() {
        CuttingHeightConfigService spyConfig = org.mockito.Mockito.mock(CuttingHeightConfigService.class);
        WorkerCuttingHeightService svc = new WorkerCuttingHeightService(productionScanService, spyConfig,
                orderItemMapper, orderMapper, processingOrderMapper, processingOrderSetMapper, productAttributeMapper);
        stubScan(setPositionView());
        stubOrderLine(items());
        when(spyConfig.preview(any(), any())).thenReturn(new LinkedHashMap<>(Map.of(
                "base", new BigDecimal("2.700"), "cutting_height", new BigDecimal("2.700"),
                "rounding", Map.of("mode", "half_up", "digits", 3), "hits", List.of(), "misses", List.of())));

        svc.read("7K3M9QP2", TENANT);

        ArgumentCaptor<Map<String, Object>> body = ArgumentCaptor.forClass(Map.class);
        // 两个部位 ⇒ 两次调用；本用例钉的是**逐字取值**（取第一次 = 扫到的布帘）
        verify(spyConfig, org.mockito.Mockito.atLeastOnce())
                .preview(org.mockito.ArgumentMatchers.eq(TENANT), body.capture());
        Map<String, Object> first = body.getAllValues().get(0);
        assertThat(first.get("position")).isEqualTo("布帘");
        assertThat(first.get("finished_height")).isEqualTo(new BigDecimal("2.700"));
        assertThat(first.get("craft")).isEqualTo("韩褶");
        assertThat(first.get("cutting_mode")).isEqualTo("定高买宽");
        assertThat(first.get("special_options")).isEqualTo(List.of("加线", "画线"));
        assertThat(first.get("processing_items")).isEqualTo(List.of("包边"));
        assertThat(first.get("is_shaped")).isEqualTo(true);
    }

    // ────────────────────────── ③ 未配置取值：不计入 + 显式报出 ──────────────────────────

    @Test
    @DisplayName("③ 命中而**未配置取值**的「画线」⇒ misses(unresolved)、不计入合计、**不按 0 算**")
    void unresolvedItemIsReportedAndNeverCountedAsZero() {
        stubScan(setPositionView());
        stubOrderLine(items());
        when(cuttingHeightConfigMapper.selectActiveByTenant(TENANT)).thenReturn(storedConfig());

        Map<String, Object> cloth = positionsOf(service.read("7K3M9QP2", TENANT)).get(0);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> misses = (List<Map<String, Object>>) cloth.get("misses");
        assertThat(misses).extracting(m -> m.get("key")).containsExactly("huaxian");
        assertThat(misses).extracting(m -> m.get("name")).containsExactly("画线");
        assertThat(misses).extracting(m -> m.get("reason")).containsExactly("unresolved");
        // 合计里没有画线（0.145 之类都没进）：3.0275 是四项相加的结果
        assertThat((BigDecimal) cloth.get("cutting_height")).isEqualByComparingTo("3.028");
        assertThat(hitsOf(cloth)).extracting(h -> h.get("key")).doesNotContain("huaxian");
    }

    // ────────────────────────── ④ 取整三位小数 ──────────────────────────

    @Test
    @DisplayName("④ 取整 = half_up 三位小数：成品高 2.700 + 0.0625 + 0.015 + 0.2 + 0.05 = 3.028")
    void cuttingHeightIsRoundedToThreeDecimals() {
        stubScan(setPositionView());
        stubOrderLine(items());
        when(cuttingHeightConfigMapper.selectActiveByTenant(TENANT)).thenReturn(storedConfig());

        Map<String, Object> cloth = positionsOf(service.read("7K3M9QP2", TENANT)).get(0);

        BigDecimal value = (BigDecimal) cloth.get("cutting_height");
        assertThat(value).isEqualByComparingTo("3.028");
        assertThat(value.scale()).as("机器屏要三位小数（mm 精度）").isEqualTo(3);
        @SuppressWarnings("unchecked")
        Map<String, Object> rounding = (Map<String, Object>) cloth.get("rounding");
        assertThat(rounding.get("mode")).isEqualTo("half_up");
        assertThat(rounding.get("digits")).isEqualTo(3);
    }

    // ────────────────────────── ⑤ 缺成品高 ⇒ 显式报缺 ──────────────────────────

    @Test
    @DisplayName("⑤ 缺成品高 ⇒ missing=[finished_height]、裁高为 null（**不按 0 算**，也不整屏 4xx）")
    void missingFinishedHeightIsReportedInsteadOfGuessed() {
        stubScan(setPositionView());
        List<OrderItem> items = new ArrayList<>(items());
        items.get(0).setHeight(null);
        stubOrderLine(items);
        when(cuttingHeightConfigMapper.selectActiveByTenant(TENANT)).thenReturn(storedConfig());

        Map<String, Object> out = service.read("7K3M9QP2", TENANT);
        Map<String, Object> cloth = positionsOf(out).get(0);

        assertThat(cloth.get("missing")).isEqualTo(List.of("finished_height"));
        assertThat(cloth.get("base")).isNull();
        assertThat(cloth.get("cutting_height")).isNull();
        assertThat(cloth.get("missing_reason").toString()).contains("finished_height");
        assertThat(hitsOf(cloth)).isEmpty();
        // 同屏的另一个部位照常算出来（一个部位缺值不拖垮整屏）
        assertThat((BigDecimal) positionsOf(out).get(1).get("cutting_height")).isEqualByComparingTo("2.480");
    }

    // ────────────────────────── ⑥ 旧码 ⇒ 显式拒绝 ──────────────────────────

    @Test
    @DisplayName("🔴 旧码（只到加工单级）⇒ 422 显式拒绝，**绝不默认取第 1 个部位**")
    void legacyOrderLevelCodeIsRejectedExplicitly() {
        Map<String, Object> degraded = new LinkedHashMap<>();
        degraded.put("granularity", "order");
        degraded.put("order_id", ORDER_ID);
        degraded.put("needs_selection", List.of("set", "position"));
        when(productionScanService.resolve("JG20260929001", null, TENANT)).thenReturn(degraded);

        assertThatThrownBy(() -> service.read("JG20260929001", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("部位级");
        verify(cuttingHeightConfigMapper, never()).selectActiveByTenant(any());
    }

    @Test
    @DisplayName("空码 / 空套 ⇒ 显式拒绝（不发请求也不算一个数）")
    void blankTokenAndEmptySetAreRejected() {
        assertThatThrownBy(() -> service.read("   ", TENANT))
                .isInstanceOf(BusinessException.class);
        Map<String, Object> view = setPositionView();
        view.put("set_overview", Map.of("positions", List.of(), "cut_plan", List.of()));
        when(productionScanService.resolve("7K3M9QP2", null, TENANT)).thenReturn(view);

        assertThatThrownBy(() -> service.read("7K3M9QP2", TENANT))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("部位");
    }

    // ============================================================ 夹具

    /** 扫码解析结果（部位级）：两部位（布帘扫到的 / 纱帘）+ 用料清单。 */
    private static Map<String, Object> setPositionView() {
        Map<String, Object> scanned = new LinkedHashMap<>();
        scanned.put("order_item_id", "it-cloth");
        scanned.put("position_kind", "布帘");
        scanned.put("position_name", "布帘");
        Map<String, Object> cloth = new LinkedHashMap<>();
        cloth.put("order_item_id", "it-cloth");
        cloth.put("position_kind", "布帘");
        cloth.put("position_name", "布帘");
        cloth.put("remark", "左窗");
        Map<String, Object> gauze = new LinkedHashMap<>();
        gauze.put("order_item_id", "it-gauze");
        gauze.put("position_kind", "纱帘");
        gauze.put("position_name", "纱帘");
        Map<String, Object> cutPlan = new LinkedHashMap<>();
        cutPlan.put("order_item_id", "it-cloth");
        cutPlan.put("fabric_meters", new BigDecimal("8.10"));
        Map<String, Object> overview = new LinkedHashMap<>();
        overview.put("positions", List.of(cloth, gauze));
        overview.put("cut_plan", List.of(cutPlan));

        Map<String, Object> view = new LinkedHashMap<>();
        view.put("granularity", "set_position");
        view.put("order_id", ORDER_ID);
        view.put("processing_order_no", "JG20260929001");
        view.put("set_no", "1");
        view.put("set_index", 1);
        view.put("position", scanned);
        view.put("set_overview", overview);
        view.put("needs_selection", List.of());
        return view;
    }

    /** 订单行：布帘命中四类触发 + 一个未配置取值的「画线」；纱帘只有包纱折。 */
    private static List<OrderItem> items() {
        OrderItem cloth = new OrderItem();
        cloth.setId("it-cloth");
        cloth.setTenantId(TENANT);
        cloth.setOrderId(ORDER_ID);
        cloth.setProductId("p-cloth");
        cloth.setProductName("全遮光布窗帘");
        cloth.setWidth(new BigDecimal("3.500"));
        cloth.setHeight(new BigDecimal("2.700"));
        cloth.setCraft("韩褶");
        cloth.setCurtainType("布帘");
        cloth.setOpenCount(2);
        cloth.setCuttingMode("定高买宽");
        cloth.setFullness(new BigDecimal("2.0"));
        cloth.setIsShaped(true);
        cloth.setProcessingInfo(Map.of(
                "specialOptions", List.of("加线", "画线"),
                "processingItems", List.of(Map.of("name", "包边"))));

        OrderItem gauze = new OrderItem();
        gauze.setId("it-gauze");
        gauze.setTenantId(TENANT);
        gauze.setOrderId(ORDER_ID);
        gauze.setProductId("p-gauze");
        gauze.setProductName("幻影纱");
        gauze.setHeight(new BigDecimal("2.400"));
        gauze.setCurtainType("纱帘");
        gauze.setProcessingInfo(Map.of("specialOptions", List.of("包纱折")));
        return List.of(cloth, gauze);
    }

    /** 租户已存的裁高配置：四类触发各一条 + 「画线」有项无值 + 一条部位限定项。 */
    private static CuttingHeightConfig storedConfig() {
        List<Map<String, Object>> items = new ArrayList<>();
        items.add(item("jiaxian", "加线", "0.0625", "add", hit("option", "加线", "布帘")));
        items.add(item("butie", "布贴", "0.015", "add", hit("craft", "韩褶", null)));
        items.add(item("jiagao", "加高拼接", "0.2", "add", hit("shaped", "true", null)));
        items.add(item("baobian", "包边", "0.05", "add", hit("processing_item", "包边", null)));
        items.add(item("shahe", "纱折", "0.08", "add", hit("option", "包纱折", "纱帘")));
        items.add(item("huaxian", "画线", null, "add", hit("option", "画线", null)));
        return CuttingHeightConfig.builder()
                .tenantId(TENANT)
                .items(items)
                .rounding(Map.of("mode", "half_up", "digits", 3))
                .build();
    }

    private static Map<String, Object> item(String key, String name, String value, String direction,
                                            Map<String, Object> hit) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("key", key);
        item.put("name", name);
        item.put("value", value == null ? null : new BigDecimal(value));
        item.put("direction", direction);
        item.put("height_join", false);
        item.put("hit", hit);
        item.put("hit_expr", null);
        item.put("enabled", true);
        return item;
    }

    private static Map<String, Object> hit(String kind, String value, String position) {
        Map<String, Object> hit = new LinkedHashMap<>();
        hit.put("trigger_kind", kind);
        hit.put("trigger_value", value);
        hit.put("position", position);
        return hit;
    }

    private void stubScan(Map<String, Object> view) {
        when(productionScanService.resolve("7K3M9QP2", null, TENANT)).thenReturn(view);
    }

    private void stubOrderLine(List<OrderItem> items) {
        when(orderItemMapper.selectByOrderId(ORDER_ID, TENANT)).thenReturn(items);
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> positionsOf(Map<String, Object> out) {
        return (List<Map<String, Object>>) out.get("positions");
    }

    private static List<Map<String, Object>> hitsOf(Map<String, Object> out, int index) {
        return hitsOf(positionsOf(out).get(index));
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> hitsOf(Map<String, Object> position) {
        return (List<Map<String, Object>>) position.get("hits");
    }
}
