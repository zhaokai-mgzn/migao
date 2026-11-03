package com.migao.admin.mapper;

import com.migao.admin.entity.Role;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * 角色Mapper接口
 *
 * <p><b>issue #7255</b>：{@code roles} 上有 {@code UNIQUE(tenant_id, code)}（建库脚本的表内约束；
 * V206 负责把它 ensure 到存量库），而 {@code RoleService#createRole} 原先是「{@code selectOne} 判空 →
 * {@code insert}」—— 并发下两个请求都判「不存在」⇒ 第二个撞唯一键 ⇒ <b>500</b>。
 * 现在建行收敛到下面这条**原子条件插入**，影响 0 行 = 已存在 ⇒ 由服务层收敛成**具名 422**。</p>
 */
@Mapper
public interface RoleMapper extends BaseMapper<Role> {

    /**
     * 插一条角色行，**撞唯一键不插**（并发兜底；issue #7255）。
     *
     * @return 影响行数（1 = 本次插入；0 = {@code (tenant_id, code)} 已存在 ⇒ 幂等收敛）
     */
    @Insert("INSERT INTO roles (id, tenant_id, name, code, description, status, created_at, updated_at, deleted) "
            + "VALUES (#{r.id}, #{r.tenantId}, #{r.name}, #{r.code}, #{r.description}, 'active', NOW(), NOW(), 0) "
            + "ON CONFLICT (tenant_id, code) DO NOTHING")
    int insertIfAbsent(@Param("r") Role role);
}
