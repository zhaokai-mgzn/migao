package com.migao.admin.service;

// case_ids=[PR-029, PR-030, PR-031, PR-032, PR-033, PR-045, PR-046, PR-048, PR-058, PR-061, FN-006]
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
import com.migao.admin.time.BusinessClock;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
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
import static org.mockito.Mockito.inOrder;
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
    /**
     * 业务时钟（与生产**同一份**口径，issue #3802）：测试里的「今天 / 现在」只能从这里取。
     *
     * <p>⛔ 不许写裸 {@code LocalDate.now()} —— 那读的是 <b>JVM 默认时区</b>，而生产的业务日固定
     * {@code Asia/Shanghai}（{@link BusinessClock}）；CI runner 的 JVM 默认时区是 <b>UTC</b>
     * ⇒ 两侧在 <b>UTC 16:00–24:00（北京 00:00–08:00）差一天</b>，本类的日期断言会每天红 8 小时
     * （实测：2026-09-26T22:14Z / 23:59Z 两轮 required 检查红，期望 2026-09-26 实际 2026-09-27）。
     * 注入同一个 {@code BusinessClock} ⇒ 夹具与生产**同源同区**，与 runner 时区无关。</p>
     */
    @Spy
    private BusinessClock businessClock = new BusinessClock();


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
        markPostedRows = 1;
        org.mockito.Mockito.doAnswer(inv -> {
            InboundOrder o = inv.getArgument(0);
            // 单号唯一性由 mock 承担（与真库 uk_inbound_orders_no 同语义）：号已被占 ⇒ 唯一索引冲突。
            // 没有这层，「单号重试」用例会因为「重复号也照样插进去」而恒绿（空断言）。
            if (o.getInboundNo() != null && !takenInboundNos.add(o.getInboundNo())) {
                throw new org.springframework.dao.DuplicateKeyException(
                        "uk_inbound_orders_no: " + o.getInboundNo());
            }
            if (o.getId() == null) {
                o.setId("inbound-uuid-" + (++insertSeq));
            }
            lastInsertedOrder = o;
            return 1;
        }).when(inboundOrderMapper).insert(any(InboundOrder.class));
        // 「单号是否被占用」= 查库（candidate 就在 LambdaQueryWrapper 的入参值里）。
        // ⚠️ MyBatis-Plus 是**惰性**物化入参：不先取一次 SQL 段，paramNameValuePairs 还是空的
        //    ⇒ 探测恒返回 false、重试用例变成空断言（本用例第一版就是这么假绿的）。
        org.mockito.Mockito.doAnswer(inv -> {
            LambdaQueryWrapper<InboundOrder> wrapper = inv.getArgument(0);
            if (wrapper.getParamNameValuePairs().isEmpty()) {
                wrapper.getSqlSegment();
            }
            return wrapper.getParamNameValuePairs().values().stream()
                    .filter(String.class::isInstance)
                    .map(String.class::cast)
                    .anyMatch(takenInboundNos::contains);
        }).when(inboundOrderMapper).exists(any(LambdaQueryWrapper.class));
        // 过账原子闸：默认「抢到过账权」（影响行数 1）；抢不到的场景在各用例里覆盖成 0
        org.mockito.Mockito.doAnswer(inv -> markPostedRows)
                .when(inboundOrderMapper).markPosted(anyString(), anyLong(), any(), any());
        // 批次号**原子取号**（issue #6248）：`update(` 的受影响行数 = 号归不归我。
        // mock 承担 `uk_stock_batches_no` 的同语义：同一个 (tenant, batch_no) 第二次 ⇒ 0 行
        // （没有这层，「撞号后重试」用例会因为「重复号也照样成功」而恒绿 = 空断言）。
        batchNosTaken.clear();
        org.mockito.Mockito.doAnswer(inv -> {
            StockBatch b = inv.getArgument(0);
            if (b.getBatchNo() != null && !batchNosTaken.add(b.getBatchNo())) {
                return 0;
            }
            lastInsertedBatch = b;
            return 1;
        }).when(stockBatchMapper).update(any(StockBatch.class));
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

    /** 批次号尾部四位序号（`PC-yyyyMMdd-NNNN` → NNNN）。 */
    private static int ordinalOf(String batchNo) {
        return Integer.parseInt(batchNo.substring(batchNo.length() - 4));
    }

    /** 进程内批次号计数器（`BATCH_SEQ`）的**现取值**：期望值由它算，不写死（防执行顺序漂移）。 */
    private static int batchSeq() {
        try {
            java.lang.reflect.Field seq = InboundOrderService.class.getDeclaredField("BATCH_SEQ");
            seq.setAccessible(true);
            return ((java.util.concurrent.atomic.AtomicInteger) seq.get(null)).get();
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("BATCH_SEQ 读取失败（字段被改名 ⇒ 判据必须一起改）", e);
        }
    }

    /** 已被占用的批次号（mock 承担 `uk_stock_batches_no` 的同语义，见 setUp）。 */
    private final java.util.Set<String> batchNosTaken = new java.util.HashSet<>();

    /** 最近一次真正落库的批次行（`update(` 返回 1 的那次）。 */
    private StockBatch lastInsertedBatch;

    /** 过账原子闸的影响行数（1 = 抢到；0 = 已被并发的另一个请求过账） */
    private int markPostedRows = 1;

    /** 库内**已被占用**的入库单号（模拟真库的 uk_inbound_orders_no；进程重启后重新建单会撞上它） */
    private final java.util.Set<String> takenInboundNos = new java.util.HashSet<>();

    /** 模拟「服务重启 / 另一个副本」：把进程内单号计数器归零（改前正是靠它从 0001 重走 ⇒ 撞已用的号） */
    private static void resetInboundSeq() {
        try {
            java.lang.reflect.Field f = InboundOrderService.class.getDeclaredField("INBOUND_SEQ");
            f.setAccessible(true);
            ((java.util.concurrent.atomic.AtomicInteger) f.get(null)).set(0);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("无法重置单号计数器（字段改名了？）—— 该用例的判别力依赖它", e);
        }
    }

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
            assertThat(saved.getInboundDate()).isEqualTo(businessClock.today());
            assertThat(saved.getCreatedBy()).isEqualTo("13800000000");
            // PR-058（V117）：来源缺省 = purchase（存量口径不变）、未带运行标识则不去重
            assertThat(saved.getSource()).isEqualTo(InboundOrder.SOURCE_PURCHASE);
            assertThat(saved.getImportRunId()).isNull();

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
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
            verify(stockLedgerService, never()).record(anyLong(), anyString(), anyLong(), anyString(),
                    any(), any(), anyString(), any(), any(), any(), any(), any());
            verify(stockBatchMapper, never()).update(any(StockBatch.class));
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
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
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

    // ============================================================ PR-061 期初建账（V118 / issue #5153）

    @Nested
    @DisplayName("PR-061 期初建账：<1 米尾料可登记 + 旧系统批次号")
    class OpeningRegister {

        /** 期初建账单：来源 + 运行标识（幂等键）都由调用方给（V117 的既有件，本单不新造） */
        private InboundOrderCreateRequest openingRequest(InboundOrderCreateRequest.Item... items) {
            InboundOrderCreateRequest req = request(items);
            req.setSource(InboundOrder.SOURCE_OPENING);
            req.setImportRunId("opening-register-20260924-01");
            return req;
        }

        private void stubCreate() {
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(sku(11L, "prod-1", 0, null)));
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class)))
                    .thenAnswer(inv -> lastInsertedOrder);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenAnswer(inv -> lastInsertedLines);
        }

        @Test
        @DisplayName("GAP-12：数量 0.5 米 ⇒ 建单**通过**（改前被「≥1 米」拒绝，文案可复现）")
        void acceptsHalfMeterTail() {
            stubCreate();

            // 红证（改前形态）：`validateRequest` 判 `quantity.compareTo(BigDecimal.ONE) < 0`
            // ⇒ 0.5 当场抛「商品明细第 1 项的数量必须 ≥1 米（按米入库）」——
            //    用户痛点「剩余了大量的 0.5 米左右的批次布料」正是被这条挡在门外。
            service.create(openingRequest(itemQty("prod-1", 11L, "0.5", "12.50")), TENANT, "op");

            ArgumentCaptor<InboundOrderItem> itemCap = ArgumentCaptor.forClass(InboundOrderItem.class);
            verify(inboundOrderItemMapper).insert(itemCap.capture());
            // 落库就是 0.5 —— 既没被下限挡下，也没被任何归一改写成 1（系统性虚增的反面）
            assertThat(itemCap.getValue().getQuantity()).isEqualByComparingTo("0.5");
            assertThat(itemCap.getValue().getAmount()).isEqualByComparingTo("6.25");
        }

        @Test
        @DisplayName("放宽下限**不**连带放宽精度：2.755 仍显式拒绝，不静默取整成 2.8")
        void relaxingLowerBoundKeepsThePrecisionGate() {
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(sku(11L, "prod-1", 0, null)));

            assertThatThrownBy(() -> service.create(
                    openingRequest(itemQty("prod-1", 11L, "2.755", null)), TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("1 位小数")
                    .hasMessageContaining("2.755");
            verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
        }

        @Test
        @DisplayName("旧系统批次号只在期初建账可填：opening 落库、purchase（含缺省来源）拒绝")
        void legacyBatchNoIsScopedToOpening() {
            stubCreate();
            InboundOrderCreateRequest.Item line = itemQty("prod-1", 11L, "0.5", null);
            line.setLegacyBatchNo("OLD-2024-0001");

            service.create(openingRequest(line), TENANT, "op");

            ArgumentCaptor<InboundOrderItem> itemCap = ArgumentCaptor.forClass(InboundOrderItem.class);
            verify(inboundOrderItemMapper).insert(itemCap.capture());
            assertThat(itemCap.getValue().getLegacyBatchNo()).isEqualTo("OLD-2024-0001");
            // 系统批次号此时还不存在（过账才生成）⇒ 旧号**没有**被塞进 batch_no（不得互相冒充）
            assertThat(itemCap.getValue().getBatchNo()).isNull();

            // 采购收货（缺省来源）填旧号 ⇒ 拒绝：采购批次号由服务端生成，没有「旧系统批次号」这个事实
            InboundOrderCreateRequest.Item purchaseLine = itemQty("prod-1", 11L, "0.5", null);
            purchaseLine.setLegacyBatchNo("OLD-2024-0001");
            assertThatThrownBy(() -> service.create(request(purchaseLine), TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("旧系统批次号只在期初建账");
        }

        @Test
        @DisplayName("过账：旧系统批次号由明细行**透传**到批次行（batch_no 与 legacy_batch_no 两列两义）")
        void postCarriesLegacyBatchNoToTheBatchRow() {
            InboundOrder order = new InboundOrder();
            order.setId("inbound-uuid-1");
            order.setTenantId(TENANT);
            order.setInboundNo("RK-20260924-0301");
            order.setStatus(InboundOrder.STATUS_DRAFT);
            order.setSource(InboundOrder.SOURCE_OPENING);
            order.setInboundDate(businessClock.today());
            InboundOrderItem line = new InboundOrderItem();
            line.setId(100L);
            line.setTenantId(TENANT);
            line.setInboundOrderId("inbound-uuid-1");
            line.setSkuId(11L);
            line.setProductId("prod-1");
            line.setQuantity(new BigDecimal("0.5"));
            line.setLegacyBatchNo("OLD-2024-0001");
            line.setDyeLot("缸A-8891");
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(order);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(line)).thenReturn(List.of(line));
            when(productSkuMapper.selectById(11L)).thenReturn(sku(11L, "prod-1", 0, null));

            service.post("RK-20260924-0301", TENANT, "op");

            ArgumentCaptor<StockBatch> batchCap = ArgumentCaptor.forClass(StockBatch.class);
            verify(stockBatchMapper).update(batchCap.capture());
            StockBatch batch = batchCap.getValue();
            assertThat(batch.getQuantity()).isEqualByComparingTo("0.5");
            assertThat(batch.getLegacyBatchNo()).isEqualTo("OLD-2024-0001");
            assertThat(batch.getDyeLot()).isEqualTo("缸A-8891");
            // 「不得互相冒充」：系统批次号是 PC-*，与旧号各占一列、值不同
            assertThat(batch.getBatchNo()).matches("PC-\\d{8}-\\d{4}");
            assertThat(batch.getBatchNo()).isNotEqualTo(batch.getLegacyBatchNo());
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
            o.setInboundDate(businessClock.today());
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
            // 过账是原子条件更新，并**同时返回变更前/变更后**（SQL 的 RETURNING，issue #6300）
            when(productSkuMapper.receiveStock(eq(11L), eq(new BigDecimal("30")), any(), anyString(), any()))
                    .thenReturn(java.util.Map.of("beforeQuantity", new BigDecimal("5"),
                            "afterQuantity", new BigDecimal("35")));

            service.post("RK-20260923-0001", TENANT, "13800000000");

            // ① 加库存（数量 + **算好的**移动加权均价 + 批次号一次写入）
            //    均价传的是 afterAvg（首次入库 = 进价 12.50），不是 unitCost ——
            //    与台账里的 avg_cost_after 同源同值（公式只有 InboundOrderService.movingAverage 一处）
            ArgumentCaptor<String> batchCap = ArgumentCaptor.forClass(String.class);
            verify(productSkuMapper).receiveStock(eq(11L), eq(BigDecimal.valueOf(30)), eq(new BigDecimal("12.50")), batchCap.capture(), any());
            String batchNo = batchCap.getValue();
            assertThat(batchNo).matches("PC-\\d{8}-\\d{4}");

            // ② 批次号回写到明细行（草稿态是 NULL ⇒ 过账后必须有）
            ArgumentCaptor<InboundOrderItem> patchCap = ArgumentCaptor.forClass(InboundOrderItem.class);
            verify(inboundOrderItemMapper).updateById(patchCap.capture());
            assertThat(patchCap.getValue().getBatchNo()).isEqualTo(batchNo);

            // ③ 批次台账：缸号随批次可见（AHFA 卷标须带 Lot number）
            ArgumentCaptor<StockBatch> batchRowCap = ArgumentCaptor.forClass(StockBatch.class);
            verify(stockBatchMapper).update(batchRowCap.capture());
            StockBatch batchRow = batchRowCap.getValue();
            assertThat(batchRow.getBatchNo()).isEqualTo(batchNo);
            assertThat(batchRow.getDyeLot()).isEqualTo("G-2026-0912");
            assertThat(batchRow.getInboundNo()).isEqualTo("RK-20260923-0001");
            assertThat(batchRow.getQuantity()).isEqualTo(BigDecimal.valueOf(30));
            assertThat(batchRow.getReceivedDate()).isEqualTo(order.getInboundDate());

            // ④ 过账权由**条件更新（CAS）**拿到，且操作人在同一句里留痕（不再有「最后再写一次状态」）
            ArgumentCaptor<java.time.OffsetDateTime> postedAtCap =
                    ArgumentCaptor.forClass(java.time.OffsetDateTime.class);
            verify(inboundOrderMapper).markPosted(
                    eq("inbound-uuid-1"), eq(TENANT), eq("13800000000"), postedAtCap.capture());
            assertThat(postedAtCap.getValue()).isNotNull();
            // 内存对象与 CAS 写入同源（回读详情用的就是它）
            assertThat(order.getStatus()).isEqualTo(InboundOrder.STATUS_POSTED);
            assertThat(order.getPostedBy()).isEqualTo("13800000000");
            verify(inboundOrderMapper, never()).updateById(any(InboundOrder.class));

            // ⑤ **闸在库存写入之前**（顺序判据）：CAS → 加库存，顺序颠倒 = 互斥发生在伤害之后
            org.mockito.InOrder inOrder = inOrder(inboundOrderMapper, productSkuMapper);
            inOrder.verify(inboundOrderMapper).markPosted(anyString(), anyLong(), any(), any());
            inOrder.verify(productSkuMapper).receiveStock(anyLong(), any(), any(), anyString(), any());
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
            when(productSkuMapper.receiveStock(eq(11L), eq(new BigDecimal("60.5")), any(), anyString(), any()))
                    .thenReturn(java.util.Map.of("beforeQuantity", new BigDecimal("5"),
                            "afterQuantity", new BigDecimal("65.5")));

            service.post("RK-20260923-0001", TENANT, "13800000000");

            // ① 加库存：改前是 int 形参 ⇒ 60.5 只能被截断或根本无法表达
            verify(productSkuMapper).receiveStock(eq(11L), eq(new BigDecimal("60.5")),
                    eq(new BigDecimal("12.50")), anyString(), any());

            // ② 批次台账：与入库行同值（账实一致）
            ArgumentCaptor<StockBatch> batchCap = ArgumentCaptor.forClass(StockBatch.class);
            verify(stockBatchMapper).update(batchCap.capture());
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
            // 过账是原子条件更新，并**同时返回变更前/变更后**（SQL 的 RETURNING，issue #6300）
            when(productSkuMapper.receiveStock(eq(11L), eq(BigDecimal.valueOf(30)), any(), anyString(), any()))
                    .thenReturn(java.util.Map.of("beforeQuantity", new BigDecimal("5"),
                            "afterQuantity", new BigDecimal("35")));

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
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
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
            // 无效请求不占行锁：明细校验在抢闸之前 ⇒ 一次 CAS 都不该发
            verify(inboundOrderMapper, never()).markPosted(anyString(), anyLong(), any(), any());
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
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
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
            verify(stockBatchMapper, times(2)).update(batchCap.capture());
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
            verify(productSkuMapper, times(2)).receiveStock(anyLong(), any(), any(), receiveCap.capture(), any());
            assertThat(receiveCap.getAllValues()).doesNotHaveDuplicates();
        }

        /**
         * 原子取号：候选号刚被别人抢走（{@code update(} 返回 0）⇒ **换号重试**，
         * 且落库的批次行就是最终那个号（issue #6248）。
         *
         * <p>缺陷形态（修复前）：{@code exists} 判假 ⇒ 返回候选 ⇒ <b>之后</b>才 insert ——
         * 多实例 / 重启时两边的进程内计数器从同一位置起步 ⇒ 同一个候选 ⇒ 后到者撞
         * {@code uk_stock_batches_no} 抛 {@code DuplicateKeyException} ⇒ 用户侧 500
         * （重试只覆盖「生成时已存在」，不覆盖「插入时被抢」）。真库读数见
         * {@code BatchNoTakeRaceRealDbTest} 判据 ④；本条是**廉价的正向判据**：
         * 抢号失败 ⇒ 必须换号并成功，而不是把冲突留给调用方。</p>
         */
        @Test
        @DisplayName("PR-045/#6248 候选号刚被抢走（受影响行数 0）⇒ 换号重试并把**最终号**落库")
        void postRetriesWhenCandidateIsSnatchedBetweenCheckAndInsert() {
            InboundOrder order = draftOrder();
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(order);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(line(100L, 11L))).thenReturn(List.of(line(100L, 11L)));
            when(productSkuMapper.selectById(11L)).thenReturn(sku(11L, "prod-1", 5, null));
            // 第一次写号被抢（0 行）⇒ 第二次成功（1 行）。**每次尝试的在途批次号按当时取值记下来**
            //（候选是同一个 batch 对象只换 batchNo 字段 ⇒ 捕获对象只能在末尾读到最终值，
            //  那样这条判据会假绿 —— 本判据第一版踩过）。
            List<String> attempted = new java.util.ArrayList<>();
            java.util.concurrent.atomic.AtomicBoolean firstAttemptSnatched =
                    new java.util.concurrent.atomic.AtomicBoolean(false);
            org.mockito.Mockito.doAnswer(inv -> {
                StockBatch b = inv.getArgument(0);
                attempted.add(b.getBatchNo());
                if (firstAttemptSnatched.compareAndSet(false, true)) {
                    return 0;                       // 号刚被别人抢走（DB 唯一索引挡住）
                }
                batchNosTaken.add(b.getBatchNo());
                lastInsertedBatch = b;
                return 1;                           // 换号后拿到号
            }).when(stockBatchMapper).update(any(StockBatch.class));
            // 基线紧贴被测调用读（计数器是进程内静态的；不写死绝对值 ⇒ 与执行顺序无关）
            String today = businessClock.today().format(java.time.format.DateTimeFormatter.ofPattern("yyyyMMdd"));
            int seqBefore = batchSeq();

            service.post("RK-20260923-0001", TENANT, "op");

            assertThat(attempted).as("写号必须被**尝试两次**（第一次被抢 ⇒ 换号再试）").hasSize(2);
            assertThat(attempted.get(0)).as("第一次尝试的候选号").matches("PC-\\d{8}-\\d{4}");
            assertThat(attempted.get(0)).as("第一次候选必须是今天号段里的号（不是别的天）")
                    .startsWith("PC-" + today + "-");
            assertThat(attempted.get(1))
                    .as("失败必须换号（同一个号再试一次 = 不重试）—— 实测两次尝试="
                            + attempted.get(0) + " / " + attempted.get(1))
                    .isNotEqualTo(attempted.get(0));
            assertThat(ordinalOf(attempted.get(1)) - ordinalOf(attempted.get(0)))
                    .as("换号必须取**下一个**候选（计数器每次 +1）—— 实测 "
                            + attempted.get(0) + " → " + attempted.get(1))
                    .isEqualTo(1);
            assertThat(seqBefore).as("基线是被测调用前读的计数器值").isNotNegative();
            // 落库的就是最终那次尝试的号，且它被用于库存 / 明细行回写（三处同源同值）
            assertThat(lastInsertedBatch.getBatchNo()).isEqualTo(attempted.get(1));
            ArgumentCaptor<String> receiveCap = ArgumentCaptor.forClass(String.class);
            verify(productSkuMapper).receiveStock(anyLong(), any(), any(), receiveCap.capture(), any());
            assertThat(receiveCap.getValue()).isEqualTo(attempted.get(1));
            ArgumentCaptor<InboundOrderItem> patchCap = ArgumentCaptor.forClass(InboundOrderItem.class);
            verify(inboundOrderItemMapper).updateById(patchCap.capture());
            assertThat(patchCap.getValue().getBatchNo()).isEqualTo(attempted.get(1));
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
            verify(stockBatchMapper, times(2)).update(batchCap.capture());
            assertThat(batchCap.getAllValues()).extracting(StockBatch::getBatchNo).doesNotHaveDuplicates();
            // 缸号随之各归各行 —— 合并批次会让两行只剩一个缸号（追溯断链）
            assertThat(batchCap.getAllValues()).extracting(StockBatch::getDyeLot)
                    .containsExactly("G-2026-0912", "G-2026-0913");
        }
    }

    // ============================================================ PR-058 幂等与并发闸（issue #5148）

    /**
     * 幂等与并发（V117 / issue #5148）—— 三条承重判据：
     *
     * <ol>
     *   <li><b>并发过账闸</b>：抢不到过账权（条件更新影响行数 0）⇒ 拒绝，且**不加库存、不落台账、不落批次**；</li>
     *   <li><b>单号重试</b>：进程重启（计数器归零）后当天首个建单**必须成功**（改前撞
     *       {@code RK-<今天>-0001} 直接失败）；mock 承担真库的唯一索引语义，重号当场抛
     *       {@link org.springframework.dao.DuplicateKeyException}；</li>
     *   <li><b>建单幂等</b>：同一 {@code importRunId} 重跑 ⇒ 只落一张单、返回同一张
     *       （否则两张草稿都过账 = 库存加两次）。</li>
     * </ol>
     */
    @Nested
    @DisplayName("PR-058 幂等与并发闸（V117 / issue #5148）")
    class IdempotencyAndGate {

        private InboundOrder draftOrder() {
            InboundOrder o = new InboundOrder();
            o.setId("inbound-uuid-1");
            o.setTenantId(TENANT);
            o.setInboundNo("RK-20260923-0001");
            o.setStatus(InboundOrder.STATUS_DRAFT);
            o.setInboundDate(businessClock.today());
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
            return l;
        }

        private void givenSkuAndDetail() {
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(sku(11L, "prod-1", 5, null)));
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class)))
                    .thenAnswer(inv -> lastInsertedOrder);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenAnswer(inv -> lastInsertedLines);
        }

        @Test
        @DisplayName("并发过账闸：抢不到过账权（影响行数 0）⇒ 拒绝，且**不**加库存、**不**落台账、**不**落批次")
        void postLosesTheGateWithoutDoublePosting() {
            InboundOrder order = draftOrder();
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class))).thenReturn(order);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(line(100L, 11L)));
            InboundOrder posted = draftOrder();
            posted.setStatus(InboundOrder.STATUS_POSTED);
            when(inboundOrderMapper.selectById("inbound-uuid-1")).thenReturn(posted);
            markPostedRows = 0;   // 并发的另一个请求刚刚抢到过账权（它已经加过库存了）

            assertThatThrownBy(() -> service.post("RK-20260923-0001", TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("只有草稿可以过账");

            // 红线：抢不到闸就**一点库存副作用都不许有**（改前两个并发请求各加一遍 ⇒ 库存加两次）
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
            verify(stockLedgerService, never()).record(anyLong(), anyString(), anyLong(), anyString(),
                    any(), any(), anyString(), any(), any(), any(), any(), any());
            verify(stockBatchMapper, never()).update(any(StockBatch.class));
        }

        @Test
        @DisplayName("单号重试：进程重启（计数器归零）后当天首个建单**成功**（改前撞 RK-…-0001 直接失败）")
        void createRetriesWhenTodaysNumberIsAlreadyTaken() {
            givenSkuAndDetail();

            resetInboundSeq();   // 计数器归零 ⇒ 本次取到当天 0001（可预期，便于断言「换号」）
            service.create(request(item("prod-1", 11L, 30, "12.50")), TENANT, "op");
            String first = lastInsertedOrder.getInboundNo();
            assertThat(first).matches("RK-\\d{8}-\\d{4}").endsWith("-0001");

            // 模拟服务重启 / 换副本：计数器从 0 重走 ⇒ 下一个候选号**又是** 0001（已被占）
            resetInboundSeq();
            org.mockito.Mockito.clearInvocations(inboundOrderMapper);
            service.create(request(item("prod-1", 11L, 30, "12.50")), TENANT, "op");
            String second = lastInsertedOrder.getInboundNo();

            assertThat(second).matches("RK-\\d{8}-\\d{4}").endsWith("-0002");
            assertThat(second).isNotEqualTo(first);
            // 判别力：第二次确实**探测了两次**（0001 被占 ⇒ 重新生成）
            verify(inboundOrderMapper, times(2)).exists(any(LambdaQueryWrapper.class));
        }

        @Test
        @DisplayName("红证：mock 承担了真库的唯一索引语义 —— 手工插入重号当场 DuplicateKeyException")
        void duplicateNumberIsRejectedLikeTheRealUniqueIndex() {
            givenSkuAndDetail();
            resetInboundSeq();
            service.create(request(item("prod-1", 11L, 30, "12.50")), TENANT, "op");
            String used = lastInsertedOrder.getInboundNo();

            // 不做去重重试、直接用同一个号插一次 —— 应当当场冲突（这正是改前的失败形态）
            InboundOrder dup = new InboundOrder();
            dup.setTenantId(TENANT);
            dup.setInboundNo(used);
            assertThatThrownBy(() -> inboundOrderMapper.insert(dup))
                    .isInstanceOf(org.springframework.dao.DuplicateKeyException.class)
                    .hasMessageContaining(used);
        }

        @Test
        @DisplayName("建单幂等（GAP-02）：同一 import_run_id 重跑 ⇒ **只落一张单**、返回同一张")
        void createIsIdempotentForTheSameImportRun() {
            givenSkuAndDetail();
            InboundOrderCreateRequest first = request(item("prod-1", 11L, 30, "12.50"));
            first.setSource(InboundOrder.SOURCE_OPENING);
            first.setImportRunId("opening-20260924-01");

            InboundOrderResponse created = service.create(first, TENANT, "op");
            assertThat(created.getSource()).isEqualTo(InboundOrder.SOURCE_OPENING);
            assertThat(created.getImportRunId()).isEqualTo("opening-20260924-01");

            // 重跑同一份导入（同运行标识）⇒ 走幂等分支：不建第二张、返回同一张
            InboundOrderCreateRequest again = request(item("prod-1", 11L, 30, "12.50"));
            again.setSource(InboundOrder.SOURCE_OPENING);
            again.setImportRunId("opening-20260924-01");
            InboundOrderResponse replayed = service.create(again, TENANT, "op");

            verify(inboundOrderMapper, times(1)).insert(any(InboundOrder.class));   // 只落了一张单
            assertThat(replayed.getId()).isEqualTo(created.getId());
            assertThat(replayed.getInboundNo()).isEqualTo(created.getInboundNo());
            assertThat(takenInboundNos).hasSize(1);                                 // 也没有偷偷占第二个号
        }

        @Test
        @DisplayName("并发同键：唯一索引挡下第二个（DuplicateKeyException）⇒ 明确 409，不静默建第二张")
        void concurrentSameImportRunFailsClosed() {
            givenSkuAndDetail();
            when(inboundOrderMapper.insert(any(InboundOrder.class)))
                    .thenThrow(new org.springframework.dao.DuplicateKeyException(
                            "uk_inbound_orders_tenant_import_run"));
            InboundOrderCreateRequest req = request(item("prod-1", 11L, 30, "12.50"));
            req.setImportRunId("migration-run-7");

            assertThatThrownBy(() -> service.create(req, TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("刚刚已被创建");
        }

        /** 一个 SKU 已就绪的最小请求（本类里只用于「建一张单」的场景） */
        private InboundOrderCreateRequest.Item itemNeedSku() {
            return item("prod-1", 11L, 30, "12.50");
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
        @DisplayName("数量为 0 / 负数 ⇒ 拒绝（下限是「大于 0 米」；0.5 米的尾料**可以**登记，见 PR-061）")
        void rejectsBadQuantity() {
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenReturn(List.of(sku(11L, "prod-1", 0, null)));

            assertThatThrownBy(() -> service.create(request(item("prod-1", 11L, 0, null)), TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("必须大于 0 米");
            assertThatThrownBy(() -> service.create(request(item("prod-1", 11L, -3, null)), TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("必须大于 0 米");
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
        @DisplayName("PR-058 来源只支持 purchase / opening：写别的值 ⇒ 拒绝（不把 DB 的 23514 透传成 500）")
        void rejectsUnknownSource() {
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(sku(11L, "prod-1", 0, null)));
            InboundOrderCreateRequest req = request(item("prod-1", 11L, 5, null));
            req.setSource("gift");

            assertThatThrownBy(() -> service.create(req, TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("单据来源只支持");
            verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
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

    // ════════════════ issue #6228：金额入口小数位准入（超 2 位有效小数 ⇒ 422 + 零写入）════════════════

    @Nested
    @DisplayName("#6228 入库金额精度准入：单价 2 位小数 + 「积」逐处准入")
    class MoneyScaleAdmission {

        @Test
        @DisplayName("单价 0.005（3 位有效小数）⇒ 422，inbound_orders / inbound_order_items **零写入**")
        void rejectsUnitCostOverScale() {
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(sku(11L, "prod-1", 0, null)));

            assertThatThrownBy(() -> service.create(
                    request(itemQty("prod-1", 11L, "2.5", "0.005")), TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("2 位小数")
                    .hasMessageContaining("0.005");

            verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
            verify(inboundOrderItemMapper, never()).insert(any(InboundOrderItem.class));
        }

        @Test
        @DisplayName("「积」超精度（数量 1.5 × 单价 0.01 = 0.015）⇒ 422，明细/单据零写入（单价本身合法）")
        void rejectsAmountProductOverScale() {
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(sku(11L, "prod-1", 0, null)));

            assertThatThrownBy(() -> service.create(
                    request(itemQty("prod-1", 11L, "1.5", "0.01")), TENANT, "op"))
                    .isInstanceOf(BusinessException.class)
                    .hasMessageContaining("入库金额")
                    .hasMessageContaining("0.015");

            verify(inboundOrderItemMapper, never()).insert(any(InboundOrderItem.class));
            verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
        }

        @Test
        @DisplayName("正对照 数量 2.5 × 单价 12.50 ⇒ 建单成功，单价/金额落库逐字 12.50 / 31.250（有效 2 位）")
        void acceptsTwoDecimalProduct() {
            when(productMapper.selectById("prod-1")).thenReturn(new Product());
            when(productSkuMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenReturn(List.of(sku(11L, "prod-1", 0, null)));
            // 建单末尾会回读详情（真实部署里单据已落库）——同本类 PR-029 用例的既有口径
            when(inboundOrderMapper.selectOne(any(LambdaQueryWrapper.class)))
                    .thenAnswer(inv -> lastInsertedOrder);
            when(inboundOrderItemMapper.selectList(any(LambdaQueryWrapper.class)))
                    .thenAnswer(inv -> lastInsertedLines);

            service.create(request(itemQty("prod-1", 11L, "2.5", "12.50")), TENANT, "op");

            ArgumentCaptor<InboundOrderItem> itemCap = ArgumentCaptor.forClass(InboundOrderItem.class);
            verify(inboundOrderItemMapper).insert(itemCap.capture());
            assertThat(itemCap.getValue().getUnitCost().toPlainString()).isEqualTo("12.50");
            assertThat(itemCap.getValue().getAmount().toPlainString()).isEqualTo("31.250");
        }
    }
}
