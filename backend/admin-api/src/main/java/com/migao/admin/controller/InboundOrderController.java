package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.InboundBatchView;
import com.migao.admin.dto.InboundOrderActionRequest;
import com.migao.admin.dto.InboundOrderCreateRequest;
import com.migao.admin.dto.InboundOrderLine;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.dto.OpeningImportReport;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.RequirePermission;
import com.migao.admin.security.SecurityUser;
import com.migao.admin.service.InboundOrderService;
import com.migao.admin.service.OpeningRegisterImportService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.StringUtils;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * 入库单 Controller（V111，issue #5034）
 *
 * <p>端点：建单 / 列表 / 详情 / 动作（过账·作废）/ 批次查询；V118（issue #5153）追加
 * <b>期初建账</b>的模板下载与 Excel 批量导入（{@code opening-import}）。</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/admin/inbound-orders")
@RequiredArgsConstructor
public class InboundOrderController {

    private final InboundOrderService inboundOrderService;
    private final OpeningRegisterImportService openingRegisterImportService;

    /**
     * 入库单列表（权限 inbound:view）
     * GET /api/admin/inbound-orders?keyword=&status=
     */
    @GetMapping
    @RequirePermission("inbound:view")
    public ApiResponse<List<InboundOrderLine>> list(@RequestParam(required = false) String keyword,
                                                    @RequestParam(required = false) String status) {
        return ApiResponse.success(inboundOrderService.list(keyword, status, TenantContext.getTenantId()));
    }

    /**
     * 批次查询（权限 inbound:view）
     * GET /api/admin/inbound-orders/batches?skuId=&dyeLot=&inboundNo=&legacyBatchNo=
     *
     * <p>{@code legacyBatchNo}（V118 / issue #5153）：按**旧系统批次号**查回期初登记进来的批次
     * —— 迁移期最常见的问法是「旧系统那个号在 MIGAO 里是哪一批、还剩多少」。</p>
     */
    @GetMapping("/batches")
    @RequirePermission("inbound:view")
    public ApiResponse<List<InboundBatchView>> batches(@RequestParam(required = false) Long skuId,
                                                       @RequestParam(required = false) String dyeLot,
                                                       @RequestParam(required = false) String inboundNo,
                                                       @RequestParam(required = false) String legacyBatchNo) {
        return ApiResponse.success(
                inboundOrderService.batches(skuId, dyeLot, inboundNo, legacyBatchNo,
                        TenantContext.getTenantId()));
    }

    /**
     * 期初建账**模板**下载（权限 inbound:create）—— .xlsx，第 1 表只有表头 + 第 2 表填写说明。
     *
     * <p>模板**不放示例数据行**：示例行会和真数据一样被解析成批次 ⇒ 「下载模板原样上传」会建出
     * 一批假账（真库存 + 假批次，事后极难分辨）。</p>
     *
     * GET /api/admin/inbound-orders/opening-template
     */
    @GetMapping("/opening-template")
    @RequirePermission("inbound:create")
    public ResponseEntity<byte[]> openingTemplate() {
        byte[] body = openingRegisterImportService.template();
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=\"opening-register-template.xlsx\"")
                .contentType(MediaType.parseMediaType(
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
                .body(body);
    }

    /**
     * 期初建账**批量导入**（权限 inbound:create）—— Excel → 一张 {@code source=opening} 的期初入库单
     * （建单 + 过账走服务层；**逐行校验报告**；全或无）。
     *
     * <p>🔴 {@code importRunId} 必填：没有幂等键就不许上批量导入 —— 重跑（网络重试 / 双击 /
     * 刷新后重交）会建出第二张单，两张都过账就是**库存加两次**。同一标识重跑 ⇒ 返回既有那张、
     * **不重复加库存**。</p>
     *
     * POST /api/admin/inbound-orders/opening-import  (multipart/form-data: file, importRunId)
     */
    @PostMapping("/opening-import")
    @RequirePermission("inbound:create")
    public ApiResponse<OpeningImportReport> openingImport(@RequestParam("file") MultipartFile file,
                                                         @RequestParam("importRunId") String importRunId) {
        return ApiResponse.success(openingRegisterImportService.importOpening(
                file, importRunId, TenantContext.getTenantId(), currentOperator()));
    }

    /**
     * 建单（权限 inbound:create）—— 草稿态，**不动库存**
     * POST /api/admin/inbound-orders
     */
    @PostMapping
    @RequirePermission("inbound:create")
    public ApiResponse<InboundOrderResponse> create(@RequestBody InboundOrderCreateRequest request) {
        return ApiResponse.success(
                inboundOrderService.create(request, TenantContext.getTenantId(), currentOperator()));
    }

    /**
     * 入库单详情（权限 inbound:view）
     * GET /api/admin/inbound-orders/{id}   id 可为 UUID / 入库单号 / 单号前缀
     */
    @GetMapping("/{id}")
    @RequirePermission("inbound:view")
    public ApiResponse<InboundOrderResponse> detail(@PathVariable String id) {
        return ApiResponse.success(inboundOrderService.detail(id, TenantContext.getTenantId()));
    }

    /**
     * 过账 / 作废（权限 inbound:create）
     * PATCH /api/admin/inbound-orders/{id}   action: post | cancel
     */
    @PatchMapping("/{id}")
    @RequirePermission("inbound:create")
    public ApiResponse<InboundOrderResponse> act(@PathVariable String id,
                                                 @RequestBody InboundOrderActionRequest request) {
        Long tenantId = TenantContext.getTenantId();
        String operator = currentOperator();
        String action = request == null ? null : request.getAction();
        if ("post".equalsIgnoreCase(action)) {
            return ApiResponse.success(inboundOrderService.post(id, tenantId, operator));
        }
        if ("cancel".equalsIgnoreCase(action)) {
            return ApiResponse.success(
                    inboundOrderService.cancel(id, request.getReason(), tenantId, operator));
        }
        throw BusinessException.validationError("action 只支持 post（过账）/ cancel（作废）");
    }

    /** 操作人：登录用户名（手机号）；无认证上下文 = system（同 StockLedgerService 口径） */
    private static String currentOperator() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof SecurityUser securityUser) {
            return StringUtils.hasText(securityUser.getUsername())
                    ? securityUser.getUsername() : securityUser.getUserId();
        }
        return "system";
    }
}
