package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.ProcessingSetReadService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 加工套件**只读**端点（issue #5247 的 admin-api 半边；设计
 * {@code docs/design/set-code-and-scan-loop.md} 为真值源）。
 *
 * <p><b>为什么新开一个控制器</b>：{@code processing_order_sets}（V92 / issue #4698）此前**没有任何读面**
 * （全仓 {@code grep 套件} 在 Java 侧零命中）—— 工人扫码面只把「本套明细」作为解析响应的
 * {@code set_overview} 键回给扫到的那一套，商家/agent 侧**没有可查询对象**。本控制器补的正是这三条
 * 只读面，**不改**任何既有路径（{@code ProcessingOrderController} / {@code ProductionController} 一字不动）。</p>
 *
 * <h2>端点（全部只读：不写库、不触发扫码副作用、不占幂等键）</h2>
 * <ul>
 *   <li>{@code GET /api/admin/processing-order-sets} —— 套件列表（{@code orderNo} / {@code processingOrderNo}
 *       过滤 + 分页 {@code page}/{@code size}）；</li>
 *   <li>{@code GET /api/admin/processing-order-sets/scan-progress} —— 扫码循环进度（按订单 / 加工单）；</li>
 *   <li>{@code GET /api/admin/processing-order-sets/{id}} —— 套件详情（套 → 部位 → 工序明细）。</li>
 * </ul>
 *
 * <h2>🔴 权限锚定（#5246 / #5247 的锚定规则：有菜单节点锚节点码，无节点锚既有生效码）</h2>
 * <p><b>实测事实</b>：加工单（{@code processing_order_sets} 的父实体）在 S1 侧边栏**没有独立菜单节点**
 * —— {@code frontend/admin-web/src/config/menu.ts} 的「加工单」已按 issue #4357 并入「生产看板」
 * （{@code permissionCode: 'processing:manage'}，路径 {@code /production}），而**加工套件本身零菜单项**。
 * 因此按锚定规则退到第二档：<b>锚「最接近的兄弟读端点」的既有生效码</b>——
 * 兄弟 = {@link ProcessingOrderController} 的 {@code GET /api/admin/processing-orders} 与
 * {@code GET /api/admin/processing-orders/{id}}（同一实体族、同一张表族）。</p>
 * <p>⚠️ <b>本控制器的三个读端点现为 {@code production:view}</b>（issue #5291 新增的生产域**读**码）——
 * 与兄弟读端点（{@link ProcessingOrderController} 的两个 GET）**逐字同码**，也与「生产看板」侧边栏节点同码。
 * 沿革：issue #5246 曾把兄弟读端点从 {@code processing:view} 改到 {@code processing:manage}（当时该域
 * 没有读码，而 {@code processing:view} 在四处菜单源里没有任何节点 ⇒ 持它的客服/销售/财务能经 API 读到
 * 页面里看不到的生产数据）；issue #5291 读出读码后，本控制器**跟随兄弟锚点**再改挂读码
 * （方向仍是**只收窄**：只持 {@code processing:view} 的岗位既无管理码也无本读码，仍失去这份只读套件面）。
 * 「加工套件在侧边栏无入口」这一事实已在 PR 报告里显式登记为 residual
 * （⇒ UI 与 agent 之间不存在可见性分歧可保护：没有任何页面按菜单码渲染这份数据）。</p>
 *
 * <h2>冻结键集</h2>
 * <p>三个端点的响应键集由 {@code ProcessingOrderSetControllerTest} 冻结（同
 * {@code AgentProductionControllerTest} 的既有约定）：<b>不得删键</b>；缺值给 {@code null} 而不是省键
 * （{@code position}-类字段恒在），{@code unit_price} 为 {@code null} = 未定价，**不折 0**
 * （V90 / issue #4696）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/processing-order-sets")
@RequiredArgsConstructor
public class ProcessingOrderSetController {

    /** 套件读面的唯一实现（含与工人扫码面共用的 {@code setOverview} 单一口径聚合）。 */
    private final ProcessingSetReadService processingSetReadService;

    /**
     * 扫码循环进度（按订单 / 加工单）。
     *
     * <p>GET /api/admin/processing-order-sets/scan-progress?orderNo=…&amp;processingOrderNo=…</p>
     *
     * <p>两者至少给一个（都不给 ⇒ 422）。按订单号时取该订单**当前活跃加工单**，
     * 该订单还没有加工单 ⇒ 零值行（与既有 {@code GET /agent/production/progress} 的
     * 「还没生产就是 0」同口径）；按加工单号时点名即须存在 ⇒ 404。</p>
     */
    // issue #5291：三个读端点改挂生产域读码 `production:view`（写面无 Agent 工具调用）。
    @GetMapping("/scan-progress")
    @RequirePermission("production:view")
    public ApiResponse<Map<String, Object>> scanProgress(
            @RequestParam(value = "orderNo", required = false) String orderNo,
            @RequestParam(value = "processingOrderNo", required = false) String processingOrderNo) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(
                processingSetReadService.scanProgress(orderNo, processingOrderNo, tenantId));
    }

    /**
     * 套件列表（分页；{@code orderNo} / {@code processingOrderNo} 可选过滤，后者更具体）。
     *
     * <p>GET /api/admin/processing-order-sets?orderNo=…&amp;processingOrderNo=…&amp;page=1&amp;size=20</p>
     *
     * <p>分页信封 = 既有 {@link PageResponse}（{@code {total, page, size, items[]}}）；
     * {@code size} 上限 100（超出按上限收敛，不报错）。过滤条件命中但该订单没有加工单 ⇒ 空页（200）。</p>
     */
    @GetMapping
    @RequirePermission("production:view")
    public ApiResponse<PageResponse<Map<String, Object>>> list(
            @RequestParam(value = "orderNo", required = false) String orderNo,
            @RequestParam(value = "processingOrderNo", required = false) String processingOrderNo,
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "20") int size) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(
                processingSetReadService.listSets(orderNo, processingOrderNo, page, size, tenantId));
    }

    /**
     * 套件详情：套 → 部位 → 工序明细（应做数量 / 单位 / 单价 / 状态 / 已报数量）。
     *
     * <p>GET /api/admin/processing-order-sets/{id}</p>
     *
     * <p>{@code set_overview} 键 = 与工人扫码面 {@code set_overview} **同一份**聚合（同一实现、
     * 同一形状）—— 商家/agent 看到的「这一套还有哪几道没做」与工人屏上逐字一致。
     * 跨租户 / 已软删 / 不存在 ⇒ 404（fail-closed）。</p>
     */
    @GetMapping("/{id}")
    @RequirePermission("production:view")
    public ApiResponse<Map<String, Object>> detail(@PathVariable String id) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(processingSetReadService.setDetail(id, tenantId));
    }
}