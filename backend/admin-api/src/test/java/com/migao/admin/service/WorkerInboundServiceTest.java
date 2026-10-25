// case_ids: PR-029, PR-030, PR-031, PR-032, PR-110, PR-111, PR-112, FN-006
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.dto.WorkerInboundDraftRequest;
import com.migao.admin.dto.WorkerInboundDraftView;
import com.migao.admin.dto.WorkerInboundPostRequest;
import com.migao.admin.dto.WorkerInboundRecognizeRequest;
import com.migao.admin.dto.WorkerInboundRecognizeResponse;
import com.migao.admin.dto.WorkerInboundSkuMatch;
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
 * <h3>本类钉住的六条（每条都能红）</h3>
 * <ol>
 *   <li><b>草稿不动库存</b>：建草稿**不得**调 {@code receiveStock} / 不得落台账 / 不得写批次；</li>
 *   <li><b>过账才动库存，且台账可对账</b>：一行 {@code reason=inbound}，
 *       {@code after_qty - before_qty == delta == 入库量}；</li>
 *   <li><b>零命中不建品</b>（设计 §6.3）：识别零命中 ⇒ 空匹配；建草稿缺 skuId / skuId 不存在 ⇒ 拒绝，
 *       且 {@code products} / {@code product_skus} 的 insert **零调用**（防 AI 幻觉造出假 SKU 带库存流水）；</li>
 *   <li><b>不确定 ⇒ 不预填</b>（§6.4）：vision 降级 ⇒ 三个候选字段全 null，只给人工录入提示；</li>
 *   <li><b>成本守卫</b>（§6.1）：请求带前端解码的条码 ⇒ {@code ImageRecognitionClient} **零调用**；</li>
 *   <li><b>供应商标签能入库</b>（issue #7759）：型号 {@code 2659-4} 归一后命中 {@code 2659-04} 的两个门幅
 *       （2.8 / 3.2 交工人选）—— 用本条缺陷的**真库读数**做夹具，见 {@code SupplierLabel} 组。</li>
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
        // 批次号取号（issue #6248）= `stockBatchMapper.update(...)` 的**受影响行数**（1 = 号归我）。
        // Mockito 对 int 返回**默认 0** ⇒ 不桩这一句会被读成「号每次都被别人抢走」⇒ 20 次耗尽 409。
        when(stockBatchMapper.update(any(StockBatch.class))).thenReturn(1);
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
        when(productSkuMapper.receiveStock(anyLong(), any(), any(), anyString(), any())).thenAnswer(inv -> {
            BigDecimal q = inv.getArgument(1);
            Map<String, Object> change = new LinkedHashMap<>();
            change.put("beforeQuantity", new BigDecimal("10"));
            change.put("afterQuantity", new BigDecimal("10").add(q));
            return change;
        });

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

    /**
     * 工人面草稿请求（issue #6812 之后的口径）：参数是**每卷米数（卷长）**，卷数恒为工人端默认的 **1**
     * ⇒ 入库米数 = 1 × 卷长。理由：工人拍的是**一卷布**，标签上的米数是这一卷的卷长。
     */
    private static WorkerInboundDraftRequest draftRequest(String rollLengthMeters) {
        WorkerInboundDraftRequest req = new WorkerInboundDraftRequest();
        req.setProductId(PRODUCT_ID);
        req.setSkuId(SKU_ID);
        req.setQuantity(BigDecimal.ONE);
        req.setRollLengthM(rollLengthMeters == null ? null : new BigDecimal(rollLengthMeters));
        req.setUnitCost(new BigDecimal("12.5"));
        req.setSupplierDocNo("DN-20260926-01");
        return req;
    }

    /** 显式给卷数（一张单收多卷 / 非法卷数）时的请求形态。 */
    private static WorkerInboundDraftRequest draftRequestOfRolls(String rollCount, String rollLengthMeters) {
        WorkerInboundDraftRequest req = draftRequest(rollLengthMeters);
        req.setQuantity(rollCount == null ? null : new BigDecimal(rollCount));
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

    /** 真库读数（issue #7759）：一个商品 {@code sku_code=2659}、两个门幅（2.8 / 3.2）。 */
    private static final String REAL_PRODUCT_ID = "P-2659";
    private static final String REAL_PRODUCT_NAME = "奶油风纯色遮光窗帘 桂月白露系列";
    private static final String REAL_PRODUCT_SKU_CODE = "2659";

    private void stubRealSupplierLabelRows() {
        Product product = Product.builder()
                .id(REAL_PRODUCT_ID).tenantId(TENANT)
                .name(REAL_PRODUCT_NAME).skuCode(REAL_PRODUCT_SKU_CODE).build();
        when(productMapper.selectList(any())).thenReturn(List.of(product));
        when(productSkuMapper.selectList(any())).thenReturn(List.of(
                ProductSku.builder().id(28L).tenantId(TENANT).productId(REAL_PRODUCT_ID)
                        .skuCode("2659-04-28").colorName("2659-04 绵绵奶咖").doorWidth("2.8")
                        .stock(new BigDecimal("0")).build(),
                ProductSku.builder().id(32L).tenantId(TENANT).productId(REAL_PRODUCT_ID)
                        .skuCode("2659-04-32").colorName("2659-04 绵绵奶咖").doorWidth("3.2")
                        .stock(new BigDecimal("0")).build()));
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
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
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

    // ============================================================ ①' 供应商标签（issue #7759）

    /**
     * **本条缺陷的真实读数**（云 dev 真库实测，2026-10-25）：
     *
     * | 对象 | 真值 |
     * |---|---|
     * | 供应商标签 | 型号 `2659-4`、品名 `雪尼尔2659-4绵绵奶咖`、色号 `2659-4绵绵奶咖`、52.4 米 |
     * | `products` | `name='奶油风纯色遮光窗帘 桂月白露系列'`、`sku_code='2659'` |
     * | `product_skus` | `2659-04-28`（2.8）/ `2659-04-32`（3.2），`color_name='2659-04 绵绵奶咖'` |
     *
     * <p>门幅口径（用户 2026-10-25 裁定）：「这张图没有展示门幅是多少，按照行业标准就是 2.8 的，
     * 如果是其他规格的门幅会在标签上展示真实门幅数字」⇒ 标签这张图**没印门幅** ⇒ 命中的是该货号
     * **2.8 米那一档**（唯一候选、预选），不是「两个门幅都交工人选」。</p>
     *
     * <p>红证（实跑过，见 PR body 的注入式红证表）：把 {@code normalizeCode} 退化成 {@code trim}、
     * 摘掉 {@code model_no} 这一级、或删掉「默认 2.8」那一段 ⇒ 本组必红。</p>
     */
    @Nested
    @DisplayName("供应商标签（issue #7759）：型号 2659-4 ↔ 货号 2659-04")
    class SupplierLabel {

        @Test
        @DisplayName("🔴 ① 型号 2659-4 + 色号 2659-4绵绵奶咖 + 标签无门幅 ⇒ 命中 2.8 那档（唯一候选、预选）")
        void supplierModelLabelWithoutDoorWidthMatchesTheStandard28() {
            stubRealSupplierLabelRows();
            when(imageRecognitionClient.recognize(eq(WorkerInboundService.TARGET_INBOUND), any()))
                    .thenReturn(vision(List.of(
                            field("model_no", "2659-4"),
                            field("product_name", "雪尼尔2659-4绵绵奶咖"),
                            field("color_name", "2659-4绵绵奶咖"),
                            field("quantity_meters", "52.4"),
                            field("barcode", null)), false));

            WorkerInboundRecognizeResponse resp = service.recognize(recognizeRequest(null, IMAGE_URL), TENANT);

            assertThat(resp.getModelNo()).isEqualTo("2659-4");
            // 唯一候选 ⇒ 前端预选（页面仍要工人勾「我确认」，§6.5 不动）
            assertThat(resp.getSkuMatches()).hasSize(1);
            assertThat(resp.getSkuMatches().get(0).getSkuCode()).isEqualTo("2659-04-28");
            assertThat(resp.getSkuMatches().get(0).getDoorWidth()).isEqualTo("2.8");
            // 门幅是**默认值**补的 ⇒ 服务端如实标出（页面用陈述句说明，不猜也不惊）
            assertThat(resp.isDoorWidthAssumed()).isTrue();
            assertThat(resp.getDoorWidth()).isEqualTo(WorkerInboundService.DEFAULT_DOOR_WIDTH);
            assertThat(resp.isRequiresManualEntry()).isFalse();
        }

        @Test
        @DisplayName("🔴 供应商写法差异（全角 / NO. 前缀 / 空格）⇒ 归一化后照样命中 2 条（去掉归一化 ⇒ 零命中）")
        void fullWidthSupplierSpellingStillMatches() {
            stubRealSupplierLabelRows();
            // 同一块布的另一种写法：全角数字 + 全角连字符 + `NO.` 前缀 + 空格分隔
            when(imageRecognitionClient.recognize(eq(WorkerInboundService.TARGET_INBOUND), any()))
                    .thenReturn(vision(List.of(
                            field("model_no", "NO.２６５９－４"),
                            field("color_name", "２６５９－４ 绵绵奶咖"),
                            field("quantity_meters", "52.4")), false));

            WorkerInboundRecognizeResponse resp = service.recognize(recognizeRequest(null, IMAGE_URL), TENANT);

            assertThat(resp.getSkuMatches()).extracting(WorkerInboundSkuMatch::getSkuCode)
                    .containsExactly("2659-04-28");
        }

        @Test
        @DisplayName("型号命中但色名一条都不中 ⇒ 回该型号下的全部货号（不是零命中，也不替工人挑）")
        void modelHitWithoutColorHitStillReturnsTheModelCandidates() {
            stubRealSupplierLabelRows();
            // 「奶咖灰」在库里不存在：色名这一级 0 命中 ⇒ 降到「型号命中的全部色号」
            assertThat(WorkerInboundService.colorMatches("2659-04 绵绵奶咖", "2659-04奶咖灰")).isFalse();
            when(imageRecognitionClient.recognize(eq(WorkerInboundService.TARGET_INBOUND), any()))
                    .thenReturn(vision(List.of(
                            field("model_no", "2659-4"),
                            field("product_name", "雪尼尔2659-4绵绵奶咖"),
                            field("color_name", "2659-4奶咖灰"),
                            field("door_width", "3.2"),
                            field("quantity_meters", "52.4")), false));

            WorkerInboundRecognizeResponse resp = service.recognize(recognizeRequest(null, IMAGE_URL), TENANT);

            // 色名一条都不中 ⇒ 降到「型号命中的全部货号」，再按写明的门幅 3.2 取档
            assertThat(resp.getSkuMatches()).extracting(WorkerInboundSkuMatch::getSkuCode)
                    .containsExactly("2659-04-32");
        }

        @Test
        @DisplayName("🔴 归一化是纯函数：全角 / 分隔符 / NO. 前缀 / 补零 / 空白 都归到同一形态")
        void normalizationCollapsesEverySupplierSpelling() {
            for (String spelling : List.of("2659-4", "2659—4", "2659－4", " 2659 - 4 ", "NO.2659-4",
                    "２６５９－４", "2659*4", "2659·4")) {
                assertThat(WorkerInboundService.normalizeCode(spelling))
                        .as("写法 %s 没有归一到 2659-04", spelling)
                        .isEqualTo("2659-04");
            }
            // 库里的色号写法（带空格）与图上写法（连写）归一到同一形态
            assertThat(WorkerInboundService.normalizeCode("2659-04 绵绵奶咖"))
                    .isEqualTo(WorkerInboundService.normalizeCode("2659-4绵绵奶咖"));
            assertThat(WorkerInboundService.productCodeOf("2659-04")).isEqualTo("2659");
            assertThat(WorkerInboundService.colorTokenOf("2659-04绵绵奶咖")).isEqualTo("绵绵奶咖");
            // 空白 / 全空白 ⇒ null（不参与匹配，也不拿空串去查库）
            assertThat(WorkerInboundService.normalizeCode("   ")).isNull();
            assertThat(WorkerInboundService.normalizeCode(null)).isNull();
        }

        @Test
        @DisplayName("🔴 型号键只按「段前缀」命中：2659-05 不得吃进 2659-04 的货号（仍绝不猜）")
        void modelKeyDoesNotBleedAcrossColourNumbers() {
            assertThat(WorkerInboundService.modelMatchesProduct("2659", "2659-04")).isTrue();
            assertThat(WorkerInboundService.modelMatchesProduct("2659-04", "2659-04")).isTrue();
            // 反向（型号说到 `-04`、商品货号只到 `2659`）由 `productCodeOf` 的第一段负责，不是靠前缀放宽
            assertThat(WorkerInboundService.productCodeOf("2659-04")).isEqualTo("2659");
            // 型号只到 `2659` 时**不**去猜 `2659-04` 的货号（商品侧更细 = 标签没说的信息，不补）
            assertThat(WorkerInboundService.modelMatchesProduct("2659-04", "2659")).isFalse();
            assertThat(WorkerInboundService.modelMatchesProduct("2659-05", "2659-04")).isFalse();
            assertThat(WorkerInboundService.modelMatchesProduct("26590", "2659-04")).isFalse();
            assertThat(WorkerInboundService.colorMatches("2659-04 绵绵奶咖", "绵绵奶咖")).isTrue();
            assertThat(WorkerInboundService.colorMatches("2659-04 绵绵奶咖", "奶咖")).isTrue();
            assertThat(WorkerInboundService.colorMatches("2659-04 绵绵奶咖", "奶咖灰")).isFalse();
        }

        @Test
        @DisplayName("零命中仍拒绝入库：三个键全对不上 ⇒ 空匹配 + 不建品（红线不动）")
        void nothingMatchesStillRefusesToCreateAnything() {
            when(productMapper.selectList(any())).thenReturn(List.of());
            when(productSkuMapper.selectList(any())).thenReturn(List.of());
            when(imageRecognitionClient.recognize(any(), any()))
                    .thenReturn(vision(List.of(
                            field("model_no", "9999-1"),
                            field("product_name", "雪尼尔2659-4绵绵奶咖"),
                            field("color_name", "2659-4绵绵奶咖"),
                            field("quantity_meters", "52.4")), false));

            WorkerInboundRecognizeResponse resp = service.recognize(recognizeRequest(null, IMAGE_URL), TENANT);

            assertThat(resp.getSkuMatches()).isEmpty();
            assertThat(resp.isRequiresManualEntry()).isTrue();
            verify(productMapper, never()).insert(any(Product.class));
            verify(productSkuMapper, never()).insert(any(ProductSku.class));
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
        }

        @Test
        @DisplayName("只读搜索：按货号 / 色名都能搜到既有货号；空白与单字 ⇒ 400（不去扫全表）")
        void readOnlySearchFindsExistingSkus() {
            stubRealSupplierLabelRows();

            assertThat(service.searchSkus("2659", TENANT))
                    .extracting(WorkerInboundSkuMatch::getSkuCode)
                    .containsExactly("2659-04-28", "2659-04-32");
            assertThat(service.searchSkus("绵绵奶咖", TENANT)).hasSize(2);

            for (String blank : List.of("", "   ", "布")) {
                assertThatThrownBy(() -> service.searchSkus(blank, TENANT))
                        .isInstanceOf(BusinessException.class)
                        .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(400));
            }
            // 只读：搜索不得写任何东西
            verify(productMapper, never()).insert(any(Product.class));
            verify(productSkuMapper, never()).insert(any(ProductSku.class));
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
        }
    }

    // ============================================================ ①'' 门幅口径（用户 2026-10-25 裁定）

    /**
     * **门幅口径**（用户 2026-10-25 逐字裁定：「这张图没有展示门幅是多少，按照行业标准就是 2.8 的，
     * 如果是其他规格的门幅会在标签上展示真实门幅数字」）。
     *
     * <p>规则一句话：**标签写了就以标签为准；没印就按 2.8；写了库里没有 ⇒ 零命中，绝不回落。**</p>
     *
     * <p>红证（实跑过）：删掉 {@code selectByDoorWidth} 里「没写门幅就用默认值」的那一句
     * ⇒ 默认门幅那两条用例当场红（命中数 1 → 2、{@code doorWidthAssumed} 恒 false）。</p>
     */
    @Nested
    @DisplayName("门幅口径（issue #7759 用户裁定 2026-10-25）")
    class DoorWidthRule {

        private WorkerInboundRecognizeResponse recognizeWith(String doorWidth) {
            stubRealSupplierLabelRows();
            List<Map<String, Object>> fields = new ArrayList<>();
            fields.add(field("model_no", "2659-4"));
            fields.add(field("color_name", "2659-4绵绵奶咖"));
            if (doorWidth != null) {
                fields.add(field("door_width", doorWidth));
            }
            when(imageRecognitionClient.recognize(eq(WorkerInboundService.TARGET_INBOUND), any()))
                    .thenReturn(vision(fields, false));
            return service.recognize(recognizeRequest(null, IMAGE_URL), TENANT);
        }

        @Test
        @DisplayName("① 标签没印门幅 ⇒ 按行业标准 2.8 取档（唯一候选、预选，页面仍要工人确认）")
        void missingDoorWidthUsesTheIndustryStandard() {
            WorkerInboundRecognizeResponse resp = recognizeWith(null);

            assertThat(resp.getSkuMatches()).hasSize(1);
            assertThat(resp.getSkuMatches().get(0).getSkuCode()).isEqualTo("2659-04-28");
            assertThat(resp.isDoorWidthAssumed()).isTrue();
            assertThat(resp.getDoorWidth()).isEqualTo(WorkerInboundService.DEFAULT_DOOR_WIDTH);
            assertThat(resp.isRequiresManualEntry()).isFalse();
        }

        @Test
        @DisplayName("② 标签写了 3.2 ⇒ 只取 3.2 那档（不因为 2.8 是默认值就取 2.8）")
        void writtenDoorWidthWins() {
            WorkerInboundRecognizeResponse resp = recognizeWith("3.2");

            assertThat(resp.getSkuMatches()).hasSize(1);
            assertThat(resp.getSkuMatches().get(0).getSkuCode()).isEqualTo("2659-04-32");
            assertThat(resp.getSkuMatches().get(0).getDoorWidth()).isEqualTo("3.2");
            assertThat(resp.isDoorWidthAssumed()).isFalse();
            assertThat(resp.getDoorWidth()).isEqualTo("3.2");
        }

        @Test
        @DisplayName("③ 标签写了库里没有的 3.5 ⇒ 零命中且**不回落** 2.8（回落 = 替工人猜）")
        void unknownWrittenDoorWidthNeverFallsBackToTheDefault() {
            WorkerInboundRecognizeResponse resp = recognizeWith("3.5");

            assertThat(resp.getSkuMatches()).isEmpty();
            assertThat(resp.isRequiresManualEntry()).isTrue();
            assertThat(resp.isDoorWidthAssumed()).isFalse();
            // 文案要说清「是门幅对不上」，而不是笼统的「没匹配到货号」
            assertThat(resp.getMessage()).contains("门幅");
            verify(productMapper, never()).insert(any(Product.class));
            verify(productSkuMapper, never()).insert(any(ProductSku.class));
        }

        @Test
        @DisplayName("该商品没有 2.8 档 ⇒ 退回候选交工人选（不得自动换别的门幅，也不得零命中）")
        void missingStandardAisleFallsBackToWorkerChoice() {
            Product product = Product.builder().id(REAL_PRODUCT_ID).tenantId(TENANT)
                    .name(REAL_PRODUCT_NAME).skuCode(REAL_PRODUCT_SKU_CODE).build();
            when(productMapper.selectList(any())).thenReturn(List.of(product));
            // 该客户没建 2.8 档：只有 3.2 / 3.5
            when(productSkuMapper.selectList(any())).thenReturn(List.of(
                    ProductSku.builder().id(32L).tenantId(TENANT).productId(REAL_PRODUCT_ID)
                            .skuCode("2659-04-32").colorName("2659-04 绵绵奶咖").doorWidth("3.2").build(),
                    ProductSku.builder().id(35L).tenantId(TENANT).productId(REAL_PRODUCT_ID)
                            .skuCode("2659-04-35").colorName("2659-04 绵绵奶咖").doorWidth("3.5").build()));
            when(imageRecognitionClient.recognize(eq(WorkerInboundService.TARGET_INBOUND), any()))
                    .thenReturn(vision(List.of(
                            field("model_no", "2659-4"),
                            field("color_name", "2659-4绵绵奶咖")), false));

            WorkerInboundRecognizeResponse resp = service.recognize(recognizeRequest(null, IMAGE_URL), TENANT);

            assertThat(resp.getSkuMatches()).extracting(WorkerInboundSkuMatch::getSkuCode)
                    .containsExactly("2659-04-32", "2659-04-35");
            // 没用上默认值 ⇒ 不许声称「按行业标准 2.8」（那是编的）
            assertThat(resp.isDoorWidthAssumed()).isFalse();
            assertThat(resp.isRequiresManualEntry()).isFalse();
        }

        @Test
        @DisplayName("门幅归一：2.8 / 2.80 / 280 / 280cm / 全角 归到同一档；空白 ⇒ null（不猜）")
        void doorWidthNormalisation() {
            for (String spelling : List.of("2.8", "2.80", "280", "280cm", "280CM", "２．８", " 2.8 米 ")) {
                assertThat(WorkerInboundService.normalizeDoorWidth(spelling))
                        .as("写法 %s 没有归一到 2.8", spelling).isEqualTo("2.8");
            }
            assertThat(WorkerInboundService.normalizeDoorWidth("3.2")).isEqualTo("3.2");
            assertThat(WorkerInboundService.normalizeDoorWidth("")).isNull();
            assertThat(WorkerInboundService.normalizeDoorWidth(null)).isNull();
            assertThat(WorkerInboundService.doorWidthMatches("2.8", "280cm")).isTrue();
            assertThat(WorkerInboundService.doorWidthMatches("2.8", "3.2")).isFalse();
        }
    }

    // ============================================================ ② 建草稿

    @Nested
    @DisplayName("建草稿（草稿态完全不动库存）")
    class CreateDraft {

        @Test
        @DisplayName("🔴 建草稿只写单据与明细：不加库存、不落台账、不写批次、来源恒 photo（工人链强制）")
        void draftNeverTouchesStock() {
            WorkerInboundDraftView view = createDraft("60.5");

            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
            verify(stockLedgerService, never()).record(anyLong(), anyString(), anyLong(), anyString(),
                    any(), any(), anyString(), anyString(), anyString(), any(), any(), any());
            verify(stockBatchMapper, never()).insert(any(StockBatch.class));
            assertThat(view.getStatus()).isEqualTo(InboundOrder.STATUS_DRAFT);
            assertThat(view.getSource()).isEqualTo(InboundOrder.SOURCE_PHOTO);
            assertThat(view.getNeedsConfirmation()).isTrue();
            assertThat(view.getItems()).hasSize(1);
            assertThat(view.getItems().get(0).getBatchNo()).isNull();
            // 工人面视图的「数量」仍是**卷数**（工人核对「我拍了几卷」，issue #6812 / #7709）
            assertThat(view.getItems().get(0).getQuantity()).isEqualByComparingTo("1");
            // 而落库的明细行「数量」**恒为米数**（1 卷 × 60.5 米 = 60.5），卷数进 roll_count
            org.mockito.ArgumentCaptor<InboundOrderItem> persisted =
                    org.mockito.ArgumentCaptor.forClass(InboundOrderItem.class);
            verify(inboundOrderItemMapper).insert(persisted.capture());
            assertThat(persisted.getValue().getQuantity()).isEqualByComparingTo("60.5");
            assertThat(persisted.getValue().getRollCount()).isEqualTo(1);
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
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
        }

        @Test
        @DisplayName("0.5 米的尾料可以如实登记（1 卷 × 0.5 米；下限仍是 > 0，不是 ≥ 1）")
        void halfMeterTailIsAccepted() {
            createDraft("0.5");

            org.mockito.ArgumentCaptor<InboundOrderItem> lineCap =
                    org.mockito.ArgumentCaptor.forClass(InboundOrderItem.class);
            verify(inboundOrderItemMapper).insert(lineCap.capture());
            assertThat(lineCap.getValue().getQuantity())
                    .as("入库米数 = 1 卷 × 0.5 米（issue #7709：数量列恒为米数）")
                    .isEqualByComparingTo("0.5");
            assertThat(lineCap.getValue().getRollCount()).isEqualTo(1);
            assertThat(lineCap.getValue().getRollLengthM()).isEqualByComparingTo("0.5");
        }

        @Test
        @DisplayName("🔴 #6812 拍照单：来源由**服务端**强制 photo，明细行「数量」= 卷数、「卷长」= 每卷米数")
        void photoDraftIsServerForcedWithRollFields() {
            createDraft("67.2");

            org.mockito.ArgumentCaptor<InboundOrder> orderCap =
                    org.mockito.ArgumentCaptor.forClass(InboundOrder.class);
            verify(inboundOrderMapper).insert(orderCap.capture());
            assertThat(orderCap.getValue().getSource())
                    .as("工人链的服务端强制来源：请求体里没有被客户端写入口")
                    .isEqualTo(InboundOrder.SOURCE_PHOTO);

            org.mockito.ArgumentCaptor<InboundOrderItem> lineCap =
                    org.mockito.ArgumentCaptor.forClass(InboundOrderItem.class);
            verify(inboundOrderItemMapper).insert(lineCap.capture());
            assertThat(lineCap.getValue().getQuantity())
                    .as("入库米数 = 1 卷 × 67.2 米（数量列恒为米数）")
                    .isEqualByComparingTo("67.2");
            assertThat(lineCap.getValue().getRollCount()).as("卷数进 roll_count").isEqualTo(1);
            assertThat(lineCap.getValue().getRollLengthM()).isEqualByComparingTo("67.2");
        }

        @Test
        @DisplayName("🔴 #6812 卷数必须是正整数（2.5 / 0 / -1 卷 ⇒ 400）；缺卷长 ⇒ 400（不许按「1 米」入账）")
        void rollCountAndRollLengthAreFailClosed() {
            for (String bad : List.of("2.5", "0", "-1")) {
                assertThatThrownBy(() -> service.createDraft(
                        draftRequestOfRolls(bad, "60"), TENANT, WORKER_ID, null))
                        .as("卷数 %s 必须被拒（400）", bad)
                        .isInstanceOf(BusinessException.class)
                        .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(400));
            }
            assertThatThrownBy(() -> service.createDraft(
                    draftRequestOfRolls("1", null), TENANT, WORKER_ID, null))
                    .as("缺卷长必须被拒 —— 否则「1 卷」会被当成「1 米」真加进库存")
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(400));

            verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
        }

        @Test
        @DisplayName("🔴 #6812 米数不是 0.1 米的整数倍（3 卷 × 0.33 米 = 0.99）⇒ 400，不静默取整")
        void metersOffTenthGranularityAreRejected() {
            assertThatThrownBy(() -> service.createDraft(
                    draftRequestOfRolls("3", "0.33"), TENANT, WORKER_ID, null))
                    .isInstanceOf(BusinessException.class)
                    .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus()).isEqualTo(400));

            verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
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
                    .receiveStock(eq(SKU_ID), eq(new BigDecimal("60.5")), eq(new BigDecimal("12.5")), anyString(), any());
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
        @DisplayName("🔴 #6812 过账按**米数**加库存：2 卷 × 30 米 ⇒ 库存 +60（不是 +2 卷）")
        void photoPostAddsMetersNotRollCount() {
            WorkerInboundDraftView draft = service.createDraft(
                    draftRequestOfRolls("2", "30"), TENANT, WORKER_ID, null);

            service.postDraft(draft.getDraftId(), confirmed(), TENANT, WORKER_ID, null);

            verify(productSkuMapper, times(1))
                    .receiveStock(eq(SKU_ID), eq(new BigDecimal("60")), any(), anyString(), any());
            org.mockito.ArgumentCaptor<BigDecimal> beforeCap =
                    org.mockito.ArgumentCaptor.forClass(BigDecimal.class);
            org.mockito.ArgumentCaptor<BigDecimal> afterCap =
                    org.mockito.ArgumentCaptor.forClass(BigDecimal.class);
            verify(stockLedgerService, times(1)).record(
                    eq(TENANT), eq(PRODUCT_ID), eq(SKU_ID), eq(SKU_CODE),
                    beforeCap.capture(), afterCap.capture(),
                    eq(StockLedger.REASON_INBOUND), eq(draft.getInboundNo()), anyString(),
                    any(), any(), any());
            assertThat(afterCap.getValue().subtract(beforeCap.getValue()))
                    .as("台账 delta 必须是**米数**（卷数 × 卷长），不是卷数")
                    .isEqualByComparingTo("60");
            // issue #7709：明细行的「数量」列存**米数**（2 卷 × 30 米 = 60），卷数进 roll_count
            org.mockito.ArgumentCaptor<InboundOrderItem> lineCap =
                    org.mockito.ArgumentCaptor.forClass(InboundOrderItem.class);
            verify(inboundOrderItemMapper).insert(lineCap.capture());
            assertThat(lineCap.getValue().getQuantity()).isEqualByComparingTo("60");
            assertThat(lineCap.getValue().getRollCount()).isEqualTo(2);
            assertThat(lineCap.getValue().getRollLengthM()).isEqualByComparingTo("30");
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

            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
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

            verify(productSkuMapper, times(1)).receiveStock(anyLong(), any(), any(), anyString(), any());
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
            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
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

            verify(productSkuMapper, never()).receiveStock(anyLong(), any(), any(), anyString(), any());
        }
    }

    private static WorkerInboundPostRequest confirmedWith(Boolean value) {
        WorkerInboundPostRequest req = new WorkerInboundPostRequest();
        req.setConfirmed(value);
        return req;
    }

    // ════════════════ issue #6228：工人面入库单价小数位准入（超 2 位有效小数 ⇒ 拒绝 + 零写入）════════════

    @Test
    @DisplayName("#6228 入库单价 0.005（3 位有效小数）⇒ 400 且 inbound_orders **零写入**（不静默舍成 0.01）")
    void subCentUnitCostIsRejectedWithoutWrites() {
        WorkerInboundDraftRequest req = draftRequest("60.5");
        req.setUnitCost(new BigDecimal("0.005"));

        assertThatThrownBy(() -> service.createDraft(req, TENANT, WORKER_ID, null))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("2 位小数")
                .satisfies(e -> assertThat(((BusinessException) e).getHttpStatus())
                        .as("工人面参数类拒绝的状态码是 400（口径本体仍是 MoneyScale 那一处）")
                        .isEqualTo(400));

        verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
        verify(inboundOrderItemMapper, never()).insert(any(InboundOrderItem.class));
    }

    @Test
    @DisplayName("#6228 正对照 入库单价 12.50（2 位小数）⇒ 建草稿成功且行单价逐字 12.50")
    void twoDecimalUnitCostIsAccepted() {
        WorkerInboundDraftRequest req = draftRequest("60.5");
        req.setUnitCost(new BigDecimal("12.50"));

        WorkerInboundDraftView view = service.createDraft(req, TENANT, WORKER_ID, null);

        assertThat(view.getItems()).hasSize(1);
        org.mockito.ArgumentCaptor<InboundOrderItem> captor =
                org.mockito.ArgumentCaptor.forClass(InboundOrderItem.class);
        verify(inboundOrderItemMapper).insert(captor.capture());
        assertThat(captor.getValue().getUnitCost().toPlainString()).isEqualTo("12.50");
    }
}
