package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.InboundOrderCreateRequest;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.dto.WorkerInboundDraftRequest;
import com.migao.admin.dto.WorkerInboundDraftView;
import com.migao.admin.dto.WorkerInboundPostRequest;
import com.migao.admin.dto.WorkerInboundRecognizeRequest;
import com.migao.admin.dto.WorkerInboundRecognizeResponse;
import com.migao.admin.dto.WorkerInboundSkuMatch;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 工人可达的入库服务（issue #5052 <b>P1</b>，设计真值源 {@code docs/design/inbound-photo-and-label.md} §5 / §6 / §9）。
 *
 * <h3>本类只做「载体与校验」——过账逻辑一行都不新造</h3>
 * <p>建草稿与过账**全部**落到 #5045 的 {@link InboundOrderService#create} /
 * {@link InboundOrderService#post}（同一 {@code @Transactional} 语义、同一批次号口径、
 * 同一台账写法）。本类<b>不</b>直接写库存、<b>不</b>落任何台账行、<b>不</b>碰
 * {@code product_skus} 的写方法 —— 设计 §5.3 硬约束 2 / §11.2 N10
 * （判据 = 本类源码里没有库存写入语句，见 {@code WorkerInboundSurfaceGuardTest}）。</p>
 *
 * <h3>三条硬约束的落点</h3>
 * <ol>
 *   <li><b>只表达入库语义</b>：请求 DTO 的字段集就是能力集（无 {@code adjustment} / 无 {@code source}
 *       / 无 {@code operator}）⇒ 设计 §5.3 硬约束 1；</li>
 *   <li><b>复用 #5045 过账</b>：见上；</li>
 *   <li><b>零商家权限码</b>：本类与其控制器**不注入** {@code PermissionInterceptor}、
 *       不带任何 {@code @RequirePermission}（设计 §9.3 红线）。</li>
 * </ol>
 *
 * <h3>幂等（设计 §9.2 的「幂等键」防线）</h3>
 * <p>建草稿与过账都收 {@code Idempotency-Key}，实现**复用** {@link ClientRequestIdService}
 * （issue #4037 的单一实现：占位 / 回放 / 快照 / 陈旧回收四件事只有那一份）：
 * 同键重复 ⇒ <b>不重复执行</b>，回放首次结果（{@code replayed:true}）。</p>
 * <p>为什么不用 V117 的 {@code import_run_id}：它是**运行级**键（同一份期初/迁移导入重跑），
 * 其 javadoc 已写明与「同一 HTTP 请求重放」是两回事；把手机重试键塞进导入审计面会让
 * 「这批基线是哪次导入冻结的」这个问题再也答不准。两者各司其职，不互相冒充。</p>
 * <p>不带键时不报错（老客户端兼容）：此时重复过账由 {@code InboundOrderService.post} 的
 * 条件更新（CAS）闸挡住 —— 库存仍只加一次，只是第二次会得到 409 而不是回放结果。</p>
 *
 * <h3>🔴 号码状态码为什么在工人面被改写成 400</h3>
 * <p>设计 §5.2 逐字要求「负数 / 0 / 超 1 位小数 ⇒ <b>400</b>」「{@code skuId} 不存在或零命中 ⇒
 * <b>400</b>/409」，而 {@code InboundOrderService} 的参数类拒绝统一是 <b>422</b>
 * （{@code BusinessException.validationError}）。<b>口径本体不动</b>（仍是
 * {@code requireItemNumbers} 那一处，文案逐字复用），本类只把**参数类**拒绝的状态码
 * 搬到 400（{@link #asCarrierBadRequest}），使工人面的窄契约与设计单一致。
 * 语义类拒绝（{@code NOT_FOUND} 404 / {@code CONFLICT} 409）**原样上抛，不改判**。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WorkerInboundService {

    /** 建草稿端点的幂等标识（进 {@code client_request_keys.endpoint}，同键跨端点复用时可查）。 */
    public static final String ENDPOINT_DRAFTS = "worker/inbound/drafts";

    /** 过账端点的幂等标识。 */
    public static final String ENDPOINT_POST = "worker/inbound/drafts/post";

    /** 识别路径：前端解码命中（0 次 LLM 调用）。 */
    public static final String PATH_BARCODE = "barcode_decode";

    /** 识别路径：vision 兜底。 */
    public static final String PATH_VISION = "vision";

    /**
     * 入库识别 target —— 与 {@code backend/ai-agent-service/app/vision/targets.py} 的
     * {@code TARGET_FIELDS} 键**逐字同名**（单一真值在 ai-agent 侧：字段表、消歧阈值、
     * {@code [图片识别]} 标注都由它给，Java 侧不复制第二份）。
     */
    static final String TARGET_INBOUND = "inbound";

    /** 一次识别最多 3 张（设计 §9.4 图片上限，沿用现状）。 */
    static final int MAX_IMAGES = 3;

    /** vision 字段表的键（与 {@code targets.py} 的 {@code TargetField.key} 同源）。 */
    private static final String FIELD_PRODUCT_NAME = "product_name";
    private static final String FIELD_COLOR_NAME = "color_name";
    private static final String FIELD_QUANTITY_METERS = "quantity_meters";
    private static final String FIELD_BARCODE = "barcode";

    private static final String MSG_MANUAL_VISION_DEGRADED =
            "照片没能认出可用信息（太暗 / 太模糊 / 图上的字看不清）—— 请重拍一张更清晰的，或直接手工录入品名、色号与米数。系统不会替你猜。";
    private static final String MSG_MANUAL_NO_SKU_MATCH =
            "识别到的品名 + 色号在系统里没有匹配到任何已有货号 —— 请从**已有商品**里人工选择；"
                    + "本系统不会为了这条记录自动新建商品或货号（防 AI 幻觉造出假货号，还带着库存流水）。";

    private final InboundOrderService inboundOrderService;
    private final ImageRecognitionClient imageRecognitionClient;
    private final ClientRequestIdService clientRequestIdService;
    private final ProductMapper productMapper;
    private final ProductSkuMapper productSkuMapper;

    // ============================================================ ① 识别（不落库）

    /**
     * 照片 → 候选字段（<b>不落库、不动库存</b>）。
     *
     * <p>顺序由服务端掌握（设计 §6.2）：① 前端已解码出条码（{@code barcode} 非空）⇒
     * 走 {@link #PATH_BARCODE}，**一次 LLM 都不调**（成本守卫）；② 否则走 vision 兜底
     * （{@link ImageRecognitionClient#recognize} → ai-agent
     * {@code POST /api/internal/vision/recognize}，target 固定 {@code inbound}）。</p>
     *
     * <p>两条路径共同的三条：<b>零命中不建品</b>（只在既有 {@code product_skus} 里查）、
     * <b>不确定就不预填</b>（降级时候选一律 null）、<b>任何情况下不返回凭空构造的 SKU</b>。</p>
     */
    public WorkerInboundRecognizeResponse recognize(WorkerInboundRecognizeRequest req, Long tenantId) {
        List<String> images = validImages(req);
        String barcode = req == null ? null : trimToNull(req.getBarcode());

        WorkerInboundRecognizeResponse resp = new WorkerInboundRecognizeResponse();
        resp.setSkuMatches(new ArrayList<>());
        resp.setFields(new ArrayList<>());
        resp.setBarcode(barcode);

        if (barcode != null) {
            // ① 解码优先：条码原文 → 按货号精确匹配既有 SKU。零 LLM 调用（可断言远端调用次数 = 0）
            resp.setPath(PATH_BARCODE);
            resp.setSkuMatches(matchesBySkuCode(barcode, tenantId));
            resp.setRequiresManualEntry(resp.getSkuMatches().isEmpty());
            resp.setMessage(resp.getSkuMatches().isEmpty()
                    ? "扫到的条码在系统里没有对应的货号 —— 请人工录入，或从已有商品里选择（不会自动建品）。"
                    : "条码命中已有货号，请核对后填写米数。");
            log.info("[工人入库] 解码优先路径（未调用 LLM）: tenant={}, 命中={}",
                    tenantId, resp.getSkuMatches().size());
            return resp;
        }

        // ② vision 兜底（唯一的 LLM 调用点；target 由服务端固定，客户端不可选）
        ImageRecognitionClient.ImageRecognitionResult result =
                imageRecognitionClient.recognize(TARGET_INBOUND, images);
        resp.setPath(PATH_VISION);
        resp.setDegraded(result.degraded());
        resp.setFields(result.fields());

        if (result.degraded()) {
            // 不确定 ⇒ 不预填（设计 §6.4 / §11.1 第 8 条）：候选一个都不给，只给可行动提示
            resp.setRequiresManualEntry(true);
            resp.setMessage(MSG_MANUAL_VISION_DEGRADED);
            return resp;
        }

        String productName = fieldValue(result.fields(), FIELD_PRODUCT_NAME);
        String colorName = fieldValue(result.fields(), FIELD_COLOR_NAME);
        resp.setProductName(productName);
        resp.setColorName(colorName);
        resp.setQuantityMeters(fieldValue(result.fields(), FIELD_QUANTITY_METERS));
        if (resp.getBarcode() == null) {
            resp.setBarcode(fieldValue(result.fields(), FIELD_BARCODE));
        }

        // ③ SKU 匹配门禁（设计 §6.3）：品名 + 色号必须命中既有 product_skus；零命中 ⇒ 拒绝入库、不自动建品
        resp.setSkuMatches(matchesByNameAndColor(productName, colorName, tenantId));
        resp.setRequiresManualEntry(resp.getSkuMatches().isEmpty());
        if (resp.getSkuMatches().isEmpty()) {
            resp.setMessage(MSG_MANUAL_NO_SKU_MATCH);
        } else if (resp.getSkuMatches().size() == 1) {
            resp.setMessage("已匹配到 1 个已有货号，请核对品名、色号与米数后提交。");
        } else {
            resp.setMessage("匹配到多个已有货号，请工人确认是哪一个（服务端不替工人猜）。");
        }
        return resp;
    }

    // ============================================================ ② 建草稿（不动库存）

    /**
     * 建入库单草稿（<b>草稿态完全不动库存</b>，与 #5045 逐字同语义）。
     *
     * <p>请求体没有 {@code source} ⇒ {@link InboundOrderCreateRequest#getSource()} 恒为 {@code null}
     * ⇒ {@code normalizeSource} 归一为 {@code purchase}（V117 的
     * {@code ck_inbound_orders_source} 只认 purchase / opening，不新增取值、不需要迁移）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public WorkerInboundDraftView createDraft(WorkerInboundDraftRequest req, Long tenantId,
                                              String operator, String idempotencyKey) {
        if (req == null || req.getSkuId() == null || !StringUtils.hasText(req.getProductId())) {
            // 零命中匹配的落法：工人**结构上**只能提交一个既有 skuId —— 没有 skuId 就没有草稿，
            // 也就不存在「服务端顺手建一个」的路径（设计 §6.3）
            throw BusinessException.validationError(
                    "入库草稿需要 productId 与 skuId：请先识别（或人工）选定**已有**商品与货号，"
                            + "系统不会自动新建商品/SKU");
        }
        if (!clientRequestIdService.claim(tenantId, idempotencyKey, ENDPOINT_DRAFTS)) {
            return replay(tenantId, idempotencyKey, "入库单草稿");
        }
        try {
            InboundOrderResponse created = inboundOrderService.create(toCreateRequest(req), tenantId, operator);
            WorkerInboundDraftView view = viewOf(created);
            clientRequestIdService.complete(tenantId, idempotencyKey, view);
            log.info("[工人入库] 草稿已建（未动库存）: tenant={}, inboundNo={}, skuId={}, operator={}",
                    tenantId, created.getInboundNo(), req.getSkuId(), operator);
            return view;
        } catch (BusinessException e) {
            throw asCarrierBadRequest(e);
        }
    }

    // ============================================================ ③ 过账（过账才动库存）

    /**
     * 提交过账（<b>过账才动库存</b>；过账本体 = {@link InboundOrderService#post}）。
     *
     * <p>三道闸，顺序即安全顺序：① <b>人工确认</b>（缺标记 ⇒ 409，一行库存都不动）；
     * ② <b>本人本租户</b>（非本租户 / 非本人 ⇒ <b>404</b> —— 不用 403，避免存在性泄露，
     * 设计 §5.2 逐字）；③ <b>幂等键</b>（同键 ⇒ 回放，不重复加库存）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public WorkerInboundDraftView postDraft(String draftId, WorkerInboundPostRequest req, Long tenantId,
                                            String operator, String idempotencyKey) {
        if (req == null || !Boolean.TRUE.equals(req.getConfirmed())) {
            // 未确认不落库（设计 §6.5 / §11.1 第 5 条）：服务端必须能区分「有确认」与「无确认」的提交，
            // 而不是靠前端按钮形态。此处必须早于任何读写 —— 未确认的请求不该占幂等键、更不该碰单据。
            throw BusinessException.conflict(
                    "未收到人工确认标记，本次过账未执行（未确认不落库）",
                    "请工人核对品名 / 色号 / 米数后，带 confirmed=true 重新提交");
        }
        requireOwnDraft(draftId, tenantId, operator);
        if (!clientRequestIdService.claim(tenantId, idempotencyKey, ENDPOINT_POST)) {
            return replay(tenantId, idempotencyKey, "入库单过账");
        }
        try {
            InboundOrderResponse posted = inboundOrderService.post(draftId, tenantId, operator);
            WorkerInboundDraftView view = viewOf(posted);
            clientRequestIdService.complete(tenantId, idempotencyKey, view);
            log.info("[工人入库] 过账完成: tenant={}, inboundNo={}, operator={}",
                    tenantId, posted.getInboundNo(), operator);
            return view;
        } catch (BusinessException e) {
            throw asCarrierBadRequest(e);
        }
    }

    // ============================================================ 内部

    /** 请求里的有效图片 URL（保序、去空）；张数 1~3 之外 ⇒ 400（设计 §5.2 拒绝口径）。 */
    private static List<String> validImages(WorkerInboundRecognizeRequest req) {
        List<String> raw = req == null ? null : req.getImages();
        List<String> images = new ArrayList<>();
        if (raw != null) {
            for (String url : raw) {
                if (StringUtils.hasText(url)) {
                    images.add(url.trim());
                }
            }
        }
        if (images.isEmpty()) {
            throw new BusinessException("INBOUND_RECOGNIZE_NO_IMAGE",
                    "请至少上传 1 张照片（上游标签 / 布卷包装）", 400,
                    "拍照后先上传拿 URL，再把 URL 列表传给 images。系统不会拿空列表去问模型（那只会白烧一次 vision 调用）。");
        }
        if (images.size() > MAX_IMAGES) {
            throw new BusinessException("INBOUND_RECOGNIZE_TOO_MANY_IMAGES",
                    "一次最多上传 " + MAX_IMAGES + " 张照片（收到 " + images.size() + " 张）", 400,
                    "请只保留最能看清标签的那几张（最多 " + MAX_IMAGES + " 张）再上传。");
        }
        // ⚠️ 刻意**不**在 Java 侧预筛 URL 格式：无效 URL 由 ai-agent 的
        // `vision.pipeline.normalize_image_urls` 统一过滤 + CDN 重写（既有
        // ImageRecognitionController 的同一取舍）—— 两处各筛一次必然漂移。
        return images;
    }

    /** 取字段表里某一格的值（字段表由 ai-agent 给，Java 侧只读不重建）。 */
    private static String fieldValue(List<Map<String, Object>> fields, String key) {
        if (fields == null) {
            return null;
        }
        for (Map<String, Object> field : fields) {
            if (field != null && key.equals(field.get("key"))) {
                Object value = field.get("value");
                return value == null ? null : trimToNull(String.valueOf(value));
            }
        }
        return null;
    }

    /**
     * 按**货号**精确匹配既有 SKU（解码路径）：{@code product_skus.sku_code == 条码原文}。
     * 零命中 ⇒ 空列表（**不建品、不猜**）。
     */
    private List<WorkerInboundSkuMatch> matchesBySkuCode(String skuCode, Long tenantId) {
        List<ProductSku> skus = productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .eq(ProductSku::getSkuCode, skuCode));
        return toMatches(skus, tenantId);
    }

    /**
     * SKU 匹配门禁（设计 §6.3）：**品名 + 色号**必须命中既有 {@code product_skus}。
     *
     * <p>品名在 {@code products.name}（SKU 表没有名字列）、色号在 {@code product_skus.color_name}
     * ⇒ 两次查询（都在本租户内）。零命中 ⇒ 空列表：<b>拒绝入库、不自动建品</b>
     * —— 防的是「AI 幻觉造出的假 SKU 带着库存流水进系统，且没有任何东西会变红」。</p>
     */
    private List<WorkerInboundSkuMatch> matchesByNameAndColor(String productName, String colorName, Long tenantId) {
        if (!StringUtils.hasText(productName) || !StringUtils.hasText(colorName)) {
            return new ArrayList<>();
        }
        List<Product> products = productMapper.selectList(new LambdaQueryWrapper<Product>()
                .eq(Product::getTenantId, tenantId)
                .eq(Product::getName, productName));
        if (products.isEmpty()) {
            return new ArrayList<>();
        }
        List<String> productIds = new ArrayList<>();
        for (Product product : products) {
            productIds.add(product.getId());
        }
        List<ProductSku> skus = productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                .eq(ProductSku::getTenantId, tenantId)
                .eq(ProductSku::getColorName, colorName)
                .in(ProductSku::getProductId, productIds));
        return toMatches(skus, tenantId);
    }

    /** 实读行 → 响应行（名字取自 {@code products}，一次查询；**不构造任何 SKU**） */
    private List<WorkerInboundSkuMatch> toMatches(List<ProductSku> skus, Long tenantId) {
        List<WorkerInboundSkuMatch> matches = new ArrayList<>();
        if (skus == null || skus.isEmpty()) {
            return matches;
        }
        Map<String, String> nameById = new LinkedHashMap<>();
        List<String> productIds = new ArrayList<>();
        for (ProductSku sku : skus) {
            if (sku.getProductId() != null && !nameById.containsKey(sku.getProductId())) {
                nameById.put(sku.getProductId(), null);
                productIds.add(sku.getProductId());
            }
        }
        if (!productIds.isEmpty()) {
            for (Product product : productMapper.selectList(new LambdaQueryWrapper<Product>()
                    .eq(Product::getTenantId, tenantId)
                    .in(Product::getId, productIds))) {
                nameById.put(product.getId(), product.getName());
            }
        }
        for (ProductSku sku : skus) {
            WorkerInboundSkuMatch match = new WorkerInboundSkuMatch();
            match.setSkuId(sku.getId());
            match.setProductId(sku.getProductId());
            match.setProductName(nameById.get(sku.getProductId()));
            match.setSkuCode(sku.getSkuCode());
            match.setColorName(sku.getColorName());
            match.setDoorWidth(sku.getDoorWidth());
            match.setStock(sku.getStock());
            matches.add(match);
        }
        return matches;
    }

    /** 工人面请求 → #5045 的建单请求（**一次一行**：一个入库单行 = 一个 SKU）。 */
    private static InboundOrderCreateRequest toCreateRequest(WorkerInboundDraftRequest req) {
        InboundOrderCreateRequest create = new InboundOrderCreateRequest();
        create.setSupplier(trimToNull(req.getSupplier()));
        create.setSupplierDocNo(trimToNull(req.getSupplierDocNo()));
        create.setWarehouse(trimToNull(req.getWarehouse()));
        create.setRemark(trimToNull(req.getRemark()));
        // 🔴 source / importRunId 一律不设：工人面**结构上**没有这两个键 ⇒ 归一为 purchase（V117 口径）
        InboundOrderCreateRequest.Item item = new InboundOrderCreateRequest.Item();
        item.setProductId(req.getProductId());
        item.setSkuId(req.getSkuId());
        item.setQuantity(req.getQuantity());
        item.setUnitCost(req.getUnitCost());
        item.setDyeLot(trimToNull(req.getDyeLot()));
        item.setRollLengthM(req.getRollLengthM());
        create.setItems(List.of(item));
        return create;
    }

    /** 入库单 → 工人面视图（两个端点同一形状；{@code needsConfirmation} 只对草稿为 true）。 */
    private static WorkerInboundDraftView viewOf(InboundOrderResponse order) {
        WorkerInboundDraftView view = new WorkerInboundDraftView();
        view.setDraftId(order.getId());
        view.setInboundNo(order.getInboundNo());
        view.setStatus(order.getStatus());
        view.setSource(order.getSource());
        view.setNeedsConfirmation(InboundOrder.STATUS_DRAFT.equals(order.getStatus()));
        List<WorkerInboundDraftView.Line> lines = new ArrayList<>();
        if (order.getItems() != null) {
            for (InboundOrderResponse.Item item : order.getItems()) {
                WorkerInboundDraftView.Line line = new WorkerInboundDraftView.Line();
                line.setSkuId(item.getSkuId());
                line.setSkuCode(item.getSkuCode());
                line.setQuantity(item.getQuantity());
                line.setBatchNo(item.getBatchNo());
                lines.add(line);
            }
        }
        view.setItems(lines);
        return view;
    }

    /**
     * 草稿必须是**本租户 + 本人**创建的，否则 <b>404</b>（设计 §5.2 逐字：跨租户 ⇒ 404 而不是 403，
     * 避免存在性泄露）。租户这一半由 {@code detail(rawId, tenantId)} 的查询承担；
     * 本人这一半在这里判（{@code created_by} = 建单时的工人身份）。
     */
    private void requireOwnDraft(String draftId, Long tenantId, String operator) {
        InboundOrderResponse draft = inboundOrderService.detail(draftId, tenantId);
        if (operator == null || !operator.equals(draft.getCreatedBy())) {
            log.warn("[工人入库] 非本人草稿，按不存在处理（404，不泄露存在性）: tenant={}, operator={}, inboundNo={}",
                    tenantId, operator, draft.getInboundNo());
            throw BusinessException.notFound("入库单", "请在自己的设备上重新建单并提交（入库单只能由建单本人过账）");
        }
    }

    /** 幂等回放（同键重复 ⇒ 不重复执行、回同结果；占位在飞 ⇒ fail-closed 409，绝不回空结果）。 */
    private WorkerInboundDraftView replay(Long tenantId, String idempotencyKey, String what) {
        return clientRequestIdService.replay(tenantId, idempotencyKey, WorkerInboundDraftView.class)
                .orElseThrow(() -> new BusinessException("IDEMPOTENT_REPLAY_EMPTY",
                        "同一 Idempotency-Key 的「" + what + "」已受理但无可回放结果", 409,
                        "请勿重复提交；请先用查询接口确认结果"));
    }

    /**
     * 把**参数类**拒绝从 422 改写成 400（设计 §5.2 的工人面窄契约）。
     * 语义类拒绝（404 / 409 / 401）**原样上抛**——状态码本身是判据，不许被顺手改掉。
     */
    private static BusinessException asCarrierBadRequest(BusinessException e) {
        if (!"VALIDATION_ERROR".equals(e.getCode())) {
            return e;
        }
        return new BusinessException(e.getCode(), e.getMessage(), 400, e.getSuggestion());
    }

    private static String trimToNull(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }
}
