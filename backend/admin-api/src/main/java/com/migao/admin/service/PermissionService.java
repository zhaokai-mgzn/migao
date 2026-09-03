package com.migao.admin.service;

import com.migao.admin.entity.Permission;
import com.migao.admin.mapper.PermissionMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 权限服务类
 * 处理权限相关的业务逻辑
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PermissionService {

    private final PermissionMapper permissionMapper;

    /**
     * 查询所有权限列表
     *
     * @return 权限列表
     */
    public List<Permission> getAllPermissions() {
        LambdaQueryWrapper<Permission> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Permission::getDeleted, 0)
                .eq(Permission::getStatus, "active")
                .orderByAsc(Permission::getCode);
        return permissionMapper.selectList(wrapper);
    }

    /**
     * 根据租户ID查询权限列表
     *
     * @param tenantId 租户ID
     * @return 权限列表
     */
    public List<Permission> getPermissionsByTenant(Long tenantId) {
        LambdaQueryWrapper<Permission> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Permission::getTenantId, tenantId)
                .eq(Permission::getDeleted, 0)
                .eq(Permission::getStatus, "active")
                .orderByAsc(Permission::getCode);
        return permissionMapper.selectList(wrapper);
    }

    /**
     * 根据权限代码查询权限
     *
     * @param code 权限代码
     * @return 权限实体
     */
    public Permission getPermissionByCode(String code) {
        LambdaQueryWrapper<Permission> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Permission::getCode, code)
                .eq(Permission::getDeleted, 0);
        return permissionMapper.selectOne(wrapper);
    }

    /**
     * 根据ID查询权限
     *
     * @param id 权限ID
     * @return 权限实体
     */
    public Permission getPermissionById(String id) {
        return permissionMapper.selectById(id);
    }

    /**
     * 根据角色查询权限
     *
     * @param roleCode 角色代码
     * @return 权限列表
     */
    public List<Permission> getPermissionsByRole(String roleCode) {
        // 根据角色代码查询对应的权限
        // 这里简化处理，实际项目中可以从 role_permissions 中间表查询
        List<String> permissionCodes = switch (roleCode) {
            case "admin" -> List.of("*");
            case "operator" -> List.of(
                    "dashboard:view",
                    "order:list", "order:detail", "order:refund",
                    "product:list", "product:create", "product:category",
                    "processing:manage",
                    "customer:view",
                    "finance:view",
                    "agent:session", "agent:quickreply",
                    "employee:list",
                    "system:manage"
            );
            case "product_manager" -> List.of(
                    "dashboard:view",
                    "product:list", "product:create", "product:category",
                    "processing:manage"
            );
            case "knowledge_editor" -> List.of(
                    "dashboard:view"
            );
            default -> List.of();
        };

        if (permissionCodes.isEmpty()) {
            return List.of();
        }

        LambdaQueryWrapper<Permission> wrapper = new LambdaQueryWrapper<>();
        wrapper.in(Permission::getCode, permissionCodes)
                .eq(Permission::getDeleted, 0);
        return permissionMapper.selectList(wrapper);
    }

    /**
     * 创建权限
     *
     * @param permission 权限实体
     * @return 是否成功
     */
    public boolean createPermission(Permission permission) {
        // 检查权限代码是否已存在
        Permission existing = getPermissionByCode(permission.getCode());
        if (existing != null) {
            log.warn("权限代码已存在: {}", permission.getCode());
            return false;
        }

        int result = permissionMapper.insert(permission);
        return result > 0;
    }

    /**
     * 更新权限
     *
     * @param permission 权限实体
     * @return 是否成功
     */
    public boolean updatePermission(Permission permission) {
        int result = permissionMapper.updateById(permission);
        return result > 0;
    }

    /**
     * 删除权限
     *
     * @param id 权限ID
     * @return 是否成功
     */
    public boolean deletePermission(String id) {
        int result = permissionMapper.deleteById(id);
        return result > 0;
    }

    /**
     * 幂等补全租户权限目录（RBAC 修复，2026-09-03）
     *
     * 背景：旧版新租户初始化只 seed 5 条大类码（dashboard:view / product:manage /
     * processing:manage / knowledge:manage / system:manage），而代码鉴权
     * (@RequirePermission) 与前端菜单树实际使用 order:list / employee:create 等
     * 16 个细粒度码 → 角色管理页只能勾 5 条，无法为自定义角色授予订单/员工/客户等
     * 细粒度权限（POC RBAC 走查实证：DB 目录与菜单树交集仅 3 个码）。
     *
     * 本方法对存量租户补种缺失的细粒度码（幂等：已存在则跳过），使角色管理页
     * 可勾选完整权限目录。新租户已由 RegistrationService 全量 seed，无需调用。
     *
     * @param tenantId 租户ID
     * @return 补种数量
     */
    public int ensureFullPermissionCatalog(Long tenantId) {
        // 与 RegistrationService.initializeDefaultRolesAndPermissions 的目录保持一致
        String[][] catalog = {
                {"仪表板查看", "dashboard:view", "dashboard", "view", "查看数据概览"},
                {"商品管理", "product:manage", "product", "manage", "管理商品(旧大类码，兼容)"},
                {"商品列表", "product:list", "product", "list", "查看商品列表"},
                {"新增商品", "product:create", "product", "create", "新增/编辑/上下架商品"},
                {"商品分类", "product:category", "product", "category", "管理商品分类"},
                {"加工管理", "processing:manage", "processing", "manage", "管理加工项"},
                {"知识库管理", "knowledge:manage", "knowledge", "manage", "管理知识库"},
                {"订单列表", "order:list", "order", "list", "查看订单列表"},
                {"订单详情", "order:detail", "order", "detail", "查看订单详情"},
                {"订单退款", "order:refund", "order", "refund", "处理退款/售后工单"},
                {"客户管理", "customer:view", "customer", "view", "查看客户"},
                {"财务对账", "finance:view", "finance", "view", "查看财务流水/对账"},
                {"会话监控", "agent:session", "agent", "session", "米宝对话/会话监控/人工客服"},
                {"快捷回复", "agent:quickreply", "agent", "quickreply", "机器人设置/快捷回复"},
                {"员工列表", "employee:list", "employee", "list", "查看员工列表"},
                {"新增员工", "employee:create", "employee", "create", "新增/编辑/删除员工"},
                {"系统管理", "system:manage", "system", "manage", "企业信息/角色管理/系统设置"}
        };

        // 查询当前租户已有码
        List<Permission> existing = getPermissionsByTenant(tenantId);
        java.util.Set<String> existingCodes = new java.util.HashSet<>();
        for (Permission p : existing) {
            existingCodes.add(p.getCode());
        }

        int inserted = 0;
        for (String[] row : catalog) {
            if (existingCodes.contains(row[1])) {
                continue; // 已存在，幂等跳过
            }
            Permission permission = Permission.builder()
                    .tenantId(tenantId)
                    .name(row[0])
                    .code(row[1])
                    .resourceType(row[2])
                    .action(row[3])
                    .description(row[4])
                    .status("active")
                    .build();
            permissionMapper.insert(permission);
            inserted++;
        }
        if (inserted > 0) {
            log.info("权限目录补种完成: tenantId={}, inserted={}", tenantId, inserted);
        }
        return inserted;
    }

}