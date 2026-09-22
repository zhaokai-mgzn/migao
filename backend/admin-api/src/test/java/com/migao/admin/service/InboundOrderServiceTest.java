package com.migao.admin.service;

// case_ids=[PR-029, PR-030, PR-031, PR-032, PR-033, PR-045, PR-046, PR-048]

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
        s.setStock(BigDecimal.valueOf(stock));
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
        it.setQuantity(BigDecimal.valueOf(qty));
        it.setUnitCost(unitCost == null ? null : new BigDecimal(unitCost));
        return it;
    }

    /** 小数米（1 位小数）的入库行 —— issue #5063：库存米数小数化后入库量支持 0.1 米粒度。 */
    private static InboundOrderCreateRequest.Item itemQty(String productId, long skuId, String qty, String unitCost) {
        InboundOrderCreateRequest.Item it = new InboundOrderCreateRequest.Item();
        it.setProductId(productId);
        it.setSkuId(skuId);
        it.setQuantity(new BigDecimal(qty));
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
            assertThat(line.getQuantity()).isEqualTo(BigDecimal.valueOf(30));
            assertThat(line.getAmount()).isEqualByComparingTo("375.00");
            // 批次号只在过账时生成 —— 草稿态必须是 NULL
            assertThat(line.getBatchNo()).isNull();
            // 快照：货号/颜色/门幅取建单时点的值
            assertThat(line.getSkuCode()).isEqualTo("HUOHAO-01");
            assertThat(line.getColorName()).isEqualTo("米白");
            assertThat(line.getDoorWidth()).isEqualTo("2.8");

            // 红线：草稿不动库存、不落台账
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString());
            verify(stockLedgerService, never()).record(anyLong(), anyString(), anyLong(), anyString(),
                    any(), any(), anyString(), any(), any(), any(), any(), any());
            verify(stockBatchMapper, never()).insert(any(StockBatch.class));
        }

        @Test
        @DisplayName("PR-046 数量 60.5 米 ⇒ 建单通过，落库就是 60.5（不是 60、不是 61）")
        void createAcceptsOneDecimalMeters() {
            ProductSku s = sku(11L, "prod-1", 5, null);
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(s));
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class)))
                    .thenAnswer(inv -> lastInsertedOrder);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenAnswer(inv -> lastInsertedLines);

            // 红证（改前形态）：validateRequest 把「非整数米」显式拒绝 ⇒ 这里会抛
            // 「数量必须是 ≥1 的整数（按米入库暂不支持小数米）」
            service.create(request(itemQty("prod-1", 11L, "60.5", "12.50")), TENANT, "13800000000");

            ArgumentCaptor<InboundOrderItem> itemCap = ArgumentCaptor.forClass(InboundOrderItem.class);
            verify(inboundOrderItemMapper).insert(itemCap.capture());
            assertThat(itemCap.getValue().getQuantity()).isEqualByComparingTo("60.5");
            // 金额按真实米数算（60.5 × 12.50 = 756.25），不得按取整后的 60 算
            assertThat(itemCap.getValue().getAmount()).isEqualByComparingTo("756.25");
            // 草稿不动库存（与整数场景同一红线）
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString());
        }

        @Test
        @DisplayName("PR-048 数量 2.755（3 位小数）⇒ 显式拒绝，**不静默取整成 2.8**")
        void rejectsThreeDecimalMeters() {
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(sku(11L, "prod-1", 0, null)));

            assertThatThrownBy(() -> service.create(request(itemQty("prod-1", 11L, "2.755", null)), TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("1 位小数")
                    .hasMessageContaining("2.755");
            verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
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
            l.setQuantity(BigDecimal.valueOf(30));
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
            verify(productSkuMapper).receiveStock(eq(11L), eq(BigDecimal.valueOf(30)), eq(new BigDecimal("12.50")), batchCap.capture());
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
            assertThat(batchRow.getQuantity()).isEqualTo(BigDecimal.valueOf(30));
            assertThat(batchRow.getReceivedDate()).isEqualTo(order.getInboundDate());

            // ④ 状态转 posted 且留痕操作人
            ArgumentCaptor<InboundOrder> updateCap = ArgumentCaptor.forClass(InboundOrder.class);
            verify(inboundOrderMapper, times(1)).updateById(updateCap.capture());
            assertThat(updateCap.getValue().getStatus()).isEqualTo(InboundOrder.STATUS_POSTED);
            assertThat(updateCap.getValue().getPostedBy()).isEqualTo("13800000000");
            assertThat(updateCap.getValue().getPostedAt()).isNotNull();
        }

        @Test
        @DisplayName("PR-046 过账 60.5 米：库存 5 → 65.5，批次与台账同为 60.5（改前走不到这里）")
        void postAddsFractionalMeters() {
            InboundOrder order = draftOrder();
            InboundOrderItem l = line(100L, 11L);
            l.setQuantity(new BigDecimal("60.5"));
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(order);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(l))
                    .thenReturn(List.of(l));
            when(productSkuMapper.selectById(11L)).thenReturn(sku(11L, "prod-1", 5, null));

            service.post("RK-20260923-0001", TENANT, "13800000000");

            // ① 加库存：改前是 int 形参 ⇒ 60.5 只能被截断或根本无法表达
            verify(productSkuMapper).receiveStock(eq(11L), eq(new BigDecimal("60.5")),
                    eq(new BigDecimal("12.50")), anyString());

            // ② 批次台账：与入库行同值（账实一致）
            ArgumentCaptor<StockBatch> batchCap = ArgumentCaptor.forClass(StockBatch.class);
            verify(stockBatchMapper).insert(batchCap.capture());
            assertThat(batchCap.getValue().getQuantity()).isEqualByComparingTo("60.5");

            // ③ 台账 before/after：5 → 65.5（delta 由 StockLedgerService 按 after-before 算）
            ArgumentCaptor<BigDecimal> beforeCap = ArgumentCaptor.forClass(BigDecimal.class);
            ArgumentCaptor<BigDecimal> afterCap = ArgumentCaptor.forClass(BigDecimal.class);
            verify(stockLedgerService).record(eq(TENANT), eq("prod-1"), eq(11L), eq("HUOHAO-01"),
                    beforeCap.capture(), afterCap.capture(), eq(StockLedger.REASON_INBOUND),
                    eq("RK-20260923-0001"), anyString(), any(), any(), any());
            assertThat(beforeCap.getValue()).isEqualByComparingTo("5");
            assertThat(afterCap.getValue()).isEqualByComparingTo("65.5");
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
                    eq(BigDecimal.valueOf(5)), eq(BigDecimal.valueOf(35)), eq(StockLedger.REASON_INBOUND), eq("RK-20260923-0001"),
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
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString());
            verify(stockLedgerService, never()).record(anyLong(), anyString(), anyLong(), anyString(),
                    any(), any(), anyString(), any(), any(), any(), any(), any());
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
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString());
        }

        // ---------------------------------------------------------- PR-045 多行过账

        /**
         * 多行过账：**批次号必须逐行生成**（V111 裁定「一个 SKU 行 = 一个批次」）。
         *
         * <p>整单共用一个批次号时，第 2 行插 {@code stock_batches} 会撞
         * {@code uk_stock_batches_no} = {@code UNIQUE (tenant_id, batch_no)} ⇒
         * **整个事务回滚**（≥2 行的入库单必然过账失败，issue #5141）。</p>
         *
         * <p>本测试无真实库（同本类其它用例），故判别力**全部**来自「两个批次号必须不同」
         * 这一条断言本身 —— DB 唯一索引的冲突由它间接保证，不靠 Mockito 施加约束。</p>
         */
        @Test
        @DisplayName("PR-045 多行过账：**每行各取一个批次号**（整单共用一个号 ⇒ 第 2 行撞唯一索引、整单回滚）")
        void postAssignsDistinctBatchNoPerLine() {
            InboundOrder order = draftOrder();
            // 两个 SKU 各一行 —— 真实场景 = 一张送货单上的两种布
            List<InboundOrderItem> lines = List.of(line(100L, 11L), line(101L, 12L));
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(order);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(lines)
                    .thenReturn(lines);
            when(productSkuMapper.selectById(11L)).thenReturn(sku(11L, "prod-1", 5, null));
            when(productSkuMapper.selectById(12L)).thenReturn(sku(12L, "prod-1", 0, null));

            service.post("RK-20260923-0001", TENANT, "op");

            // ① 批次台账落 **2 行**、两个批次号**不同**（相同 ⇒ 真库上第 2 行唯一索引冲突）
            ArgumentCaptor<StockBatch> batchCap = ArgumentCaptor.forClass(StockBatch.class);
            verify(stockBatchMapper, times(2)).insert(batchCap.capture());
            List<StockBatch> batches = batchCap.getAllValues();
            List<String> batchNos = batches.stream().map(StockBatch::getBatchNo).toList();
            assertThat(batchNos).hasSize(2).doesNotHaveDuplicates();
            assertThat(batchNos).allMatch(no -> no != null && no.matches("PC-\\d{8}-\\d{4}"));
            // 每行的批次行都挂在自己那行明细上（不是把整单的行都挂到第一行）
            assertThat(batches).extracting(StockBatch::getInboundItemId).containsExactly(100L, 101L);

            // ② 每行回写的批次号 = **自己那一个**（不是整单共用的首个号）
            ArgumentCaptor<InboundOrderItem> patchCap = ArgumentCaptor.forClass(InboundOrderItem.class);
            verify(inboundOrderItemMapper, times(2)).updateById(patchCap.capture());
            assertThat(patchCap.getAllValues()).extracting(InboundOrderItem::getBatchNo)
                    .containsExactly(batchNos.get(0), batchNos.get(1));

            // ③ 加库存也逐行带各自的批次号（latest_batch_no 不得被同一个号覆盖两次）
            ArgumentCaptor<String> receiveCap = ArgumentCaptor.forClass(String.class);
            verify(productSkuMapper, times(2)).receiveStock(anyLong(), any(), any(), receiveCap.capture());
            assertThat(receiveCap.getAllValues()).doesNotHaveDuplicates();
        }

        /**
         * 同一 SKU 的两行（同一天两种缸号的布）也各一个批次 —— 批次粒度是**行**，不是 SKU。
         *
         * <p>按 SKU 合并批次会丢掉缸号区分度（{@code stock_batches.dye_lot} 是<b>行级</b>快照），
         * 而 V111 的裁定逐字是「一个 SKU **行** = 一个批次」。</p>
         */
        @Test
        @DisplayName("PR-045 同一 SKU 两行（不同缸号）各一个批次：粒度 = 行，不是 SKU")
        void postAssignsDistinctBatchNoForSameSkuLines() {
            InboundOrder order = draftOrder();
            InboundOrderItem second = line(101L, 11L);
            second.setDyeLot("G-2026-0913");
            List<InboundOrderItem> lines = List.of(line(100L, 11L), second);
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(order);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(lines)
                    .thenReturn(lines);
            when(productSkuMapper.selectById(11L)).thenReturn(sku(11L, "prod-1", 5, null));

            service.post("RK-20260923-0001", TENANT, "op");

            ArgumentCaptor<StockBatch> batchCap = ArgumentCaptor.forClass(StockBatch.class);
            verify(stockBatchMapper, times(2)).insert(batchCap.capture());
            assertThat(batchCap.getAllValues()).extracting(StockBatch::getBatchNo).doesNotHaveDuplicates();
            // 缸号随之各归各行 —— 合并批次会让两行只剩一个缸号（追溯断链）
            assertThat(batchCap.getAllValues()).extracting(StockBatch::getDyeLot)
                    .containsExactly("G-2026-0912", "G-2026-0913");
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
                    .hasMessageContaining("必须 ≥1 米");
            assertThatThrownBy(() -> service.create(request(item("prod-1", 11L, -3, null)), TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("必须 ≥1 米");
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
            assertThat(InboundOrderService.movingAverage(BigDecimal.valueOf(5), new BigDecimal("10.00"), BigDecimal.valueOf(30), new BigDecimal("12.50")))
                    .isEqualByComparingTo("12.1429");
        }

        @Test
        @DisplayName("变更前无库存 ⇒ 均价 = 本次进价（首次入库）")
        void firstReceiptUsesUnitCost() {
            assertThat(InboundOrderService.movingAverage(BigDecimal.valueOf(0), null, BigDecimal.valueOf(30), new BigDecimal("12.50")))
                    .isEqualByComparingTo("12.50");
            assertThat(InboundOrderService.movingAverage(BigDecimal.valueOf(0), new BigDecimal("9.99"), BigDecimal.valueOf(30), new BigDecimal("12.50")))
                    .isEqualByComparingTo("12.50");
        }

        @Test
        @DisplayName("存量均价未知（NULL）⇒ 均价 = 本次进价，**不**用 0 冒充历史成本")
        void unknownHistoricalAvgUsesUnitCost() {
            assertThat(InboundOrderService.movingAverage(BigDecimal.valueOf(50), null, BigDecimal.valueOf(30), new BigDecimal("12.50")))
                    .isEqualByComparingTo("12.50");
        }

        @Test
        @DisplayName("本行未记单价 ⇒ 均价**保持原值**（不因「这批没记价」把已有均价抹掉）")
        void nullUnitCostKeepsPreviousAvg() {
            assertThat(InboundOrderService.movingAverage(BigDecimal.valueOf(50), new BigDecimal("8.80"), BigDecimal.valueOf(30), null))
                    .isEqualByComparingTo("8.80");
            // 从未有过成本 ⇒ 仍是未知（NULL），**不得**变成 0
            assertThat(InboundOrderService.movingAverage(BigDecimal.valueOf(0), null, BigDecimal.valueOf(30), null)).isNull();
        }
    }
}
