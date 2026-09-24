// case_ids: PR-007, PR-010
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ProductResponse;
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
}