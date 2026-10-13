package com.migao.admin.controller;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.User;
import com.migao.admin.service.WorkerAdminService;
import com.migao.admin.worker.WorkerIdentity;
import com.migao.admin.worker.WorkerPages;
import com.migao.admin.worker.WorkerSessionService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 工人端**身份 + 页面**只读端点（V141，母单 #5161）：{@code GET /api/worker/me}。
 *
 * <h3>它回答什么</h3>
 * <p>「我是谁 + 给我开了哪几个工人端页面」—— 工人端 H5 / 车间一体机登录后**第一件事**就是
 * 拉它决定渲染哪些页。</p>
 *
 * <h3>页面集 = 工人档案上的收窄（唯一一层，issue #6828）</h3>
 * <p>企业级页面开关（表 {@code worker_page_configs} / 设置页「工人端页面」域）已整层移除 ——
 * 这里下发的是 {@code users.worker_pages}（V152，issue #6788）的**单层**求值：
 * 未收窄 / 坏值 ⇒ 全部页面（fail-open）；收窄 ⇒ 收窄集（见 {@link WorkerPages#effectiveFor}）。
 * 档案查不到同样按未收窄（fail-open：绝不把工人挡在活外面）。</p>
 *
 * <h3>🔴 它不下发任何权限（本类的存在理由就是不下发权限）</h3>
 * <ul>
 *   <li>响应里的 {@code pages} 是**页面可见性**（工人档案级），<b>不是</b>权限码，
 *       <b>不得</b>被写进 {@code users.permissions}；</li>
 *   <li>工人 session 的 {@code permissions} <b>恒为 {@code []}</b>、{@code roles} 恒为
 *       {@code ["worker"]}（{@code WorkerSessionService}），工人可达面恒为 {@code /api/worker/**}，
 *       {@code /api/admin/**} 对 {@code worker} 一律 403（{@code SecurityConfig}）；</li>
 *   <li>把某个页面从 {@code pages} 里去掉<b>不等于</b>挡住对应接口 —— 服务端对每个工人都仍然
 *       按同一套授权判（页面开关只是「看不看得见」）。</li>
 * </ul>
 *
 * <p>⚠️ 本控制器**独立**于 {@code WorkerProductionController}（报工面）：报工面只回答「这笔活记到谁头上」，
 * 本面只回答「工人端有哪些页面」—— 两件事分开，改一处不影响另一处的判据。</p>
 */
@RestController
@RequestMapping("/api/worker")
@RequiredArgsConstructor
public class WorkerProfileController {

    private final WorkerSessionService workerSessionService;
    private final WorkerAdminService workerAdminService;

    /**
     * 当前工人身份 + 这位工人被开放的工人端页面。
     *
     * <p>无有效工人 session ⇒ 服务层抛 401（**不降级**成匿名或 body 口径）。</p>
     */
    @GetMapping("/me")
    public ApiResponse<Map<String, Object>> me(
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        WorkerIdentity identity = workerSessionService.resolveIdentity(sessionId);

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("worker_id", identity.workerId());
        data.put("worker_name", identity.workerName());
        data.put("session_id", identity.sessionId());
        data.put("identity_source", identity.source());
        // 页面集 = 本工人档案上的收窄（issue #6788）的单层求值（issue #6828 移除企业级层）：
        // 未收窄（null / 坏值）⇒ 全部页面；收窄 ⇒ 收窄集。档案查不到 ⇒ 同上（fail-open：
        // 绝不因读不到档案把工人挡在活外面）。
        List<String> effective = WorkerPages.effectiveFor(workerPagesOf(identity.workerId()));
        data.put("pages", effective);
        return ApiResponse.success(data);
    }

    /** 本工人档案上的页面收窄原值（{@code null} = 未收窄）；查不到档案 ⇒ {@code null}（fail-open）。 */
    private String workerPagesOf(String workerId) {
        User worker = workerAdminService.findOwnedWorker(workerId);
        return worker == null ? null : worker.getWorkerPages();
    }
}
