package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.DailyBriefing;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.entity.BriefingAction;
import com.migao.admin.service.AuditLogService;
import com.migao.admin.service.BriefingActionService;
import com.migao.admin.service.DailyBriefingService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 智能每日经营简报控制器（issue #3468，设计文档 docs/design/daily-briefing-design.md v0.2）
 *
 * 接口：
 * - GET  /api/admin/briefing/today      → 今日简报（未生成返回空态，前端引导）
 * - GET  /api/admin/briefing/config     → 简报配置（开关 + 生成时刻；菜单显隐用）
 * - PUT  /api/admin/briefing/config     → 更新配置（仅 admin，system:manage）
 * - POST /api/admin/briefing/generate   → 手动触发当日生成（仅 admin）
 *
 * 权限：查看 = dashboard:view（与看板同域）；配置读写/手动生成 = system:manage（admin）。
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/briefing")
@RequiredArgsConstructor
public class BriefingController {

    private final DailyBriefingService dailyBriefingService;
    private final BriefingActionService briefingActionService;
    private final AuditLogService auditLogService;

    /**
     * 今日简报。未生成返回 data=null + generated=false，
     * 前端展示「今日简报尚未生成」引导空态（不展示假数据，红线 4）。
     */
    @RequirePermission("dashboard:view")
    @GetMapping("/today")
    public ApiResponse<Map<String, Object>> getToday() {
        Long tenantId = TenantContext.getTenantId();
        DailyBriefing briefing = dailyBriefingService.getTodayBriefing(tenantId);
        Map<String, Object> resp = new HashMap<>();
        resp.put("generated", briefing != null);
        resp.put("verifyStatus", briefing != null ? briefing.getVerifyStatus() : null);
        resp.put("content", briefing != null ? briefing.getContent() : null);
        resp.put("bizDate", briefing != null ? briefing.getBizDate().toString() : null);
        // 逐规则接线状态（issue #5955）：由 ai-agent 引擎在 `sanitize_briefing` **之后**挂上、
        // admin-api 生成时**原样**落库 —— 这里同样只**透传**：不做对账、不重算、不改写
        // （它不是数字，不许进 `verifyAndFilter` 那套数值回填口径）。null = 未采集
        // （本列面世前的存量行）⇒ 前端据此**不渲染**该面板（未知 ≠ 没问题）。
        resp.put(DailyBriefingService.PROACTIVE_STATUS_FIELD,
                briefing != null ? briefing.getProactiveStatus() : null);
        // 主动发现（族 1 · 包 1，issue #5322）：把**聚合快照**（确定性层产出）一并返回，
        // 供 ai-agent 侧 `briefing_query` 做确定性规则扫描 —— 与简报**同源** ⇒ 两个入口口径一致。
        // 快照只含聚合数字 + 脱敏事实（无客户 PII，见 aggregateSnapshot）。
        resp.put("sourceSnapshot", briefing != null ? briefing.getSourceSnapshot() : null);
        return ApiResponse.success(resp);
    }

    /**
     * 确定性快照（**按需**消费入口，族 3 · 包 2，issue #5369）。
     *
     * <p>与 `/today` 的区别：`/today` 返回**已生成**的简报（依赖 LLM 生成链路，未生成即空态），
     * 本端点**不碰 LLM**、纯确定性装配 —— 供 ai-agent 侧「具名跨域视图」（如 `product_health`）
     * 按需下钻：同一份内核快照 ⇒ 两个入口（主动日报 / 按需视图）口径一致。</p>
     *
     * <p>租户取会话上下文（`TenantContext`），权限码与 `/today` 同码（`dashboard:view`）；
     * 行级数组有界（≤ {@code DailyBriefingService.SNAPSHOT_ROW_LIMIT}）且截断在 `row_meta` 里显式。</p>
     */
    /**
     * 记录一次决策动作（issue #8260）—— 「AI 建议了什么 → 人做了什么」的后半句。
     *
     * <p><b>fire-and-forget 语义</b>：调用方（前端）不等待结果、失败不提示用户。
     * 因此这里对非法入参**不抛错**，只回 {@code recorded=false} ——
     * 用户点的是「问黄金策」，不该因为一条内部埋点失败而失败。</p>
     *
     * <p>入参：{@code bizDate} / {@code itemKind}（todo|risk|suggestion）/ {@code title}（前端传原文，服务端只存 hash）/ {@code action}。</p>
     */
    // 🔴 码是 `agent:chat`（=「唤出黄金策对话」，员工需授权），不是 `dashboard:view`：
    // 「点『问黄金策』」在语义上就是唤出对话那个动作，能唤出的人才该产生这条记录。
    // 用读码会让本端点落进 I4（写动作挂读码）台账 —— 那张表**只许缩短**，不认新增。
    @RequirePermission("agent:chat")
    @PostMapping("/actions")
    public ApiResponse<Map<String, Object>> recordAction(@RequestBody Map<String, Object> body) {
        Long tenantId = TenantContext.getTenantId();
        String userId = null;
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof SecurityUser su) {
            userId = su.getUserId();
        }
        boolean recorded = briefingActionService.record(
                tenantId,
                asText(body.get("bizDate")),
                asText(body.get("itemKind")),
                asText(body.get("title")),
                asText(body.get("action")),
                userId);
        Map<String, Object> resp = new HashMap<>();
        resp.put("recorded", recorded);
        return ApiResponse.success(resp);
    }

    /**
     * 查决策动作记录（issue #8260）：复盘时回答「这些建议你点开过几条」。
     *
     * <p>{@code days} 由 Service 钳制（上限 {@link BriefingActionService#MAX_DAYS}），此处不重复。
     * 返回的每条**只有 itemKey**（hash）—— 要还原成标题得回到对应日期的简报，
     * 这是刻意的：事件表不该成为简报内容的第二份副本。</p>
     */
    @RequirePermission("dashboard:view")
    @GetMapping("/actions")
    public ApiResponse<List<Map<String, Object>>> listActions(
            @RequestParam(value = "days", defaultValue = "30") int days) {
        Long tenantId = TenantContext.getTenantId();
        List<BriefingAction> rows = briefingActionService.listRecent(tenantId, days);
        List<Map<String, Object>> resp = new ArrayList<>(rows.size());
        for (BriefingAction row : rows) {
            Map<String, Object> item = new HashMap<>();
            item.put("bizDate", row.getBizDate() != null ? row.getBizDate().toString() : null);
            item.put("itemKind", row.getItemKind());
            item.put("itemKey", row.getItemKey());
            item.put("action", row.getAction());
            resp.add(item);
        }
        return ApiResponse.success(resp);
    }

    private static String asText(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    /**
     * 历史简报（issue #8253）：过去 N 天 AI 提醒过什么。
     *
     * <p>复盘的第一块原料 —— 没有它，「上个月你建议我改价，效果如何？」根本答不出来。
     * {@code days} 由 Service 钳制（上限 {@link DailyBriefingService#HISTORY_MAX_DAYS}），
     * 这里**不重复**做边界，避免两处口径。</p>
     */
    @RequirePermission("dashboard:view")
    @GetMapping("/history")
    public ApiResponse<List<Map<String, Object>>> getHistory(
            @RequestParam(value = "days", defaultValue = "30") int days) {
        Long tenantId = TenantContext.getTenantId();
        List<DailyBriefing> rows = dailyBriefingService.getBriefingHistory(tenantId, days);
        List<Map<String, Object>> resp = new ArrayList<>(rows.size());
        for (DailyBriefing row : rows) {
            Map<String, Object> item = new HashMap<>();
            item.put("bizDate", row.getBizDate() != null ? row.getBizDate().toString() : null);
            item.put("content", row.getContent());
            item.put("verifyStatus", row.getVerifyStatus());
            item.put("generatedAt", row.getGeneratedAt() != null ? row.getGeneratedAt().toString() : null);
            resp.add(item);
        }
        return ApiResponse.success(resp);
    }

    @RequirePermission("dashboard:view")
    @GetMapping("/snapshot")
    public ApiResponse<Map<String, Object>> getSnapshot() {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(dailyBriefingService.aggregateSnapshot(tenantId));
    }

    /**
     * 简报配置（开关 + 生成时刻）。前端菜单显隐 = 开关 ∧ 角色权限。
     */
    @RequirePermission("dashboard:view")
    @GetMapping("/config")
    public ApiResponse<Map<String, Object>> getConfig() {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(dailyBriefingService.getConfig(tenantId));
    }

    /**
     * 更新简报配置（企业开关）。仅 admin（system:manage）。
     * 开启瞬间立即生成当日简报；关闭即熔断（调度跳过 + 生成入口拦截）。
     * 变更写操作日志（审计，设计文档 §8.4；开关变更记谁/何时/开或关）。
     */
    @RequirePermission("system:manage")
    @PutMapping("/config")
    public ApiResponse<Map<String, Object>> updateConfig(@RequestBody Map<String, Object> data) {
        Long tenantId = TenantContext.getTenantId();
        boolean enabled = Boolean.TRUE.equals(data.get("enabled"));
        String generateTime = data.get("generateTime") != null ? String.valueOf(data.get("generateTime")) : null;
        log.info("更新简报配置 tenantId={} enabled={} generateTime={}", tenantId, enabled, generateTime);
        Map<String, Object> config = dailyBriefingService.updateConfig(tenantId, enabled, generateTime);

        // 审计：开关变更（谁、何时、开/关）
        try {
            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            String userId = null, userName = null;
            if (auth != null && auth.getPrincipal() instanceof SecurityUser su) {
                userId = su.getUserId();
                userName = su.getUsername();
            }
            Map<String, Object> details = new HashMap<>();
            details.put("enabled", config.get("enabled"));
            details.put("generateTime", config.get("generateTime"));
            auditLogService.recordLogAsync(tenantId, userId, userName,
                    "update", "briefing_config", null, String.valueOf(tenantId), "智能每日经营简报配置",
                    details, null, null);
        } catch (Exception e) {
            log.warn("简报配置变更审计失败（不阻断）: {}", e.getMessage());
        }
        return ApiResponse.success(config);
    }

    /**
     * 手动触发当日生成（仅 admin）。生成失败/未开启时返回对应状态。
     */
    @RequirePermission("system:manage")
    @PostMapping("/generate")
    public ApiResponse<Map<String, Object>> generate() {
        Long tenantId = TenantContext.getTenantId();
        DailyBriefing briefing = dailyBriefingService.generateForTenant(tenantId);
        Map<String, Object> resp = new HashMap<>();
        if (briefing == null) {
            resp.put("generated", false);
            resp.put("reason", "BRIEFING_DISABLED");
        } else {
            resp.put("generated", true);
            resp.put("verifyStatus", briefing.getVerifyStatus());
            resp.put("content", briefing.getContent());
        }
        return ApiResponse.success(resp);
    }
}
