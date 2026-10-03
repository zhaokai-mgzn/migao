// case_ids: PR-007, PR-010, FN-006
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.dto.ProductSkuResponse;
import com.migao.admin.dto.agent.AgentBatchCreateRequest;
import com.migao.admin.dto.agent.AgentBatchViews;
import com.migao.admin.dto.agent.AgentProductUpdateRequest;
import com.migao.admin.entity.AgentBatch;
import com.migao.admin.entity.AgentBatchItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AgentBatchItemMapper;
import com.migao.admin.mapper.AgentBatchMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
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
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 批量更新的**服务端资源**主判据（issue #5314 服务端包；冻结契约见 issue #5314 评论
 * 「批量更新能力 —— 设计 + 冻结契约（2026-09-24）」）。
 *
 * <p>本类钉死契约里服务端那半边，逐条对应用户可见判据：</p>
 * <ol>
 *   <li><b>创建批次 = 预演</b>：落 {@code status='preview'} + 逐条落 {@code item_count}，
 *       且 {@code old_value} <b>在预览阶段就持久化</b>（撤销的唯一依据，不许只在内存里）；</li>
 *   <li><b>执行</b>：{@code preview → executing → done | partial}，逐条落
 *       {@code agent_batch_items.status / error}；<b>部分失败逐条报告，不做整体回滚</b>；</li>
 *   <li><b>撤销</b>：逐条还原为 {@code old_value}（**不是** newValue，也不是 audit_logs）；</li>
 *   <li><b>不可撤销</b>：状态非 {@code done}/{@code partial}、或已 {@code reverted}；</li>
 *   <li><b>跨租户不可见</b>：批次一律经租户过滤的 {@code selectById} 定位，查不到 ⇒ NOT_FOUND 且零写。</li>
 * </ol>
 *
 * <p><b>判据的判别力</b>不由本类自证：注入式红证 = {@code scripts/product-batch-red-proof.py}
 * （逐条变异被测源码 ⇒ 上面的「期望变红」方法必须单独变红；入口 {@code ./verify-all.sh redproof}）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("AgentBatchService —— 批量更新的批次资源（#5314 冻结契约）")
class AgentBatchServiceTest {

    private static final Long TENANT = 1001L;
    private static final String USER = "user-0001";
    private static final String BATCH_ID = "batch-0001";
    private static final String P1 = "prod-0001";
    private static final String P2 = "prod-0002";

    @Mock
    private AgentBatchMapper batchMapper;

    @Mock
    private AgentBatchItemMapper itemMapper;

    @Mock
    private ProductService productService;

    @InjectMocks
    private AgentBatchService batchService;

    @BeforeEach
    void setUp() {
        // MyBatis-Plus 的 lambda 列名缓存（CI 无 Spring 上下文，见 TenantIsolationTest 同款初始化）
        MybatisConfiguration configuration = new MybatisConfiguration();
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), AgentBatch.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), AgentBatchItem.class);
        TenantContext.setTenantId(TENANT);
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ── 夹具 ────────────────────────────────────────────────────────────────

    /** DB 里商品的**当前**值（本类是撤销依据的真值源）。 */
    private ProductResponse product(String basePrice, String status) {
        ProductResponse p = new ProductResponse();
        p.setId(P1);
        p.setBasePrice(new BigDecimal(basePrice));
        p.setStatus(status);
        return p;
    }

    private AgentBatchCreateRequest priceRequest(String... triples) {
        return request("product_price", "basePrice", triples);
    }

    /** 库存批量的请求（`inventory_stock` ⇒ field 必须是 `stock`）。 */
    private AgentBatchCreateRequest stockRequest(String... triples) {
        return request(AgentBatchService.TYPE_INVENTORY_STOCK, AgentBatchService.FIELD_STOCK, triples);
    }

    /** DB 里商品的**当前库存**：`stocks` = 各 SKU 规格的库存（`getProductById` 的 `skus[].stock`）。
     *  ⚠️ 库存批量的工作值是**每规格值**，不是汇总 —— 夹具必须给 SKU 行（多 SKU 是布艺常态）。 */
    private ProductResponse productWithSkuStocks(String... stocks) {
        ProductResponse p = product("168.00", "on_sale");
        BigDecimal total = BigDecimal.ZERO;
        List<ProductSkuResponse> skus = new ArrayList<>();
        for (int i = 0; i < stocks.length; i++) {
            BigDecimal v = new BigDecimal(stocks[i]);
            ProductSkuResponse sku = new ProductSkuResponse();
            sku.setId(2001L + i);
            sku.setProductId(P1);
            sku.setColorName("米白" + i);
            sku.setDoorWidth("2.8");
            sku.setStock(v);
            skus.add(sku);
            total = total.add(v);
        }
        p.setSkus(skus);
        p.setStock(stocks.length == 0 ? BigDecimal.ZERO : total);   // 汇总（`getProductById` 的既有口径）
        return p;
    }

    /** 库存批次的明细行（field = `stock`）。 */
    private AgentBatchItem stockItem(String resourceId, String oldValue, String newValue, String status) {
        return AgentBatchItem.builder()
                .id(1L)
                .batchId(BATCH_ID)
                .tenantId(TENANT)
                .resourceId(resourceId)
                .field(AgentBatchService.FIELD_STOCK)
                .oldValue(oldValue)
                .newValue(newValue)
                .status(status)
                .build();
    }

    private AgentBatchCreateRequest request(String batchType, String field, String... triples) {
        AgentBatchCreateRequest req = new AgentBatchCreateRequest();
        req.setBatchType(batchType);
        List<AgentBatchCreateRequest.Item> items = new ArrayList<>();
        for (int i = 0; i + 2 < triples.length; i += 3) {
            AgentBatchCreateRequest.Item it = new AgentBatchCreateRequest.Item();
            it.setResourceId(triples[i]);
            it.setOldValue(triples[i + 1]);
            it.setNewValue(triples[i + 2]);
            it.setField(field);
            items.add(it);
        }
        req.setItems(items);
        return req;
    }

    private AgentBatch batch(String status) {
        return AgentBatch.builder()
                .id(BATCH_ID)
                .tenantId(TENANT)
                .batchType(AgentBatchService.TYPE_PRODUCT_PRICE)
                .status(status)
                .itemCount(1)
                .successCount(AgentBatchService.STATUS_DONE.equals(status) ? 1 : 0)
                .failCount(AgentBatchService.STATUS_PARTIAL.equals(status) ? 1 : 0)
                .createdBy(USER)
                .createdAt(OffsetDateTime.now())
                .build();
    }

    private AgentBatchItem item(String resourceId, String oldValue, String newValue, String status) {
        return AgentBatchItem.builder()
                .id(1L)
                .batchId(BATCH_ID)
                .tenantId(TENANT)
                .resourceId(resourceId)
                .field(AgentBatchService.FIELD_BASE_PRICE)
                .oldValue(oldValue)
                .newValue(newValue)
                .status(status)
                .build();
    }

    /**
     * 记录每次 {@code updateById} **落库那一刻**的批次状态。
     *
     * <p>为什么不用 ArgumentCaptor：captor 存的是**引用**，而服务层会在同一个实体上连续改状态
     * ⇒ 事后读到的全是末态 —— 「executing 这一步真的落过库吗」这个问题就答不出来了。</p>
     */
    private List<String> recordBatchStatusWrites() {
        List<String> writes = new ArrayList<>();
        when(batchMapper.updateById(any(AgentBatch.class))).thenAnswer(inv -> {
            writes.add(((AgentBatch) inv.getArgument(0)).getStatus());
            return 1;
        });
        return writes;
    }

    private BusinessException rejection(org.assertj.core.api.ThrowableAssert.ThrowingCallable call) {
        return (BusinessException) org.assertj.core.api.Assertions.catchThrowable(call);
    }

    // ══════════════════ ① 创建 = 预演（含 old_value 持久化）══════════════════

    @Nested
    @DisplayName("POST / 创建批次（= 预演）")
    class Create {

        @Test
        @DisplayName("落 preview + 逐条落 old_value（撤销的唯一依据必须在预览阶段落库）")
        void persistsPreviewWithOldValueCollectedFromDb() {
            when(productService.getProductById(P1, TENANT)).thenReturn(product("10.00", "on_sale"));

            AgentBatchViews.Batch view = batchService.create(TENANT, USER, priceRequest(P1, "10.00", "12.00"));

            ArgumentCaptor<AgentBatch> saved = ArgumentCaptor.forClass(AgentBatch.class);
            verify(batchMapper).insert(saved.capture());
            assertThat(saved.getValue().getStatus()).isEqualTo(AgentBatchService.STATUS_PREVIEW);
            assertThat(saved.getValue().getBatchType()).isEqualTo(AgentBatchService.TYPE_PRODUCT_PRICE);
            assertThat(saved.getValue().getTenantId()).isEqualTo(TENANT);
            assertThat(saved.getValue().getCreatedBy()).isEqualTo(USER);
            assertThat(saved.getValue().getItemCount()).isEqualTo(1);
            assertThat(saved.getValue().getSuccessCount()).isZero();
            assertThat(saved.getValue().getFailCount()).isZero();
            assertThat(saved.getValue().getExecutedAt()).isNull();
            assertThat(saved.getValue().getRevertedAt()).isNull();

            ArgumentCaptor<AgentBatchItem> items = ArgumentCaptor.forClass(AgentBatchItem.class);
            verify(itemMapper).insert(items.capture());
            AgentBatchItem persisted = items.getValue();
            assertThat(persisted.getOldValue()).as("🔴 撤销的唯一依据").isEqualTo("10.00");
            assertThat(persisted.getNewValue()).isEqualTo("12.00");
            assertThat(persisted.getField()).isEqualTo(AgentBatchService.FIELD_BASE_PRICE);
            assertThat(persisted.getResourceId()).isEqualTo(P1);
            assertThat(persisted.getStatus()).isEqualTo(AgentBatchService.ITEM_PENDING);
            assertThat(persisted.getError()).isNull();
            assertThat(persisted.getTenantId()).isEqualTo(TENANT);
            assertThat(persisted.getBatchId()).as("明细必须挂到刚创建的批次上").isEqualTo(saved.getValue().getId());

            // 响应契约（冻结）：{batchId, itemCount, status:"preview"}
            assertThat(view.getStatus()).isEqualTo("preview");
            assertThat(view.getItemCount()).isEqualTo(1);
            assertThat(view.getBatchId()).isNotBlank();
            assertThat(view.getBatchId()).isEqualTo(saved.getValue().getId());
        }

        @Test
        @DisplayName("old_value 取自 DB 当前值：调用方给的写法不同也按**值**比对（10.0 == 10.00）")
        void oldValueComparedByNumericValueAndPersistedFromDb() {
            when(productService.getProductById(P1, TENANT)).thenReturn(product("10.00", "on_sale"));

            AgentBatchViews.Batch view = batchService.create(TENANT, USER, priceRequest(P1, "10.0", "12.00"));

            assertThat(view.getStatus()).isEqualTo("preview");
            ArgumentCaptor<AgentBatchItem> items = ArgumentCaptor.forClass(AgentBatchItem.class);
            verify(itemMapper).insert(items.capture());
            assertThat(items.getValue().getOldValue()).as("落库值 = DB 真值，不是调用方字符串")
                    .isEqualTo("10.00");
        }

        @Test
        @DisplayName("old_value 与 DB 当前值不符 ⇒ 拒绝且零写（防把错的撤销依据落库）")
        void rejectsOldValueMismatchWithDb() {
            when(productService.getProductById(P1, TENANT)).thenReturn(product("10.00", "on_sale"));

            BusinessException ex = rejection(() ->
                    batchService.create(TENANT, USER, priceRequest(P1, "9.99", "12.00")));

            assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
            assertThat(ex.getMessage()).contains(P1);
            verify(batchMapper, never()).insert(any(AgentBatch.class));
            verify(itemMapper, never()).insert(any(AgentBatchItem.class));
        }

        @Test
        @DisplayName("资源不在本租户 ⇒ 拒绝且零写（预演不得对不可见的行编造 before）")
        void rejectsResourceMissingInTenant() {
            when(productService.getProductById(P2, TENANT)).thenReturn(null);

            BusinessException ex = rejection(() ->
                    batchService.create(TENANT, USER, priceRequest(P2, "10.00", "12.00")));

            assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
            assertThat(ex.getMessage()).contains(P2);
            verify(itemMapper, never()).insert(any(AgentBatchItem.class));
        }

        @Test
        @DisplayName("N > 50 ⇒ 拒绝并提示分批（本单不做后台任务）")
        void rejectsOverThreshold() {
            String[] triples = new String[51 * 3];
            for (int i = 0; i < 51; i++) {
                triples[i * 3] = "prod-" + i;
                triples[i * 3 + 1] = "10.00";
                triples[i * 3 + 2] = "12.00";
            }

            BusinessException ex = rejection(() -> batchService.create(TENANT, USER, priceRequest(triples)));

            assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
            assertThat(ex.getMessage()).contains("50");
            verify(batchMapper, never()).insert(any(AgentBatch.class));
        }

        @Test
        @DisplayName("batchType 白名单外 ⇒ 拒绝（本单只做 product_price / product_status）")
        void rejectsUnknownBatchType() {
            BusinessException ex = rejection(() -> batchService.create(TENANT, USER,
                    request("product_stock", "stock", P1, "1", "2")));

            assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
            assertThat(ex.getMessage()).contains("batchType");
            verify(itemMapper, never()).insert(any(AgentBatchItem.class));
        }

        @Test
        @DisplayName("field 与 batchType 不配对 ⇒ 拒绝（不新开通用批量）")
        void rejectsFieldBatchTypeMismatch() {
            BusinessException ex = rejection(() -> batchService.create(TENANT, USER,
                    request("product_price", "status", P1, "on_sale", "off_sale")));

            assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
            verify(itemMapper, never()).insert(any(AgentBatchItem.class));
        }

        @Test
        @DisplayName("同一资源的同一字段重复出现 ⇒ 拒绝（撤销顺序会变得不确定）")
        void rejectsDuplicateResourceField() {
            when(productService.getProductById(P1, TENANT)).thenReturn(product("10.00", "on_sale"));

            BusinessException ex = rejection(() -> batchService.create(TENANT, USER,
                    priceRequest(P1, "10.00", "12.00", P1, "10.00", "13.00")));

            assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
            verify(itemMapper, never()).insert(any(AgentBatchItem.class));
        }
    }

    // ══════════════════ ①.5 第三个具名批量：inventory_stock（issue #5950）════════════════

    /**
     * 库存调整批次 —— **复用**同一套批次资源 / 状态机 / 撤销语义，只多一条 `batchType`。
     *
     * <h2>工作值的口径（issue #5950 复核订正，**不是**商品级汇总）</h2>
     * 库存的权威在 **SKU 级**（#4038），而 `getProductById` 把响应里的 `stock` 覆盖成 Σ 汇总。
     * 本批量的执行口径是「该商品的**每个规格**都置为 X」⇒ before/after 必须按**规格值**取，
     * 否则多 SKU 商品三方不自洽（预览 40→100 / 实际汇总 100×N / 撤销回 40×N ≠ 40）。
     * 故准入 = **≥1 个 SKU 且各规格一致**（不一致 ⇒ preview 整批拒绝，绝不给出失真预览）。
     */
    @Nested
    @DisplayName("inventory_stock（批量库存调整，issue #5950）")
    class InventoryStock {

        @Test
        @DisplayName("🔴 红判据①「预览即承诺」：多 SKU 商品的工作值 = **每规格值**，且执行后同口径回读 == newValue")
        void previewValueIsThePerSkuValueAndMatchesTheReadbackAfterExecute() {
            // 两个规格各 40（汇总 80）—— 修前（取汇总）这里会得到 "80"，与执行口径（每规格 80）不符
            when(productService.getProductById(P1, TENANT)).thenReturn(productWithSkuStocks("40", "40"));

            batchService.create(TENANT, USER, stockRequest(P1, "40", "80"));

            ArgumentCaptor<AgentBatchItem> inserted = ArgumentCaptor.forClass(AgentBatchItem.class);
            verify(itemMapper).insert(inserted.capture());
            assertThat(inserted.getValue().getOldValue())
                    .as("🔴 预览的 before 必须是**每规格值**（不是 SKU 汇总 80）——否则预览即失真")
                    .isEqualTo("40");
            assertThat(inserted.getValue().getNewValue()).isEqualTo("80");

            // 执行后：该商品每个规格都置为 80 ⇒ 用**同一口径**回读仍是 "80" == 预览承诺的 newValue
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_PREVIEW));
            when(itemMapper.selectList(any())).thenReturn(List.of(
                    stockItem(P1, "40", "80", AgentBatchService.ITEM_PENDING)));
            when(productService.updateProductForAgent(eq(P1), any(), eq(TENANT)))
                    .thenReturn(productWithSkuStocks("80", "80"));
            batchService.execute(TENANT, BATCH_ID);

            when(productService.getProductById(P1, TENANT)).thenReturn(productWithSkuStocks("80", "80"));
            batchService.create(TENANT, USER, stockRequest(P1, "80", "90"));
            ArgumentCaptor<AgentBatchItem> second = ArgumentCaptor.forClass(AgentBatchItem.class);
            verify(itemMapper, times(2)).insert(second.capture());
            assertThat(second.getAllValues().get(1).getOldValue())
                    .as("执行后同口径回读 == 预览承诺的 newValue（预览即承诺）")
                    .isEqualTo(inserted.getValue().getNewValue());
        }

        @Test
        @DisplayName("🔴 红判据②「撤销即还原」：各规格互不相等的商品 ⇒ preview 拒绝且零写（不给失真预览）")
        void rejectsNonUniformSpecStocksAtPreview() {
            when(productService.getProductById(P1, TENANT)).thenReturn(productWithSkuStocks("10", "30"));

            BusinessException ex = rejection(() -> batchService.create(TENANT, USER,
                    stockRequest(P1, "40", "80")));

            assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
            assertThat(ex.getMessage()).as("必须把实际值报出来（可行动）").contains("10").contains("30");
            verify(batchMapper, never()).insert(any(AgentBatch.class));
            verify(itemMapper, never()).insert(any(AgentBatchItem.class));
        }

        @Test
        @DisplayName("🔴 红判据②「撤销即还原」：各规格一致 ⇒ 撤销逐值回 oldValue（每规格 == 原值）")
        void revertRestoresEverySpecToThePersistedOldStock() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_DONE));
            when(itemMapper.selectList(any())).thenReturn(List.of(
                    stockItem(P1, "40", "80", AgentBatchService.ITEM_SUCCESS)));

            AgentBatchViews.Batch view = batchService.revert(TENANT, BATCH_ID);

            ArgumentCaptor<AgentProductUpdateRequest> req =
                    ArgumentCaptor.forClass(AgentProductUpdateRequest.class);
            verify(productService).updateProductForAgent(eq(P1), req.capture(), eq(TENANT));
            assertThat(req.getValue().getStock()).as("🔴 还原的是 old_value（每规格值）")
                    .isEqualByComparingTo("40");
            assertThat(view.getStatus()).isEqualTo(AgentBatchService.STATUS_REVERTED);
            assertThat(view.getRevertible()).as("已撤销 ⇒ revertible=false").isFalse();
        }

        @Test
        @DisplayName("无 SKU 规格的商品 ⇒ preview 拒绝（否则执行会静默空转：0 行可写 + 派生列回写早退）")
        void rejectsProductsWithoutSkus() {
            when(productService.getProductById(P1, TENANT)).thenReturn(productWithSkuStocks());

            BusinessException ex = rejection(() -> batchService.create(TENANT, USER,
                    stockRequest(P1, "0", "80")));

            assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
            assertThat(ex.getMessage()).contains("SKU");
            verify(itemMapper, never()).insert(any(AgentBatchItem.class));
        }

        @Test
        @DisplayName("白名单 + 字段配对：batchType=inventory_stock ⇒ field 必须是 stock")
        void createsPreviewWithStockFieldCollectedFromDb() {
            when(productService.getProductById(P1, TENANT)).thenReturn(productWithSkuStocks("40", "40"));

            AgentBatchViews.Batch view = batchService.create(TENANT, USER,
                    stockRequest(P1, "40", "80"));

            assertThat(view.getBatchType()).isEqualTo(AgentBatchService.TYPE_INVENTORY_STOCK);
            assertThat(view.getStatus()).isEqualTo(AgentBatchService.STATUS_PREVIEW);
            ArgumentCaptor<AgentBatchItem> items = ArgumentCaptor.forClass(AgentBatchItem.class);
            verify(itemMapper).insert(items.capture());
            assertThat(items.getValue().getField()).isEqualTo("stock");
        }

        @Test
        @DisplayName("field 不配对（inventory_stock + status）⇒ 拒绝且零写")
        void rejectsMismatchedFieldForStockBatch() {
            BusinessException ex = rejection(() -> batchService.create(TENANT, USER,
                    request(AgentBatchService.TYPE_INVENTORY_STOCK, AgentBatchService.FIELD_STATUS,
                            P1, "on_sale", "off_sale")));

            assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
            assertThat(ex.getMessage()).contains("stock");
            verify(itemMapper, never()).insert(any(AgentBatchItem.class));
        }

        @Test
        @DisplayName("改后库存 > 1 位小数 ⇒ 拒绝且零写（精度准入与单条写同一收口 StockQuantity）")
        void rejectsSubTenthStockPrecision() {
            when(productService.getProductById(P1, TENANT)).thenReturn(productWithSkuStocks("40", "40"));

            BusinessException ex = rejection(() -> batchService.create(TENANT, USER,
                    stockRequest(P1, "40", "12.25")));

            assertThat(ex.getCode()).isEqualTo("VALIDATION_ERROR");
            verify(batchMapper, never()).insert(any(AgentBatch.class));
            verify(itemMapper, never()).insert(any(AgentBatchItem.class));
        }

        @Test
        @DisplayName("执行：写的是 stock 字段（不是 status / basePrice）")
        void executesIntoTheStockField() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_PREVIEW));
            when(itemMapper.selectList(any())).thenReturn(List.of(
                    stockItem(P1, "40", "80", AgentBatchService.ITEM_PENDING)));
            when(productService.updateProductForAgent(eq(P1), any(), eq(TENANT)))
                    .thenReturn(productWithSkuStocks("80", "80"));

            AgentBatchViews.Batch view = batchService.execute(TENANT, BATCH_ID);

            ArgumentCaptor<AgentProductUpdateRequest> req =
                    ArgumentCaptor.forClass(AgentProductUpdateRequest.class);
            verify(productService).updateProductForAgent(eq(P1), req.capture(), eq(TENANT));
            assertThat(req.getValue().getStock()).as("执行 = 写 newValue 到 stock")
                    .isEqualByComparingTo("80");
            assertThat(req.getValue().getStatus()).as("不得落到 status 分支").isNull();
            assertThat(req.getValue().getBasePrice()).as("不得落到价格分支").isNull();
            assertThat(view.getStatus()).isEqualTo(AgentBatchService.STATUS_DONE);
            assertThat(view.getRevertible()).as("done ⇒ revertible（撤销如实反映）").isTrue();
        }

        @Test
        @DisplayName("撤销逐条失败 ⇒ revert_partial（不掩盖哪几条没还原回去）")
        void revertFailureIsReportedPerItem() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_DONE));
            when(itemMapper.selectList(any())).thenReturn(List.of(
                    stockItem(P1, "40", "80", AgentBatchService.ITEM_SUCCESS),
                    stockItem(P2, "30", "80", AgentBatchService.ITEM_SUCCESS)));
            when(productService.updateProductForAgent(eq(P1), any(), eq(TENANT)))
                    .thenReturn(productWithSkuStocks("40", "40"));
            when(productService.updateProductForAgent(eq(P2), any(), eq(TENANT)))
                    .thenThrow(new BusinessException("VALIDATION_ERROR", "库存还原失败"));

            AgentBatchViews.Batch view = batchService.revert(TENANT, BATCH_ID);

            assertThat(view.getStatus()).isEqualTo(AgentBatchService.STATUS_REVERT_PARTIAL);
            assertThat(view.getResults()).extracting(AgentBatchViews.Result::isSuccess)
                    .containsExactly(true, false);
            assertThat(view.getResults().get(1).getError()).contains(P2);
        }
    }

    // ══════════════════ ② 执行（逐条 + 部分失败）════════════════════════════

    @Nested
    @DisplayName("POST /{batchId}/execute（逐条执行）")
    class Execute {

        @Test
        @DisplayName("状态机 preview → executing → done，逐条落 status 并回 results")
        void movesToDoneAndPersistsPerItemStatus() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_PREVIEW));
            when(itemMapper.selectList(any())).thenReturn(List.of(item(P1, "10.00", "12.00", AgentBatchService.ITEM_PENDING)));
            when(productService.updateProductForAgent(eq(P1), any(), eq(TENANT))).thenReturn(product("12.00", "on_sale"));
            List<String> batchStatusWrites = recordBatchStatusWrites();

            AgentBatchViews.Batch view = batchService.execute(TENANT, BATCH_ID);

            ArgumentCaptor<AgentProductUpdateRequest> req = ArgumentCaptor.forClass(AgentProductUpdateRequest.class);
            verify(productService).updateProductForAgent(eq(P1), req.capture(), eq(TENANT));
            assertThat(req.getValue().getBasePrice()).as("执行 = 写 newValue").isEqualByComparingTo("12.00");
            assertThat(req.getValue().getStatus()).as("只改这一个字段，其余留 null").isNull();

            ArgumentCaptor<AgentBatchItem> itemUpdates = ArgumentCaptor.forClass(AgentBatchItem.class);
            verify(itemMapper, atLeastOnce()).updateById(itemUpdates.capture());
            assertThat(itemUpdates.getAllValues()).extracting(AgentBatchItem::getStatus)
                    .contains(AgentBatchService.ITEM_SUCCESS);
            assertThat(itemUpdates.getAllValues()).allSatisfy(i -> assertThat(i.getError()).isNull());

            assertThat(batchStatusWrites)
                    .as("状态机：executing 是**落库**的中间态，不是内存里跳过去的")
                    .containsExactly(AgentBatchService.STATUS_EXECUTING, AgentBatchService.STATUS_DONE);
            assertThat(view.getSuccessCount()).isEqualTo(1);
            assertThat(view.getFailCount()).isZero();
            assertThat(view.getExecutedAt()).isNotNull();

            assertThat(view.getStatus()).isEqualTo(AgentBatchService.STATUS_DONE);
            assertThat(view.getResults()).hasSize(1);
            assertThat(view.getResults().get(0).getResourceId()).isEqualTo(P1);
            assertThat(view.getResults().get(0).isSuccess()).isTrue();
            assertThat(view.getResults().get(0).getError()).isNull();
        }

        @Test
        @DisplayName("部分失败**逐条报告、不做整体回滚**（成功行留 success，失败行留 error）")
        void reportsPartialFailurePerItemWithoutRollback() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_PREVIEW));
            when(itemMapper.selectList(any())).thenReturn(List.of(
                    item(P1, "10.00", "12.00", AgentBatchService.ITEM_PENDING),
                    item(P2, "20.00", "22.00", AgentBatchService.ITEM_PENDING)));
            when(productService.updateProductForAgent(eq(P1), any(), eq(TENANT))).thenReturn(product("12.00", "on_sale"));
            when(productService.updateProductForAgent(eq(P2), any(), eq(TENANT)))
                    .thenThrow(new BusinessException("VALIDATION_ERROR", "商品 " + P2 + " 改价失败"));
            List<String> batchStatusWrites = recordBatchStatusWrites();

            AgentBatchViews.Batch view = batchService.execute(TENANT, BATCH_ID);

            assertThat(view.getStatus()).isEqualTo(AgentBatchService.STATUS_PARTIAL);
            assertThat(view.getResults()).extracting(AgentBatchViews.Result::isSuccess)
                    .containsExactly(true, false);
            assertThat(view.getResults().get(1).getError()).contains(P2);
            assertThat(view.getResults().get(1).getResourceId()).isEqualTo(P2);

            ArgumentCaptor<AgentBatchItem> itemUpdates = ArgumentCaptor.forClass(AgentBatchItem.class);
            verify(itemMapper, atLeastOnce()).updateById(itemUpdates.capture());
            assertThat(itemUpdates.getAllValues()).extracting(AgentBatchItem::getStatus)
                    .as("逐条落 status：成功的不因后一条失败被回滚")
                    .containsExactly(AgentBatchService.ITEM_SUCCESS, AgentBatchService.ITEM_FAILED);
            assertThat(itemUpdates.getAllValues().get(1).getError()).contains(P2);

            assertThat(batchStatusWrites)
                    .as("不做整体回滚：状态只沿 preview→executing→partial 前进（不回 preview、不出现 reverted）")
                    .containsExactly(AgentBatchService.STATUS_EXECUTING, AgentBatchService.STATUS_PARTIAL);
            assertThat(view.getSuccessCount()).isEqualTo(1);
            assertThat(view.getFailCount()).isEqualTo(1);
        }

        @Test
        @DisplayName("已执行过的批次不得重复执行（防二次改价）")
        void refusesAlreadyExecutedBatch() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_DONE));

            BusinessException ex = rejection(() -> batchService.execute(TENANT, BATCH_ID));

            assertThat(ex.getCode()).isEqualTo("CONFLICT");
            verify(productService, never()).updateProductForAgent(any(), any(), any());
        }

        @Test
        @DisplayName("跨租户批次不可见 ⇒ NOT_FOUND 且零写")
        void crossTenantBatchIsInvisible() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(null);

            BusinessException ex = rejection(() -> batchService.execute(TENANT, BATCH_ID));

            assertThat(ex.getCode()).isEqualTo("NOT_FOUND");
            verify(productService, never()).updateProductForAgent(any(), any(), any());
            verify(itemMapper, never()).updateById(any(AgentBatchItem.class));
        }
    }

    // ══════════════════ ③ 撤销（逐条还原 old_value）═════════════════════════

    @Nested
    @DisplayName("POST /{batchId}/revert（撤销）")
    class Revert {

        @Test
        @DisplayName("逐条还原为持久化的 old_value（不是 newValue），并留 reverted_at")
        void revertRestoresPersistedOldValuePerItem() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_DONE));
            when(itemMapper.selectList(any())).thenReturn(List.of(
                    item(P1, "10.00", "12.00", AgentBatchService.ITEM_SUCCESS)));
            when(productService.updateProductForAgent(eq(P1), any(), eq(TENANT))).thenReturn(product("10.00", "on_sale"));

            AgentBatchViews.Batch view = batchService.revert(TENANT, BATCH_ID);

            ArgumentCaptor<AgentProductUpdateRequest> req = ArgumentCaptor.forClass(AgentProductUpdateRequest.class);
            verify(productService).updateProductForAgent(eq(P1), req.capture(), eq(TENANT));
            assertThat(req.getValue().getBasePrice())
                    .as("🔴 撤销 = 还原 old_value（落库那一份），不是 newValue")
                    .isEqualByComparingTo("10.00");
            assertThat(req.getValue().getBasePrice()).isNotEqualByComparingTo("12.00");

            ArgumentCaptor<AgentBatchItem> itemUpdates = ArgumentCaptor.forClass(AgentBatchItem.class);
            verify(itemMapper, atLeastOnce()).updateById(itemUpdates.capture());
            assertThat(itemUpdates.getAllValues()).extracting(AgentBatchItem::getStatus)
                    .contains(AgentBatchService.ITEM_REVERTED);
            assertThat(itemUpdates.getAllValues()).allSatisfy(i -> assertThat(i.getError()).isNull());

            ArgumentCaptor<AgentBatch> batchUpdates = ArgumentCaptor.forClass(AgentBatch.class);
            verify(batchMapper, atLeastOnce()).updateById(batchUpdates.capture());
            AgentBatch last = batchUpdates.getAllValues().get(batchUpdates.getAllValues().size() - 1);
            assertThat(last.getStatus()).isEqualTo(AgentBatchService.STATUS_REVERTED);
            assertThat(last.getRevertedAt()).isNotNull();

            assertThat(view.getStatus()).isEqualTo(AgentBatchService.STATUS_REVERTED);
            assertThat(view.getResults()).extracting(AgentBatchViews.Result::isSuccess).containsExactly(true);
        }

        @Test
        @DisplayName("执行时失败过的行从不曾生效 ⇒ 撤销时跳过（逐条报告 skipped，不误写）")
        void revertSkipsItemsThatNeverApplied() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_PARTIAL));
            when(itemMapper.selectList(any())).thenReturn(List.of(
                    item(P1, "10.00", "12.00", AgentBatchService.ITEM_SUCCESS),
                    item(P2, "20.00", "22.00", AgentBatchService.ITEM_FAILED)));
            when(productService.updateProductForAgent(eq(P1), any(), eq(TENANT))).thenReturn(product("10.00", "on_sale"));

            AgentBatchViews.Batch view = batchService.revert(TENANT, BATCH_ID);

            assertThat(view.getStatus()).isEqualTo(AgentBatchService.STATUS_REVERTED);
            ArgumentCaptor<AgentBatchItem> itemUpdates = ArgumentCaptor.forClass(AgentBatchItem.class);
            verify(itemMapper, atLeastOnce()).updateById(itemUpdates.capture());
            assertThat(itemUpdates.getAllValues()).extracting(AgentBatchItem::getStatus)
                    .containsExactly(AgentBatchService.ITEM_REVERTED, AgentBatchService.ITEM_SKIPPED);
            verify(productService, never()).updateProductForAgent(eq(P2), any(), any());
        }

        @Test
        @DisplayName("撤销也有部分失败：逐条报告 + revert_partial（不整体回滚）")
        void revertPartialFailureIsReportedPerItem() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_DONE));
            when(itemMapper.selectList(any())).thenReturn(List.of(
                    item(P1, "10.00", "12.00", AgentBatchService.ITEM_SUCCESS),
                    item(P2, "20.00", "22.00", AgentBatchService.ITEM_SUCCESS)));
            when(productService.updateProductForAgent(eq(P1), any(), eq(TENANT))).thenReturn(product("10.00", "on_sale"));
            when(productService.updateProductForAgent(eq(P2), any(), eq(TENANT)))
                    .thenThrow(new BusinessException("VALIDATION_ERROR", "商品 " + P2 + " 状态流转无效"));

            AgentBatchViews.Batch view = batchService.revert(TENANT, BATCH_ID);

            assertThat(view.getStatus()).isEqualTo(AgentBatchService.STATUS_REVERT_PARTIAL);
            assertThat(view.getResults()).extracting(AgentBatchViews.Result::isSuccess)
                    .containsExactly(true, false);
            ArgumentCaptor<AgentBatchItem> itemUpdates = ArgumentCaptor.forClass(AgentBatchItem.class);
            verify(itemMapper, atLeastOnce()).updateById(itemUpdates.capture());
            assertThat(itemUpdates.getAllValues()).extracting(AgentBatchItem::getStatus)
                    .containsExactly(AgentBatchService.ITEM_REVERTED, AgentBatchService.ITEM_REVERT_FAILED);
            assertThat(itemUpdates.getAllValues().get(1).getError()).contains(P2);
        }

        @Test
        @DisplayName("已撤销不可再撤销（契约：不可撤销条件之一）")
        void alreadyRevertedBatchIsNotRevertibleAgain() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_REVERTED));

            BusinessException ex = rejection(() -> batchService.revert(TENANT, BATCH_ID));

            assertThat(ex.getCode()).isEqualTo("CONFLICT");
            verify(productService, never()).updateProductForAgent(any(), any(), any());
            verify(itemMapper, never()).updateById(any(AgentBatchItem.class));
        }

        @Test
        @DisplayName("状态非 done/partial（如 preview / executing）不可撤销")
        void nonTerminalBatchIsNotRevertible() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_PREVIEW));

            BusinessException ex = rejection(() -> batchService.revert(TENANT, BATCH_ID));

            assertThat(ex.getCode()).isEqualTo("CONFLICT");
            verify(productService, never()).updateProductForAgent(any(), any(), any());
        }

        @Test
        @DisplayName("跨租户批次不可见 ⇒ NOT_FOUND 且零写")
        void crossTenantBatchIsInvisible() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(null);

            BusinessException ex = rejection(() -> batchService.revert(TENANT, BATCH_ID));

            assertThat(ex.getCode()).isEqualTo("NOT_FOUND");
            verify(productService, never()).updateProductForAgent(any(), any(), any());
        }
    }

    // ══════════════════ ④ 查询（进度 / 结果 / 可撤销性）══════════════════════

    @Nested
    @DisplayName("GET /{batchId}（查询）")
    class Query {

        @Test
        @DisplayName("done ⇒ revertible=true，且逐条回 before → after（撤销依据可核对）")
        void reportsItemsAndRevertibleForDone() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_DONE));
            when(itemMapper.selectList(any())).thenReturn(List.of(
                    item(P1, "10.00", "12.00", AgentBatchService.ITEM_SUCCESS)));

            AgentBatchViews.Batch view = batchService.get(TENANT, BATCH_ID);

            assertThat(view.getBatchId()).isEqualTo(BATCH_ID);
            assertThat(view.getStatus()).isEqualTo(AgentBatchService.STATUS_DONE);
            assertThat(view.getRevertible()).isTrue();
            assertThat(view.getItems()).hasSize(1);
            assertThat(view.getItems().get(0).getOldValue()).isEqualTo("10.00");
            assertThat(view.getItems().get(0).getNewValue()).isEqualTo("12.00");
            assertThat(view.getItems().get(0).getField()).isEqualTo(AgentBatchService.FIELD_BASE_PRICE);
        }

        @Test
        @DisplayName("reverted ⇒ revertible=false（已撤销的不再给撤销入口）")
        void revertedIsNotRevertible() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_REVERTED));
            when(itemMapper.selectList(any())).thenReturn(List.of());

            AgentBatchViews.Batch view = batchService.get(TENANT, BATCH_ID);

            assertThat(view.getRevertible()).isFalse();
        }

        @Test
        @DisplayName("跨租户批次不可见 ⇒ NOT_FOUND")
        void crossTenantBatchIsInvisible() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(null);

            BusinessException ex = rejection(() -> batchService.get(TENANT, BATCH_ID));

            assertThat(ex.getCode()).isEqualTo("NOT_FOUND");
            verify(itemMapper, never()).selectList(any());
        }
    }

    // ════════════════ issue #6228：改后价小数位准入（超 2 位有效小数 ⇒ 拒绝 + 零写商品）════════════════

    @Nested
    @DisplayName("#6228 批量改价的精度准入（单点复用 MoneyScale）")
    class MoneyScaleAdmission {

        @Test
        @DisplayName("改后价 1.005（3 位有效小数）⇒ 逐条拒绝、productService **零调用**（不静默舍成 1.00/1.01）")
        void rejectsSubCentPriceAtExecute() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_PREVIEW));
            when(itemMapper.selectList(any())).thenReturn(List.of(
                    item(P1, "10.00", "1.005", AgentBatchService.ITEM_PENDING)));

            AgentBatchViews.Batch view = batchService.execute(TENANT, BATCH_ID);

            assertThat(view.getStatus()).isEqualTo(AgentBatchService.STATUS_PARTIAL);
            assertThat(view.getFailCount()).isEqualTo(1);
            assertThat(view.getResults()).singleElement()
                    .satisfies(r -> assertThat(r.getError()).contains("2 位小数"));
            verify(productService, never()).updateProductForAgent(any(), any(), any());
        }

        @Test
        @DisplayName("正对照 改后价 12.50（2 位小数）⇒ 执行成功并逐字写入 12.50")
        void acceptsTwoDecimalPrice() {
            when(batchMapper.selectById(BATCH_ID)).thenReturn(batch(AgentBatchService.STATUS_PREVIEW));
            when(itemMapper.selectList(any())).thenReturn(List.of(
                    item(P1, "10.00", "12.50", AgentBatchService.ITEM_PENDING)));
            when(productService.updateProductForAgent(eq(P1), any(), eq(TENANT)))
                    .thenReturn(product("12.50", "on_sale"));

            AgentBatchViews.Batch view = batchService.execute(TENANT, BATCH_ID);

            ArgumentCaptor<AgentProductUpdateRequest> req =
                    ArgumentCaptor.forClass(AgentProductUpdateRequest.class);
            verify(productService).updateProductForAgent(eq(P1), req.capture(), eq(TENANT));
            assertThat(req.getValue().getBasePrice().toPlainString()).isEqualTo("12.50");
            assertThat(view.getSuccessCount()).isEqualTo(1);
        }
    }
}