// case_ids: PR-110, PR-111, PR-112
package com.migao.admin.controller;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.config.GlobalExceptionHandler;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.InboundOrderItem;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.entity.StockBatch;
import com.migao.admin.mapper.InboundOrderItemMapper;
import com.migao.admin.mapper.InboundOrderMapper;
import com.migao.admin.mapper.InboundOrderQueryMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.migao.admin.mapper.StockBatchMapper;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ImageRecognitionClient;
import com.migao.admin.service.InboundOrderService;
import com.migao.admin.service.StockLedgerService;
import com.migao.admin.service.WorkerInboundService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人入库端点的 <b>HTTP 层</b>契约（issue #5052 P1，设计 §5.2）—— 三端点 × 状态码。
 *
 * <p>与 {@link com.migao.admin.service.WorkerInboundServiceTest} 的分工：那边钉**副作用**
 * （台账一行 / 不建品 / 不调 LLM / 幂等不加两次库存），本类钉**线上可观察的状态码**
 * （401 / 400 / 409 / 404）与**身份与幂等键的载体**（头 → 服务端解身份，body 不参与）。
 * 两处都不改用例强度。</p>
 *
 * <p>🔴 无工人 session ⇒ 401 是本包的第一道门（设计 §5.2 拒绝口径第一行）：工人路径上
 * 「谁」只有 {@code X-Worker-Session-Id} 一个来源，因此控制器**必须显式判空**，
 * 而不是「调了 resolveIdentity 就算」（不判空时端点会 200，见
 * {@code WorkerProductionController} 的既有注释）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("WorkerInboundController（#5052 P1）：状态码与身份载体")
class WorkerInboundControllerTest {

    @Mock private InboundOrderMapper inboundOrderMapper;
    @Mock private InboundOrderItemMapper inboundOrderItemMapper;
    @Mock private InboundOrderQueryMapper inboundOrderQueryMapper;
    @Mock private StockBatchMapper stockBatchMapper;
    @Mock private ProductSkuMapper productSkuMapper;
    @Mock private ProductMapper productMapper;
    @Mock private StockLedgerService stockLedgerService;
    @Mock private ImageRecognitionClient imageRecognitionClient;
    @Mock private ClientRequestIdService clientRequestIdService;
    @Mock private WorkerSessionService workerSessionService;

    private MockMvc mockMvc;

    private static final Long TENANT = 1L;
    private static final String SESSION = "sess-zhang-1";

    @BeforeEach
    void setUp() {
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(assistant, Product.class);
        TableInfoHelper.initTableInfo(assistant, ProductSku.class);
        TableInfoHelper.initTableInfo(assistant, InboundOrder.class);
        TableInfoHelper.initTableInfo(assistant, InboundOrderItem.class);
        TableInfoHelper.initTableInfo(assistant, StockBatch.class);

        TenantContext.setTenantId(TENANT);
        // 跨租户 / 不存在的单据：租户过滤后查不到（本类只用这一条读路径）
        when(inboundOrderMapper.selectOne(any())).thenReturn(null);
        when(inboundOrderMapper.selectList(any())).thenReturn(List.of());
        when(clientRequestIdService.claim(anyLong(), any(), anyString())).thenReturn(true);

        InboundOrderService inboundOrderService = new InboundOrderService(
                inboundOrderMapper, inboundOrderItemMapper, inboundOrderQueryMapper,
                stockBatchMapper, productSkuMapper, productMapper, stockLedgerService);
        WorkerInboundService service = new WorkerInboundService(inboundOrderService, imageRecognitionClient,
                clientRequestIdService, productMapper, productSkuMapper);
        WorkerInboundController controller = new WorkerInboundController(service, workerSessionService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    private void loginAsZhang() {
        when(workerSessionService.resolveIdentity(SESSION))
                .thenReturn(new WorkerIdentity("worker-zhang", "张三",
                        WorkerIdentity.SOURCE_SERVER_SESSION, SESSION));
    }

    private static final String DRAFT_BODY =
            "{\"productId\":\"P-1\",\"skuId\":10,\"quantity\":-1}";

    // ============================================================ ① 无 session ⇒ 401（三端点）

    @Test
    @DisplayName("🔴 三个端点都要求有效工人 session：无 / 过期 ⇒ 401（fail-closed，不是 200）")
    void everyEndpointRequiresAWorkerSession() throws Exception {
        when(workerSessionService.resolveIdentity(any())).thenReturn(null);

        mockMvc.perform(post("/api/worker/inbound/recognize")
                        .contentType(MediaType.APPLICATION_JSON).content("{\"images\":[\"https://a/b.jpg\"]}"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(post("/api/worker/inbound/drafts")
                        .contentType(MediaType.APPLICATION_JSON).content(DRAFT_BODY))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(post("/api/worker/inbound/drafts/draft-1/post")
                        .contentType(MediaType.APPLICATION_JSON).content("{\"confirmed\":true}"))
                .andExpect(status().isUnauthorized());

        verify(imageRecognitionClient, never()).recognize(any(), any());
        verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
    }

    // ============================================================ ② 状态码契约

    @Test
    @DisplayName("🔴 负数数量 ⇒ 400（设计 §5.2 的工人面窄契约；口径本体仍是 #5063 那一处）")
    void negativeQuantityIsABadRequest() throws Exception {
        loginAsZhang();

        mockMvc.perform(post("/api/worker/inbound/drafts")
                        .header(WorkerSessionService.SESSION_HEADER, SESSION)
                        .contentType(MediaType.APPLICATION_JSON).content(DRAFT_BODY))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("VALIDATION_ERROR"));

        verify(inboundOrderMapper, never()).insert(any(InboundOrder.class));
    }

    @Test
    @DisplayName("🔴 未确认（缺人工确认标记）就提交 ⇒ 409，过账一步都没走")
    void unconfirmedPostIsAConflict() throws Exception {
        loginAsZhang();
        when(inboundOrderMapper.selectOne(any())).thenReturn(ownedDraft());

        mockMvc.perform(post("/api/worker/inbound/drafts/draft-1/post")
                        .header(WorkerSessionService.SESSION_HEADER, SESSION)
                        .contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("CONFLICT"));

        verify(inboundOrderMapper, never()).markPosted(anyString(), anyLong(), anyString(), any());
    }

    @Test
    @DisplayName("🔴 非本租户 / 非本人草稿 ⇒ 404（不是 403，避免存在性泄露）")
    void foreignDraftIsNotFoundNotForbidden() throws Exception {
        loginAsZhang();

        mockMvc.perform(post("/api/worker/inbound/drafts/other-tenant-draft/post")
                        .header(WorkerSessionService.SESSION_HEADER, SESSION)
                        .contentType(MediaType.APPLICATION_JSON).content("{\"confirmed\":true}"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error.code").value("NOT_FOUND"));

        verify(inboundOrderMapper, never()).markPosted(anyString(), anyLong(), anyString(), any());
    }

    // ============================================================ ③ 身份与幂等键的载体

    @Test
    @DisplayName("身份只来自 X-Worker-Session-Id：body 里塞 operator/workerId/tenantId 也不被读取")
    void identityComesFromTheSessionHeaderOnly() throws Exception {
        loginAsZhang();
        when(inboundOrderMapper.selectOne(any())).thenReturn(ownedDraft());
        when(inboundOrderMapper.markPosted(anyString(), anyLong(), anyString(), any())).thenReturn(1);
        when(inboundOrderItemMapper.selectList(any())).thenReturn(List.of(ownedDraftLine()));
        when(productSkuMapper.selectById(anyLong())).thenReturn(ownedSku());
        when(stockBatchMapper.exists(any())).thenReturn(false);
        when(stockBatchMapper.insert(any(StockBatch.class))).thenReturn(1);
        when(productSkuMapper.selectList(any())).thenReturn(List.of(ownedSku()));
        when(productMapper.updateById(any(Product.class))).thenReturn(1);

        mockMvc.perform(post("/api/worker/inbound/drafts/draft-1/post")
                        .header(WorkerSessionService.SESSION_HEADER, SESSION)
                        .header(WorkerInboundController.IDEMPOTENCY_HEADER, "pk-http-1")
                        .contentType(MediaType.APPLICATION_JSON)
                        // 伪造字段：post 请求 DTO 里根本没有这两个键 ⇒ 连读取代码都没有
                        .content("{\"confirmed\":true,\"operator\":\"worker-li\",\"tenantId\":99}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.status").value(InboundOrder.STATUS_POSTED));

        // 身份取自 session（worker-zhang），不是 body 里的 worker-li；幂等键取自请求头
        verify(clientRequestIdService).claim(eq(TENANT), eq("pk-http-1"), eq(WorkerInboundService.ENDPOINT_POST));
        verify(inboundOrderMapper).markPosted(anyString(), eq(TENANT), eq("worker-zhang"), any());
    }

    private static InboundOrder ownedDraft() {
        return InboundOrder.builder()
                .id("draft-1").tenantId(TENANT).inboundNo("RK-20260926-0001")
                .status(InboundOrder.STATUS_DRAFT).createdBy("worker-zhang").build();
    }

    private static com.migao.admin.entity.InboundOrderItem ownedDraftLine() {
        return InboundOrderItem.builder()
                .id(101L).tenantId(TENANT).inboundOrderId("draft-1")
                .skuId(10L).productId("P-1").skuCode("SKU-001")
                .quantity(new java.math.BigDecimal("60.5")).unitCost(new java.math.BigDecimal("12.5"))
                .build();
    }

    private static ProductSku ownedSku() {
        return ProductSku.builder()
                .id(10L).tenantId(TENANT).productId("P-1").skuCode("SKU-001").colorName("米白")
                .stock(new java.math.BigDecimal("10")).build();
    }
}
