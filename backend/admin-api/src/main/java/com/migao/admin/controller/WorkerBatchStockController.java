package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.WorkerBatchCorrectionRequest;
import com.migao.admin.dto.WorkerBatchStockViews;
import com.migao.admin.service.WorkerBatchStockService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 工人端**批次库存修正**（issue #8104）——{@code /api/worker/batch-stock/**}。
 *
 * <p>用户 2026-10-29 逐字：「手机端还要增加一个库存修正的功能，apk程序也要同步增加这个功能，
 * 允许工人对某个批次的布匹进行修正」。</p>
 *
 * <h3>两个端点（一个读面、一个写面）</h3>
 * <ol>
 *   <li>{@code GET /api/worker/batch-stock/batches?keyword=&page=&size=} —— 按批次找
 *       （批次号 / 旧系统批次号 / 货号 / 缸号 / 入库单号任一段），回余量 + 品名 + <b>原因闭词表</b>；</li>
 *   <li>{@code POST /api/worker/batch-stock/correction} —— 选一个批次、填实盘米数、选原因，提交修正。</li>
 * </ol>
 *
 * <h3>五条边界（每条都在实现里，不靠约定）</h3>
 * <ul>
 *   <li><b>零商家权限码</b>：本路径在 {@code /api/worker/**} 内 ⇒ 工人 {@code permissions=[]}，
 *       挂 {@code @RequirePermission} 只会恒 403；准入 = 有效工人 session（无 ⇒ 401，fail-closed）；</li>
 *   <li><b>身份只由会话解</b>：请求体结构上**没有** {@code worker_id} / {@code worker_name}
 *       （{@link WorkerBatchCorrectionRequest} 的字段集就是能力集）⇒ 想冒名的人改前端也没用；</li>
 *   <li><b>租户只由会话解</b>：{@link TenantContext#getTenantId()} 由 {@code WorkerSessionFilter}
 *       从会话行定下来；跨租户的批次 id ⇒ 404（查不到，不泄露存在性）；</li>
 *   <li><b>不写第二套库存账</b>：本控制器只调 {@link WorkerBatchStockService}，后者复用
 *       {@code BatchStocktakeService#stocktake}（批次分录 + SKU 库存同一事务）；</li>
 *   <li><b>幂等</b>：{@code clientRequestId} 是必填的幂等键（缺 / 形态非法 ⇒ 422），
 *       重试 / 连点只记一笔。</li>
 * </ul>
 */
@Slf4j
@RestController
@RequestMapping("/api/worker/batch-stock")
@RequiredArgsConstructor
public class WorkerBatchStockController {

    private final WorkerBatchStockService workerBatchStockService;
    private final WorkerSessionService workerSessionService;

    /**
     * 按批次搜（工人认布：品名 + 货号 + 缸号 + 系统余量）。
     *
     * <p>{@code keyword} 可为空 = 最近入库的批次（工人可以直接浏览）；
     * {@code page} 从 1 起、{@code size} 服务端夹到上限（{@code StockBatchConsumptionService} 的既有口径）。</p>
     */
    @GetMapping("/batches")
    public ApiResponse<WorkerBatchStockViews.BatchPage> batches(
            @RequestParam(name = "keyword", required = false) String keyword,
            @RequestParam(name = "page", defaultValue = "1") long page,
            @RequestParam(name = "size", defaultValue = "20") long size,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        WorkerIdentity identity = workerSessionService.resolveIdentity(sessionId);
        if (identity == null) {
            throw com.migao.admin.exception.BusinessException.authFailed(
                    "尚未登录工人身份，请先用工号 + PIN 登录");
        }
        return ApiResponse.success(workerBatchStockService.search(
                TenantContext.getTenantId(), keyword, page, size));
    }

    /**
     * 提交一次修正（实盘为准）。
     *
     * <p>回执三态（与按批次盘点同源）：{@code applied} 真的落账 · {@code unchanged} 实盘 == 系统余量
     * （零写入）· {@code replayed} 同一次提交此前已记过（幂等回放，未重复修正）。</p>
     */
    @PostMapping("/correction")
    public ApiResponse<WorkerBatchStockViews.Correction> correction(
            @RequestBody(required = false) WorkerBatchCorrectionRequest request,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        WorkerIdentity identity = workerSessionService.resolveIdentity(sessionId);
        if (identity == null) {
            throw com.migao.admin.exception.BusinessException.authFailed(
                    "尚未登录工人身份，请先用工号 + PIN 登录");
        }
        log.info("工人库存修正请求: tenant={}, worker={}, batch={}", TenantContext.getTenantId(),
                identity.workerName(), request == null ? null : request.getBatchId());
        return ApiResponse.success(workerBatchStockService.correct(
                TenantContext.getTenantId(), identity, request));
    }
}
