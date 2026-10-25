// case_ids: WH-007, WH-008
package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.FinishedGoodsService;
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

import java.util.Map;

/**
 * 工人端**扫水洗唛出库**（V197 / issue #7762）。
 *
 * <p>用户口径（2026-10-25）：「允许工人扫码水洗唛进行成品出库打标签操作」「只有关联打包工序的
 * 工人扫码后才能操作出库」—— 本条动线因此落在**移动端报工页**，不新造菜单：扫水洗唛 → 报工页
 * 显示「成品出库」卡片（标签预览 + 打印 + 出库）→ 出库即写成品出库单（{@code source=scan}）。</p>
 *
 * <p>🔴 授权在**服务端**：工人身份只从 {@code X-Worker-Session-Id} 解出（body 里的同名字段一律不信），
 * 「是不是打包工序工人」由 {@code production_work_logs} 的既有报工记录判 —— 前端只负责隐藏按钮，
 * 绕过前端也拿不到 403 以外的结果。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/worker/stock")
@RequiredArgsConstructor
public class WorkerFinishedStockController {

    private final FinishedGoodsService finishedGoodsService;
    private final WorkerSessionService workerSessionService;

    /**
     * 扫水洗唛的只读视图：标签内容 + 能否出库（{@code allowed / reason / bin_code / label}）。
     *
     * <p>GET /api/worker/stock/wash-label?token=…（token 或短码 / 整条印刷 URL）</p>
     */
    @GetMapping("/wash-label")
    public ApiResponse<Map<String, Object>> washLabel(
            @RequestParam("token") String token,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        WorkerIdentity identity = requireWorker(sessionId);
        return ApiResponse.success(finishedGoodsService.washLabelView(
                TenantContext.getTenantId(), token, identity.workerId(), identity.workerName()));
    }

    /**
     * 扫水洗唛出库（幂等：同一张码第二次提交 ⇒ 409「已经出库」，不会重复扣减、不会建第二张单）。
     *
     * <p>POST /api/worker/stock/finished-outbound body {@code {"token": "…"}}</p>
     */
    @PostMapping("/finished-outbound")
    public ApiResponse<Map<String, Object>> finishedOutbound(
            @RequestBody Map<String, String> body,
            @RequestHeader(value = WorkerSessionService.SESSION_HEADER, required = false) String sessionId) {
        WorkerIdentity identity = requireWorker(sessionId);
        String token = body == null ? null : body.get("token");
        return ApiResponse.success(finishedGoodsService.issueByWashLabel(
                TenantContext.getTenantId(), token, identity.workerId(), identity.workerName()));
    }

    private WorkerIdentity requireWorker(String sessionId) {
        WorkerIdentity identity = workerSessionService.resolveIdentity(sessionId);
        if (identity == null) {
            throw BusinessException.authFailed("尚未登录工人身份，请先用工号 + PIN 登录");
        }
        return identity;
    }
}
