package com.aikf.admin.service;

import com.aikf.admin.entity.Permission;
import com.aikf.admin.mapper.PermissionMapper;
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
            case "super_admin" -> List.of(
                    "dashboard:view",
                    "product:manage",
                    "processing:manage",
                    "knowledge:manage",
                    "system:manage"
            );
            case "admin" -> List.of(
                    "dashboard:view",
                    "product:manage",
                    "processing:manage",
                    "knowledge:manage",
                    "system:manage"
            );
            case "operator" -> List.of(
                    "dashboard:view",
                    "product:manage",
                    "knowledge:manage"
            );
            case "product_manager" -> List.of(
                    "dashboard:view",
                    "product:manage",
                    "processing:manage"
            );
            case "knowledge_editor" -> List.of(
                    "dashboard:view",
                    "knowledge:manage"
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
}
