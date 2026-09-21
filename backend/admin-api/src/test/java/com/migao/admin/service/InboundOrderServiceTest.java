package com.migao.admin.service;

// case_ids=[PR-029, PR-030, PR-031, PR-032, PR-033]

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import com.migao.admin.dto.InboundOrderCreateRequest;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.InboundOrderItem;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.entity.StockLedger;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.InboundOrderItemMapper;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.InboundOrderQueryMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 入库单服务契约（V111，issue #5034）—— 商品布料入库的标准能力。
 *
 * <p>守三条会被下一个验收者重开的判据：</p>
 * <ol>
 *   <li><b>草稿不动库存</b>：建单只写单据与明细，**不得**调 {@code receiveStock}、不得落台账。
 *       若建单即加库存，录错一行就得反向出库去冲 —— 而库存是资金级数据，冲销必须留痕。</li>
 *   <li><b>过账一次性</b>：{@code draft → posted} 是幂等闸，已过账再调必须被拒
 *       （放行 = 重复入库 = 虚增库存，是超卖的反面但同样是账实不符）。</li>
 *   <li><b>批次号自动生成且落在行上</b>：{@code PC-yyyyMMdd-NNNN}，草稿态为 NULL
 *       （批次号 = 「真的收货了」的标识），过账后明细行与批次台账都要有。</li>
 * </ol>
 *
 * <p>成本口径（移动加权平均）另有 {@link MovingAverageTest} 做纯函数断言。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("入库单服务（V111 / issue #5034）")
class InboundOrderServiceTest {

    @Mock private InboundOrderMapper inboundOrderMapper;
    @Mock private InboundOrderItemMapper inboundOrderItemMapper;
    @Mock private InboundOrderQueryMapper inboundOrderQueryMapper;
    @Mock private StockBatchMapper stockBatchMapper;
    @Mock private ProductSkuMapper productSkuMapper;
    @Mock private ProductMapper productMapper;
    @Mock private StockLedgerService stockLedgerService;

    @InjectMocks private InboundOrderService service;

    private static final Long TENANT = 1L;

    @BeforeEach
    void setUp() {
        // LambdaQueryWrapper 需要实体元数据缓存，否则抛
        // MybatisPlusException: can not find lambda cache for this entity
        // （同 AgentProductServiceTest 的既有口径）
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant asst = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(asst, Product.class);
        TableInfoHelper.initTableInfo(asst, ProductSku.class);
        TableInfoHelper.initTableInfo(asst, InboundOrder.class);
        TableInfoHelper.initTableInfo(asst, InboundOrderItem.class);
        TableInfoHelper.initTableInfo(asst, StockBatch.class);

        // 建单时 MyBatis-Plus 会回填 UUID 主键；测试里给一个确定值，便于断言「单据与明细对得上」
        lastInsertedOrder = null;
        lastInsertedLines = new java.util.ArrayList<>();
        org.mockito.Mockito.doAnswer(inv -> {
            InboundOrder o = inv.getArgument(0);
            if (o.getId() == null) {
                o.setId("inbound-uuid-1");
            }
            lastInsertedOrder = o;
            return 1;
        }).when(inboundOrderMapper).insert(any(InboundOrder.class));
        org.mockito.Mockito.doAnswer(inv -> {
            InboundOrderItem it = inv.getArgument(0);
            if (it.getId() == null) {
                it.setId(100L + (long) insertSeq++);
            }
            lastInsertedLines.add(it);
            return 1;
        }).when(inboundOrderItemMapper).insert(any(InboundOrderItem.class));
    }

    private int insertSeq = 0;

    /** 最近一次 insert 的单据/明细（供 detail() 回读 stub 使用；单测无真实库） */
    private InboundOrder lastInsertedOrder;
    private List<InboundOrderItem> lastInsertedLines = List.of();

    // ============================================================ 工具

    private static ProductSku sku(long id, String productId, int stock, BigDecimal avgCost) {
        ProductSku s = new ProductSku();
        s.setId(id);
        s.setProductId(productId);
        s.setTenantId(TENANT);
        s.setStock(stock);
        s.setAvgCost(avgCost);
        s.setSkuCode("HUOHAO-01");
        s.setColorName("米白");
        s.setDoorWidth("2.8");
        return s;
    }

    private static InboundOrderCreateRequest.Item item(String productId, long skuId, int qty, String unitCost) {
        InboundOrderCreateRequest.Item it = new InboundOrderCreateRequest.Item();
        it.setProductId(productId);
        it.setSkuId(skuId);
        it.setQuantity(qty);
        it.setUnitCost(unitCost == null ? null : new BigDecimal(unitCost));
        return it;
    }

    private static InboundOrderCreateRequest request(InboundOrderCreateRequest.Item... items) {
        InboundOrderCreateRequest req = new InboundOrderCreateRequest();
        req.setSupplier("柯桥××布行");
        req.setItems(List.of(items));
        return req;
    }

    // ============================================================ PR-029 建单

    @Nested
    @DisplayName("PR-029 建单：草稿态，不动库存")
    class Create {

        @Test
        @DisplayName("建单写单据+明细（含快照），状态 draft，且**不**加库存、**不**落台账、**不**生成批次号")
        void createWritesDraftOnly() {
            ProductSku s = sku(11L, "prod-1", 5, null);
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(s));

            // 建单路径末尾会回读详情（真实部署里单据已落库）；单测没有库，让回读返回刚写入的单据，
            // 断言则落在**写入动作**上（insert / updateById）—— 那才是 create 的真实副作用。
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class)))
                    .thenAnswer(inv -> lastInsertedOrder);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenAnswer(inv -> lastInsertedLines);
            service.create(request(item("prod-1", 11L, 30, "12.50")), TENANT, "13800000000");

            ArgumentCaptor<InboundOrder> orderCap = ArgumentCaptor.forClass(InboundOrder.class);
            verify(inboundOrderMapper).insert(orderCap.capture());
            InboundOrder saved = orderCap.getValue();
            assertThat(saved.getStatus()).isEqualTo(InboundOrder.STATUS_DRAFT);
            assertThat(saved.getInboundNo()).startsWith("RK-")
                    .matches("RK-\\d{8}-\\d{4}");
            assertThat(saved.getInboundDate()).isEqualTo(LocalDate.now());
            assertThat(saved.getCreatedBy()).isEqualTo("13800000000");

            ArgumentCaptor<InboundOrderItem> itemCap = ArgumentCaptor.forClass(InboundOrderItem.class);
            verify(inboundOrderItemMapper).insert(itemCap.capture());
            InboundOrderItem line = itemCap.getValue();
            assertThat(line.getQuantity()).isEqualTo(30);
            assertThat(line.getAmount()).isEqualByComparingTo("375.00");
            // 批次号只在过账时生成 —— 草稿态必须是 NULL
            assertThat(line.getBatchNo()).isNull();
            // 快照：货号/颜色/门幅取建单时点的值
            assertThat(line.getSkuCode()).isEqualTo("HUOHAO-01");
            assertThat(line.getColorName()).isEqualTo("米白");
            assertThat(line.getDoorWidth()).isEqualTo("2.8");

            // 红线：草稿不动库存、不落台账
            verify(productSkuMapper, never()).receiveStock(anyLong(), anyInt(), any(), anyString());
            verify(stockLedgerService, never()).record(anyLong(), anyString(), anyLong(), anyString(),
                    anyInt(), anyInt(), anyString(), any(), any(), any(), any(), any());
            verify(stockBatchMapper, never()).insert(any(StockBatch.class));
        }

        @Test
        @DisplayName("明细为空 ⇒ 拒绝建单（不落一张没有行的空单）")
        void createRejectsEmptyItems() {
            InboundOrderCreateRequest req = new InboundOrderCreateRequest();
            req.setItems(List.of());
            assertThatThrownBy(() -> service.create(req, TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("至少要有 1 行明细");
            verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
        }
    }

    // ============================================================ PR-030 过账

    @Nested
    @DisplayName("PR-030 过账：自动生成批次号 + 自动加库存 + 落台账 + 落批次")
    class Post {

        private InboundOrder draftOrder() {
            InboundOrder o = new InboundOrder();
            o.setId("inbound-uuid-1");
            o.setTenantId(TENANT);
            o.setInboundNo("RK-20260923-0001");
            o.setStatus(InboundOrder.STATUS_DRAFT);
            o.setInboundDate(LocalDate.now());
            o.setSupplier("柯桥××布行");
            return o;
        }

        private InboundOrderItem line(long id, long skuId) {
            InboundOrderItem l = new InboundOrderItem();
            l.setId(id);
            l.setTenantId(TENANT);
            l.setInboundOrderId("inbound-uuid-1");
            l.setSkuId(skuId);
            l.setProductId("prod-1");
            l.setQuantity(30);
            l.setUnitCost(new BigDecimal("12.50"));
            l.setDyeLot("G-2026-0912");
            return l;
        }

        @Test
        @DisplayName("过账：加库存 + 批次号回写明细 + 批次台账带缸号 + 状态转 posted")
        void postAddsStockAndBatch() {
            InboundOrder order = draftOrder();
            InboundOrderItem l = line(100L, 11L);
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(order);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(l))
                    .thenReturn(List.of(l));
            when(productSkuMapper.selectById(11L)).thenReturn(sku(11L, "prod-1", 5, null));

            service.post("RK-20260923-0001", TENANT, "13800000000");

            // ① 加库存（数量 + **算好的**移动加权均价 + 批次号一次写入）
            //    均价传的是 afterAvg（首次入库 = 进价 12.50），不是 unitCost ——
            //    与台账里的 avg_cost_after 同源同值（公式只有 InboundOrderService.movingAverage 一处）
            ArgumentCaptor<String> batchCap = ArgumentCaptor.forClass(String.class);
            verify(productSkuMapper).receiveStock(eq(11L), eq(30), eq(new BigDecimal("12.50")), batchCap.capture());
            String batchNo = batchCap.getValue();
            assertThat(batchNo).matches("PC-\\d{8}-\\d{4}");

            // ② 批次号回写到明细行（草稿态是 NULL ⇒ 过账后必须有）
            ArgumentCaptor<InboundOrderItem> patchCap = ArgumentCaptor.forClass(InboundOrderItem.class);
            verify(inboundOrderItemMapper).updateById(patchCap.capture());
            assertThat(patchCap.getValue().getBatchNo()).isEqualTo(batchNo);

            // ③ 批次台账：缸号随批次可见（AHFA 卷标须带 Lot number）
            ArgumentCaptor<StockBatch> batchRowCap = ArgumentCaptor.forClass(StockBatch.class);
            verify(stockBatchMapper).insert(batchRowCap.capture());
            StockBatch batchRow = batchRowCap.getValue();
            assertThat(batchRow.getBatchNo()).isEqualTo(batchNo);
            assertThat(batchRow.getDyeLot()).isEqualTo("G-2026-0912");
            assertThat(batchRow.getInboundNo()).isEqualTo("RK-20260923-0001");
            assertThat(batchRow.getQuantity()).isEqualTo(30);
            assertThat(batchRow.getReceivedDate()).isEqualTo(order.getInboundDate());

            // ④ 状态转 posted 且留痕操作人
            ArgumentCaptor<InboundOrder> updateCap = ArgumentCaptor.forClass(InboundOrder.class);
            verify(inboundOrderMapper, times(1)).updateById(updateCap.capture());
            assertThat(updateCap.getValue().getStatus()).isEqualTo(InboundOrder.STATUS_POSTED);
            assertThat(updateCap.getValue().getPostedBy()).isEqualTo("13800000000");
            assertThat(updateCap.getValue().getPostedAt()).isNotNull();
        }

        @Test
        @DisplayName("过账落库存台账：reason=inbound、ref_no=入库单号、before/after 与成本快照齐备")
        void postWritesLedgerWithCost() {
            InboundOrder order = draftOrder();
            InboundOrderItem l = line(100L, 11L);
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(order);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(l))
                    .thenReturn(List.of(l));
            // 变更前：库存 5、均价 10.00 ⇒ 移动加权 = (5*10 + 30*12.5)/35 = 425/35 = 12.142857… ⇒ 12.1429
            when(productSkuMapper.selectById(11L)).thenReturn(sku(11L, "prod-1", 5, new BigDecimal("10.00")));

            service.post("RK-20260923-0001", TENANT, "op");

            verify(stockLedgerService).record(
                    eq(TENANT), eq("prod-1"), eq(11L), eq("HUOHAO-01"),
                    eq(5), eq(35), eq(StockLedger.REASON_INBOUND), eq("RK-20260923-0001"),
                    anyString(), eq(new BigDecimal("12.50")),
                    eq(new BigDecimal("10.00")), eq(new BigDecimal("12.1429")));
        }

        @Test
        @DisplayName("幂等闸：已过账的单再过账 ⇒ 拒绝，且**不**二次加库存")
        void postIsRejectedWhenAlreadyPosted() {
            InboundOrder posted = draftOrder();
            posted.setStatus(InboundOrder.STATUS_POSTED);
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(posted);

            assertThatThrownBy(() -> service.post("RK-20260923-0001", TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("只有草稿可以过账");
            verify(productSkuMapper, never()).receiveStock(anyLong(), anyInt(), any(), anyString());
            verify(stockLedgerService, never()).record(anyLong(), anyString(), anyLong(), anyString(),
                    anyInt(), anyInt(), anyString(), any(), any(), any(), any(), any());
        }

        @Test
        @DisplayName("过账时明细为空 ⇒ 拒绝（不落一张零变更的「已过账」单）")
        void postRejectsEmptyLines() {
            InboundOrder order = draftOrder();
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(order);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

            assertThatThrownBy(() -> service.post("RK-20260923-0001", TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("没有明细行");
            verify(inboundOrderMapper, never()).updateById(any(InboundOrder.class));
        }

        @Test
        @DisplayName("过账时 SKU 已被删除 ⇒ 拒绝（不把库存加到不存在的 SKU 上）")
        void postRejectsMissingSku() {
            InboundOrder order = draftOrder();
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(order);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(line(100L, 11L)));
            when(productSkuMapper.selectById(11L)).thenReturn(null);

            assertThatThrownBy(() -> service.post("RK-20260923-0001", TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("SKU 已不存在");
            verify(productSkuMapper, never()).receiveStock(anyLong(), anyInt(), any(), anyString());
        }
    }

    // ============================================================ PR-031 作废

    @Nested
    @DisplayName("PR-031 作废：仅草稿")
    class Cancel {

        @Test
        @DisplayName("草稿可作废，状态转 cancelled 且留痕原因")
        void cancelDraft() {
            InboundOrder order = new InboundOrder();
            order.setId("inbound-uuid-1");
            order.setTenantId(TENANT);
            order.setInboundNo("RK-20260923-0001");
            order.setStatus(InboundOrder.STATUS_DRAFT);
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(order);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of());

            service.cancel("RK-20260923-0001", "送货单录错", TENANT, "op");

            ArgumentCaptor<InboundOrder> cap = ArgumentCaptor.forClass(InboundOrder.class);
            verify(inboundOrderMapper).updateById(cap.capture());
            assertThat(cap.getValue().getStatus()).isEqualTo(InboundOrder.STATUS_CANCELLED);
            assertThat(cap.getValue().getCancelledReason()).isEqualTo("送货单录错");
            assertThat(cap.getValue().getCancelledAt()).isNotNull();
        }

        @Test
        @DisplayName("已过账的单不得作废（库存已进台账，冲销须另开单据）")
        void cancelRejectedAfterPost() {
            InboundOrder posted = new InboundOrder();
            posted.setId("inbound-uuid-1");
            posted.setTenantId(TENANT);
            posted.setInboundNo("RK-20260923-0001");
            posted.setStatus(InboundOrder.STATUS_POSTED);
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(posted);

            assertThatThrownBy(() -> service.cancel("RK-20260923-0001", "反悔", TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("只有草稿可以作废");
            verify(inboundOrderMapper, never()).updateById(any(InboundOrder.class));
        }
    }

    // ============================================================ PR-032 校验

    @Nested
    @DisplayName("PR-032 建单校验：数量/单价/SKU 归属")
    class Validation {

        @Test
        @DisplayName("数量为 0 / 负数 / 非整数 ⇒ 拒绝（按米入库暂不支持小数米，**不静默取整**）")
        void rejectsBadQuantity() {
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(sku(11L, "prod-1", 0, null)));

            assertThatThrownBy(() -> service.create(request(item("prod-1", 11L, 0, null)), TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("≥1 的整数");
            assertThatThrownBy(() -> service.create(request(item("prod-1", 11L, -3, null)), TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("≥1 的整数");
            verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
        }

        @Test
        @DisplayName("单价 ≤ 0 ⇒ 拒绝（不记单价请留空，不要填 0）")
        void rejectsNonPositiveUnitCost() {
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(sku(11L, "prod-1", 0, null)));

            assertThatThrownBy(() -> service.create(request(item("prod-1", 11L, 5, "0")), TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("入库单价必须大于 0");
        }

        @Test
        @DisplayName("SKU 不属于该商品 ⇒ 拒绝（否则库存会加到别的货号上）")
        void rejectsSkuProductMismatch() {
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(sku(99L, "prod-1", 0, null)));

            assertThatThrownBy(() -> service.create(request(item("prod-1", 11L, 5, null)), TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("SKU 不属于该商品");
            verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
        }
    }

    // ============================================================ PR-033 移动加权平均

    @Nested
    @DisplayName("PR-033 移动加权平均（纯函数口径）")
    class MovingAverageTest {

        @Test
        @DisplayName("有库存且有均价 ⇒ 加权平均：(5×10 + 30×12.5) / 35 = 12.1429")
        void weightedWhenStockAndAvgKnown() {
            assertThat(InboundOrderService.movingAverage(5, new BigDecimal("10.00"), 30, new BigDecimal("12.50")))
                    .isEqualByComparingTo("12.1429");
        }

        @Test
        @DisplayName("变更前无库存 ⇒ 均价 = 本次进价（首次入库）")
        void firstReceiptUsesUnitCost() {
            assertThat(InboundOrderService.movingAverage(0, null, 30, new BigDecimal("12.50")))
                    .isEqualByComparingTo("12.50");
            assertThat(InboundOrderService.movingAverage(0, new BigDecimal("9.99"), 30, new BigDecimal("12.50")))
                    .isEqualByComparingTo("12.50");
        }

        @Test
        @DisplayName("存量均价未知（NULL）⇒ 均价 = 本次进价，**不**用 0 冒充历史成本")
        void unknownHistoricalAvgUsesUnitCost() {
            assertThat(InboundOrderService.movingAverage(50, null, 30, new BigDecimal("12.50")))
                    .isEqualByComparingTo("12.50");
        }

        @Test
        @DisplayName("本行未记单价 ⇒ 均价**保持原值**（不因「这批没记价」把已有均价抹掉）")
        void nullUnitCostKeepsPreviousAvg() {
            assertThat(InboundOrderService.movingAverage(50, new BigDecimal("8.80"), 30, null))
                    .isEqualByComparingTo("8.80");
            // 从未有过成本 ⇒ 仍是未知（NULL），**不得**变成 0
            assertThat(InboundOrderService.movingAverage(0, null, 30, null)).isNull();
        }
    }
}
