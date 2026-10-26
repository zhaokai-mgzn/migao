// case_ids: WH-007, WH-008
package com.migao.admin.service;

import com.migao.admin.entity.FinishedGoodsStock;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.OutboundOrder;
import com.migao.admin.entity.ProcessingOrderSet;
import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.FinishedGoodsStockMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderSetMapper;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import com.migao.admin.mapper.ProductionWorkLogMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 扫水洗唛出库（V197 / issue #7762）的服务层判据。
 *
 * <p>用户口径（2026-10-25 逐字）：① 「允许工人扫码水洗唛进行成品出库打标签操作」；
 * ② 「只有关联打包工序的工人扫码后才能操作出库」。这两句在实现上分别是
 * <b>一张唛 = 一个在库行</b>（套 × 部位）与 <b>授权取自报工记录</b>（{@code production_work_logs} 有打包工序）。
 * 本类把四条会红的形态钉住：非打包工人、未入库、重复出库、标签缺值不渲染。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("扫水洗唛出库：套×部位粒度 + 打包工序授权 + 幂等 + 标签缺值不渲染（V197）")
class FinishedWashLabelTest {

    private static final Long TENANT = 1L;
    private static final String TOKEN = "tok-abc123";
    private static final String SHORT = "7K2M9QX4";

    @Mock private FinishedGoodsStockMapper stockMapper;
    @Mock private OrderItemMapper orderItemMapper;
    @Mock private WarehouseService warehouseService;
    @Mock private InboundOrderService inboundOrderService;
    @Mock private OutboundOrderService outboundOrderService;
    @Mock private ProcessingSetPartTokenMapper tokenMapper;
    @Mock private ProcessingOrderSetMapper setMapper;
    @Mock private ProductionWorkLogMapper workLogMapper;
    @Mock private OrderMapper orderMapper;

    @InjectMocks private FinishedGoodsService service;

    private ProcessingSetPartToken token;
    private ProcessingOrderSet set;
    private FinishedGoodsStock stock;
    private Order order;
    private OrderItem item;

    @BeforeEach
    void setUp() {
        token = ProcessingSetPartToken.builder()
                .id("tok-row-1").tenantId(TENANT).processingOrderId("po-1").setId("set-3")
                .orderItemId("item-cloth").positionKind("布帘").token(TOKEN).shortCode(SHORT).deleted(0).build();
        set = ProcessingOrderSet.builder().id("set-3").tenantId(TENANT).processingOrderId("po-1")
                .setIndex(3).setNo("SET-3").deleted(0).build();
        stock = FinishedGoodsStock.builder().id(9L).tenantId(TENANT).orderId("order-1")
                .orderNo("0901-00084").orderItemId("item-cloth").productName("布帘").quantity(BigDecimal.ONE)
                .unit("set").status(FinishedGoodsStock.STATUS_IN_STOCK).binCode("A-01")
                .setId("set-3").setNo("SET-3").setIndex(3).partTokenId("tok-row-1").shortCode(SHORT).build();
        order = Order.builder().id("order-1").tenantId(TENANT).orderNo("0901-00084")
                .customerName("肖风伟").createdAt(OffsetDateTime.parse("2026-09-01T10:00:00+08:00")).build();
        item = OrderItem.builder().id("item-cloth").tenantId(TENANT).skuCode("2706-03")
                .productName("布帘").width(new BigDecimal("3.00")).height(new BigDecimal("2.70")).openCount(2).build();

        when(tokenMapper.selectByTokenOrShortCode(TENANT, TOKEN)).thenReturn(token);
        when(tokenMapper.selectByTokenOrShortCode(TENANT, SHORT)).thenReturn(token);
        when(stockMapper.selectInStockByWashLabel(TENANT, TOKEN)).thenReturn(stock);
        when(stockMapper.selectInStockByWashLabel(TENANT, SHORT)).thenReturn(stock);
        when(setMapper.selectById("set-3")).thenReturn(set);
        when(setMapper.selectCount(any())).thenReturn(5L);
        when(orderMapper.selectById("order-1")).thenReturn(order);
        when(orderItemMapper.selectById("item-cloth")).thenReturn(item);
        Warehouse warehouse = new Warehouse();
        warehouse.setId(1L);
        warehouse.setName("成品仓");
        when(warehouseService.ensureFinishedWarehouse(TENANT)).thenReturn(warehouse);
        when(outboundOrderService.createScanOutbound(anyString(), any(), any(), anyLong(), anyString()))
                .thenReturn(OutboundOrder.builder().id("ob-1").outboundNo("CK-0001").build());
        when(stockMapper.markShippedById(TENANT, 9L, "ob-1")).thenReturn(1);
    }

    // ── ① 允许出库：包装工序工人 + 在库

    @Test
    @DisplayName("打包工序工人扫在库唛 ⇒ allowed=true，标签「打包区域」= 仓位号、套数 = 第3套/共5套")
    void packerCanOutboundAndLabelCarriesBinAndSetNo() {
        when(workLogMapper.countPackerLogs(TENANT, "po-1", "w-1")).thenReturn(1);

        Map<String, Object> view = service.washLabelView(TENANT, TOKEN, "w-1", "张三");

        assertThat(view).containsEntry("allowed", true)
                .containsEntry("bin_code", "A-01")
                .containsEntry("short_code", SHORT);
        @SuppressWarnings("unchecked")
        List<Map<String, String>> rows = (List<Map<String, String>>)
                ((Map<String, Object>) view.get("label")).get("rows");
        assertThat(rows).extracting(r -> r.get("label"))
                .contains("订单编号", "客户", "下单日期", "套数", "尺寸", "开数", "帘种", "主布货号", "打包区域")
                // issue #7856：纸面标签统一叫「帘种」，不再有「部位」行
                .doesNotContain("部位")
                // 安装信息缺值（本夹具 processingInfo 为空）⇒ 整行不印（不印 `—`）
                .doesNotContain("安装小区", "安装位置");
        assertThat(rows).filteredOn(r -> "打包区域".equals(r.get("label")))
                .singleElement().satisfies(r -> assertThat(r.get("value")).isEqualTo("A-01"));
        assertThat(rows).filteredOn(r -> "套数".equals(r.get("label")))
                .singleElement().satisfies(r -> assertThat(r.get("value")).isEqualTo("第3套/共5套"));
        assertThat(rows).filteredOn(r -> "尺寸".equals(r.get("label")))
                .singleElement().satisfies(r -> assertThat(r.get("value")).isEqualTo("3*2.7"));
        // 没有稳定来源的字段不得出现（不印 `—`、不编造）
        assertThat(rows).extracting(r -> r.get("label"))
                .doesNotContain("项目名称", "款式", "安装工艺", "扩展选项");
    }

    @Test
    @DisplayName("🔴 成品入库标签带安装信息（issue #7856）：有值按「帘种→安装小区→安装位置→主布货号」印，缺值整行不印")
    void finishedLabelCarriesInstallInfo() {
        when(workLogMapper.countPackerLogs(TENANT, "po-1", "w-1")).thenReturn(1);
        // 真值 = 订单行 `processing_info` 顶层两键（零迁移）；测试直连 service ⇒ 字段注入的 mapper 手动补上
        item.setProcessingInfo(Map.of("installCommunity", "春江花园 3栋2单元", "installRoom", "主卧"));
        org.springframework.test.util.ReflectionTestUtils.setField(
                service, "objectMapper", new com.fasterxml.jackson.databind.ObjectMapper());

        @SuppressWarnings("unchecked")
        List<Map<String, String>> rows = (List<Map<String, String>>)
                ((Map<String, Object>) service.washLabelView(TENANT, TOKEN, "w-1", "张三").get("label")).get("rows");
        // 行序：安装信息紧跟在帘种之后、主布货号之前（拣货/贴箱的人先认这户人家、再认布）
        assertThat(rows).extracting(r -> r.get("label"))
                .containsSubsequence("帘种", "安装小区", "安装位置", "主布货号");
        assertThat(rows).filteredOn(r -> "安装小区".equals(r.get("label")))
                .singleElement().satisfies(r -> assertThat(r.get("value")).isEqualTo("春江花园 3栋2单元"));
        assertThat(rows).filteredOn(r -> "安装位置".equals(r.get("label")))
                .singleElement().satisfies(r -> assertThat(r.get("value")).isEqualTo("主卧"));

        // 缺值对照：键清空 ⇒ 两行都不得出现（「不印 —」不是只对水洗唛成立）
        item.setProcessingInfo(Map.of());
        @SuppressWarnings("unchecked")
        List<Map<String, String>> blankRows = (List<Map<String, String>>)
                ((Map<String, Object>) service.washLabelView(TENANT, TOKEN, "w-1", "张三").get("label")).get("rows");
        assertThat(blankRows).extracting(r -> r.get("label")).doesNotContain("安装小区", "安装位置");
    }

    @Test
    @DisplayName("出库：在库行置 shipped + 出库单 source=scan（单行 + 仓位号），重复提交 409 且不再建单")
    void outboundMarksStockShippedAndCreatesScanDocIdempotently() {
        when(workLogMapper.countPackerLogs(TENANT, "po-1", "w-1")).thenReturn(1);

        Map<String, Object> out = service.issueByWashLabel(TENANT, TOKEN, "w-1", "张三");

        assertThat(out).containsEntry("allowed", false).containsEntry("reason", "已出库")
                .containsEntry("outbound_no", "CK-0001");
        verify(stockMapper).markShippedById(TENANT, 9L, "ob-1");
        verify(outboundOrderService).createScanOutbound(eq("0901-00084"), eq(stock), any(), eq(TENANT), eq("张三"));

        // 第二次：在库行已不存在 ⇒ 服务端拒绝，且不再建第二张单、不再扣减
        // （先清掉第一次调用的记录，`never()` 才是在问「第二次有没有再建单」）
        org.mockito.Mockito.clearInvocations(outboundOrderService, stockMapper);
        when(stockMapper.selectInStockByWashLabel(TENANT, TOKEN)).thenReturn(null);
        assertThatThrownBy(() -> service.issueByWashLabel(TENANT, TOKEN, "w-1", "张三"))
                .isInstanceOf(BusinessException.class);
        org.mockito.Mockito.verify(outboundOrderService, never())
                .createScanOutbound(any(), any(), any(), any(), any());
    }

    // ── ② 授权：非打包工序工人

    @Test
    @DisplayName("非打包工序工人扫同一张唛 ⇒ allowed=false + 说清原因；写面 409，零库存变动、零出库单")
    void nonPackerIsRejectedWithZeroInventoryChange() {
        when(workLogMapper.countPackerLogs(TENANT, "po-1", "w-2")).thenReturn(0);

        Map<String, Object> view = service.washLabelView(TENANT, TOKEN, "w-2", "李四");
        assertThat(view).containsEntry("allowed", false)
                .containsEntry("reason", "只有做过打包工序的工人才能扫码出库");

        assertThatThrownBy(() -> service.issueByWashLabel(TENANT, TOKEN, "w-2", "李四"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("打包工序");
        verify(stockMapper, never()).markShippedById(anyLong(), anyLong(), any());
        verify(outboundOrderService, never()).createScanOutbound(any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("未入库 / 已出库 ⇒ allowed=false（原因说「不在库」），标签仍带仓位号为空")
    void notInStockIsNotAllowed() {
        when(workLogMapper.countPackerLogs(TENANT, "po-1", "w-1")).thenReturn(1);
        when(stockMapper.selectInStockByWashLabel(TENANT, TOKEN)).thenReturn(null);

        Map<String, Object> view = service.washLabelView(TENANT, TOKEN, "w-1", "张三");
        assertThat(view).containsEntry("allowed", false);
        assertThat(String.valueOf(view.get("reason"))).contains("不在库");
        assertThat(view).containsEntry("bin_code", null);
    }

    @Test
    @DisplayName("短码与 token 是同一行的两种表示 ⇒ 两种输入给同一张标签")
    void shortCodeAndTokenResolveToSameLabel() {
        when(workLogMapper.countPackerLogs(TENANT, "po-1", "w-1")).thenReturn(1);

        Map<String, Object> byToken = service.washLabelView(TENANT, TOKEN, "w-1", "张三");
        Map<String, Object> byShort = service.washLabelView(TENANT, SHORT, "w-1", "张三");

        assertThat(((Map<?, ?>) byShort.get("label")).get("rows"))
                .isEqualTo(((Map<?, ?>) byToken.get("label")).get("rows"));
        assertThat(((Map<?, ?>) byShort.get("label")).get("qr_value")).isEqualTo("/s/" + SHORT);
    }
}
