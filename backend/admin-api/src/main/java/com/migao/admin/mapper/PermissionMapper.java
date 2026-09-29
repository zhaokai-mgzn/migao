package com.migao.admin.mapper;

import com.migao.admin.entity.Permission;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * 权限Mapper接口
 */
@Mapper
public interface PermissionMapper extends BaseMapper<Permission> {

    /**
     * **租户维度**：该租户是否有**任一岗位**持有指定权限码（issue #5792 的「AI 接待占比」可插拔开关）。
     *
     * <p>为什么需要它：`Capabilities.aiService` 要按**租户**判（用户 2026-09-29 裁定 = 方案 B），
     * 而不是按当前用户判 —— 否则无该码的决策者反而看不到 AI 接入情况。</p>
     *
     * <p>⚠️ 显式带 {@code tenant_id} 过滤：不依赖拦截器注入（本方法是**跨角色**的集合判定，
     * 语义上就是租户级事实）。</p>
     *
     * @param tenantId 租户
     * @param code     权限码（本单用 {@code agent:session} —— 会话读码）
     * @return 有 ⇒ {@code true}
     */
    @Select("SELECT COUNT(*) > 0 FROM permissions p "
            + "JOIN role_permissions rp ON rp.permission_id = p.id "
            + "WHERE p.tenant_id = #{tenantId} AND p.code = #{code} "
            + "AND rp.tenant_id = #{tenantId} AND rp.deleted = 0")
    boolean tenantHasPermissionCode(@Param("tenantId") Long tenantId, @Param("code") String code);
}
