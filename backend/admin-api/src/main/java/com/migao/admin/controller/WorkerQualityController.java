package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.User;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.QualityCheckService;
import com.migao.admin.service.WorkerAdminService;
import com.migao.admin.time.BusinessClock;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerPages;
import com.migao.admin.worker.WorkerSessionService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 工人端**质检单**（issue #7162，用户 2026-10-17 裁定）。
 *
 * <h3>为什么有这个面</h3>
 * <p>用户逐字：「工人不能进入观星台，维持这个设计，现在只需要在小程序端扫码进入报工页后
 * 有入口进行质检即可」「因为工人主要通过扫水洗唛进入质检流程」「质检等同发货工序一样，
 * 打包发货完成后生成发货单，质检完成后生成质检单，一样的意思」。</p>
 *
 * <p>⇒ 质检的**录入面**从「只有观星台」扩到「工人端也能录」，但工人会话**不进** {@code /api/admin/**}
 * （该前缀对 {@code worker} 一律 403，见 {@code SecurityConfig.ADMIN_API_REJECTED_ROLES}）——
 * 所以本控制器单独挂在 {@code /api/worker/quality/**} 上。</p>
 *
 * <h3>🔴 授权（不是「藏起按钮」）</h3>
 * <p>写/读都要求该工人档案的页面集里有 {@link WorkerPages#INSPECT}（{@code inspect}）——
 * 这是 {@code users.worker_pages} 上**唯一**一个被当作服务端准入的页面键（见
 * {@link WorkerPages} 类注释的例外条）。没有该键 ⇒ <b>403</b>，与「界面不显示入口」是两件事。</p>
 *
 * <h3>🔴 检验人身份</h3>
 * <p>只从 {@code X-Worker-Session-Id} 解（{@link WorkerSessionService#resolveIdentity}）——
 * body 里的 {@code worker_id} / {@code inspector_id} 一个字节都不读。落库时
 * {@code inspector_kind='worker'}、{@code inspector_id/name} = 该工人（工资/责任凭证不能信前端）。</p>
 *
 * <p>本面**不重算任何数量**、不碰报工：报工（数量事实）与质检（成品帘判定）两套口径并存。</p>
 */
@RestController
@RequestMapping("/api/worker/quality")
@RequiredArgsConstructor
public class WorkerQualityController {

    /** 质检记录读面上限（issue #7973，§31 P1：常驻面克制，一屏最多 20 条）。 */
    private static final int RECORD_LIMIT = 20;

    private final WorkerSessionService workerSessionService;
    private final WorkerAdminService workerAdminService;
    private final QualityCheckService qualityCheckService;
    private final BusinessClock businessClock;

    /**
     * 某件成品帘的**最新质检判定 + 记录列表**（无记录 ⇒ {@code latest=null}、{@code records=[]}）。
     *
     * <p>工人扫水洗唛后，报工页用这个读面渲染「质检记录（做工）」块并判断是否处于「待复检」。
     * 件 = 套号 × 部位（issue #7945 / #7973）：给了 {@code set_no} ⇒ 只读这一件，
     * {@code latest} 与 {@code records[0]} **同源**（多套同部位不串）；没给 ⇒ 沿用按部位行的存量口径。</p>
     */
    @GetMapping("/latest")
    public ApiResponse<Map<String, Object>> latest(
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId,
            @RequestParam(name = "order_item_id", required = false) String orderItemId,
            // issue #7973：件 = 套号 × 部位；只按部位行取最新会把多套同部位串件
            @RequestParam(name = "set_no", required = false) String setNo) {
        requireInspector(sessionId);
        Long tenantId = TenantContext.getTenantId();
        List<Map<String, Object>> records = qualityCheckService.records(tenantId, orderItemId, setNo, RECORD_LIMIT);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("order_item_id", orderItemId);
        data.put("set_no", setNo);
        // 未检 ≠ 合格：没有记录就如实给 null（读面不编值）。
        // 件级（set_no 给了）⇒ latest 与 records 第一行**同源**（不再另走按部位行的 DISTINCT ON）；
        // 没给套号（存量 / 旧调用方）⇒ 沿用既有 latest（按部位行，不猜套）。
        data.put("latest", StringUtils.hasText(setNo)
                ? (records.isEmpty() ? null : records.get(0))
                : qualityCheckService.latest(tenantId, orderItemId));
        // 记录列表（最新在前）：页面「质检记录（做工）」块 + 待复检门禁的**唯一**数据源
        data.put("records", records);
        return ApiResponse.success(data);
    }

    /**
     * 录入一条质检判定 ⇒ 生成一张**质检单**（= {@code quality_inspections} 的一行）。
     *
     * <p>body = {@code {order_item_id, set_no?, result ∈ pass|rework|scrap, reason?, recheck?}}；
     * 判定 ≠ 合格 ⇒ 原因必填（缺 ⇒ 422 具名报错、零写入 —— 与观星台同一份服务层校验，不重造第二份）。</p>
     *
     * <p>🔴 件级闭环（issue #7973）：这一件最新判定 = {@code rework} 且 {@code recheck != true}
     * ⇒ 409（「正在等复检」），不给盲重复提交；【复检通过】用 {@code result=pass}，
     * 【复检仍有问题】用 {@code result=rework&recheck=true}（显式的新一轮判定）。</p>
     */
    @PostMapping("/inspections")
    public ApiResponse<Map<String, Object>> create(
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId,
            @RequestBody(required = false) Map<String, Object> body) {
        WorkerIdentity me = requireInspector(sessionId);
        Long tenantId = TenantContext.getTenantId();
        String orderItemId = str(body, "order_item_id");
        String result = str(body, "result");
        String setNo = str(body, "set_no");
        // 件级闭环（issue #7973）：同一件已记「做工返工」且未复检 ⇒ 拒普通的重记
        requireNoPendingRework(tenantId, orderItemId, setNo, result, flag(body, "recheck"));
        return ApiResponse.success(qualityCheckService.create(
                tenantId,
                orderItemId,
                result,
                str(body, "reason"),
                me.workerId(),
                me.workerName(),
                QualityCheckService.INSPECTOR_WORKER,
                // 🔴 业务时钟单点（issue #3802 / BusinessClockSourceGuardTest）：不在这里写时区字面量
                businessClock.nowOffset(),
                // issue #7165：工人端录判定 ⇒ 合格时联动完成「质检」工序，计件记给这位工人
                me,
                // issue #7945：件 = 套号 × 部位；多套未给 ⇒ 服务端 422（不猜第 1 套）
                setNo));
    }

    /**
     * 件级闭环（issue #7973）：最新判定 = {@code rework} ⇒ 这一件处于「待复检」，普通「记返工」被拒（409）。
     *
     * <p>🔴 为什么要有 {@code recheck} 这个显式入口：修好了要【复检通过】（{@code pass}），
     * 没修好要【复检仍有问题】——后者是**新的一轮**判定（允许追加），不是盲重复提交。
     * 两条路都必须由复检动作触发；只有它能把「报了还能一直报」变成「一次问题一条记录」。
     * 服务端不验证「实物真的复检过」（与录入判定同一信任级：师傅点这一下就是复检动作）。</p>
     */
    private void requireNoPendingRework(Long tenantId, String orderItemId, String setNo,
                                        String result, boolean recheck) {
        if (!"rework".equals(result) || recheck) {
            return;
        }
        Map<String, Object> latest = qualityCheckService.latestForPiece(tenantId, orderItemId, setNo);
        if (latest == null || !"rework".equals(latest.get("result"))) {
            return;
        }
        throw new BusinessException("QUALITY_REWORK_PENDING",
                "这一件已记「做工返工」，正在等复检",
                409,
                "请在质检记录里点「复检通过」（修好了）或「复检仍有问题」（还没修好）；后者会追加一条新判定");
    }

    /** body 布尔开关（缺键 / 非 true ⇒ false；不把字符串 "false" 当真）。 */
    private static boolean flag(Map<String, Object> body, String key) {
        if (body == null) {
            return false;
        }
        Object v = body.get(key);
        return Boolean.TRUE.equals(v) || "true".equalsIgnoreCase(String.valueOf(v));
    }

    /**
     * 当前工人必须是「被逐人开了质检页」的工人（否则 403），并返回其服务端身份。
     *
     * <p>档案查不到 / 页面集里没有 {@code inspect} ⇒ 同一个 403（不区分「没有这个工人」与
     * 「没开这个页」，避免把档案存在性当探针）。</p>
     */
    private WorkerIdentity requireInspector(String sessionId) {
        // 无有效工人 session ⇒ 401（resolveIdentity 内部 fail-closed，不降级成 body 口径）
        WorkerIdentity me = workerSessionService.resolveIdentity(sessionId);
        User worker = workerAdminService.findOwnedWorker(me.workerId());
        Set<String> granted = WorkerPages.restrictedOrNull(worker == null ? null : worker.getWorkerPages());
        if (granted == null || !granted.contains(WorkerPages.INSPECT)) {
            throw BusinessException.permissionDenied();
        }
        return me;
    }

    /** body 取值（缺键 ⇒ null；**不**从 body 取租户 / 检验人身份）。 */
    private String str(Map<String, Object> body, String key) {
        if (body == null) {
            return null;
        }
        Object v = body.get(key);
        return v == null ? null : String.valueOf(v);
    }
}
