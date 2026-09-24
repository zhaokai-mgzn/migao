package com.migao.admin.controller;

import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.ApiResponse;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.entity.CustomerTag;
import com.migao.admin.service.CustomerService;
import com.migao.admin.security.RequirePermission;
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
     *
     * issue #5246 追加单：类级 customer:view 已移除 ⇒ **逐端点**标注（读 customer:view /
     * 写 customer:create）。原形态下「能看客户」=「能改档案、删客户、增删标签」—— 只读持有者
     * 被动拿到写能力（本单要关掉的那一类）。逐端点标注（而非保留类级 + 覆盖写面）是为了让
     * **日后新增的端点不会静默继承读码**。
     */
    @GetMapping("/api/admin/customers")
    @RequirePermission("customer:view")
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
     * 客户画像视图（**按需**消费入口，族 3 · 包 3，issue #5456）
     *
     * GET /api/admin/customers/profile-view?limit=50
     *
     * 与客户列表/详情**同权限码**（`customer:view`）：返回的是跨域视图内核形状的确定性快照
     * （自描述的行字段 + 有界行数 + 真值声明 + 客户档案行），供 ai-agent 侧的具名视图
     * `customer_profile` 做逐字段三态与「未知 ≠ 0」判定。
     *
     * 🔴 客户档案含 PII ⇒ 本端点**不得**并入 `dashboard:view` 的简报表快照（Agent 能力 ≡ 页面权限，
     * issue #5246）；路径是**字面量**，优先于 `/api/admin/customers/{id}` 这个模式
     * （Spring 的字面量比通配更具体）⇒ 不会把 detail 请求抢过来。
     */
    @GetMapping("/api/admin/customers/profile-view")
    @RequirePermission("customer:view")
    public ApiResponse<Map<String, Object>> getProfileView(
            @RequestParam(defaultValue = "50") int limit) {
        Long tenantId = TenantContext.getTenantId();
        log.info("查询客户画像视图: limit={}, tenantId={}", limit, tenantId);
        return ApiResponse.success(customerService.profileViewSnapshot(tenantId, limit));
    }

    /**
     * 查询客户详情
     *
     * GET /api/admin/customers/{id}
     */
    @GetMapping("/api/admin/customers/{id}")
    @RequirePermission("customer:view")
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
    @RequirePermission("customer:create")
    public ApiResponse<CustomerProfile> updateCustomer(
            @PathVariable String id,
            @RequestBody CustomerProfile profile) {
        log.info("更新客户档案: id={}", id);
        CustomerProfile updated = customerService.updateCustomer(id, profile);
        return ApiResponse.success(updated);
    }

    /**
     * 删除客户档案
     *
     * DELETE /api/admin/customers/{id}
     */
    @DeleteMapping("/api/admin/customers/{id}")
    @RequirePermission("customer:create")
    public ApiResponse<Void> deleteCustomer(@PathVariable String id) {
        log.info("删除客户档案: id={}", id);
        customerService.removeById(id);
        return ApiResponse.success();
    }

    /**
     * 给客户添加标签
     *
     * POST /api/admin/customers/{customerId}/tags/{tagId}
     */
    @PostMapping("/api/admin/customers/{customerId}/tags/{tagId}")
    @RequirePermission("customer:create")
    public ApiResponse<Void> addTagToCustomer(
            @PathVariable String customerId,
            @PathVariable String tagId) {
        log.info("给客户添加标签: customerId={}, tagId={}", customerId, tagId);
        customerService.addTagToCustomer(customerId, tagId);
        return ApiResponse.success();
    }

    /**
     * 移除客户标签
     *
     * DELETE /api/admin/customers/{customerId}/tags/{tagId}
     */
    @DeleteMapping("/api/admin/customers/{customerId}/tags/{tagId}")
    @RequirePermission("customer:create")
    public ApiResponse<Void> removeTagFromCustomer(
            @PathVariable String customerId,
            @PathVariable String tagId) {
        log.info("移除客户标签: customerId={}, tagId={}", customerId, tagId);
        customerService.removeTagFromCustomer(customerId, tagId);
        return ApiResponse.success();
    }

    // ==================== 客户标签 ====================

    /**
     * 查询所有客户标签
     *
     * GET /api/admin/customer-tags
     */
    @GetMapping("/api/admin/customer-tags")
    @RequirePermission("customer:view")
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
    @RequirePermission("customer:create")
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
    @RequirePermission("customer:create")
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
    @RequirePermission("customer:create")
    public ApiResponse<Void> deleteCustomerTag(@PathVariable String id) {
        log.info("删除客户标签: id={}", id);
        customerService.deleteTag(id);
        return ApiResponse.success();
    }
}
