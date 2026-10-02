package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.ShipmentListRow;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.service.OrderShipmentService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 发货单 Controller（issue #5939）—— 大菜单「仓储与物料 ▸ 发货单」的读面。
 *
 * <h2>它与工人面 / 按单读面的关系</h2>
 * <ul>
 *   <li><b>按单读面</b> {@code GET /api/admin/orders/{id}/shipments}（issue #5651）：「这一单发了多少」，
 *       要先知道是哪张订单；</li>
 *   <li><b>工人写面</b> {@code /api/worker/shipment/**}（issue #5648）：拍照 / 打包 / 发货；</li>
 *   <li><b>本面</b>：<b>流水读面</b> —— 「这个租户发过哪些货」，按发货单号 / 订单号 / 客户名检索，
 *       是发货单**作为单据**的入口（此前零入口，用户 2026-10-02 原话：「在大菜单上没见到这个单据」）。</li>
 * </ul>
 *
 * <h2>🔴 权限码 = {@code order:list}（取**既有**码，不新造）</h2>
 * <p>与同域既有读面（{@code GET /api/admin/orders/{id}/shipments}、订单详情）**逐字同码**
 * ⇒ <b>零授权 delta</b>：能看订单的人就能看发货单，不存在「菜单看得见、点进去 403」。</p>
 * <p>反例（为什么不能新造一个 {@code shipment:view}）：新码今天**没有任何岗位持有** ⇒ 菜单节点
 * 对**所有人**不可见（#4203 同族坑：生产模块曾因权限码与页面不同码而「零菜单入口」）；
 * 要真按岗位细分，得连带岗位默认权限 / 迁移 / 岗位权限页多处对齐 —— 那是授权变更，须人类裁定。</p>
 *
 * <h2>只读</h2>
 * <p>本单只补读面：发货写面（拍照 / 打包 / 发货 / 撤销）全归 issue #5648 的工人面，此处一个写动词都没有
 * （判据：{@code AdminShipmentListReadTest.listFaceIsReadOnly}）。</p>
 *
 * <p>租户隔离：{@code TenantContext.getTenantId()} 一路传到 SQL 的 {@code WHERE tenant_id = ?}
 * （真库判据 {@code ShipmentListQueryRealDbTest.otherTenantsShipmentsAreNotVisible}）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/shipments")
@RequiredArgsConstructor
public class ShipmentController {

    private final OrderShipmentService orderShipmentService;

    /**
     * 发货单列表（权限 order:list）
     * GET /api/admin/shipments?keyword=
     *
     * @param keyword 发货单号 / 订单号 / 客户名 的模糊匹配；不传 = 本租户最近的 {@code LIST_LIMIT} 张
     */
    @GetMapping
    @RequirePermission("order:list")
    public ApiResponse<List<ShipmentListRow>> list(@RequestParam(required = false) String keyword) {
        return ApiResponse.success(
                orderShipmentService.listShipments(keyword, TenantContext.getTenantId()));
    }
}
