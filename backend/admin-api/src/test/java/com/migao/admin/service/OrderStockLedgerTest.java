// case_ids: OR-006, OR-007, OR-047, PR-049, PR-050
// 订单腿库存流水（issue #4137）—— 补齐 #4055 台账唯一缺口：下单扣减 / 取消回补此前**不进台账**
// （StockLedger.REASON_ORDER 只声明未落码），「某 SKU 的库存为什么从 X 变成 Y」在订单腿上答不出来。
//
// 语义与既有两处写入方（ProductService.adjustStockForAgent / AfterSalesTicketService.maybeRestockOnReturn）
// 同款：**变更前快照 → 变更 → 用实际值比对，只落真实变化的 SKU**（delta 一律由 StockLedgerService
// 按 after-before 算出，调用方不传 delta）。
//
// 红证（本文件）：注释掉 OrderService.deductSkuStock 的落账调用 ⇒ 断言 1/2 变红（台账缺 order 行）；
// 注释掉 restoreSkuStock 的落账调用 ⇒ 断言 2 变红；把 restoreStockForReturn 改回写 order 行
// ⇒ 断言 5 变红（同一次售后回补出现两行，delta 翻倍）。
//
// 装配：**真实** StockLedgerService + 真实 OrderService，mapper 用 mock 顶替，
// SKU 库存与台账落在一个内存账本里（写真的改值 / 真的追加行）——断言的是「扣减 → 台账行」
// 的真实因果，不是「某个方法被调过」。

package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.entity.Order;
import com.migao.admin.entity.OrderItem;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.mapper.FinanceTransactionMapper;
import com.migao.admin.mapper.OrderItemMapper;
import com.migao.admin.mapper.OrderLogisticsMapper;
import com.migao.admin.mapper.OrderMapper;
import com.migao.admin.mapper.ProcessingOrderMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockLedgerMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.assertj.core.groups.Tuple;
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
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.when;

/**
 * 订单腿库存流水（issue #4137）：确认支付扣减 / 取消回补必须落 reason=order 的台账行。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("订单腿库存流水（issue #4137）")
class OrderStockLedgerTest {

    private static final Long TENANT_ID = 1L;
    private static final Long SKU_ID = 100L;
    private static final String PRODUCT_ID = "prod-order-ledger";
    private static final String ORDER_ID = "order-ledger-1";
    private static final String ORDER_NO = "ORD-20260918-0001";

    @Mock private OrderMapper orderMapper;
    @Mock private OrderItemMapper orderItemMapper;
    @Mock private OrderLogisticsMapper orderLogisticsMapper;
    @Mock private CustomerService customerService;
    @Mock private ProductMapper productMapper;
    @Mock private ProductSkuMapper productSkuMapper;
    @Mock private FinanceTransactionMapper financeTransactionMapper;
    @Mock private NotificationService notificationService;
    @Mock private ProcessingOrderMapper processingOrderMapper;
    @Mock private UserService userService;
    @Mock private ClientRequestIdService clientRequestIdService;
    @Mock private StockLedgerMapper stockLedgerMapper;
    /** 加工费组合价目表（issue #4406 的取价依赖；本类不涉及加工费口径 ⇒ 空表） */
    @Mock private com.migao.admin.mapper.ProcessingFeeCombinationMapper processingFeeCombinationMapper;
    /** 特殊选项对客单价（issue #4525 的取价依赖；本类不涉及 ⇒ 空表 ⇒ 选项计 0） */
    @Mock
    private com.migao.admin.mapper.ProductionRouteRuleMapper routeRuleMapper;

    /** 内存「库」：skuId → SKU（deductStock/restoreStock 真的改这里的值） */
    private final Map<Long, ProductSku> skuStore = new LinkedHashMap<>();
    /** 内存「库」：stock_ledger_entries（insert 追加，id 模拟 IDENTITY 自增 → 提供全序） */
    private final List<StockLedger> ledger = new ArrayList<>();

    private OrderService orderService;
    private Order order;

    @BeforeEach
    void setUp() {
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Order.class);
        TableInfoHelper.initTableInfo(assistant, OrderItem.class);
        TableInfoHelper.initTableInfo(assistant, ProductSku.class);

        StockLedgerService stockLedgerService = new StockLedgerService(stockLedgerMapper, productSkuMapper);
        orderService = new OrderService(orderMapper, orderItemMapper, orderLogisticsMapper, customerService,
                productMapper, productSkuMapper, financeTransactionMapper, new ObjectMapper(),
                notificationService, processingOrderMapper, userService, clientRequestIdService,
                stockLedgerService,
                // issue #4406：加工费取价点（本类不涉及加工费口径 ⇒ 空价目表 ⇒ 未定价 0）
                new ProcessingFeeCalculator(processingFeeCombinationMapper, routeRuleMapper),
                // issue #4872：建单回写加工费组合（本类零 manual 行 ⇒ 该路径不可达；给 mock，不留 null 依赖）
                org.mockito.Mockito.mock(ProcessingFeeCombinationCommandService.class));

        order = Order.builder()
                .id(ORDER_ID)
                .tenantId(TENANT_ID)
                .orderNo(ORDER_NO)
                .status("pending")
                .totalAmount(new BigDecimal("599.00"))
                .build();

        when(orderMapper.selectById(ORDER_ID)).thenReturn(order);
        when(orderMapper.update(any(), any())).thenReturn(1);
        // thenAnswer（不是 thenReturn）：本类有小数用例会在 arrange 阶段改 itemQty，
        // 固定返回值会让 run 阶段读到改前的数量（判据假绿）
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenAnswer(inv -> List.of(orderItem()));

        // ── 内存账本接线（与 StockLedgerTest 同一口径）：读返回快照副本，写改内存值 ──
        when(productSkuMapper.selectById(anyLong()))
                .thenAnswer(inv -> copyOf(skuStore.get(inv.<Long>getArgument(0))));
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenAnswer(inv -> skuStore.values().stream().map(OrderStockLedgerTest::copyOf).toList());
        when(productSkuMapper.deductStock(anyLong(), any())).thenAnswer(inv -> {
            ProductSku stored = skuStore.get(inv.<Long>getArgument(0));
            if (stored == null) {
                return 0;
            }
            // 与 ProductSkuMapper.deductStock 的 SQL 同口径：GREATEST(COALESCE(stock,0)-qty, 0)
            stored.setStock(stockOf(stored).subtract(inv.<BigDecimal>getArgument(1)).max(BigDecimal.ZERO));
            return 1;
        });
        when(productSkuMapper.restoreStock(anyLong(), any())).thenAnswer(inv -> {
            ProductSku stored = skuStore.get(inv.<Long>getArgument(0));
            if (stored == null) {
                return 0;
            }
            stored.setStock(stockOf(stored).add(inv.<BigDecimal>getArgument(1)));
            return 1;
        });
        when(stockLedgerMapper.insert(any(StockLedger.class))).thenAnswer(inv -> {
            StockLedger row = inv.getArgument(0);
            row.setId((long) (ledger.size() + 1));
            ledger.add(row);
            return 1;
        });
    }

    // ======================== 站点 3：订单扣减（OrderService.deductSkuStock）========================

    @Test
    @DisplayName("确认支付扣减 —— 落 reason=order 一行：ref_no=订单号，before/after 为实际值")
    void confirmPaymentRecordsOrderLedgerRow() {
        // given: SKU 库存 30，明细数量 2
        skuStore.put(SKU_ID, sku(BigDecimal.valueOf(30)));

        // when: pending → confirmed（扣减库存）
        orderService.confirmPayment(ORDER_ID);

        // then: 台账一行 —— 库存为什么从 30 变成 28，答案在台账里
        assertThat(skuStore.get(SKU_ID).getStock()).isEqualTo(BigDecimal.valueOf(28));
        assertThat(ledger).hasSize(1);
        StockLedger row = ledger.get(0);
        assertThat(row.getReason()).isEqualTo(StockLedger.REASON_ORDER);
        assertThat(row.getRefNo()).as("order 行必须能回溯到订单号（ref_no=orderNo）").isEqualTo(ORDER_NO);
        assertThat(row.getTenantId()).isEqualTo(TENANT_ID);
        assertThat(row.getSkuId()).isEqualTo(SKU_ID);
        assertThat(row.getSkuCode()).isEqualTo("SKU-100");
        assertThat(Tuple.tuple(row.getBeforeQty(), row.getDelta(), row.getAfterQty()))
                .isEqualTo(Tuple.tuple(BigDecimal.valueOf(30), BigDecimal.valueOf(-2), BigDecimal.valueOf(28)));
    }

    @Test
    @DisplayName("取消订单回补 —— 落 reason=order 一行，且与扣减行首尾相接")
    void cancelOrderRecordsOrderLedgerRow() {
        // given: 先确认支付（30 → 28），再取消（28 → 30）
        skuStore.put(SKU_ID, sku(BigDecimal.valueOf(30)));
        orderService.confirmPayment(ORDER_ID);
        order.setStatus("confirmed");

        // when
        orderService.cancelOrder(ORDER_ID, "客户改主意");

        // then: 两行同链 —— 扣减(30→28) 之后是 回补(28→30)
        assertThat(skuStore.get(SKU_ID).getStock()).isEqualTo(BigDecimal.valueOf(30));
        assertThat(ledger).hasSize(2);
        assertThat(ledger.get(1).getReason()).isEqualTo(StockLedger.REASON_ORDER);
        assertThat(ledger.get(1).getRefNo()).isEqualTo(ORDER_NO);
        assertThat(ledger.get(1).getBeforeQty())
                .as("回补行的 before 必须等于扣减行的 after（首尾相接才能对账）")
                .isEqualTo(ledger.get(0).getAfterQty());
        assertThat(rowsOf(SKU_ID)).extracting(StockLedger::getBeforeQty, StockLedger::getDelta,
                        StockLedger::getAfterQty)
                .containsExactly(Tuple.tuple(BigDecimal.valueOf(30), BigDecimal.valueOf(-2), BigDecimal.valueOf(28)),
                        Tuple.tuple(BigDecimal.valueOf(28), BigDecimal.valueOf(2), BigDecimal.valueOf(30)));
    }

    @Test
    @DisplayName("扣减未真正改库（update 命中 0 行）—— 不落行：只记真实发生的变更")
    void deductWithoutActualChangeRecordsNothing() {
        // given: SKU 行不存在/更新命中 0 行（主键漂移后的陈旧 skuId）→ 库存实际没变
        skuStore.put(SKU_ID, sku(BigDecimal.valueOf(30)));
        when(productSkuMapper.deductStock(anyLong(), any())).thenReturn(0);

        // when
        orderService.confirmPayment(ORDER_ID);

        // then: 请求了扣减但库存没变 ⇒ 台账不能记这条「未发生的变更」
        assertThat(skuStore.get(SKU_ID).getStock()).isEqualTo(BigDecimal.valueOf(30));
        assertThat(ledger).isEmpty();
    }

    @Test
    @DisplayName("明细无 SKU 规格 —— 无 SKU 级库存变更，不落行")
    void itemWithoutSkuMatchRecordsNothing() {
        // given: 明细 processingInfo 不带任何 SKU 规格（既有设计：该明细不做 SKU 级库存调整）
        skuStore.put(SKU_ID, sku(BigDecimal.valueOf(30)));
        OrderItem bare = orderItem();
        bare.setProcessingInfo(null);
        when(orderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(bare));

        // when
        orderService.confirmPayment(ORDER_ID);

        // then
        assertThat(skuStore.get(SKU_ID).getStock()).isEqualTo(BigDecimal.valueOf(30));
        assertThat(ledger).as("没动过库存就不该有台账行（0 变更噪声会被误读成「动过」）").isEmpty();
    }

    // ======================== 与售后站点的边界：同一次变更只记一行 ========================

    @Test
    @DisplayName("售后回补路径（restoreStockForReturn）—— 不写 order 行：那一次变更归 aftersales 站点")
    void restoreStockForReturnLeavesLedgerToAftersalesSite() {
        // given: 售后完结触发的回补（调用方 AfterSalesTicketService 用「调用前快照 vs 调用后实际值」
        //        落 reason=aftersales 行）
        skuStore.put(SKU_ID, sku(BigDecimal.valueOf(30)));

        // when
        orderService.restoreStockForReturn(ORDER_ID);

        // then: 库存真的回补了，但本路径不落 order 行 ——
        //       若这里再写一行，同一次变更会出现两行（20→22 与 20→22），delta 翻倍且相邻行接不上
        assertThat(skuStore.get(SKU_ID).getStock()).isEqualTo(BigDecimal.valueOf(32));
        assertThat(ledger).as("order 行只能由订单自身的扣减/取消回补产生，售后回补由 aftersales 站点记").isEmpty();
    }

    // ──────────────── issue #5063：小数米（0.1 米粒度）───────────────

    @Test
    @DisplayName("PR-049 确认支付 2.7 米 —— 台账 delta = -2.7、after = before - 2.7（改前：扣 2、0.7 米凭空消失）")
    void confirmPaymentDeductsRealMeters() {
        // given: SKU 库存 30，明细数量 2.7
        skuStore.put(SKU_ID, sku(new BigDecimal("30")));
        itemQty = new BigDecimal("2.7");

        // when
        orderService.confirmPayment(ORDER_ID);

        // then: 库存扣的是 2.7（不是 2），台账三值自洽
        assertThat(skuStore.get(SKU_ID).getStock()).isEqualByComparingTo("27.3");
        assertThat(ledger).hasSize(1);
        StockLedger row = ledger.get(0);
        assertThat(row.getBeforeQty()).isEqualByComparingTo("30");
        assertThat(row.getAfterQty()).isEqualByComparingTo("27.3");
        assertThat(row.getDelta()).isEqualByComparingTo("-2.7");
        assertThat(row.getAfterQty().subtract(row.getBeforeQty())).isEqualByComparingTo(row.getDelta());
    }

    @Test
    @DisplayName("PR-049 取消回补同口径 —— 扣 2.7 就补 2.7，两行首尾相接（净变化恰为 0）")
    void cancelOrderRestoresRealMeters() {
        skuStore.put(SKU_ID, sku(new BigDecimal("30")));
        itemQty = new BigDecimal("2.7");
        orderService.confirmPayment(ORDER_ID);
        order.setStatus("confirmed");

        orderService.cancelOrder(ORDER_ID, "客户改主意");

        assertThat(skuStore.get(SKU_ID).getStock()).isEqualByComparingTo("30");
        assertThat(rowsOf(SKU_ID)).hasSize(2);
        assertThat(rowsOf(SKU_ID).get(1).getDelta()).isEqualByComparingTo("2.7");
        // 对账不变式（小数下用 compareTo —— `2.70` 与 `2.7` 的 equals 为 false）
        assertThat(rowsOf(SKU_ID).get(1).getBeforeQty())
                .isEqualByComparingTo(rowsOf(SKU_ID).get(0).getAfterQty());
    }

    @Test
    @DisplayName("PR-049 顾客数量 2.75（2 位小数）⇒ 按 §8 用料口径向上进位到 0.1（落 2.8，不截断成 2）")
    void confirmPaymentCeilsTwoDecimalQuantityToStockScale() {
        skuStore.put(SKU_ID, sku(new BigDecimal("30")));
        itemQty = new BigDecimal("2.75");

        orderService.confirmPayment(ORDER_ID);

        // docs/curtain-fabric-quote-rules.md §8「用料米数一律向上进位到 0.1」 —— 库存按同一粒度同向变化
        assertThat(skuStore.get(SKU_ID).getStock()).isEqualByComparingTo("27.2");
        assertThat(ledger.get(0).getDelta()).isEqualByComparingTo("-2.8");
    }

    @Test
    @DisplayName("PR-050 整数场景逐值不变 —— 买 2 米仍是 30 → 28、delta = -2（scale 也不变）")
    void integerOrderValuesAreUnchanged() {
        skuStore.put(SKU_ID, sku(BigDecimal.valueOf(30)));

        orderService.confirmPayment(ORDER_ID);

        assertThat(skuStore.get(SKU_ID).getStock()).isEqualTo(BigDecimal.valueOf(28));
        assertThat(ledger.get(0).getBeforeQty()).isEqualTo(BigDecimal.valueOf(30));
        assertThat(ledger.get(0).getAfterQty()).isEqualTo(BigDecimal.valueOf(28));
        assertThat(ledger.get(0).getDelta()).isEqualTo(BigDecimal.valueOf(-2));
    }

    // ======================== 夹具 ========================

    private List<StockLedger> rowsOf(Long skuId) {
        return ledger.stream()
                .filter(r -> skuId.equals(r.getSkuId()))
                .sorted(Comparator.comparing(StockLedger::getId))
                .toList();
    }

    private ProductSku sku(BigDecimal stock) {
        ProductSku s = new ProductSku();
        s.setId(SKU_ID);
        s.setTenantId(TENANT_ID);
        s.setProductId(PRODUCT_ID);
        s.setSkuCode("SKU-100");
        s.setStock(stock);
        return s;
    }

    private static ProductSku copyOf(ProductSku s) {
        if (s == null) {
            return null;
        }
        ProductSku copy = new ProductSku();
        copy.setId(s.getId());
        copy.setTenantId(s.getTenantId());
        copy.setProductId(s.getProductId());
        copy.setSkuCode(s.getSkuCode());
        copy.setStock(s.getStock());
        return copy;
    }

    private static BigDecimal stockOf(ProductSku sku) {
        return StockQuantity.orZero(sku != null ? sku.getStock() : null);
    }

    /** 订单行数量（默认 2 米 = 整数场景；小数用例在 arrange 阶段改写它）。 */
    private BigDecimal itemQty = BigDecimal.valueOf(2);

    private OrderItem orderItem() {
        return OrderItem.builder()
                .id("item-1")
                .tenantId(TENANT_ID)
                .orderId(ORDER_ID)
                .productId(PRODUCT_ID)
                .productName("遮光窗帘")
                .quantity(itemQty)
                .subtotal(new BigDecimal("599.00"))
                .processingInfo(Map.of("skuId", SKU_ID))
                .build();
    }
}