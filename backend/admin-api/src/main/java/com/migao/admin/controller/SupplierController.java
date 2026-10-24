package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.SupplierPayableSummary;
import com.migao.admin.dto.UnassignedInboundSupplier;
import com.migao.admin.entity.Supplier;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.TenantOwnedResource;
import com.migao.admin.service.SupplierService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 供应商主数据（issue #7369，P0-1 段 1）。
 *
 * <p>前端对齐：{@code supplierApi}（frontend/admin-web/src/lib/api.ts）
 * <ul>
 *   <li>GET  /api/admin/suppliers           → 列表（keyword 可模糊搜名称/联系人/电话）</li>
 *   <li>POST /api/admin/suppliers           → 建档</li>
 *   <li>PUT  /api/admin/suppliers/{id}      → 更新（**停用也走这里**改 status）</li>
 * </ul>
 *
 * <h3>为什么权限码取 {@code inbound:view} / {@code inbound:create}（不新造 {@code supplier:*}）</h3>
 * 新码今天**没有任何岗位持有** ⇒ 页面与菜单对所有人不可见（#4203 同族坑，同组「发货单」取
 * {@code order:list}、省料看板取 {@code product:list} 是同一先例）。供应商档案的读者与入库单**同群**
 * （仓管看收货、财务看账期）⇒ 本段复用入库码，**零授权 delta**；采购域（段 2 的采购单）引入自己的码时，
 * 再评估把供应商读写拆成 {@code supplier:*}。
 */
@Slf4j
@RestController
@RequiredArgsConstructor
public class SupplierController {

    private final SupplierService supplierService;

    /** 供应商列表。 */
    @GetMapping("/api/admin/suppliers")
    @RequirePermission("inbound:view")
    public ApiResponse<List<Supplier>> list(@RequestParam(required = false) String keyword) {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(supplierService.list(tenantId, keyword));
    }

    /**
     * 「待指派」清单（issue #7369 段 2）：入库单上有供应商**文本**、但还没挂档案的，按名字分组。
     *
     * <p>这是 A 口径（精确匹配、不猜）的**人工出口** —— 读码与列表同码（能看档案的人才能看这批缺口）。</p>
     */
    @GetMapping("/api/admin/suppliers/unassigned-inbound")
    @RequirePermission("inbound:view")
    public ApiResponse<List<UnassignedInboundSupplier>> unassignedInbound() {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(supplierService.unassignedInboundSuppliers(tenantId));
    }

    /**
     * 供应商应付对账（issue #7369 段 3-A）：每家供应商的累计收货额 / 单据数 / 首末入库日 / 尚欠。
     *
     * <p>⚠️ <b>A 段没有付款登记</b>：响应里 {@code paymentsRecorded = false}、{@code paidAmount = 0}，
     * 前端据此显示「未登记」而不是「已付 ¥0」。读码沿用 {@code inbound:view} —— 该页读者与入库单同群，
     * 且入库单列表本来就带金额，不新增暴露面。</p>
     */
    @GetMapping("/api/admin/suppliers/payables")
    @RequirePermission("inbound:view")
    public ApiResponse<SupplierPayableSummary> payables() {
        Long tenantId = TenantContext.getTenantId();
        return ApiResponse.success(supplierService.payableSummary(tenantId));
    }

    /** 新建供应商档案。 */
    @PostMapping("/api/admin/suppliers")
    @RequirePermission("inbound:create")
    public ApiResponse<Supplier> create(@RequestBody Supplier supplier) {
        Long tenantId = TenantContext.getTenantId();
        log.info("新建供应商: tenantId={} name={}", tenantId, supplier.getName());
        return ApiResponse.success(supplierService.create(tenantId, supplier));
    }

    /** 更新供应商档案（含停用/启用）。归属认定先于载荷校验（#6158）。 */
    @PutMapping("/api/admin/suppliers/{id}")
    @RequirePermission("inbound:create")
    @TenantOwnedResource("supplier")
    public ApiResponse<Supplier> update(@PathVariable String id, @RequestBody Supplier supplier) {
        Long tenantId = TenantContext.getTenantId();
        log.info("更新供应商: tenantId={} id={}", tenantId, id);
        return ApiResponse.success(supplierService.update(id, tenantId, supplier));
    }
}
