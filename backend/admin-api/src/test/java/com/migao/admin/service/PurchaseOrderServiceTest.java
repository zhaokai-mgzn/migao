// case_ids: SP-005
package com.migao.admin.service;

import com.migao.admin.dto.PurchaseOrderCreateRequest;
import com.migao.admin.dto.PurchaseOrderReceiveRequest;
import com.migao.admin.dto.PurchaseOrderView;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.PurchaseOrder;
import com.migao.admin.entity.PurchaseOrderItem;
import com.migao.admin.entity.PurchaseOrderReceipt;
import com.migao.admin.entity.Supplier;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.PurchaseOrderItemMapper;
import com.migao.admin.mapper.PurchaseOrderMapper;
import com.migao.admin.mapper.PurchaseOrderReceiptMapper;
import com.migao.admin.mapper.SupplierMapper;
import com.migao.admin.time.BusinessClock;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 采购单（issue #7369 段 4）—— 常见做法：**一单可多次收货**，允许提前关闭（写原因）。
 *
 * <p>本判据守五条：① 收货不许超收；② 只能在 ordered / partially_received 上收货；
 * ③ 关单必须写原因；④ 停用供应商不许下新单；⑤ 状态是**派生**的（收齐 ⇒ received，部分 ⇒ partially_received）。</p>
 *
 * <p>红证方向：把 ① 的上限比较删掉 ⇒ {@link #receiveCannotExceedRemaining} 当场红。</p>
 */
@ExtendWith(MockitoExtension.class)
class PurchaseOrderServiceTest {

    private static final Long TENANT = 2001L;
    private static final String SUPPLIER = "sup-1";
    private static final String PO = "po-1";
    private static final String ITEM = "item-1";

    @Mock private PurchaseOrderMapper orderMapper;
    @Mock private PurchaseOrderItemMapper itemMapper;
    @Mock private PurchaseOrderReceiptMapper receiptMapper;
    @Mock private SupplierMapper supplierMapper;
    @Mock private InboundOrderMapper inboundOrderMapper;
    @Mock private ProductSkuMapper skuMapper;
    @Mock private ProductMapper productMapper;
    @Mock private BusinessClock businessClock;

    @InjectMocks private PurchaseOrderService service;

    @BeforeEach
    void setUp() {
        lenient().when(businessClock.today()).thenReturn(LocalDate.of(2026, 10, 20));
        lenient().when(supplierMapper.selectById(SUPPLIER)).thenReturn(
                Supplier.builder().id(SUPPLIER).tenantId(TENANT).name("杭州染整一厂").status("active").build());
        // issue #7568：建单要校验 SKU 归属，故夹具里的 SKU 必须是**真的存在**的（默认夹具 SKU-1）。
        lenient().when(skuMapper.selectById("SKU-1")).thenReturn(
                ProductSku.builder().id(1L).tenantId(TENANT).productId("prod-1").skuCode("SKU-1").build());
    }

    private PurchaseOrder order(String status) {
        return PurchaseOrder.builder()
                .id(PO).tenantId(TENANT).poNo("CG-20261020-0001").supplierId(SUPPLIER)
                .orderDate(LocalDate.of(2026, 10, 20)).status(status)
                .totalAmount(new BigDecimal("1000.0000")).build();
    }

    private PurchaseOrderItem item(String qty) {
        return PurchaseOrderItem.builder()
                .id(ITEM).tenantId(TENANT).purchaseOrderId(PO).lineNo(1).skuId("SKU-1")
                .quantity(new BigDecimal(qty)).unitPrice(new BigDecimal("10.00"))
                .amount(new BigDecimal("1000.00")).build();
    }

    /** 让 insert 把 id 写回实体（真实 Mapper 由 MyBatis 赋值）；后续 detail() 能读回。 */
    private void givenInsertsAssignIds() {
        lenient().when(orderMapper.insert(any(PurchaseOrder.class))).thenAnswer(inv -> {
            PurchaseOrder o = inv.getArgument(0);
            o.setId(PO);
            lenient().when(orderMapper.selectById(PO)).thenReturn(o);
            return 1;
        });
        lenient().when(itemMapper.insert(any(PurchaseOrderItem.class))).thenAnswer(inv -> {
            PurchaseOrderItem it = inv.getArgument(0);
            it.setId(ITEM);
            return 1;
        });
        lenient().when(orderMapper.selectCount(any())).thenReturn(0L);
        lenient().when(orderMapper.updateById(any(PurchaseOrder.class))).thenReturn(1);
        lenient().when(itemMapper.selectById(ITEM)).thenReturn(item("100"));
    }

    @Test
    @DisplayName("建单：单号 CG-yyyyMMdd-NNNN、金额 = 数量 × 单价（2 位小数）、状态一律 ordered")
    void createComputesAmountAndStatus() {
        givenInsertsAssignIds();
        lenient().when(itemMapper.selectList(any())).thenReturn(List.of(item("100")));
        lenient().when(receiptMapper.selectList(any())).thenReturn(List.of());

        PurchaseOrderView view = service.create(new PurchaseOrderCreateRequest(
                SUPPLIER, null, LocalDate.of(2026, 10, 25), "补货",
                List.of(new PurchaseOrderCreateRequest.Item("SKU-1", new BigDecimal("100"), new BigDecimal("10.00"), null))),
                TENANT, "buyer");

        assertThat(view.poNo()).startsWith("CG-20261020-");
        assertThat(view.status()).isEqualTo(PurchaseOrder.STATUS_ORDERED);
        assertThat(view.totalAmount()).isEqualByComparingTo("1000");
        assertThat(view.items()).hasSize(1);
        assertThat(view.items().get(0).remainingQuantity()).isEqualByComparingTo("100");
    }

    @Test
    @DisplayName("明细带展示名（issue #7567）：收货面要认得出是哪块布 —— 服务端解析商品 / 颜色 / 门幅")
    void itemViewCarriesDisplayNames() {
        // 真实量级的雪花号（> 2^53）：用玩具 id 测不出「字符串被数字化」那类洞
        String snowflake = "2097126615461462018";
        when(orderMapper.selectById(PO)).thenReturn(order(PurchaseOrder.STATUS_ORDERED));
        lenient().when(itemMapper.selectList(any())).thenReturn(List.of(
                PurchaseOrderItem.builder().id(ITEM).tenantId(TENANT).purchaseOrderId(PO).lineNo(1)
                        .skuId(snowflake).productId("prod-1")
                        .quantity(new BigDecimal("100")).unitPrice(new BigDecimal("10.00"))
                        .amount(new BigDecimal("1000.00")).build()));
        lenient().when(receiptMapper.selectList(any())).thenReturn(List.of());
        lenient().when(skuMapper.selectList(any())).thenReturn(List.of(
                ProductSku.builder().id(Long.valueOf(snowflake)).tenantId(TENANT).productId("prod-1")
                        .skuCode("H-2699-01").colorName("米白").doorWidth("3.2").build()));
        lenient().when(productMapper.selectList(any())).thenReturn(List.of(
                Product.builder().id("prod-1").tenantId(TENANT).name("遮光窗帘布").build()));

        PurchaseOrderView view = service.detail(PO, TENANT);

        PurchaseOrderView.ItemView line = view.items().get(0);
        assertThat(line.skuId()).isEqualTo(snowflake);
        assertThat(line.productName()).isEqualTo("遮光窗帘布");
        assertThat(line.skuCode()).isEqualTo("H-2699-01");
        assertThat(line.colorName()).isEqualTo("米白");
        assertThat(line.doorWidth()).isEqualTo("3.2");
    }

    @Test
    @DisplayName("取不到商品时展示字段留空（**绝不**拿 skuId 冒充商品名 —— 内部标识不上屏）")
    void itemViewLeavesDisplayNamesNullWhenSkuMissing() {
        when(orderMapper.selectById(PO)).thenReturn(order(PurchaseOrder.STATUS_ORDERED));
        lenient().when(itemMapper.selectList(any())).thenReturn(List.of(item("100")));
        lenient().when(receiptMapper.selectList(any())).thenReturn(List.of());
        // item("100") 的 skuId = "SKU-1"（非数字）⇒ 不进批量查询 ⇒ 展示字段全 null
        PurchaseOrderView view = service.detail(PO, TENANT);

        // 非数字 id 连查询都不该发（也就不会把 null 当键去取 map）
        verify(skuMapper, never()).selectList(any());

        PurchaseOrderView.ItemView line = view.items().get(0);
        assertThat(line.productName()).isNull();
        assertThat(line.skuCode()).isNull();
        assertThat(line.colorName()).isNull();
        assertThat(line.doorWidth()).isNull();
    }

    @Test
    @DisplayName("建单被拒的三类：停用供应商 / 空明细 / 单价超两位小数（钱只有两位小数的物理意义）")
    void createRejectsInvalidInput() {
        when(supplierMapper.selectById("sup-off")).thenReturn(
                Supplier.builder().id("sup-off").tenantId(TENANT).status("inactive").build());
        assertThatThrownBy(() -> service.create(new PurchaseOrderCreateRequest(
                "sup-off", null, null, null,
                List.of(new PurchaseOrderCreateRequest.Item("SKU-1", BigDecimal.ONE, BigDecimal.ONE, null))),
                TENANT, "buyer"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("已停用");

        assertThatThrownBy(() -> service.create(new PurchaseOrderCreateRequest(
                SUPPLIER, null, null, null, List.of()), TENANT, "buyer"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("至少要有一行");

        assertThatThrownBy(() -> service.create(new PurchaseOrderCreateRequest(
                SUPPLIER, null, null, null,
                List.of(new PurchaseOrderCreateRequest.Item("SKU-1", BigDecimal.ONE, new BigDecimal("1.005"), null))),
                TENANT, "buyer"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("小数");
        verify(orderMapper, never()).insert(any(PurchaseOrder.class));
    }

    @Test
    @DisplayName("建单拒绝不存在的 SKU（issue #7568）：直连 API 不许落指向鬼 SKU 的明细 —— 收货面会解析不到、应付照算")
    void createRejectsUnknownSku() {
        assertThatThrownBy(() -> service.create(new PurchaseOrderCreateRequest(
                SUPPLIER, null, null, null,
                List.of(new PurchaseOrderCreateRequest.Item("SKU-ghost", BigDecimal.ONE,
                        new BigDecimal("10.00"), null))),
                TENANT, "buyer"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("SKU 不存在或不属于当前租户");
        // 先校验、后写：任何一行不合法都不留半张采购单
        verify(orderMapper, never()).insert(any(PurchaseOrder.class));
        verify(itemMapper, never()).insert(any(PurchaseOrderItem.class));
    }

    @Test
    @DisplayName("建单拒绝「商品与 SKU 不一致」（issue #7568）：别家商品的 productId 不许挂在别人的 SKU 上")
    void createRejectsSkuFromAnotherProduct() {
        lenient().when(skuMapper.selectById("SKU-9")).thenReturn(
                ProductSku.builder().id(9L).tenantId(TENANT).productId("prod-9").skuCode("SKU-9").build());
        assertThatThrownBy(() -> service.create(new PurchaseOrderCreateRequest(
                SUPPLIER, null, null, null,
                List.of(new PurchaseOrderCreateRequest.Item("SKU-9", BigDecimal.ONE,
                        new BigDecimal("10.00"), "prod-1"))),
                TENANT, "buyer"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("商品与 SKU 不一致");
        verify(orderMapper, never()).insert(any(PurchaseOrder.class));
    }

    @Test
    @DisplayName("合法 SKU ⇒ 建单成功且 product_id 落库（issue #7568 的反向对照：校验不许把正常路径一起挡死）")
    void createPersistsProductIdOfValidSku() {
        givenInsertsAssignIds();
        lenient().when(itemMapper.selectList(any())).thenReturn(List.of(item("100")));
        lenient().when(receiptMapper.selectList(any())).thenReturn(List.of());

        service.create(new PurchaseOrderCreateRequest(
                SUPPLIER, null, null, null,
                List.of(new PurchaseOrderCreateRequest.Item("SKU-1", new BigDecimal("100"),
                        new BigDecimal("10.00"), "prod-1"))),
                TENANT, "buyer");

        ArgumentCaptor<PurchaseOrderItem> captor = ArgumentCaptor.forClass(PurchaseOrderItem.class);
        verify(itemMapper).insert(captor.capture());
        assertThat(captor.getValue().getProductId()).isEqualTo("prod-1");
        assertThat(captor.getValue().getSkuId()).isEqualTo("SKU-1");
    }

    @Test
    @DisplayName("部分收货 ⇒ partially_received；收齐 ⇒ received（状态由 Σ收货派生）")
    void statusIsDerivedFromReceipts() {
        givenInsertsAssignIds();
        when(orderMapper.selectById(PO)).thenReturn(order(PurchaseOrder.STATUS_ORDERED));
        lenient().when(itemMapper.selectList(any())).thenReturn(List.of(item("100")));
        lenient().when(itemMapper.selectById(ITEM)).thenReturn(item("100"));

        // 收货记录「落库」= insert 进这个可变表，selectList 读它（真实 Mapper 是同表读写）
        java.util.List<PurchaseOrderReceipt> persisted = new java.util.ArrayList<>();
        PurchaseOrderReceipt seed = null;
        lenient().when(receiptMapper.insert(any(PurchaseOrderReceipt.class))).thenAnswer(inv -> {
            persisted.add(inv.getArgument(0));
            return 1;
        });
        lenient().when(receiptMapper.selectList(any()))
                .thenAnswer(inv -> new java.util.ArrayList<>(persisted));

        // 第一次：收 40 ⇒ partially_received
        PurchaseOrderView afterFirst = service.receive(PO,
                new PurchaseOrderReceiveRequest(null, "首批", List.of(
                        new PurchaseOrderReceiveRequest.Line(ITEM, new BigDecimal("40"), null))), TENANT, "wh");
        assertThat(afterFirst.status()).isEqualTo(PurchaseOrder.STATUS_PARTIALLY_RECEIVED);

        // 第二次：再收 60 ⇒ received
        PurchaseOrderView afterSecond = service.receive(PO,
                new PurchaseOrderReceiveRequest(null, "尾批", List.of(
                        new PurchaseOrderReceiveRequest.Line(ITEM, new BigDecimal("60"), null))), TENANT, "wh");
        assertThat(afterSecond.status()).isEqualTo(PurchaseOrder.STATUS_RECEIVED);
        verify(receiptMapper, org.mockito.Mockito.times(2)).insert(any(PurchaseOrderReceipt.class));
    }

    @Test
    @DisplayName("收货不许超收（本次 ≤ 采购数量 − 已收）：多收了账就永远对不上")
    void receiveCannotExceedRemaining() {
        when(orderMapper.selectById(PO)).thenReturn(order(PurchaseOrder.STATUS_ORDERED));
        lenient().when(itemMapper.selectList(any())).thenReturn(List.of(item("100")));
        when(receiptMapper.selectList(any())).thenReturn(List.of(PurchaseOrderReceipt.builder()
                .id("r-1").tenantId(TENANT).purchaseOrderId(PO).purchaseOrderItemId(ITEM)
                .quantity(new BigDecimal("90")).build()));

        assertThatThrownBy(() -> service.receive(PO, new PurchaseOrderReceiveRequest(null, null,
                List.of(new PurchaseOrderReceiveRequest.Line(ITEM, new BigDecimal("20"), null))), TENANT, "wh"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("超出该行未收数量");
        verify(receiptMapper, never()).insert(any(PurchaseOrderReceipt.class));
    }

    @Test
    @DisplayName("已关闭 / 已收齐的单不许再收货（关单决定不能被绕过）")
    void closedOrReceivedOrderCannotReceive() {
        when(orderMapper.selectById(PO)).thenReturn(order(PurchaseOrder.STATUS_CLOSED));
        assertThatThrownBy(() -> service.receive(PO, new PurchaseOrderReceiveRequest(null, null,
                List.of(new PurchaseOrderReceiveRequest.Line(ITEM, BigDecimal.ONE, null))), TENANT, "wh"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("已关闭");

        when(orderMapper.selectById(PO)).thenReturn(order(PurchaseOrder.STATUS_RECEIVED));
        assertThatThrownBy(() -> service.receive(PO, new PurchaseOrderReceiveRequest(null, null,
                List.of(new PurchaseOrderReceiveRequest.Line(ITEM, BigDecimal.ONE, null))), TENANT, "wh"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("已收齐");
        verify(receiptMapper, never()).insert(any(PurchaseOrderReceipt.class));
    }

    @Test
    @DisplayName("关单：必须写原因、收齐的不能关、已关闭不能重复关")
    void closeRequiresReason() {
        PurchaseOrder partially = order(PurchaseOrder.STATUS_PARTIALLY_RECEIVED);
        when(orderMapper.selectById(PO)).thenReturn(partially);
        assertThatThrownBy(() -> service.close(PO, " ", TENANT, "buyer"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("必须写原因");

        lenient().when(itemMapper.selectList(any())).thenReturn(List.of(item("100")));
        lenient().when(receiptMapper.selectList(any())).thenReturn(List.of());
        PurchaseOrderView closed = service.close(PO, "供应商断货", TENANT, "buyer");
        assertThat(closed.status()).isEqualTo(PurchaseOrder.STATUS_CLOSED);
        assertThat(closed.closedReason()).isEqualTo("供应商断货");

        assertThatThrownBy(() -> service.close(PO, "再关一次", TENANT, "buyer"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("已关闭");

        when(orderMapper.selectById(PO)).thenReturn(order(PurchaseOrder.STATUS_RECEIVED));
        assertThatThrownBy(() -> service.close(PO, "收齐了还想关", TENANT, "buyer"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("已收齐");
    }

    @Test
    @DisplayName("关联入库单：必须本租户、已过账、且属于同一供应商")
    void linkedInboundOrderMustMatch() {
        when(orderMapper.selectById(PO)).thenReturn(order(PurchaseOrder.STATUS_ORDERED));
        lenient().when(itemMapper.selectList(any())).thenReturn(List.of(item("100")));
        when(receiptMapper.selectList(any())).thenReturn(List.of());

        when(inboundOrderMapper.selectById("in-draft")).thenReturn(InboundOrder.builder()
                .id("in-draft").inboundNo("RK-D").supplierId(SUPPLIER).status(InboundOrder.STATUS_DRAFT).build());
        assertThatThrownBy(() -> service.receive(PO, new PurchaseOrderReceiveRequest(null, null,
                List.of(new PurchaseOrderReceiveRequest.Line(ITEM, BigDecimal.ONE, "in-draft"))), TENANT, "wh"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("已过账");

        when(inboundOrderMapper.selectById("in-other")).thenReturn(InboundOrder.builder()
                .id("in-other").inboundNo("RK-O").supplierId("sup-other").status(InboundOrder.STATUS_POSTED).build());
        assertThatThrownBy(() -> service.receive(PO, new PurchaseOrderReceiveRequest(null, null,
                List.of(new PurchaseOrderReceiveRequest.Line(ITEM, BigDecimal.ONE, "in-other"))), TENANT, "wh"))
                .isInstanceOf(BusinessException.class).hasMessageContaining("不属于本采购单的供应商");
        verify(receiptMapper, never()).insert(any(PurchaseOrderReceipt.class));
    }
}
