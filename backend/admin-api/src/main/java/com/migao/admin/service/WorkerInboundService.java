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
import com.migao.admin.entity.InboundLabel;
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

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
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

    /**
     * 一次识别最多 3 张（设计 §9.4 图片上限，沿用现状）。
     *
     * <p>public 是**刻意**的（issue #5052 P2）：工人上传端点
     * （{@code WorkerInboundUploadController}）的张数上限必须与识别端点**同一个常量**
     * —— 两处各写一个 3 会在某次「顺手放宽」后漂移（上传放 5 张、识别只收 3 张 = 工人白拍）。</p>
     */
    public static final int MAX_IMAGES = 3;

    /** vision 字段表的键（与 {@code targets.py} 的 {@code TargetField.key} 同源）。 */
    private static final String FIELD_MODEL_NO = "model_no";
    private static final String FIELD_DOOR_WIDTH = "door_width";
    private static final String FIELD_PRODUCT_NAME = "product_name";
    private static final String FIELD_COLOR_NAME = "color_name";
    private static final String FIELD_QUANTITY_METERS = "quantity_meters";
    private static final String FIELD_BARCODE = "barcode";

    private static final String MSG_MANUAL_VISION_DEGRADED =
            "照片没能认出可用信息（太暗 / 太模糊 / 图上的字看不清）—— 请重拍一张更清晰的，或直接手工录入品名、色号与米数。系统不会替你猜。";
    private static final String MSG_MANUAL_NO_SKU_MATCH =
            "识别到的型号 / 品名 / 色号在系统里没有匹配到任何已有货号 —— 可以按货号或色名搜一下已有货号，"
                    + "或让文员先建档。本系统不会为了这条记录自动新建商品或货号（防 AI 幻觉造出假货号，还带着库存流水）。";

    /** 门幅命中不到时的说明（**不回落**默认值 —— 回落就是替工人猜）。 */
    private static final String MSG_MANUAL_NO_SKU_FOR_DOOR_WIDTH =
            "标签上的门幅在系统里没有对应的货号 —— 不能入库（不会拿别的门幅顶替，也不会自动建品）。"
                    + "请核对标签上的门幅数字，或按货号 / 色名搜一下已有货号。";

    /** 按货号 / 色名搜既有货号时一次最多回多少条（搜索是**只读辅助**，不是列表页）。 */
    static final int SEARCH_LIMIT = 20;

    /**
     * **行业标准默认门幅（米）** —— 用户 2026-10-25 裁定逐字：
     * 「这张图没有展示门幅是多少，按照行业标准就是 2.8 的，如果是其他规格的门幅会在标签上展示真实门幅数字」。
     *
     * <p>🔴 <b>只许出现在这一处</b>（前后端不得各写一份）：识别面在图没印门幅时**留空**，
     * 这里才是补默认值的地方；页面上的数字取自识别响应的 {@code doorWidth}。</p>
     */
    public static final String DEFAULT_DOOR_WIDTH = "2.8";

    private final InboundOrderService inboundOrderService;
    private final ImageRecognitionClient imageRecognitionClient;
    private final ClientRequestIdService clientRequestIdService;
    private final ProductMapper productMapper;
    private final ProductSkuMapper productSkuMapper;
    /** 入库标签（P2）：过账成功后**同一事务**为每一行发短码（缺码不画假码 ⇒ 发不出码就连过账一起回滚）。 */
    private final InboundLabelService inboundLabelService;

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

        String doorWidth = normalizeDoorWidth(fieldValue(result.fields(), FIELD_DOOR_WIDTH));
        String modelNo = fieldValue(result.fields(), FIELD_MODEL_NO);
        String productName = fieldValue(result.fields(), FIELD_PRODUCT_NAME);
        String colorName = fieldValue(result.fields(), FIELD_COLOR_NAME);
        resp.setModelNo(modelNo);
        resp.setProductName(productName);
        resp.setColorName(colorName);
        resp.setQuantityMeters(fieldValue(result.fields(), FIELD_QUANTITY_METERS));
        if (resp.getBarcode() == null) {
            resp.setBarcode(fieldValue(result.fields(), FIELD_BARCODE));
        }

        // ③ SKU 匹配门禁（设计 §6.3，issue #7759 改判）：归一化 + 多级降级 + 门幅消歧；
        //    零命中仍拒绝入库、不自动建品
        List<WorkerInboundSkuMatch> matches = matchInboundSkus(modelNo, colorName, doorWidth, tenantId);
        resp.setSkuMatches(matches);
        resp.setRequiresManualEntry(matches.isEmpty());
        if (matches.isEmpty()) {
            // 门幅是「写明了但库里没有」⇒ 单独一句（说清不回落），别让工人以为系统没看懂标签
            resp.setMessage(doorWidth != null ? MSG_MANUAL_NO_SKU_FOR_DOOR_WIDTH : MSG_MANUAL_NO_SKU_MATCH);
            return resp;
        }
        // 标签没印门幅 ⇒ 本次按行业标准默认值取档（用户 2026-10-25 裁定）；页面据此用陈述句说明
        boolean assumed = doorWidth == null && hasOnlyDoorWidth(matches, DEFAULT_DOOR_WIDTH);
        resp.setDoorWidthAssumed(assumed);
        resp.setDoorWidth(doorWidth != null ? doorWidth : (assumed ? DEFAULT_DOOR_WIDTH : null));
        if (assumed) {
            resp.setMessage("标签没有印门幅，已按行业标准 " + DEFAULT_DOOR_WIDTH + " 米匹配到 "
                    + matches.size() + " 个货号，请核对实物后提交。");
        } else if (matches.size() == 1) {
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
            InboundOrderResponse created = inboundOrderService.create(toCreateRequest(req), tenantId, operator,
                    // 服务端**强制**来源 = photo（issue #6812）：这条链一次收一卷布 ⇒ 明细行「数量」是
                    // **卷数**、「卷长」是每卷米数，入库米数 = 卷数 × 卷长。走 4 参重载 ⇒ 客户端传什么都不生效。
                    InboundOrder.SOURCE_PHOTO);
            WorkerInboundDraftView view = viewOf(created, null);
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
            // 过账成功后**同一事务**为每一行发码（issue #5052 P2；§7.1「缺码不画假码」）：
            // 「已过账但永远没有码」是不可恢复的中间态（没有「按单补码」的产品路径）⇒ fail-closed，
            // 工人带同一个 Idempotency-Key 重试即可（幂等占位随本次事务一起回滚 = 重试仍是首次执行）。
            List<InboundLabel> labels = inboundLabelService.ensureLabels(
                    tenantId, posted.getId(), posted.getItems(), operator);
            WorkerInboundDraftView view = viewOf(posted, labels);
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
     * SKU 匹配门禁（设计 §6.3；issue #7759 改判为「<b>归一化 + 多级降级 + 仍绝不猜</b>」）。
     *
     * <h3>为什么要改（实测，不是推测）</h3>
     * <p>原来两道门都是**精确相等**（{@code products.name = 识别品名} 且
     * {@code product_skus.color_name = 识别色号}）。而供应商标签用的是**它自己的型号命名空间**
     * —— 实测品名（{@code 雪尼尔2659-4绵绵奶咖}）与色号（{@code 2659-4绵绵奶咖}）两条都零命中，
     * 于是这条链**恒不可入库**；而真正能对上的键（{@code 2659-4} → {@code 2659-04}）
     * 当时连承载的字段都没有。</p>
     *
     * <h3>三级，逐级降级（每一级都只在**既有** {@code product_skus} 里查）</h3>
     * <ol>
     *   <li><b>一级 · 型号 / 货号</b>：归一后的 {@code model_no} 命中 {@code products.sku_code}
     *       精确（{@code 2659}）或更细的分层（{@code 2659-04}）；</li>
     *   <li><b>二级 · 色名消歧</b>：归一后的色名在 {@code product_skus.color_name} 里**包含**即命中
     *       （{@code 绵绵奶咖} ⊂ {@code 2659-04 绵绵奶咖}）；型号命中时**只在型号命中的商品内**消歧；</li>
     *   <li><b>三级 · 型号兜底</b>：型号命中、色名一条都不中 ⇒ 该型号下的**全部**货号进下一级；</li>
     *   <li><b>四级 · 门幅消歧</b>（用户 2026-10-25 裁定）：标签写了门幅 ⇒ 精确取该档，库里没有就**零命中**
     *       （不回落）；标签没印门幅 ⇒ 取 **2.8 米**那一档（非标准门幅会印在标签上），该档不存在 ⇒
     *       退回候选列表交工人选。</li>
     * </ol>
     *
     * <p><b>商品名不再参与匹配</b>，只在响应里作展示：供应商标签上的品名是**它自己的**命名，
     * 拿它跟内部商品名做相等/包含匹配只会造出「看起来命中、其实不是同一块布」的候选 —— 那就是「猜」。</p>
     *
     * <p>🔴 <b>红线一条都不动</b>：0 命中 ⇒ 空列表（拒绝入库、不建品、不建 SKU、不落台账）；
     * 多命中 ⇒ 原样返回由工人确认；本方法只读，没有任何写路径。</p>
     */
    private List<WorkerInboundSkuMatch> matchInboundSkus(String modelNo, String colorName, String doorWidth,
                                                        Long tenantId) {
        String model = normalizeCode(modelNo);
        String color = normalizeCode(colorName);
        if (model == null && color == null) {
            return new ArrayList<>();
        }

        // 一级：型号 / 货号 → products.sku_code（SQL 只做第一段的前缀下推，规则本身在 Java 里精筛）
        List<String> modelProductIds = new ArrayList<>();
        String productCode = productCodeOf(model);
        if (productCode != null && productCode.length() >= 2) {
            for (Product product : productMapper.selectList(new LambdaQueryWrapper<Product>()
                    .eq(Product::getTenantId, tenantId)
                    .likeRight(Product::getSkuCode, productCode))) {
                if (modelMatchesProduct(product.getSkuCode(), model)) {
                    modelProductIds.add(product.getId());
                }
            }
        }

        // 二级：色名包含（型号命中时只在型号命中的商品内消歧 —— 型号是更强的证据）
        List<ProductSku> colorCandidates = new ArrayList<>();
        if (color != null) {
            for (ProductSku sku : productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                    .eq(ProductSku::getTenantId, tenantId)
                    .like(ProductSku::getColorName, colorTokenOf(color)))) {
                if (!modelProductIds.isEmpty() && !modelProductIds.contains(sku.getProductId())) {
                    continue;
                }
                if (colorMatches(sku.getColorName(), color)) {
                    colorCandidates.add(sku);
                }
            }
        }
        List<ProductSku> candidates;
        if (!colorCandidates.isEmpty()) {
            candidates = colorCandidates;
        } else if (!modelProductIds.isEmpty()) {
            // 三级：型号命中但色名一条都不中 ⇒ 该型号下的全部货号（交工人选，不当零命中）
            candidates = productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                    .eq(ProductSku::getTenantId, tenantId)
                    .in(ProductSku::getProductId, modelProductIds));
        } else {
            return new ArrayList<>();
        }

        // 四级 · 门幅消歧（用户 2026-10-25 裁定）：写明了就精确取；没写就按行业标准 2.8 取
        return toMatches(sorted(selectByDoorWidth(candidates, doorWidth)), tenantId);
    }

    /**
     * 门幅消歧（issue #7759 用户裁定 2026-10-25）—— <b>取不到就是零命中，绝不回落</b>。
     *
     * <ol>
     *   <li>标签**写了**门幅 ⇒ 只留该档；一档都没有 ⇒ 空列表（<b>不许</b>拿默认值顶替 = 替工人猜）；</li>
     *   <li>标签**没写**门幅 ⇒ 只留 {@link #DEFAULT_DOOR_WIDTH} 那一档
     *       （用户裁定：非标准门幅会在标签上印真实数字 ⇒ 没印就是行业标准 2.8）；
     *       该档不存在 ⇒ <b>原样返回全部候选</b>（交工人选，**不许**自动换别的门幅）。</li>
     * </ol>
     */
    private static List<ProductSku> selectByDoorWidth(List<ProductSku> candidates, String doorWidth) {
        String wanted = doorWidth != null ? doorWidth : DEFAULT_DOOR_WIDTH;
        List<ProductSku> hits = new ArrayList<>();
        for (ProductSku sku : candidates) {
            if (doorWidthMatches(sku.getDoorWidth(), wanted)) {
                hits.add(sku);
            }
        }
        if (!hits.isEmpty()) {
            return hits;
        }
        return doorWidth != null ? new ArrayList<>() : candidates;
    }

    /** 这批候选是不是**全部**落在同一门幅上（用于回填 {@code doorWidthAssumed} 与那句话术）。 */
    private static boolean hasOnlyDoorWidth(List<WorkerInboundSkuMatch> matches, String doorWidth) {
        for (WorkerInboundSkuMatch match : matches) {
            if (!doorWidthMatches(match.getDoorWidth(), doorWidth)) {
                return false;
            }
        }
        return !matches.isEmpty();
    }

    /**
     * 按**货号 / 色名**搜既有 SKU（issue #7759；**只读**，与 {@code /api/worker/inbound/**} 的零商家权限码口径相同）。
     *
     * <p>为什么要这个读面：零命中时页面原来只说一句「请从已有商品里选一个」，而工人面**没有任何可选的地方**
     * （识别 / 建草稿 / 过账之外没有查询端点）⇒ 工人只能放弃。这里补的就是那个出口：
     * 工人自己输入货号或色名的一部分，从**既有** {@code product_skus} 里找。</p>
     *
     * <p>只读、不改库存、不建品；空白 / 单字查询直接 400（单字下推等于全表扫，而搜索只是辅助）。</p>
     */
    public List<WorkerInboundSkuMatch> searchSkus(String query, Long tenantId) {
        String raw = trimToNull(query);
        String key = normalizeCode(raw);
        if (raw == null || key == null || key.length() < 2) {
            throw new BusinessException("INBOUND_SKU_SEARCH_TOO_SHORT",
                    "请至少输入 2 个字 / 位货号或色名再搜（空白查询不会去扫全表）", 400,
                    "例如输入货号 2659，或色名绵绵奶咖。");
        }
        List<String> needles = new ArrayList<>();
        addNeedle(needles, raw);
        addNeedle(needles, key);
        addNeedle(needles, productCodeOf(key));
        addNeedle(needles, colorTokenOf(key));
        Map<Long, ProductSku> hitById = new LinkedHashMap<>();
        for (String needle : needles) {
            for (ProductSku sku : productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                    .eq(ProductSku::getTenantId, tenantId)
                    .like(ProductSku::getSkuCode, needle))) {
                hitById.putIfAbsent(sku.getId(), sku);
            }
            for (ProductSku sku : productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>()
                    .eq(ProductSku::getTenantId, tenantId)
                    .like(ProductSku::getColorName, needle))) {
                hitById.putIfAbsent(sku.getId(), sku);
            }
        }
        List<ProductSku> hits = new ArrayList<>(hitById.values());
        return toMatches(sorted(hits.size() > SEARCH_LIMIT ? hits.subList(0, SEARCH_LIMIT) : hits), tenantId);
    }

    /** 搜索用的下推片段：去空、至少 2 字、去重（单字下推 ≈ 全表扫）。 */
    private static void addNeedle(List<String> needles, String value) {
        if (value != null && value.length() >= 2 && !needles.contains(value)) {
            needles.add(value);
        }
    }

    // ============================================================ 归一化（纯函数，可单测）

    /**
     * 归一化「型号 / 货号 / 色号」文本（issue #7759）—— <b>纯函数</b>，不读库、不猜。
     *
     * <p>供应商标签与内部编码**不是同一套写法**（实测：图上 {@code 2659-4绵绵奶咖}、
     * 库里 {@code products.sku_code='2659'} + {@code product_skus.color_name='2659-04 绵绵奶咖'}）——
     * 拿原文做精确相等必然零命中。归一化只抹平**写法**差异，不抹平**语义**差异
     * （图上没写的位一个都不补、图上看不清的字一个都不猜）：</p>
     * <ol>
     *   <li>全角 → 半角（{@code －} 跟着变成 {@code -}）；</li>
     *   <li>去空白（标签上 {@code 2659-04 绵绵奶咖} 与图上 {@code 2659-4绵绵奶咖} 的唯一差别就是空格）；</li>
     *   <li>大小写不敏感；</li>
     *   <li>去 {@code NO.} / {@code NO:} / {@code 编号} 前缀；</li>
     *   <li>分隔符统一成 {@code -}（{@code —} {@code ·} {@code *} {@code _} {@code /} {@code 、}）；</li>
     *   <li>第一段之后的**纯数字段补零两位**（{@code 2659-4} → {@code 2659-04}）。</li>
     * </ol>
     *
     * @return 归一化结果；入参空白 / 归一后为空 ⇒ {@code null}
     */
    static String normalizeCode(String raw) {
        if (!StringUtils.hasText(raw)) {
            return null;
        }
        StringBuilder halfWidth = new StringBuilder(raw.length());
        for (int i = 0; i < raw.length(); i++) {
            char c = raw.charAt(i);
            if (c == '\u3000') {
                continue;   // 全角空格 = 空白，直接去掉（与半角空格同一处置）
            }
            if (c >= '\uFF01' && c <= '\uFF5E') {
                c = (char) (c - 0xFEE0);   // 全角 ASCII 区 → 半角
            }
            halfWidth.append(c);
        }
        String s = halfWidth.toString().toLowerCase(Locale.ROOT);
        s = s.replaceFirst("^(no[.:\\-]?|编号[.:\\-]?)", "");
        s = s.replaceAll("[\\s]", "");   // 去空白（半角 + 全角 U+3000 在上一步已丢）：不是折成分隔符
        s = s.replaceAll("[\\u2013\\u2014\\u2015\\u2212\\u00b7\\u2022\\u30fb*_/\\\\、,，。]", "-");
        s = s.replaceAll("-{2,}", "-");
        s = s.replaceAll("^-+", "").replaceAll("-+$", "");
        if (s.isEmpty()) {
            return null;
        }
        String[] segments = s.split("-");
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < segments.length; i++) {
            // 色号补零两位：`2659-4` → `2659-04`；连写时连段首那一位一起补（`4绵绵奶咖` → `04绵绵奶咖`）
            String segment = i > 0 ? padLeadingNumber(segments[i]) : segments[i];
            if (i > 0) {
                out.append('-');
            }
            out.append(segment);
        }
        return out.toString();
    }

    /** 段的**前导数字**补零两位（`4` → `04`、`4绵绵奶咖` → `04绵绵奶咖`）；已是两位及以上 ⇒ 原样。 */
    private static String padLeadingNumber(String segment) {
        int end = 0;
        while (end < segment.length() && Character.isDigit(segment.charAt(end))) {
            end++;
        }
        return end == 1 ? "0" + segment : segment;
    }

    /** 归一化型号的**第一段**（{@code 2659-04} ⇒ {@code 2659}）—— {@code products.sku_code} 的键。 */
    static String productCodeOf(String normalizedModel) {
        if (normalizedModel == null) {
            return null;
        }
        int dash = normalizedModel.indexOf('-');
        String head = dash < 0 ? normalizedModel : normalizedModel.substring(0, dash);
        return head.length() >= 2 ? head : normalizedModel;
    }

    /**
     * 色名的**非编码段**（{@code 2659-04绵绵奶咖} ⇒ {@code 绵绵奶咖}、{@code 01米白} ⇒ {@code 米白}）。
     *
     * <p>用途 = 下推 SQL：库里的 {@code color_name} 带前缀与空格，拿整串去 LIKE 会因写法差异漏掉，
     * 只留色名那段才是两边共有的部分。剥完不足 2 字（如色名整串就是数字）⇒ 退回整串。</p>
     */
    static String colorTokenOf(String normalizedColor) {
        if (normalizedColor == null) {
            return null;
        }
        String token = normalizedColor.replaceFirst("^\\d+(-\\d+)*-?", "");
        return token.length() >= 2 ? token : normalizedColor;
    }

    /**
     * 门幅归一（纯函数）：{@code 2.8} / {@code 2.80} / {@code 280} / {@code 280cm} / 全角写法 ⇒ 同一个 {@code 2.8}。
     *
     * <p>标签上写的是「真实门幅数字」（用户裁定），而库里的 {@code product_skus.door_width} 是米数 ——
     * 打印成公分（`280`）与带单位（`280cm`）在行业里都很常见，所以三种写法都得落到同一档。
     * 归一**不等于猜**：它只换算能确定的等价写法（280cm ≡ 2.8m），不产生新信息。</p>
     *
     * @return 归一后的米数（一位小数，如 {@code 2.8}）；空白 / 非数字 ⇒ {@code null}
     */
    static String normalizeDoorWidth(String raw) {
        String s = normalizeCode(raw);
        if (s == null) {
            return null;
        }
        s = s.replaceAll("(厘米|公分|cm|米|m)$", "").replaceAll("[^0-9.]", "");
        if (s.isEmpty() || ".".equals(s)) {
            return null;
        }
        try {
            java.math.BigDecimal meters = new java.math.BigDecimal(s);
            if (meters.compareTo(new java.math.BigDecimal("100")) >= 0) {
                meters = meters.divide(new java.math.BigDecimal("100"));   // 280(cm) → 2.8
            }
            return meters.setScale(1, java.math.RoundingMode.HALF_UP).toPlainString();
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /** 两个门幅写法是否同一档（{@code 2.8} ≡ {@code 2.80} ≡ {@code 280cm}）。 */
    static boolean doorWidthMatches(String storedDoorWidth, String wantedDoorWidth) {
        String stored = normalizeDoorWidth(storedDoorWidth);
        String wanted = normalizeDoorWidth(wantedDoorWidth);
        return stored != null && wanted != null && stored.equals(wanted);
    }

    /** 型号 / 货号键命中商品：{@code products.sku_code} 与归一化型号相等、或它是该型号的一段前缀。 */
    static boolean modelMatchesProduct(String productSkuCode, String normalizedModel) {
        String code = normalizeCode(productSkuCode);
        if (code == null || normalizedModel == null || code.length() < 2) {
            return false;
        }
        return code.equals(normalizedModel)
                || code.equals(productCodeOf(normalizedModel))
                || normalizedModel.startsWith(code + "-");
    }

    /** 色名命中：归一后**双向包含**（任一侧更长的写法都算），短的一侧至少 2 字（防退化成一字命中）。 */
    static boolean colorMatches(String storedColorName, String normalizedColor) {
        String stored = normalizeCode(storedColorName);
        if (stored == null || normalizedColor == null) {
            return false;
        }
        return containsAtLeastTwo(stored, normalizedColor)
                || containsAtLeastTwo(normalizedColor, stored)
                || containsAtLeastTwo(stored, colorTokenOf(normalizedColor));
    }

    private static boolean containsAtLeastTwo(String haystack, String needle) {
        return needle != null && needle.length() >= 2 && haystack.contains(needle);
    }

    /** 稳定排序：货号 → 门幅。**只排序、不筛选** —— 多命中仍原样交工人选。 */
    private static List<ProductSku> sorted(List<ProductSku> skus) {
        List<ProductSku> ordered = new ArrayList<>(skus);
        ordered.sort(Comparator
                .comparing((ProductSku sku) -> sku.getSkuCode() == null ? "" : sku.getSkuCode())
                .thenComparing(sku -> sku.getDoorWidth() == null ? "" : sku.getDoorWidth()));
        return ordered;
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
        // 🔴 importRunId 不设（工人面结构上没有这个键）；source 由调用方**服务端强制**为 photo（issue #6812）
        //    ⇒ 这里的 item.quantity 是**卷数**、item.rollLengthM 是**每卷米数**（入库米数 = 两者之积）
        InboundOrderCreateRequest.Item item = new InboundOrderCreateRequest.Item();
        item.setProductId(req.getProductId());
        item.setSkuId(req.getSkuId());
        item.setQuantity(req.getQuantity());
        // 金额精度准入（issue #6228）：工人面单价是**工人输入**，下游入库单价列 NUMERIC(·,2)。
        // 本文件是工人面的入口（结构上没有别的写面）⇒ 在这里显式拒绝，不让值先流进下游再被舍掉。
        item.setUnitCost(MoneyScale.requireTwoDecimalsOrNull(req.getUnitCost(), "入库单价"));
        item.setDyeLot(trimToNull(req.getDyeLot()));
        item.setRollLengthM(req.getRollLengthM());
        create.setItems(List.of(item));
        return create;
    }

    /**
     * 入库单 → 工人面视图（两个端点同一形状；{@code needsConfirmation} 只对草稿为 true）。
     *
     * @param labels 过账后为每一行发出的标签（**草稿态为 null** —— 标签只在过账后存在，§4 步骤 11）
     */
    private static WorkerInboundDraftView viewOf(InboundOrderResponse order, List<InboundLabel> labels) {
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
                // 🔴 工人面「数量」= **卷数**（issue #6812 的读面口径，工人核对「我拍了几卷」）：
                //    issue #7709 起明细行的 quantity 恒为米数、卷数在 roll_count ⇒ 这里映射卷数，
                //    工人端 UI 与既有判据一字不动；米数由标签 / 商家端明细看
                line.setQuantity(item.getRollCount() != null
                        ? BigDecimal.valueOf(item.getRollCount())
                        : item.getQuantity());
                line.setBatchNo(item.getBatchNo());
                // 标签短码（P2）：草稿态没有、过账后每行一个；P3 拿它拼 /i/<短码> 出 50×30mm 标签
                for (InboundLabel label : labels == null ? List.<InboundLabel>of() : labels) {
                    if (label != null && item.getId() != null && item.getId().equals(label.getInboundItemId())) {
                        line.setShortCode(label.getShortCode());
                        line.setPrintCount(label.getPrintCount());
                    }
                }
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
