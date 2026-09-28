package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.WorkerInboundDraftRequest;
import com.migao.admin.dto.WorkerInboundDraftView;
import com.migao.admin.dto.WorkerInboundPostRequest;
import com.migao.admin.dto.WorkerInboundRecognizeRequest;
import com.migao.admin.dto.WorkerInboundRecognizeResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.WorkerInboundService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerSessionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 工人可达的入库端点（issue #5052 <b>P1</b>）：{@code /api/worker/inbound/**}。
 *
 * <h3>为什么必须是新路径（设计 §5.1，两条实测理由）</h3>
 * <ol>
 *   <li>唯一可用的识别控制器 {@code ImageRecognitionController} 挂在 {@code /api/admin/image-recognition}，
 *       而 {@code /api/admin/**} 的门禁把 {@code worker} 列在 {@code ADMIN_API_REJECTED_ROLES} 里 ⇒ 被拒；</li>
 *   <li>即便放行，该控制器的权限码**按 target 取**（{@code product:create} / {@code order:create}），
 *       而工人**零商家权限码** ⇒ 仍被 {@code requirePermission} 拒。
 *       ⇒ 「工人拍照识别」这条链**必须新建工人可达入口**；<b>不得</b>靠给工人挂商家权限码来「复用」
 *       现有端点（那正是 #4727 要防的形态，设计 §11.2 N3）。</li>
 * </ol>
 *
 * <h3>载体分离（设计 §5.3 硬约束 3 / §9.3 红线）</h3>
 * <p>本控制器**不注入** {@code PermissionInterceptor}、**没有**任何 {@code @RequirePermission} ——
 * 准入判据只有一条：<b>有效工人 session</b>（{@link WorkerSessionService#resolveIdentity}；
 * 无 / 已结束 / 已闲置超时 ⇒ 401）。工人**零商家权限码**在这里是**结构事实**，不是配置。</p>
 *
 * <h3>身份纪律（同 {@code WorkerProductionController}，一字不改）</h3>
 * <p>身份**只**从 {@code X-Worker-Session-Id} 解；body 里的 {@code worker_id} / {@code operator} /
 * {@code tenantId} **连读取代码都没有**（请求 DTO 里根本没这几个键）。</p>
 *
 * <h3>本包只有三个端点</h3>
 * <p>标签位图 / 短码 / 打印计数（P2）、工人端页面（P3）、打印适配层（P4）、拍照补打（P5）
 * **不在本包**（{@code #5052} 的实现切包计划）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/worker/inbound")
@RequiredArgsConstructor
public class WorkerInboundController {

    /**
     * 幂等键请求头（设计 §5.2 / §9.2：建单与过账都带 {@code Idempotency-Key}）。
     *
     * <p>名字取设计单逐字的那一个；实现侧**复用** {@code ClientRequestIdService}
     * （同键去重 / 结果回放 / 快照 / 陈旧回收的唯一实现，issue #4037），
     * <b>不新建第二套幂等表</b>。</p>
     */
    public static final String IDEMPOTENCY_HEADER = "Idempotency-Key";

    private final WorkerInboundService workerInboundService;
    private final WorkerSessionService workerSessionService;

    /**
     * 上传照片 → 识别候选（<b>不落库、不动库存</b>）。
     *
     * <p>POST /api/worker/inbound/recognize，body {@code {images, barcode}}。</p>
     */
    @PostMapping("/recognize")
    public ApiResponse<WorkerInboundRecognizeResponse> recognize(
            @RequestBody(required = false) WorkerInboundRecognizeRequest body,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        requireWorker(sessionId);
        return ApiResponse.success(workerInboundService.recognize(body, TenantContext.getTenantId()));
    }

    /**
     * 建入库单草稿（一个入库单行 = 一个 SKU；**草稿态完全不动库存**）。
     *
     * <p>POST /api/worker/inbound/drafts，body 见 {@link WorkerInboundDraftRequest}。</p>
     */
    @PostMapping("/drafts")
    public ApiResponse<WorkerInboundDraftView> createDraft(
            @RequestBody(required = false) WorkerInboundDraftRequest body,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId,
            @RequestHeader(value = IDEMPOTENCY_HEADER, required = false) String idempotencyKey) {
        WorkerIdentity identity = requireWorker(sessionId);
        return ApiResponse.success(workerInboundService.createDraft(
                body, TenantContext.getTenantId(), identity.workerId(), idempotencyKey));
    }

    /**
     * 提交过账（<b>过账才动库存</b>）。
     *
     * <p>POST /api/worker/inbound/drafts/{id}/post，body {@code {confirmed:true}}。</p>
     */
    @PostMapping("/drafts/{id}/post")
    public ApiResponse<WorkerInboundDraftView> post(
            @PathVariable("id") String draftId,
            @RequestBody(required = false) WorkerInboundPostRequest body,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId,
            @RequestHeader(value = IDEMPOTENCY_HEADER, required = false) String idempotencyKey) {
        WorkerIdentity identity = requireWorker(sessionId);
        return ApiResponse.success(workerInboundService.postDraft(
                draftId, body, TenantContext.getTenantId(), identity.workerId(), idempotencyKey));
    }

    /** 有效工人 session 或 401（fail-closed 的**唯一**一处判据：工人路径上「谁」没有第二条来源）。 */
    private WorkerIdentity requireWorker(String sessionId) {
        WorkerIdentity identity = workerSessionService.resolveIdentity(sessionId);
        if (identity == null) {
            throw BusinessException.authFailed("尚未登录工人身份，请先用工号 + PIN 登录");
        }
        return identity;
    }
}
