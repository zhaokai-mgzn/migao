package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
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
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.task.TaskExecutor;
import org.springframework.core.task.TaskRejectedException;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
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
 *   <li><b>同步 + 后台双形态</b>：同步 {@code execute}/{@code revert} 保留 #5314 冻结契约；
 *       {@code executeAsync}/{@code revertAsync}（issue #8283）提交进程内线程池并立即返回
 *       {@code executing}，进度由 GET 查询。{@code N > 50} 仍直接拒绝并提示分批。</li>
 *   <li><b>后台 job 的生命周期边界</b>：进程内线程池 + 优雅停机等待 60s；JVM 崩溃 / 强杀可能留下
 *       {@code executing} 批次（不自动回收 —— 跨实例需 lease/heartbeat，另开单跟踪）。</li>
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
public class AgentBatchService {

    /** 单批上限（契约：N &gt; 50 拒绝并提示分批；后台 job 不改变这个上限）。 */
    public static final int MAX_ITEMS = 50;

    /** batchType 白名单（具名批量：商品改价 / 上下架 / 库存调整）。 */
    public static final String TYPE_PRODUCT_PRICE = "product_price";
    public static final String TYPE_PRODUCT_STATUS = "product_status";
    /** 库存调整（issue #5950）：第三具名批量 —— 复用同一套批次资源 / 状态机 / 撤销语义，
     *  **不新造第二套批量管道**；字段与词表复用 {@link AgentWriteValues#FIELD_STOCK}。 */
    public static final String TYPE_INVENTORY_STOCK = "inventory_stock";

    /** 两个具名批量各自的字段（field 与 batchType 必须配对）。
     *  ⚠️ 词表单一源 = {@link AgentWriteValues}（issue #5317）：单条改价的改前价核对
     *  用的是**同一份字段词 + 同一套按值比对**，这里只是保留既有常量名（调用方零改动）。 */
    public static final String FIELD_BASE_PRICE = AgentWriteValues.FIELD_BASE_PRICE;
    public static final String FIELD_STATUS = AgentWriteValues.FIELD_STATUS;
    public static final String FIELD_STOCK = AgentWriteValues.FIELD_STOCK;

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
            TYPE_PRODUCT_STATUS, FIELD_STATUS,
            TYPE_INVENTORY_STOCK, FIELD_STOCK);

    /** {@code agent_batch_items.error} 列宽（VARCHAR(500)）—— 超长截断，不让一次落库失败。 */
    private static final int MAX_ERROR_LEN = 500;

    private final AgentBatchMapper batchMapper;

    private final AgentBatchItemMapper itemMapper;

    /** 单条写的既有路径（含状态机校验与 SKU 价同步）—— 批量复用同一条，不另写一份写逻辑。 */
    private final ProductService productService;

    /** 批次后台执行线程池（issue #8283；显式 bean 名，避免被 @Async 默认执行器接管）。 */
    private final TaskExecutor batchExecutor;

    public AgentBatchService(AgentBatchMapper batchMapper,
                             AgentBatchItemMapper itemMapper,
                             ProductService productService,
                             @Qualifier("batchExecutor") TaskExecutor batchExecutor) {
        this.batchMapper = batchMapper;
        this.itemMapper = itemMapper;
        this.productService = productService;
        this.batchExecutor = batchExecutor;
    }

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
                    + "（本单只做 " + TYPE_PRODUCT_PRICE + " / " + TYPE_PRODUCT_STATUS
                    + " / " + TYPE_INVENTORY_STOCK + "）");
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
     * 执行批次（同步）：{@code preview → executing → done | partial}，逐条写 {@code new_value}。
     *
     * <p>同步形态保留是为了不打破 #5314 的冻结契约；页面与 Agent 新路径走
     * {@link #executeAsync(Long, String)}。两者共用 {@link #claimForExecute}（CAS 准入）与
     * {@link #runBatch}（逐条 apply）—— 不存在第二份写逻辑。</p>
     *
     * <p>🔴 <b>执行准入 = 条件更新（CAS，issue #6960）</b>：{@code preview → executing} 这一次状态迁移
     * 必须走 {@link AgentBatchMapper#markExecuting}（判断与写入同一条语句）⇒ 两个并发 execute 里
     * 只有先到者命中行，后到者影响行数 0 ⇒ 409，**一条 apply 都不跑**。</p>
     */
    public AgentBatchViews.Batch execute(Long tenantId, String batchId) {
        AgentBatch batch = claimForExecute(tenantId, batchId);
        List<AgentBatchViews.Result> results = runBatch(tenantId, batch);
        return view(batch, results, null);
    }

    /**
     * 执行批次（后台 job，issue #8283）：claim 后提交线程池，**立即**返回
     * {@code status=executing}；进度/结果由 {@link #get(Long, String)} 查询。
     *
     * <p>为什么先取 {@code accepted} 再 submit：工作线程会原地改写 {@code batch} 的 status/counts；
     * 先固化响应快照，避免调用方读到「一半执行、一半未执行」的字段。线程池饱和时 CallerRuns
     * 会内联跑完，此时响应仍是提交时刻的快照 —— 调用方按 {@code GET} 读终态即可（与异步路径同一读法）。</p>
     */
    public AgentBatchViews.Batch executeAsync(Long tenantId, String batchId) {
        AgentBatch batch = claimForExecute(tenantId, batchId);
        AgentBatchViews.Batch accepted = view(batch, null, null);
        submit(tenantId, batchId, () -> runBatch(tenantId, batch));
        return accepted;
    }

    /** 执行准入：状态检查 + 测试探针 + CAS 抢执行权；返回已置 executing 的批次。 */
    private AgentBatch claimForExecute(Long tenantId, String batchId) {
        AgentBatch batch = requireBatch(tenantId, batchId);
        if (!STATUS_PREVIEW.equals(batch.getStatus())) {
            throw BusinessException.conflict("批次当前状态为 " + batch.getStatus()
                            + "，只有 preview 的批次可以执行（不可重复执行）",
                    "用 GET /api/admin/agent/batches/" + batchId + " 查看该批次的状态与结果");
        }
        // 测试探针（issue #6960）：放大「读-判」与「抢执行权」之间的窗口（生产恒为 0，无分支成本）。
        // 与 RemnantService#recover 的探针同款 —— 窗口只有微秒级，不注入判据会退化成 flake。
        if (BATCH_PROBE_PAUSE_MILLIS > 0) {
            pauseForBatchProbe(BATCH_PROBE_PAUSE_MILLIS);
        }
        // 抢执行权：条件更新（CAS）—— 判断与写入同一条语句；0 行 ⇒ 并发的另一个请求已抢到 ⇒ 一条不写
        if (batchMapper.markExecuting(batchId, tenantId) == 0) {
            AgentBatch fresh = requireBatch(tenantId, batchId);
            throw BusinessException.conflict("批次当前状态为 " + fresh.getStatus()
                            + "，只有 preview 的批次可以执行（不可重复执行）",
                    "请刷新该批次的状态与结果后重试");
        }
        batch.setStatus(STATUS_EXECUTING);
        return batch;
    }

    /**
     * 逐条执行（同步 / 异步共用）：单条失败只影响该条；每条后更新进度，最后写终态。
     *
     * <p>job 级异常（例如读 items 失败）也必须落终态 —— 否则批次会永远停在
     * {@code executing}，既不能重试也不能撤销。这里 catch 后落 {@code partial}
     * （可撤销），已 apply 的条目仍可被逐条还原。</p>
     */
    private List<AgentBatchViews.Result> runBatch(Long tenantId, AgentBatch batch) {
        String batchId = batch.getId();
        List<AgentBatchItem> items;
        try {
            items = itemsOf(batchId);
        } catch (RuntimeException e) {
            log.error("[Agent] 批量执行读取明细失败，落 partial: batchId={}", batchId, e);
            batch.setStatus(STATUS_PARTIAL);
            batch.setFailCount(batch.getItemCount() == null ? 0 : batch.getItemCount());
            batch.setExecutedAt(OffsetDateTime.now());
            batchMapper.updateById(batch);
            return List.of();
        }

        List<AgentBatchViews.Result> results = new ArrayList<>(items.size());
        int success = 0;
        int fail = 0;
        for (AgentBatchItem item : items) {
            if (Thread.currentThread().isInterrupted()) {
                log.warn("[Agent] 批量执行被中断，剩余条目保持 pending: batchId={}", batchId);
                break;
            }
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
            // 进度：只更新计数（不写 status），让执行中的 GET 能看到「成功 / 失败」。
            // 进度写失败不应中断整批（apply 已成功，计数只是可观测面）⇒ 记日志继续。
            try {
                batchMapper.updateProgress(batchId, tenantId, success, fail);
            } catch (RuntimeException e) {
                log.warn("[Agent] 批量执行进度写入失败: batchId={}, success={}, fail={}",
                        batchId, success, fail, e);
            }
        }

        batch.setSuccessCount(success);
        batch.setFailCount(fail);
        boolean allProcessed = results.size() == items.size();
        batch.setStatus(fail == 0 && allProcessed ? STATUS_DONE : STATUS_PARTIAL);
        batch.setExecutedAt(OffsetDateTime.now());
        batchMapper.updateById(batch);
        log.info("[Agent] 批量执行完成: batchId={}, success={}, fail={}, status={}",
                batchId, success, fail, batch.getStatus());
        return results;
    }

    // ═══════════════════ ③ 撤销（逐条还原 old_value）═══════════════════

    /**
     * 撤销批次（同步）：逐条还原为持久化的 {@code old_value}，
     * {@code done | partial → reverted | revert_partial}。
     *
     * <p><b>不可撤销</b>（契约）：状态非 {@code done}/{@code partial}、或已 {@code reverted}
     * （含 {@code revert_partial} —— 撤销过的批次不再提供第二次撤销）。</p>
     *
     * <p>同步形态保留契约理由同 {@link #execute}；后台路径见 {@link #revertAsync(Long, String)}。</p>
     */
    public AgentBatchViews.Batch revert(Long tenantId, String batchId) {
        AgentBatch batch = claimForRevert(tenantId, batchId);
        List<AgentBatchViews.Result> results = runRevert(tenantId, batch);
        return view(batch, results, null);
    }

    /**
     * 撤销批次（后台 job，issue #8283）：claim 后提交线程池，立即返回 {@code executing}；
     * 终态由 {@link #get(Long, String)} 查询。
     */
    public AgentBatchViews.Batch revertAsync(Long tenantId, String batchId) {
        AgentBatch batch = claimForRevert(tenantId, batchId);
        AgentBatchViews.Batch accepted = view(batch, null, null);
        submit(tenantId, batchId, () -> runRevert(tenantId, batch));
        return accepted;
    }

    /** 撤销准入：状态检查 + 测试探针 + CAS 抢撤销权；返回已置 executing 的批次。 */
    private AgentBatch claimForRevert(Long tenantId, String batchId) {
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
        // 测试探针（issue #6960）：同 execute —— 放大「读-判」与「抢撤销权」之间的窗口（生产恒为 0）。
        if (BATCH_PROBE_PAUSE_MILLIS > 0) {
            pauseForBatchProbe(BATCH_PROBE_PAUSE_MILLIS);
        }
        // 抢撤销权：条件更新（CAS）—— 0 行 ⇒ 并发的另一个请求已抢到（或状态已不可撤销）⇒ 一条不写
        if (batchMapper.markReverting(batchId, tenantId, STATUS_DONE, STATUS_PARTIAL) == 0) {
            AgentBatch fresh = requireBatch(tenantId, batchId);
            throw BusinessException.conflict("批次当前状态为 " + fresh.getStatus()
                            + "，可撤销状态只有 " + STATUS_DONE + " / " + STATUS_PARTIAL,
                    "请先执行该批次，再撤销");
        }
        batch.setStatus(STATUS_EXECUTING);
        return batch;
    }

    /**
     * 逐条撤销（同步 / 异步共用）：只还原执行成功的条目；skipped 逐条报出，不误写。
     *
     * <p>job 级异常（例如读 items 失败）也落 {@code revert_partial}，避免永远停在
     * {@code executing}；已还原的条目仍按 DB 中的 item 状态逐条可核。</p>
     */
    private List<AgentBatchViews.Result> runRevert(Long tenantId, AgentBatch batch) {
        String batchId = batch.getId();
        List<AgentBatchItem> items;
        try {
            items = itemsOf(batchId);
        } catch (RuntimeException e) {
            log.error("[Agent] 批量撤销读取明细失败，落 revert_partial: batchId={}", batchId, e);
            batch.setStatus(STATUS_REVERT_PARTIAL);
            batch.setRevertedAt(OffsetDateTime.now());
            batchMapper.updateById(batch);
            return List.of();
        }

        List<AgentBatchViews.Result> results = new ArrayList<>(items.size());
        int failed = 0;
        for (AgentBatchItem item : items) {
            if (Thread.currentThread().isInterrupted()) {
                log.warn("[Agent] 批量撤销被中断，剩余条目保持原状态: batchId={}", batchId);
                failed++;
                continue;
            }
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
        return results;
    }

    // ══════════════════════════════════════════════════════════════════════════════════
    // 测试探针（issue #6960）：**只在包内可见**，生产恒为 0
    // ══════════════════════════════════════════════════════════════════════════════════

    /**
     * 把 {@link #execute} / {@link #revert} 的「读-判」与「抢权（CAS）」之间的窗口拉长到指定毫秒
     * （生产默认 0 = 不暂停；只在包内可见，{@code AgentBatchStatusRaceRealDbTest} 与生产同类同包）。
     *
     * <p><b>为什么需要它</b>：窗口注入是竞态类缺陷的**唯一可信证据**形态 —— 判据要在
     * 「注入 ⇒ 必红 / 撤回 ⇒ 复绿」两侧各跑一次（{@code migao-dev-flow} §28.1）。
     * 缺陷窗口本身只有微秒级，不注入就只能靠碰运气 ⇒ 判据会退化成 flake。</p>
     *
     * <p><b>为什么放在这里而不是只放测试侧</b>：窗口在服务方法体内，测试侧无法在
     * 「已判定仍可执行、尚未抢权」那一刻插进一段延时（除非用 {@code mock()} 替换真 mapper ——
     * 那会把唯一的 DB 原子判据换成 mock 的恒真返回，判据当场失去意义）。</p>
     *
     * <p>⚠️ 探针**只让第一个到达者停顿**（后续到达者直接穿过）：一个「把所有并发者都停住」
     * 的闸会让两条判据线程都停在窗口里，而「后到者能否补位」这件事就测不出来。
     * 单占位与 {@link #setBatchProbePauseMillisForTest} 合起来才构成确定性的两段式时序
     * （先起跑者在窗口里、对手走完全程并提交，先起跑者再续跑）。</p>
     */
    static void setBatchProbePauseMillisForTest(long millis) {
        BATCH_PROBE_PAUSE_MILLIS = millis;
    }

    /** 测试探针时长（默认 0 = 不暂停）；见 {@link #setBatchProbePauseMillisForTest}。 */
    private static volatile long BATCH_PROBE_PAUSE_MILLIS = 0L;

    /** 探针**正在**暂停窗口内的信号（测试用它把「读-判已过、尚未抢权」这一刻钉住）。 */
    private static volatile boolean batchProbePaused = false;

    /** 探针占位（默认 = 未被占）：只让**第一个**到达者停顿，后面的直接穿过。 */
    private static final java.util.concurrent.atomic.AtomicBoolean BATCH_PROBE_TAKEN =
            new java.util.concurrent.atomic.AtomicBoolean(false);

    /** 测试观察点：探针是否已进入暂停窗口；生产不读。 */
    static boolean batchProbePausedForTest() {
        return batchProbePaused;
    }

    /** 进入窗口 ⇒ 抢占位（抢到者置位 → 停 → 清位；没抢到的直接返回）。 */
    private static void pauseForBatchProbe(long millis) {
        if (!BATCH_PROBE_TAKEN.compareAndSet(false, true)) {
            return;   // 窗口已被另一个线程占着 ⇒ 本线程直接穿过（两段式时序的另一半由判据编排）
        }
        batchProbePaused = true;
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } finally {
            // 🔴 清位在**窗口结束时**（不是更早）：判据要靠「正在暂停」这个信号把对手放进窗口，
            // 提前清位会让对手以为自己就是起跑者（两条线程都「等在窗口里」= 没人在窗口外走全程）
            batchProbePaused = false;
            BATCH_PROBE_TAKEN.set(false);
        }
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
            // 金额精度准入（issue #6228）：批次值来自**外部输入**（Excel/表格），`products.base_price`
            // 是 NUMERIC(·,2) ⇒ 超 2 位有效小数会被 PG 静默四舍五入。判在下游单条写路径之前。
            update.setBasePrice(MoneyScale.requireTwoDecimalsOrNull(new BigDecimal(value), "商品价格 price"));
        } else if (FIELD_STOCK.equals(item.getField())) {
            update.setStock(new BigDecimal(value));
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
        if (FIELD_STOCK.equals(field)) {
            // 🔴 库存批量的工作值 = **每个规格（SKU）**的库存，不是商品级汇总（issue #5950 复核订正）。
            //
            // 为什么不能用响应里的 `stock`：`getProductById` 把它覆盖成 **SKU 汇总**
            // （`response.setStock(totalStock)`，唯一权威是 SKU 级 = #4038）—— 而本批量的执行
            // 口径是「该商品的每个规格都置为 X」⇒ 拿汇总当 before/after 会在**多 SKU 商品**上
            // 三方不自洽：预览显示 40→100，实际汇总变 100×N，撤销逐规格回 40 ⇒ 汇总 40×N ≠ 40
            // （回不到原状 = 撤销语义失效）。
            // ⇒ 准入改为：**≥1 个 SKU 且各规格库存一致**，工作值取该一致值；不一致 ⇒ 整批拒绝
            // （预演表必须可信：一条 before 是错的，那张表就不再可信）。
            // 顺带堵住「无 SKU 商品执行静默空转」：那种商品没有任何 SKU 行可写，
            // `syncProductStockFromSkus` 也会早退 ⇒ 只写派生列 ⇒ 回读不变（假成功）。
            return uniformSkuStock(product, resourceId);
        }
        return product.getStatus();
    }

    /** 库存批量的工作值（= 每个规格的库存）—— 要求 **≥1 个 SKU 且各规格一致**，否则 fail-closed。 */
    private String uniformSkuStock(ProductResponse product, String resourceId) {
        List<ProductSkuResponse> skus = product.getSkus();
        if (skus == null || skus.isEmpty()) {
            throw BusinessException.validationError("商品没有 SKU 规格，无法逐规格调整库存：" + resourceId
                    + "（商品级库存只是 SKU 汇总的派生展示值）—— 请先在商品管理页维护规格"
                    + "（颜色 / 门幅 + 各自库存）后重试");
        }
        // 按**值**去重（40 与 40.0 是同一个库存）——与 `AgentWriteValues` 同一口径
        Set<String> distinct = new LinkedHashSet<>();
        for (ProductSkuResponse sku : skus) {
            BigDecimal stock = sku.getStock() == null ? BigDecimal.ZERO : sku.getStock();
            distinct.add(stock.stripTrailingZeros().toPlainString());
        }
        if (distinct.size() > 1) {
            throw BusinessException.validationError("该商品各规格库存不一致（"
                    + String.join(" / ", distinct) + "）：" + resourceId
                    + " —— 批量库存调整按**规格逐值**预览与撤销，故要求每个规格库存相同"
                    + "（否则预览与撤销都会失真）。请先在商品管理页把各规格调成一致，"
                    + "或在商品管理页逐个规格调整");
        }
        return distinct.iterator().next();
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
        if (FIELD_STOCK.equals(field)) {
            // 精度准入与**建品/改品路径同一收口**（`StockQuantity`，issue #5063）：> 1 位小数
            // 显式拒绝，不静默取整（账面与实物不符且无人发现）。负库存由单条写路径的既有校验管。
            try {
                StockQuantity.requireOneDecimal(new BigDecimal(value), "批量库存 stock");
            } catch (NumberFormatException e) {
                throw BusinessException.validationError("改后库存不是合法数字：" + resourceId + " ⇒ " + value);
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

    /**
     * 提交后台 job；线程池拒绝（例如已 shutdown）时退化为同步执行。
     *
     * <p>不吞 job 内部异常：逐条失败 / 读取失败已在 {@link #runBatch} / {@link #runRevert}
     * 内落成 partial（可撤销）；这里只兜「任务根本没被接收」。</p>
     */
    private void submit(Long tenantId, String batchId, Runnable job) {
        try {
            batchExecutor.execute(job);
        } catch (TaskRejectedException e) {
            log.warn("[Agent] 批次线程池拒绝任务，改为同步执行: batchId={}, tenantId={}",
                    batchId, tenantId, e);
            job.run();
        }
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