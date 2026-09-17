// case_ids: PR-005, AS-006
// 库存台账不变式（issue #4055）—— 同一 SKU 相邻两次变更必须首尾相接：
//   ① 上一行 after_qty == 下一行 before_qty（ledger 能回答「库存为什么从 X 变成 Y」）
//   ② after_qty - before_qty == delta（行内自洽）
// 红证：注释掉 ProductService.adjustStockForAgent / AfterSalesTicketService.maybeRestockOnReturn
//      里的写流水调用 ⇒ 本文件断言变红（台账缺行，链条断在第一环）。

package com.migao.admin.service;

import com.migao.admin.dto.AfterSalesStatusUpdateRequest;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.entity.AfterSalesTicket;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.mapper.AfterSalesTicketMapper;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import com.migao.admin.mapper.ProductColorMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductProcessingItemMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import com.migao.admin.mapper.TicketTimelineMapper;
import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
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
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.when;

/**
 * 库存台账不变式测试（issue #4055）。
 *
 * <p>装配方式：**真实** {@link StockLedgerService}（不 mock 落账逻辑）+ 真实
 * {@link ProductService} / {@link AfterSalesTicketService}，mapper 用 mock 顶替，
 * SKU 库存落在一个**内存账本**里（{@code updateById} 真的改内存值、{@code insert} 真的追加行）
 * —— 这样断言的是「库存变更 → 台账行」的真实因果，而不是「某个方法被调过」。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("库存台账不变式（issue #4055）")
class StockLedgerTest {

    private static final Long TENANT_ID = 1L;
    private static final String PRODUCT_ID = "prod-ledger-1";

    @Mock private ProductMapper productMapper;
    @Mock private CategoryMapper categoryMapper;
    @Mock private ProductColorMapper productColorMapper;
    @Mock private ProductSkuMapper productSkuMapper;
    @Mock private ProductProcessingItemMapper productProcessingItemMapper;
    @Mock private ProcessingItemMapper processingItemMapper;
    @Mock private ProductAttributeMapper productAttributeMapper;
    @Mock private StockLedgerMapper stockLedgerMapper;

    @Mock private AfterSalesTicketMapper afterSalesTicketMapper;
    @Mock private OrderMapper orderMapper;
    @Mock private OrderItemMapper orderItemMapper;
    @Mock private TicketTimelineMapper ticketTimelineMapper;
    @Mock private FinanceService financeService;
    @Mock private OrderService orderService;
    @Mock private NotificationService notificationService;

    /** 内存「库」：skuId → SKU（updateById 直接改这里的值） */
    private final Map<Long, ProductSku> skuStore = new LinkedHashMap<>();
    /** 内存「库」：stock_ledger_entries（insert 追加，id 模拟 IDENTITY 自增 → 提供全序） */
    private final List<StockLedger> ledger = new ArrayList<>();

    private StockLedgerService stockLedgerService;
    private ProductService productService;
    private AfterSalesTicketService afterSalesTicketService;

    @BeforeEach
    void setUp() {
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, ProductSku.class);
        TableInfoHelper.initTableInfo(assistant, Product.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);
        TableInfoHelper.initTableInfo(assistant, AfterSalesTicket.class);

        stockLedgerService = new StockLedgerService(stockLedgerMapper, productSkuMapper);
        productService = new ProductService(productMapper, categoryMapper, productColorMapper,
                productSkuMapper, productProcessingItemMapper, processingItemMapper,
                productAttributeMapper, stockLedgerService);
        afterSalesTicketService = new AfterSalesTicketService(afterSalesTicketMapper, orderMapper,
                orderItemMapper, productMapper, ticketTimelineMapper, financeService, orderService,
                new ObjectMapper(), notificationService, stockLedgerService);

        // ── 内存账本接线：读返回快照副本（隔离实体原地改写），写改内存值 ──
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenAnswer(inv -> skuStore.values().stream().map(StockLedgerTest::copyOf).toList());
        when(productSkuMapper.updateById(any(ProductSku.class))).thenAnswer(inv -> {
            ProductSku edited = inv.getArgument(0);
            ProductSku stored = skuStore.get(edited.getId());
            if (stored != null) {
                stored.setStock(edited.getStock());
            }
            return 1;
        });
        when(stockLedgerMapper.insert(any(StockLedger.class))).thenAnswer(inv -> {
            StockLedger row = inv.getArgument(0);
            row.setId((long) (ledger.size() + 1));   // 模拟 IDENTITY：单调递增 = 台账全序
            ledger.add(row);
            return 1;
        });

        // ── 商品/详情路径的最小桩（getProductById 读回校验用）──
        when(productMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(product());
        when(productMapper.selectById(PRODUCT_ID)).thenReturn(product());
        when(productMapper.updateById(any(Product.class))).thenReturn(1);
        when(productColorMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(productProcessingItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
        when(productAttributeMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());
    }

    // ======================== 不变式断言（两条腿共用） ========================

    /**
     * 台账不变式：① 同 SKU 相邻两行首尾相接 ② 行内 after-before==delta ③ 空行即空断言（防空跑）。
     */
    private void assertLedgerInvariant(Long skuId) {
        List<StockLedger> rows = rowsOf(skuId);
        assertThat(rows)
                .as("SKU %s 的台账行数（写成 0 行 = 台账没落码，链条无从谈起）", skuId)
                .isNotEmpty();
        for (int i = 0; i < rows.size(); i++) {
            StockLedger row = rows.get(i);
            assertThat(row.getAfterQty() - row.getBeforeQty())
                    .as("第 %d 行 after-before 必须等于 delta（row=%s）", i + 1, row)
                    .isEqualTo(row.getDelta());
            if (i > 0) {
                StockLedger prev = rows.get(i - 1);
                assertThat(row.getBeforeQty())
                        .as("第 %d 行 before_qty 必须等于第 %d 行 after_qty（首尾相接才能对账）", i + 1, i)
                        .isEqualTo(prev.getAfterQty());
                assertThat(row.getId()).as("台账行序必须严格递增（created_at 会撞毫秒）")
                        .isGreaterThan(prev.getId());
            }
        }
    }

    private List<StockLedger> rowsOf(Long skuId) {
        return ledger.stream()
                .filter(r -> skuId.equals(r.getSkuId()))
                .sorted(Comparator.comparing(StockLedger::getId))
                .toList();
    }

    // ======================== 站点 1：手工调整（ProductService.adjustStockForAgent）========================

    @Test
    @DisplayName("手工调整 —— 同一 SKU 连续两次变更：上一条 after == 下一条 before")
    void manualAdjustTwoConsecutiveChangesChain() {
        // given: 单 SKU 库存 30
        skuStore.put(100L, sku(100L, 30));

        // when: 出库 10 → 入库 5（同一 SKU 两次变更）
        productService.adjustStockForAgent(PRODUCT_ID, -10, "报损", TENANT_ID);
        productService.adjustStockForAgent(PRODUCT_ID, 5, "盘点", TENANT_ID);

        // then: 两行、首尾相接、行内自洽
        assertLedgerInvariant(100L);
        assertThat(rowsOf(100L)).extracting(StockLedger::getBeforeQty, StockLedger::getDelta, StockLedger::getAfterQty)
                .containsExactly(
                        org.assertj.core.groups.Tuple.tuple(30, -10, 20),
                        org.assertj.core.groups.Tuple.tuple(20, 5, 25));
    }

    @Test
    @DisplayName("手工调整 —— 多 SKU 分摊：未拿到分配量的 SKU 不落 0 变更行")
    void manualAdjustSkipsZeroChangeSku() {
        // given: 两个 SKU [30, 20]，调整量 +1 → 只第一个 SKU +1（第二个 +0 不落行）
        skuStore.put(100L, sku(100L, 30));
        skuStore.put(200L, sku(200L, 20));

        // when
        productService.adjustStockForAgent(PRODUCT_ID, 1, "理货", TENANT_ID);

        // then
        assertThat(rowsOf(100L)).hasSize(1);
        assertThat(rowsOf(200L)).as("0 变更的 SKU 不进台账（噪声行会被误读成「动过库存」）").isEmpty();
        assertLedgerInvariant(100L);
    }

    @Test
    @DisplayName("手工调整 —— 写的是 SKU 级 before/after，不是商品级汇总")
    void manualAdjustRecordsSkuLevelQuantities() {
        // given: 两个 SKU [30, 20]，出库 25 → 从库存最大的 100L 扣 25（[5, 20]）
        skuStore.put(100L, sku(100L, 30));
        skuStore.put(200L, sku(200L, 20));

        // when
        ProductResponse response = productService.adjustStockForAgent(PRODUCT_ID, -25, "出库", TENANT_ID);

        // then: 台账记 SKU 级 30→5，而商品级汇总 50→25 不入账（#4038：SKU 级是权威）
        assertLedgerInvariant(100L);
        assertThat(rowsOf(100L).get(0).getBeforeQty()).isEqualTo(30);
        assertThat(rowsOf(100L).get(0).getAfterQty()).isEqualTo(5);
        assertThat(response.getStock()).isEqualTo(25);
    }

    @Test
    @DisplayName("手工调整 —— 库存不足抛错时不落任何台账行（不记未发生的变更）")
    void manualAdjustInsufficientStockWritesNothing() {
        skuStore.put(100L, sku(100L, 30));

        org.assertj.core.api.Assertions
                .assertThatThrownBy(() -> productService.adjustStockForAgent(PRODUCT_ID, -60, "报损", TENANT_ID))
                .hasMessageContaining("库存不足");

        assertThat(ledger).isEmpty();
    }

    // ======================== 站点 2：售后回补（AfterSalesTicketService.maybeRestockOnReturn）========================

    @Test
    @DisplayName("售后回补 —— 回补链在手工调整之后：工单行的 before == 手工行的 after（跨站点同一条链）")
    void afterSalesRestockChainsAfterManualAdjust() {
        // given: 手工调整把该 SKU 从 30 扣到 20
        skuStore.put(100L, sku(100L, 30));
        productService.adjustStockForAgent(PRODUCT_ID, -10, "出库", TENANT_ID);

        // 回补场景：return 工单完结、商品允许回补；OrderService.restoreStockForReturn 内部 +2
        when(afterSalesTicketMapper.selectById("ticket-1")).thenReturn(ticket());
        when(afterSalesTicketMapper.updateById(any(AfterSalesTicket.class))).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(orderItem()));
        when(productMapper.selectBatchIds(anyCollection())).thenReturn(List.of(
                Product.builder().id(PRODUCT_ID).allowReturnRestock(true).build()));
        doAnswer(inv -> {
            skuStore.get(100L).setStock(skuStore.get(100L).getStock() + 2);  // 回补 = SKU +2
            return null;
        }).when(orderService).restoreStockForReturn(anyString());

        // when
        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("resolved");
        afterSalesTicketService.updateTicketStatus("ticket-1", request);

        // then: 两条行同链 —— 手工(30→20) 之后是 回补(20→22)
        assertLedgerInvariant(100L);
        assertThat(rowsOf(100L)).hasSize(2);
        assertThat(rowsOf(100L).get(1).getReason()).isEqualTo(StockLedger.REASON_AFTERSALES);
        assertThat(rowsOf(100L).get(1).getRefNo()).isEqualTo("AS-LEDGER-1");
        assertThat(rowsOf(100L).get(1).getBeforeQty()).isEqualTo(20);
        assertThat(rowsOf(100L).get(1).getAfterQty()).isEqualTo(22);
    }

    @Test
    @DisplayName("售后回补 —— 回补未真正改动库存（无变化）时不落行")
    void afterSalesRestockWithoutChangeWritesNothing() {
        skuStore.put(100L, sku(100L, 30));
        when(afterSalesTicketMapper.selectById("ticket-1")).thenReturn(ticket());
        when(afterSalesTicketMapper.updateById(any(AfterSalesTicket.class))).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(orderItem()));
        when(productMapper.selectBatchIds(anyCollection())).thenReturn(List.of(
                Product.builder().id(PRODUCT_ID).allowReturnRestock(true).build()));
        // restoreStockForReturn 是空操作（模拟订单明细不带 SKU 规格的既有分支）
        doAnswer(inv -> null).when(orderService).restoreStockForReturn(anyString());

        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("resolved");
        afterSalesTicketService.updateTicketStatus("ticket-1", request);

        assertThat(ledger).as("库存没变就不该有台账行（否则「动过」是假的）").isEmpty();
    }

    @Test
    @DisplayName("售后回补 —— 商品开关关闭（默认）时不回补也不落账")
    void afterSalesRestockDisabledWritesNothing() {
        skuStore.put(100L, sku(100L, 30));
        when(afterSalesTicketMapper.selectById("ticket-1")).thenReturn(ticket());
        when(afterSalesTicketMapper.updateById(any(AfterSalesTicket.class))).thenReturn(1);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(orderItem()));
        when(productMapper.selectBatchIds(anyCollection())).thenReturn(List.of(
                Product.builder().id(PRODUCT_ID).allowReturnRestock(false).build()));

        AfterSalesStatusUpdateRequest request = new AfterSalesStatusUpdateRequest();
        request.setStatus("resolved");
        afterSalesTicketService.updateTicketStatus("ticket-1", request);

        assertThat(ledger).isEmpty();
        assertThat(skuStore.get(100L).getStock()).isEqualTo(30);
    }

    // ======================== 夹具 ========================

    private Product product() {
        Product p = new Product();
        p.setId(PRODUCT_ID);
        p.setTenantId(TENANT_ID);
        p.setName("遮光窗帘");
        p.setStock(0);
        return p;
    }

    private static ProductSku sku(Long id, int stock) {
        ProductSku s = new ProductSku();
        s.setId(id);
        s.setTenantId(TENANT_ID);
        s.setProductId(PRODUCT_ID);
        s.setColorName("米白");
        s.setSellingMethod("bulk_cut");
        s.setDoorWidth("2.8米");
        s.setSkuCode("SKU-" + id);
        s.setStock(stock);
        return s;
    }

    private static ProductSku copyOf(ProductSku s) {
        return sku(s.getId(), s.getStock() != null ? s.getStock() : 0);
    }

    private AfterSalesTicket ticket() {
        return AfterSalesTicket.builder()
                .id("ticket-1")
                .tenantId(TENANT_ID)
                .ticketNo("AS-LEDGER-1")
                .orderId("order-1")
                .ticketType("return")
                .status("processing")
                .build();
    }

    private OrderItem orderItem() {
        return OrderItem.builder()
                .id("item-1")
                .orderId("order-1")
                .productId(PRODUCT_ID)
                .quantity(BigDecimal.valueOf(2))
                .build();
    }
}