package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.dto.agent.AgentBatchCreateRequest;
import com.migao.admin.dto.agent.AgentBatchViews;
import com.migao.admin.dto.agent.AgentProductUpdateRequest;
import com.migao.admin.entity.AgentBatch;
import com.migao.admin.entity.AgentBatchItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.AgentBatchItemMapper;
import com.migao.admin.mapper.AgentBatchMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * 批量更新的批次资源（issue #5314 服务端包；冻结契约见 issue #5314 评论 2026-09-24）。
 *
 * <h2>为什么批量必须先有撤销</h2>
 * 批量是「一键确认 N 条 = 用户实际没看」的<b>盲签</b>唯一来源 —— 单条可逆写能自愈，批量不能。
 * 故本服务把「撤销依据」当<b>一等数据</b>：创建批次（= 预演）时就把每条的 {@code old_value}
 * 落库（{@code agent_batch_items}），执行与撤销都**逐条**落 {@code status} / {@code error}。
 *
 * <h2>🔴 三条有意为之的取舍</h2>
 * <ol>
 *   <li><b>不复用 {@code audit_logs} 当撤销依据</b>：审计是有界 fail-open（3s 超时丢行是允许的）
 *       ⇒ 拿它当依据 = 撤销会静默失去依据。批次/明细各自落表。</li>
 *   <li><b>不做整体回滚</b>：执行与撤销都逐条提交、逐条报告；单条失败即写该条
 *       {@code status=failed} + {@code error}，其余照常。回滚会把「到底哪几条真的改坏了」
 *       一起掩盖掉 —— 那正是本能力最需要看见的信息。</li>
 *   <li><b>不加 {@code @Transactional}（有意）</b>：方法级事务会让「部分失败」变成整批回滚，
 *       与上一条直接冲突。逐条独立提交 = 部分失败的载体。</li>
 * </ol>
 *
 * <h2>边界（如实登记，不粉饰）</h2>
 * <ul>
 *   <li><b>同步 + 阈值</b>：{@code N > 50} 直接拒绝并提示分批（本单不做后台任务与进度轮询）。</li>
 *   <li><b>上/下架的撤销可能被状态机挡住</b>：例如原状态 {@code draft} 的商品被批量上架后，
 *       撤销回 {@code draft} 会被 {@code ProductService} 的状态机拒绝（{@code on_sale → draft} 不是
 *       合法流转）⇒ 该条以 {@code revert_failed} 逐条报出，批次落 {@code revert_partial}。
 *       这是**有意 fail-closed**：不绕过状态机去写一个业务上不允许的状态。</li>
 *   <li><b>条目只认精确 ID</b>：不解析商品名（单条路径才做名称解析）—— 批量条目必须精确可寻址，
 *       否则预览展示的行与撤销命中的行可能不是同一行。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AgentBatchService {

    /** 单批上限（契约：N &gt; 50 拒绝并提示分批；本单不做后台任务）。 */
    public static final int MAX_ITEMS = 50;

    /** batchType 白名单（本单只做两个具名批量）。 */
    public static final String TYPE_PRODUCT_PRICE = "product_price";
    public static final String TYPE_PRODUCT_STATUS = "product_status";

    /** 两个具名批量各自的字段（field 与 batchType 必须配对）。
     *  ⚠️ 词表单一源 = {@link AgentWriteValues}（issue #5317）：单条改价的改前价核对
     *  用的是**同一份字段词 + 同一套按值比对**，这里只是保留既有常量名（调用方零改动）。 */
    public static final String FIELD_BASE_PRICE = AgentWriteValues.FIELD_BASE_PRICE;
    public static final String FIELD_STATUS = AgentWriteValues.FIELD_STATUS;

    /** 批次状态机：preview → executing → done | partial → reverted | revert_partial。 */
    public static final String STATUS_PREVIEW = "preview";
    public static final String STATUS_EXECUTING = "executing";
    public static final String STATUS_DONE = "done";
    public static final String STATUS_PARTIAL = "partial";
    public static final String STATUS_REVERTED = "reverted";
    public static final String STATUS_REVERT_PARTIAL = "revert_partial";

    /** 逐条状态。 */
    public static final String ITEM_PENDING = "pending";
    public static final String ITEM_SUCCESS = "success";
    public static final String ITEM_FAILED = "failed";
    public static final String ITEM_REVERTED = "reverted";
    public static final String ITEM_REVERT_FAILED = "revert_failed";
    /** 执行阶段就失败过的条目 —— 从未生效，撤销时无需还原（但**逐条报出**，不静默略过）。 */
    public static final String ITEM_SKIPPED = "skipped";

    /** 上/下架批量的合法取值（与 {@code ProductService} 的状态机入口一致）。 */
    private static final List<String> ON_OFF_SALE = List.of("on_sale", "off_sale");

    /** batchType → 唯一合法 field。 */
    private static final Map<String, String> TYPE_FIELD = Map.of(
            TYPE_PRODUCT_PRICE, FIELD_BASE_PRICE,
            TYPE_PRODUCT_STATUS, FIELD_STATUS);

    /** {@code agent_batch_items.error} 列宽（VARCHAR(500)）—— 超长截断，不让一次落库失败。 */
    private static final int MAX_ERROR_LEN = 500;

    private final AgentBatchMapper batchMapper;

    private final AgentBatchItemMapper itemMapper;

    /** 单条写的既有路径（含状态机校验与 SKU 价同步）—— 批量复用同一条，不另写一份写逻辑。 */
    private final ProductService productService;

    // ═══════════════════ ① 创建批次（= 预演）═══════════════════

    /**
     * 创建批次（= 预演）：逐条采集 {@code old_value} 落库，批次置 {@code preview}。
     *
     * <p>逐条 fail-closed：任一条的 {@code oldValue} 与 DB 当前值不符、或资源不可见、
     * 或 {@code newValue} 非法 ⇒ **整批拒绝**（零写）。理由：预演表是用户唯一能复核的东西，
     * 一条 before 是错的，那张表就不再可信。</p>
     */
    public AgentBatchViews.Batch create(Long tenantId, String createdBy, AgentBatchCreateRequest request) {
        String batchType = request == null ? null : request.getBatchType();
        String expectedField = TYPE_FIELD.get(batchType);
        if (expectedField == null) {
            throw BusinessException.validationError("batchType 不在白名单内：" + batchType
                    + "（本单只做 " + TYPE_PRODUCT_PRICE + " / " + TYPE_PRODUCT_STATUS + "）");
        }
        List<AgentBatchCreateRequest.Item> requested = request.getItems();
        if (requested == null || requested.isEmpty()) {
            throw BusinessException.validationError("items 不能为空");
        }
        if (requested.size() > MAX_ITEMS) {
            throw BusinessException.validationError("一次最多 " + MAX_ITEMS + " 条（当前 "
                    + requested.size() + " 条），请分批提交");
        }

        String batchId = UUID.randomUUID().toString();
        Set<String> seen = new HashSet<>();
        List<AgentBatchItem> items = new ArrayList<>(requested.size());
        for (AgentBatchCreateRequest.Item req : requested) {
            String resourceId = req.getResourceId();
            if (!expectedField.equals(req.getField())) {
                throw BusinessException.validationError("field 与 batchType 不配对：batchType=" + batchType
                        + " ⇒ field 必须是 " + expectedField + "（收到 " + req.getField() + "）");
            }
            if (!seen.add(resourceId)) {
                throw BusinessException.validationError("同一资源在同一批次里重复出现：" + resourceId
                        + " —— 撤销顺序会变得不确定");
            }
            String current = currentValue(tenantId, resourceId, req.getField());
            if (current == null) {
                throw BusinessException.validationError("资源不可见或没有该字段，无法采集改前值："
                        + resourceId + "（请先用 product_search 查出本租户的商品 ID 后重试）");
            }
            if (req.getOldValue() != null
                    && !AgentWriteValues.sameValue(req.getField(), req.getOldValue(), current)) {
                throw BusinessException.validationError("oldValue 与当前值不符：" + resourceId
                        + " 当前 " + current + "，收到 " + req.getOldValue() + " —— 请重新预览后再提交");
            }
            validateNewValue(req.getField(), resourceId, req.getNewValue());
            items.add(AgentBatchItem.builder()
                    .batchId(batchId)
                    .tenantId(tenantId)
                    .resourceId(resourceId)
                    .field(req.getField())
                    // 🔴 落库的是 **DB 真值**，不是调用方字符串：撤销依据不能是调用方的一面之词
                    .oldValue(current)
                    .newValue(req.getNewValue())
                    .status(ITEM_PENDING)
                    .build());
        }

        AgentBatch batch = AgentBatch.builder()
                .id(batchId)
                .tenantId(tenantId)
                .batchType(batchType)
                .status(STATUS_PREVIEW)
                .itemCount(items.size())
                .successCount(0)
                .failCount(0)
                .createdBy(createdBy)
                .build();
        batchMapper.insert(batch);
        for (AgentBatchItem item : items) {
            itemMapper.insert(item);
        }
        log.info("[Agent] 批量更新批次已创建（预演）: batchId={}, type={}, items={}, tenantId={}",
                batchId, batchType, items.size(), tenantId);
        return view(batch, null, null);
    }

    // ═══════════════════ ② 执行（逐条）═══════════════════

    /**
     * 执行批次：{@code preview → executing → done | partial}，逐条写 {@code new_value}。
     *
     * <p>逐条独立提交（本方法**有意不加事务**，见类注释取舍 ②③）：单条失败只影响该条，
     * 结果里逐条回 {@code {resourceId, success, error?}}。</p>
     */
    public AgentBatchViews.Batch execute(Long tenantId, String batchId) {
        AgentBatch batch = requireBatch(tenantId, batchId);
        if (!STATUS_PREVIEW.equals(batch.getStatus())) {
            throw BusinessException.conflict("批次当前状态为 " + batch.getStatus()
                            + "，只有 preview 的批次可以执行（不可重复执行）",
                    "用 GET /api/admin/agent/batches/" + batchId + " 查看该批次的状态与结果");
        }
        batch.setStatus(STATUS_EXECUTING);
        batchMapper.updateById(batch);

        List<AgentBatchItem> items = itemsOf(batchId);
        List<AgentBatchViews.Result> results = new ArrayList<>(items.size());
        int success = 0;
        int fail = 0;
        for (AgentBatchItem item : items) {
            try {
                apply(tenantId, item, item.getNewValue());
                item.setStatus(ITEM_SUCCESS);
                success++;
                results.add(AgentBatchViews.Result.builder()
                        .resourceId(item.getResourceId()).success(true).build());
            } catch (Exception e) {
                String reason = errorText(item.getResourceId(), e);
                item.setStatus(ITEM_FAILED);
                item.setError(reason);
                fail++;
                results.add(AgentBatchViews.Result.builder()
                        .resourceId(item.getResourceId()).success(false).error(reason).build());
                log.warn("[Agent] 批量执行逐条失败: batchId={}, resourceId={}, error={}",
                        batchId, item.getResourceId(), reason);
            }
            itemMapper.updateById(item);
        }

        batch.setSuccessCount(success);
        batch.setFailCount(fail);
        batch.setStatus(fail == 0 ? STATUS_DONE : STATUS_PARTIAL);
        batch.setExecutedAt(OffsetDateTime.now());
        batchMapper.updateById(batch);
        log.info("[Agent] 批量执行完成: batchId={}, success={}, fail={}, status={}",
                batchId, success, fail, batch.getStatus());
        return view(batch, results, null);
    }

    // ═══════════════════ ③ 撤销（逐条还原 old_value）═══════════════════

    /**
     * 撤销批次：逐条还原为持久化的 {@code old_value}，{@code done | partial → reverted | revert_partial}。
     *
     * <p><b>不可撤销</b>（契约）：状态非 {@code done}/{@code partial}、或已 {@code reverted}
     * （含 {@code revert_partial} —— 撤销过的批次不再提供第二次撤销）。</p>
     */
    public AgentBatchViews.Batch revert(Long tenantId, String batchId) {
        AgentBatch batch = requireBatch(tenantId, batchId);
        if (STATUS_REVERTED.equals(batch.getStatus()) || STATUS_REVERT_PARTIAL.equals(batch.getStatus())) {
            throw BusinessException.conflict("批次当前状态为 " + batch.getStatus()
                            + "，已撤销的批次不可重复撤销",
                    "用 GET /api/admin/agent/batches/" + batchId + " 查看该批次的撤销结果");
        }
        if (!STATUS_DONE.equals(batch.getStatus()) && !STATUS_PARTIAL.equals(batch.getStatus())) {
            throw BusinessException.conflict("批次当前状态为 " + batch.getStatus()
                            + "，可撤销状态只有 " + STATUS_DONE + " / " + STATUS_PARTIAL,
                    "请先执行该批次（POST /api/admin/agent/batches/" + batchId + "/execute）");
        }

        List<AgentBatchItem> items = itemsOf(batchId);
        List<AgentBatchViews.Result> results = new ArrayList<>(items.size());
        int failed = 0;
        for (AgentBatchItem item : items) {
            if (!ITEM_SUCCESS.equals(item.getStatus())) {
                // 执行阶段就失败过的条目从未生效 ⇒ 没有东西要还原；逐条报出（不静默略过、不误写）
                item.setStatus(ITEM_SKIPPED);
                itemMapper.updateById(item);
                results.add(AgentBatchViews.Result.builder()
                        .resourceId(item.getResourceId()).success(true).build());
                continue;
            }
            try {
                // 🔴 还原的是**落库那一份** old_value（不是请求里的字符串，也不是 newValue）
                apply(tenantId, item, item.getOldValue());
                item.setStatus(ITEM_REVERTED);
                results.add(AgentBatchViews.Result.builder()
                        .resourceId(item.getResourceId()).success(true).build());
            } catch (Exception e) {
                String reason = errorText(item.getResourceId(), e);
                item.setStatus(ITEM_REVERT_FAILED);
                item.setError(reason);
                failed++;
                results.add(AgentBatchViews.Result.builder()
                        .resourceId(item.getResourceId()).success(false).error(reason).build());
                log.warn("[Agent] 批量撤销逐条失败: batchId={}, resourceId={}, error={}",
                        batchId, item.getResourceId(), reason);
            }
            itemMapper.updateById(item);
        }

        batch.setStatus(failed == 0 ? STATUS_REVERTED : STATUS_REVERT_PARTIAL);
        batch.setRevertedAt(OffsetDateTime.now());
        batchMapper.updateById(batch);
        log.info("[Agent] 批量撤销完成: batchId={}, failed={}, status={}", batchId, failed, batch.getStatus());
        return view(batch, results, null);
    }

    // ═══════════════════ ④ 查询（进度 / 结果 / 可撤销性）═══════════════════

    /** 查询批次：进度与计数 + 逐条 before → after（撤销依据可核对）+ 可撤销性。 */
    public AgentBatchViews.Batch get(Long tenantId, String batchId) {
        AgentBatch batch = requireBatch(tenantId, batchId);
        List<AgentBatchViews.Item> items = itemsOf(batchId).stream()
                .map(i -> AgentBatchViews.Item.builder()
                        .resourceId(i.getResourceId())
                        .field(i.getField())
                        .oldValue(i.getOldValue())
                        .newValue(i.getNewValue())
                        .status(i.getStatus())
                        .error(i.getError())
                        .build())
                .toList();
        return view(batch, null, items);
    }

    // ═══════════════════ 内部 ═══════════════════

    /** 批次定位（租户过滤由拦截器注入；再显式核一次 tenant 归属，防 mocked/SQL 旁路）。 */
    private AgentBatch requireBatch(Long tenantId, String batchId) {
        AgentBatch batch = batchMapper.selectById(batchId);
        if (batch == null || (batch.getTenantId() != null && !batch.getTenantId().equals(tenantId))) {
            throw BusinessException.notFound("批次", "未找到批次 " + batchId
                    + "（或它不属于当前租户）；请用创建时返回的 batchId");
        }
        return batch;
    }

    private List<AgentBatchItem> itemsOf(String batchId) {
        return itemMapper.selectList(new LambdaQueryWrapper<AgentBatchItem>()
                .eq(AgentBatchItem::getBatchId, batchId)
                .orderByAsc(AgentBatchItem::getId));
    }

    /** 用**单条写的既有路径**落一个字段（复用状态机校验 / SKU 价同步，不另写一份写逻辑）。 */
    private void apply(Long tenantId, AgentBatchItem item, String value) {
        AgentProductUpdateRequest update = new AgentProductUpdateRequest();
        if (FIELD_BASE_PRICE.equals(item.getField())) {
            update.setBasePrice(new BigDecimal(value));
        } else {
            update.setStatus(value);
        }
        productService.updateProductForAgent(item.getResourceId(), update, tenantId);
    }

    /** DB 当前值（撤销依据的真值源）；资源不可见 / 字段无值 ⇒ null。 */
    private String currentValue(Long tenantId, String resourceId, String field) {
        ProductResponse product;
        try {
            product = productService.getProductById(resourceId, tenantId);
        } catch (BusinessException e) {
            return null;   // 不存在 / 跨租户 —— 一律按「采集不到改前值」fail-closed
        }
        if (product == null) {
            return null;
        }
        if (FIELD_BASE_PRICE.equals(field)) {
            return product.getBasePrice() == null ? null : product.getBasePrice().toPlainString();
        }
        return product.getStatus();
    }

    /** 按**值**比对（数字不比字符串写法：{@code 10.0} 与 {@code 10.00} 是同一个价）。
     *  ⚠️ 实现已**唯一化**到 {@link AgentWriteValues#sameValue}（issue #5317）：单条改价的
     *  改前价核对是同一个语义 ⇒ 两处各写一份必然漂移（§17.3「同一真值两处投影」）。 */
    private void validateNewValue(String field, String resourceId, String value) {
        if (FIELD_BASE_PRICE.equals(field)) {
            try {
                if (new BigDecimal(value).compareTo(BigDecimal.ZERO) < 0) {
                    throw BusinessException.validationError("改后价不能为负：" + resourceId + " ⇒ " + value);
                }
            } catch (NumberFormatException e) {
                throw BusinessException.validationError("改后价不是合法数字：" + resourceId + " ⇒ " + value);
            }
            return;
        }
        if (!ON_OFF_SALE.contains(value)) {
            throw BusinessException.validationError("批量上/下架的改后值只能是 "
                    + String.join(" / ", ON_OFF_SALE) + "：" + resourceId + " ⇒ " + value);
        }
    }

    /** 逐条失败文案（落库 / 回给调用方同一份；超长截断到列宽）。 */
    private String errorText(String resourceId, Exception e) {
        String message = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
        String text = resourceId + ": " + message;
        return text.length() > MAX_ERROR_LEN ? text.substring(0, MAX_ERROR_LEN) : text;
    }

    private AgentBatchViews.Batch view(AgentBatch batch, List<AgentBatchViews.Result> results,
                                       List<AgentBatchViews.Item> items) {
        return AgentBatchViews.Batch.builder()
                .batchId(batch.getId())
                .batchType(batch.getBatchType())
                .status(batch.getStatus())
                .itemCount(batch.getItemCount())
                .successCount(batch.getSuccessCount())
                .failCount(batch.getFailCount())
                .revertible(STATUS_DONE.equals(batch.getStatus()) || STATUS_PARTIAL.equals(batch.getStatus()))
                .createdBy(batch.getCreatedBy())
                .createdAt(batch.getCreatedAt())
                .executedAt(batch.getExecutedAt())
                .revertedAt(batch.getRevertedAt())
                .items(items)
                .results(results)
                .build();
    }
}