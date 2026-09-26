// case_ids: PR-029, PR-030, PR-031, PR-032, PR-110, PR-111, PR-112
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.dto.WorkerInboundDraftRequest;
import com.migao.admin.dto.WorkerInboundDraftView;
import com.migao.admin.dto.WorkerInboundPostRequest;
import com.migao.admin.dto.WorkerInboundRecognizeRequest;
import com.migao.admin.dto.WorkerInboundRecognizeResponse;
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
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工人可达的入库服务（issue #5052 <b>P1</b>）—— 载体 + 判据，**过账逻辑一行都不新造**。
 *
 * <p>接线形态：真实的 {@link InboundOrderService}（#5045，**逐字复用**）+
 * 真实的 {@link WorkerInboundService} + Mock 掉的 Mapper ⇒ 断言的是「工人面走到既有过账服务
 * 之后真正发生了什么」，而不是「某个 mock 被调过」。</p>
 *
 * <h3>本类钉住的五条（每条都能红）</h3>
 * <ol>
 *   <li><b>草稿不动库存</b>：建草稿**不得**调 {@code receiveStock} / 不得落台账 / 不得写批次；</li>
 *   <li><b>过账才动库存，且台账可对账</b>：一行 {@code reason=inbound}，
 *       {@code after_qty - before_qty == delta == 入库量}；</li>
 *   <li><b>零命中不建品</b>（设计 §6.3）：识别零命中 ⇒ 空匹配；建草稿缺 skuId / skuId 不存在 ⇒ 拒绝，
 *       且 {@code products} / {@code product_skus} 的 insert **零调用**（防 AI 幻觉造出假 SKU 带库存流水）；</li>
 *   <li><b>不确定 ⇒ 不预填</b>（§6.4）：vision 降级 ⇒ 三个候选字段全 null，只给人工录入提示；</li>
 *   <li><b>成本守卫</b>（§6.1）：请求带前端解码的条码 ⇒ {@code ImageRecognitionClient} **零调用**。</li>
 * </ol>
 *
 * <p>红证读数见 PR body 的「注入式红证」表（四条：工人调 /api/admin/** 仍拒、幂等键重放不重复加库存、
 * 零命中不建品、请求体结构上无 adjustment）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("工人可达的入库服务（#5052 P1）")
class WorkerInboundServiceTest {

    @Mock private InboundOrderMapper inboundOrderMapper;
    @Mock private InboundOrderItemMapper inboundOrderItemMapper;
    @Mock private InboundOrderQueryMapper inboundOrderQueryMapper;
    @Mock private StockBatchMapper stockBatchMapper;
    @Mock private ProductSkuMapper productSkuMapper;
    @Mock private ProductMapper productMapper;
    @Mock private StockLedgerService stockLedgerService;
    @Mock private ImageRecognitionClient imageRecognitionClient;
    @Mock private com.migao.admin.service.InboundLabelService inboundLabelService;
    @Mock private ClientRequestIdService clientRequestIdService;

    private WorkerInboundService service;

    private static final Long TENANT = 1L;
    private static final String WORKER_ID = "worker-zhang";
    private static final String PRODUCT_ID = "P-1";
    private static final Long SKU_ID = 10L;
    private static final String SKU_CODE = "SKU-001";
    private static final String PRODUCT_NAME = "雪尼尔遮光窗帘";
    private static final String COLOR_NAME = "米白";
    private static final String IMAGE_URL = "https://oss.example.com/roll-1.jpg";

    private InboundOrder order;
    private InboundOrderItem line;
    private ProductSku sku;
    private final AtomicInteger idSeq = new AtomicInteger(0);

    @BeforeEach
    void setUp() {
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Product.class);
        TableInfoHelper.initTableInfo(assistant, ProductSku.class);
        TableInfoHelper.initTableInfo(assistant, InboundOrder.class);
        TableInfoHelper.initTableInfo(assistant, InboundOrderItem.class);
        TableInfoHelper.initTableInfo(assistant, StockBatch.class);

        idSeq.set(0);
        order = null;
        List<InboundOrderItem> lines = new ArrayList<>();

        doAnswer(inv -> {
            InboundOrder inserted = inv.getArgument(0);
            if (inserted.getId() == null) {
                inserted.setId("draft-" + idSeq.incrementAndGet());
            }
            order = inserted;
            return 1;
        }).when(inboundOrderMapper).insert(any(InboundOrder.class));
        when(inboundOrderMapper.exists(any())).thenReturn(false);
        when(inboundOrderMapper.updateById(any(InboundOrder.class))).thenReturn(1);
        when(inboundOrderMapper.selectOne(any())).thenAnswer(inv -> order);
        when(inboundOrderMapper.markPosted(anyString(), anyLong(), anyString(), any())).thenReturn(1);

        doAnswer(inv -> {
            InboundOrderItem inserted = inv.getArgument(0);
            inserted.setId((long) (100 + idSeq.incrementAndGet()));
            lines.add(inserted);
            return 1;
        }).when(inboundOrderItemMapper).insert(any(InboundOrderItem.class));
        when(inboundOrderItemMapper.selectList(any())).thenAnswer(inv -> lines);
        // 过账时行上回写批次号走的是**新对象**（patch），真库里是 UPDATE ⇒ 测试替身必须把 patch
        // 应用到内存行上，否则「批次号落在行上」这条断言会拿到 null（假红）
        when(inboundOrderItemMapper.updateById(any(InboundOrderItem.class))).thenAnswer(inv -> {
            InboundOrderItem patch = inv.getArgument(0);
            for (InboundOrderItem stored : lines) {
                if (stored.getId() != null && stored.getId().equals(patch.getId())) {
                    stored.setBatchNo(patch.getBatchNo());
                }
            }
            return 1;
        });

        sku = ProductSku.builder()
                .id(SKU_ID).tenantId(TENANT).productId(PRODUCT_ID)
                .skuCode(SKU_CODE).colorName(COLOR_NAME).doorWidth("2.8")
                .stock(new BigDecimal("10")).build();
        when(productSkuMapper.selectById(SKU_ID)).thenReturn(sku);
        when(productSkuMapper.selectList(any())).thenReturn(List.of(sku));
        when(productSkuMapper.receiveStock(anyLong(), any(), any(), anyString())).thenReturn(1);

        Product product = Product.builder().id(PRODUCT_ID).tenantId(TENANT).name(PRODUCT_NAME).build();
        when(productMapper.selectById(PRODUCT_ID)).thenReturn(product);
        when(productMapper.selectList(any())).thenReturn(List.of(product));
        when(productMapper.updateById(any(Product.class))).thenReturn(1);

        when(stockBatchMapper.exists(any())).thenReturn(false);
        when(stockBatchMapper.insert(any(StockBatch.class))).thenReturn(1);

        when(clientRequestIdService.claim(anyLong(), any(), anyString())).thenReturn(true);

        InboundOrderService inboundOrderService = new InboundOrderService(
                inboundOrderMapper, inboundOrderItemMapper, inboundOrderQueryMapper,
                stockBatchMapper, productSkuMapper, productMapper, stockLedgerService);
        service = new WorkerInboundService(inboundOrderService, imageRecognitionClient,
                clientRequestIdService, productMapper, productSkuMapper, inboundLabelService);
    }

    // ============================================================ 工具

    private static WorkerInboundRecognizeRequest recognizeRequest(String barcode, String... images) {
        WorkerInboundRecognizeRequest req = new WorkerInboundRecognizeRequest();
        req.setImages(new ArrayList<>(List.of(images)));
        req.setBarcode(barcode);
        return req;
    }

    private static WorkerInboundDraftRequest draftRequest(String rawQuantity) {
        WorkerInboundDraftRequest req = new WorkerInboundDraftRequest();
        req.setProductId(PRODUCT_ID);
        req.setSkuId(SKU_ID);
        req.setQuantity(rawQuantity == null ? null : new BigDecimal(rawQuantity));
        req.setUnitCost(new BigDecimal("12.5"));
        req.setSupplierDocNo("DN-20260926-01");
        return req;
    }

    private static WorkerInboundPostRequest confirmed() {
        WorkerInboundPostRequest req = new WorkerInboundPostRequest();
        req.setConfirmed(Boolean.TRUE);
        return req;
    }

    private static Map<String, Object> field(String key, String value) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("key", key);
        map.put("label", key);
        map.put("value", value);
        map.put("source", value == null ? null : "[图片识别]");
        map.put("reason", value == null ? "图片未给出该字段" : null);
        return map;
    }

    private static ImageRecognitionClient.ImageRecognitionResult vision(List<Map<String, Object>> fields,
                                                                       boolean degraded) {
        return new ImageRecognitionClient.ImageRecognitionResult("inbound", fields, degraded);
    }

    /** 走一遍「建草稿」把 order/line 造出来（后续过账用例共用）。 */
    private WorkerInboundDraftView createDraft(String quantity) {
        return service.createDraft(draftRequest(quantity), TENANT, WORKER_ID, null);
    }

    // ============================================================ ① 识别

    @Nested
    @DisplayName("识别（不落库、不动库存）")
    class Recognize {

        @Test
        @DisplayName("🔴 照片含可解条码（前端解码）⇒ 走解码路径，远端 vision 调用次数 = 0（成本守卫）")
        void decodedBarcodeSkipsVisionEntirely() {
            WorkerInboundRecognizeResponse resp =
                    service.recognize(recognizeRequest(SKU_CODE, IMAGE_URL), TENANT);

            verify(imageRecognitionClient, never()).recognize(any(), any());
            assertThat(resp.getPath()).isEqualTo(WorkerInboundService.PATH_BARCODE);
            assertThat(resp.getSkuMatches()).hasSize(1);
            assertThat(resp.getSkuMatches().get(0).getSkuId()).isEqualTo(SKU_ID);
            assertThat(resp.getSkuMatches().get(0).getProductName()).isEqualTo(PRODUCT_NAME);
            assertThat(resp.isRequiresManualEntry()).isFalse();
        }

        @Test
        @DisplayName("条码零命中 ⇒ 空匹配 + 提示人工录入（不建品、不编造）")
        void decodedBarcodeWithoutSkuCodeHitsNothing() {
            when(productSkuMapper.selectList(any())).thenReturn(List.of());

            WorkerInboundRecognizeResponse resp =
                    service.recognize(recognizeRequest("SUPPLIER-RAW-CODE", IMAGE_URL), TENANT);

            verify(imageRecognitionClient, never()).recognize(any(), any());
            assertThat(resp.getSkuMatches()).isEmpty();
            assertThat(resp.isRequiresManualEntry()).isTrue();
            verify(productMapper, never()).insert(any(Product.class));
            verify(productSkuMapper, never()).insert(any(ProductSku.class));
        }

        @Test
        @DisplayName("无条码 ⇒ vision 兜底，target 由服务端固定为 inbound（客户端不可选）")
        void visionFallbackUsesServerFixedTargetAndMatchesExistingSku() {
            when(imageRecognitionClient.recognize(eq(WorkerInboundService.TARGET_INBOUND), any()))
                    .thenReturn(vision(List.of(
                            field("product_name", PRODUCT_NAME),
                            field("color_name", COLOR_NAME),
                            field("quantity_meters", "60.5"),
                            field("barcode", null)), false));

            WorkerInboundRecognizeResponse resp = service.recognize(recognizeRequest(null, IMAGE_URL), TENANT);

            verify(imageRecognitionClient, times(1)).recognize(eq(WorkerInboundService.TARGET_INBOUND), any());
            assertThat(resp.getPath()).isEqualTo(WorkerInboundService.PATH_VISION);
            assertThat(resp.getProductName()).isEqualTo(PRODUCT_NAME);
            assertThat(resp.getColorName()).isEqualTo(COLOR_NAME);
            assertThat(resp.getQuantityMeters()).isEqualTo("60.5");
            assertThat(resp.getSkuMatches()).hasSize(1);
            assertThat(resp.isRequiresManualEntry()).isFalse();
        }

        @Test
        @DisplayName("🔴 vision 降级 ⇒ 不预填：三个候选字段全 null，只给人工录入提示（不编造）")
        void degradedVisionPrefillsNothing() {
            when(imageRecognitionClient.recognize(any(), any())).thenReturn(vision(List.of(), true));

            WorkerInboundRecognizeResponse resp = service.recognize(recognizeRequest(null, IMAGE_URL), TENANT);

            assertThat(resp.isDegraded()).isTrue();
            assertThat(resp.getProductName()).isNull();
            assertThat(resp.getColorName()).isNull();
            assertThat(resp.getQuantityMeters()).isNull();
            assertThat(resp.getSkuMatches()).isEmpty();
            assertThat(resp.isRequiresManualEntry()).isTrue();
        }

        @Test
        @DisplayName("🔴 SKU 匹配门禁：品名 + 色号零命中 ⇒ 不建品、不落库（防 AI 幻觉造出假 SKU）")
        void zeroSkuMatchNeverCreatesProduct() {
            when(imageRecognitionClient.recognize(any(), any()))
                    .thenReturn(vision(List.of(
                            field("product_name", "根本不存在的布"),
                            field("color_name", "X999"),
                            field("quantity_meters", "60.5")), false));
            when(productMapper.selectList(any())).thenReturn(List.of());

            WorkerInboundRecognizeResponse resp = service.recognize(recognizeRequest(null, IMAGE_URL), TENANT);

            assertThat(resp.getSkuMatches()).isEmpty();
            assertThat(resp.isRequiresManualEntry()).isTrue();
            verify(productMapper, never()).insert(any(Product.class));
            verify(productSkuMapper, never()).insert(any(ProductSku.class));
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString());
        }

        @Test
        @DisplayName("照片张数越界（0 张 / 4 张）⇒ 400，且一次远端调用都不发生")
        void imageCountIsGuarded() {
            assertThatThrownBy(() -> service.recognize(recognizeRequest(null), TENANT))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(400));
            assertThatThrownBy(() -> service.recognize(
                    recognizeRequest(null, IMAGE_URL, IMAGE_URL, IMAGE_URL, IMAGE_URL), TENANT))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(400));
            verify(imageRecognitionClient, never()).recognize(any(), any());
        }
    }

    // ============================================================ ② 建草稿

    @Nested
    @DisplayName("建草稿（草稿态完全不动库存）")
    class CreateDraft {

        @Test
        @DisplayName("🔴 建草稿只写单据与明细：不加库存、不落台账、不写批次、来源恒 purchase")
        void draftNeverTouchesStock() {
            WorkerInboundDraftView view = createDraft("60.5");

            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString());
            verify(stockLedgerService, never()).record(anyLong(), anyString(), anyLong(), anyString(),
                    any(), any(), anyString(), anyString(), anyString(), any(), any(), any());
            verify(stockBatchMapper, never()).insert(any(StockBatch.class));
            assertThat(view.getStatus()).isEqualTo(InboundOrder.STATUS_DRAFT);
            assertThat(view.getSource()).isEqualTo(InboundOrder.SOURCE_PURCHASE);
            assertThat(view.getNeedsConfirmation()).isTrue();
            assertThat(view.getItems()).hasSize(1);
            assertThat(view.getItems().get(0).getBatchNo()).isNull();
            assertThat(view.getItems().get(0).getQuantity()).isEqualByComparingTo("60.5");
        }

        @Test
        @DisplayName("🔴 负数 / 0 / 超 1 位小数 ⇒ 400（#5063 判据：> 0 且最多 1 位小数），一行都不落库")
        void quantityAdmissionIsEnforcedWithCarrierStatus() {
            for (String bad : List.of("-1", "0", "2.755")) {
                assertThatThrownBy(() -> createDraft(bad))
                        .as("数量 %s 必须被拒（400）", bad)
                        .isInstanceOf(BusinessException.class)
                        .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus())
                                .as("设计 §5.2：工人面参数类拒绝的状态码是 400（口径本体仍是 #5063 那一处）")
                                .isEqualTo(400));
            }
            verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString());
        }

        @Test
        @DisplayName("0.5 米的尾料可以如实登记（下限是 > 0，不是 ≥ 1）")
        void halfMeterTailIsAccepted() {
            WorkerInboundDraftView view = createDraft("0.5");

            assertThat(view.getItems().get(0).getQuantity()).isEqualByComparingTo("0.5");
        }

        @Test
        @DisplayName("🔴 skuId 不存在（零命中匹配）⇒ 400 且不自动建品")
        void unknownSkuIsRejectedWithoutCreatingProduct() {
            when(productSkuMapper.selectList(any())).thenReturn(List.of());

            assertThatThrownBy(() -> createDraft("60.5"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(400));
            verify(productMapper, never()).insert(any(Product.class));
            verify(productSkuMapper, never()).insert(any(ProductSku.class));
            verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
        }

        @Test
        @DisplayName("同 Idempotency-Key 重复建草稿 ⇒ 回放首次结果，不建第二张单")
        void repeatedDraftKeyReplaysInsteadOfCreatingASecondOrder() {
            when(clientRequestIdService.claim(eq(TENANT), eq("dk-1"), eq(WorkerInboundService.ENDPOINT_DRAFTS)))
                    .thenReturn(true, false);
            WorkerInboundDraftView first = service.createDraft(draftRequest("60.5"), TENANT, WORKER_ID, "dk-1");
            WorkerInboundDraftView replay = new WorkerInboundDraftView();
            replay.setDraftId(first.getDraftId());
            replay.setStatus(first.getStatus());
            replay.setReplayed(Boolean.TRUE);
            when(clientRequestIdService.replay(eq(TENANT), eq("dk-1"), eq(WorkerInboundDraftView.class)))
                    .thenReturn(Optional.of(replay));

            WorkerInboundDraftView second = service.createDraft(draftRequest("60.5"), TENANT, WORKER_ID, "dk-1");

            verify(inboundOrderMapper, times(1)).insert(any(InboundOrder.class));
            assertThat(second.getReplayed()).isTrue();
            assertThat(second.getDraftId()).isEqualTo(first.getDraftId());
        }
    }

    // ============================================================ ③ 过账

    @Nested
    @DisplayName("过账（过账才动库存）")
    class PostDraft {

        @Test
        @DisplayName("🔴 过账落一行 reason=inbound，after-before == delta == 入库量")
        void postWritesOneLedgerRowWithConsistentDelta() {
            WorkerInboundDraftView draft = createDraft("60.5");

            WorkerInboundDraftView posted = service.postDraft(
                    draft.getDraftId(), confirmed(), TENANT, WORKER_ID, null);

            verify(productSkuMapper, times(1))
                    .receiveStock(eq(SKU_ID), eq(new BigDecimal("60.5")), eq(new BigDecimal("12.5")), anyString());
            verify(stockLedgerService, times(1)).record(
                    eq(TENANT), eq(PRODUCT_ID), eq(SKU_ID), eq(SKU_CODE),
                    eq(new BigDecimal("10")), eq(new BigDecimal("70.5")),
                    eq(StockLedger.REASON_INBOUND), eq(draft.getInboundNo()), anyString(),
                    eq(new BigDecimal("12.5")), any(), eq(new BigDecimal("12.5")));
            assertThat(posted.getStatus()).isEqualTo(InboundOrder.STATUS_POSTED);
            assertThat(posted.getNeedsConfirmation()).isFalse();
            assertThat(posted.getItems().get(0).getBatchNo()).startsWith("PC-");
        }

        @Test
        @DisplayName("🔴 未确认（缺人工确认标记）就提交 ⇒ 409，且库存与台账一行都不动")
        void unconfirmedPostIsRejectedBeforeAnyWrite() {
            WorkerInboundDraftView draft = createDraft("60.5");
            WorkerInboundPostRequest blank = new WorkerInboundPostRequest();

            for (WorkerInboundPostRequest body : List.of(blank, confirmedWith(null), confirmedWith(Boolean.FALSE))) {
                assertThatThrownBy(() -> service.postDraft(draft.getDraftId(), body, TENANT, WORKER_ID, null))
                        .isInstanceOf(BusinessException.class)
                        .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(409));
            }
            assertThatThrownBy(() -> service.postDraft(draft.getDraftId(), null, TENANT, WORKER_ID, null))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(409));

            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString());
            verify(stockLedgerService, never()).record(anyLong(), anyString(), anyLong(), anyString(),
                    any(), any(), anyString(), anyString(), anyString(), any(), any(), any());
            verify(inboundOrderMapper, never()).markPosted(anyString(), anyLong(), anyString(), any());
        }

        @Test
        @DisplayName("🔴 幂等键重放：同键第二次提交不再加库存、不再落台账（库存只加一次）")
        void repeatedPostKeyAddsStockExactlyOnce() {
            WorkerInboundDraftView draft = createDraft("60.5");
            when(clientRequestIdService.claim(eq(TENANT), eq("pk-1"), eq(WorkerInboundService.ENDPOINT_POST)))
                    .thenReturn(true, false);
            WorkerInboundDraftView replay = new WorkerInboundDraftView();
            replay.setDraftId(draft.getDraftId());
            replay.setStatus(InboundOrder.STATUS_POSTED);
            replay.setReplayed(Boolean.TRUE);
            when(clientRequestIdService.replay(eq(TENANT), eq("pk-1"), eq(WorkerInboundDraftView.class)))
                    .thenReturn(Optional.of(replay));

            service.postDraft(draft.getDraftId(), confirmed(), TENANT, WORKER_ID, "pk-1");
            WorkerInboundDraftView second =
                    service.postDraft(draft.getDraftId(), confirmed(), TENANT, WORKER_ID, "pk-1");

            verify(productSkuMapper, times(1)).receiveStock(anyLong(), any(), any(), anyString());
            verify(stockLedgerService, times(1)).record(anyLong(), anyString(), anyLong(), anyString(),
                    any(), any(), anyString(), anyString(), anyString(), any(), any(), any());
            verify(inboundOrderMapper, times(1)).markPosted(anyString(), anyLong(), anyString(), any());
            assertThat(second.getReplayed()).isTrue();
        }

        @Test
        @DisplayName("已过账再提交（换新幂等键）⇒ 409，不二次加库存（#5045 的条件更新闸）")
        void alreadyPostedIsRejectedByTheExistingCasGuard() {
            WorkerInboundDraftView draft = createDraft("60.5");
            when(inboundOrderMapper.markPosted(anyString(), anyLong(), anyString(), any())).thenReturn(0);
            order.setStatus(InboundOrder.STATUS_POSTED);

            assertThatThrownBy(() -> service.postDraft(draft.getDraftId(), confirmed(), TENANT, WORKER_ID, "pk-2"))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(409));
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString());
        }

        @Test
        @DisplayName("🔴 跨租户 / 非本人草稿 ⇒ 404（不是 403，避免存在性泄露）")
        void foreignDraftLooksLikeNotFound() {
            WorkerInboundDraftView draft = createDraft("60.5");

            // 跨租户：tenant_id 过滤后查不到
            when(inboundOrderMapper.selectOne(any())).thenReturn(null);
            when(inboundOrderMapper.selectList(any())).thenReturn(List.of());
            assertThatThrownBy(() -> service.postDraft(draft.getDraftId(), confirmed(), TENANT, WORKER_ID, null))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));

            // 非本人：单据在、但 created_by 是别人
            when(inboundOrderMapper.selectOne(any())).thenReturn(order);
            order.setCreatedBy("worker-li");
            assertThatThrownBy(() -> service.postDraft(draft.getDraftId(), confirmed(), TENANT, WORKER_ID, null))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(404));

            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString());
        }
    }

    private static WorkerInboundPostRequest confirmedWith(Boolean value) {
        WorkerInboundPostRequest req = new WorkerInboundPostRequest();
        req.setConfirmed(value);
        return req;
    }
}
