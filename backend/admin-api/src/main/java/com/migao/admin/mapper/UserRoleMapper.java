package com.migao.admin.mapper;

import com.migao.admin.entity.UserRole;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

/**
 * 用户角色关联Mapper接口
 *
 * <p><b>issue #7256</b>：本表原先只有一条**全表** {@code UNIQUE(user_id, role_id)}（schema.sql 的表内约束），
 * 而 {@code UserRole.deleted} 是 {@code @TableLogic}（逻辑删除）—— 两者直接对撞：移除角色只把
 * {@code deleted} 置 1、行还在，再授权同一角色就撞唯一键 ⇒ 500，「移除后加不回来」。
 * 现在唯一性由**活跃行**的部分唯一索引承担（迁移 V166：{@code WHERE deleted = 0}），
 * 写面统一走下面两个方法（复活软删行 / 撞键不插），不再用裸 {@code insert}。</p>
 */
@Mapper
public interface UserRoleMapper extends BaseMapper<UserRole> {

    /**
     * 复活一条**软删**的用户角色行（issue #7256）。
     *
     * <p>为什么优先复活而不是插新行：① 全表唯一键的历史形态下，插新行会撞键（这正是本单的病）；
     * ② 保留 {@code created_at}（首次授权时刻）这条历史事实，不制造"同一个人同一角色两条历史"。</p>
     *
     * @return 复活行数（1 = 原本有软删行且已复活；0 = 没有软删行）
     */
    @Update("UPDATE user_roles SET deleted = 0, updated_at = NOW() "
            + "WHERE user_id = #{userId} AND role_id = #{roleId} AND tenant_id = #{tenantId} AND deleted = 1")
    int reviveSoftDeleted(@Param("tenantId") Long tenantId,
                          @Param("userId") String userId,
                          @Param("roleId") String roleId);

    /**
     * 插一条活跃用户角色行，**撞唯一键不插**（幂等 + 并发兜底）。
     *
     * <p>⚠️ {@code ON CONFLICT} 的目标必须带**索引谓词** {@code WHERE deleted = 0}：V166 建的是部分唯一索引，
     * PG 的冲突推断要求谓词匹配（同族先例见 {@code ProcessingOrderSetMapper#insertIfAbsent} 的注释）。</p>
     *
     * @return 影响行数（1 = 本次插入；0 = 已存在 ⇒ 幂等成功）
     */
    @Insert("INSERT INTO user_roles (id, tenant_id, user_id, role_id, created_at, updated_at, deleted) "
            + "VALUES (#{ur.id}, #{ur.tenantId}, #{ur.userId}, #{ur.roleId}, NOW(), NOW(), 0) "
            + "ON CONFLICT (user_id, role_id) WHERE deleted = 0 DO NOTHING")
    int insertIfAbsent(@Param("ur") UserRole userRole);
}
