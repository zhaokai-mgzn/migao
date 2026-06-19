package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.entity.CustomerTag;
import com.migao.admin.service.CustomerService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 客户管理控制器
 * 提供客户档案 CRUD、客户标签管理接口
 *
 * 前端对齐：customerApi (frontend/admin-web/src/lib/api.ts)
 * - GET    /api/admin/customers              → getCustomers
 * - GET    /api/admin/customers/{id}         → getCustomer
 * - PUT    /api/admin/customers/{id}         → updateCustomer
 * - POST   /api/admin/customers/{customerId}/tags/{tagId} → addTagToCustomer
 * - DELETE /api/admin/customers/{customerId}/tags/{tagId} → removeTagFromCustomer
 * - GET    /api/admin/customer-tags          → getCustomerTags
 * - POST   /api/admin/customer-tags          → createCustomerTag
 * - PUT    /api/admin/customer-tags/{id}     → updateCustomerTag
 * - DELETE /api/admin/customer-tags/{id}     → deleteCustomerTag
 */
@Slf4j
@RestController
@RequiredArgsConstructor
public class CustomerController {

    private final CustomerService customerService;

    // ==================== 客户档案 ====================

    /**
     * 分页查询客户列表
     *
     * GET /api/admin/customers?page=1&size=10&keyword=xxx&sourceChannel=wechat_mini&vipLevel=vip1
     */
    @GetMapping("/api/admin/customers")
    public ApiResponse<PageResponse<CustomerProfile>> getCustomers(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "10") long size,
            @RequestParam(required = false) String sourceChannel,
            @RequestParam(required = false) String vipLevel,
            @RequestParam(required = false) String keyword) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询客户列表: page={}, size={}, keyword={}, tenantId={}", page, size, keyword, tenantId);
        PageResponse<CustomerProfile> result = customerService.getCustomerPage(page, size, sourceChannel, vipLevel, keyword, tenantId);
        return ApiResponse.success(result);
    }

    /**
     * 查询客户详情
     *
     * GET /api/admin/customers/{id}
     */
    @GetMapping("/api/admin/customers/{id}")
    public ApiResponse<Map<String, Object>> getCustomer(@PathVariable String id) {
        log.info("查询客户详情: id={}", id);
        Map<String, Object> detail = customerService.getCustomerDetail(id);
        return ApiResponse.success(detail);
    }

    /**
     * 更新客户档案
     *
     * PUT /api/admin/customers/{id}
     */
    @PutMapping("/api/admin/customers/{id}")
    public ApiResponse<CustomerProfile> updateCustomer(
            @PathVariable String id,
            @RequestBody CustomerProfile profile) {
        log.info("更新客户档案: id={}", id);
        CustomerProfile updated = customerService.updateCustomer(id, profile);
        return ApiResponse.success(updated);
    }

    /**
     * 给客户添加标签
     *
     * POST /api/admin/customers/{customerId}/tags/{tagId}
     */
    @PostMapping("/api/admin/customers/{customerId}/tags/{tagId}")
    public ApiResponse<Void> addTagToCustomer(
            @PathVariable String customerId,
            @PathVariable String tagId) {
        log.info("给客户添加标签: customerId={}, tagId={}", customerId, tagId);
        // TODO: 实现标签关联逻辑
        return ApiResponse.success();
    }

    /**
     * 移除客户标签
     *
     * DELETE /api/admin/customers/{customerId}/tags/{tagId}
     */
    @DeleteMapping("/api/admin/customers/{customerId}/tags/{tagId}")
    public ApiResponse<Void> removeTagFromCustomer(
            @PathVariable String customerId,
            @PathVariable String tagId) {
        log.info("移除客户标签: customerId={}, tagId={}", customerId, tagId);
        // TODO: 实现标签移除逻辑
        return ApiResponse.success();
    }

    // ==================== 客户标签 ====================

    /**
     * 查询所有客户标签
     *
     * GET /api/admin/customer-tags
     */
    @GetMapping("/api/admin/customer-tags")
    public ApiResponse<List<CustomerTag>> getCustomerTags() {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询客户标签列表: tenantId={}", tenantId);
        List<CustomerTag> tags = customerService.getCustomerTags(tenantId);
        return ApiResponse.success(tags);
    }

    /**
     * 创建客户标签
     *
     * POST /api/admin/customer-tags
     */
    @PostMapping("/api/admin/customer-tags")
    public ApiResponse<CustomerTag> createCustomerTag(@RequestBody CustomerTag tag) {
        Long tenantId = TenantContext.getTenantId();
        tag.setTenantId(tenantId);
        log.info("创建客户标签: name={}, tenantId={}", tag.getName(), tenantId);
        CustomerTag created = customerService.createTag(tag);
        return ApiResponse.success(created);
    }

    /**
     * 更新客户标签
     *
     * PUT /api/admin/customer-tags/{id}
     */
    @PutMapping("/api/admin/customer-tags/{id}")
    public ApiResponse<CustomerTag> updateCustomerTag(
            @PathVariable String id,
            @RequestBody CustomerTag tag) {
        log.info("更新客户标签: id={}", id);
        CustomerTag updated = customerService.updateTag(id, tag);
        return ApiResponse.success(updated);
    }

    /**
     * 删除客户标签
     *
     * DELETE /api/admin/customer-tags/{id}
     */
    @DeleteMapping("/api/admin/customer-tags/{id}")
    public ApiResponse<Void> deleteCustomerTag(@PathVariable String id) {
        log.info("删除客户标签: id={}", id);
        customerService.deleteTag(id);
        return ApiResponse.success();
    }
}
