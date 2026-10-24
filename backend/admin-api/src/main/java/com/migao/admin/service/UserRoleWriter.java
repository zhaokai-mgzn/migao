package com.migao.admin.service;

import com.migao.admin.entity.UserRole;
import com.migao.admin.mapper.UserRoleMapper;
import lombok.extern.slf4j.Slf4j;

import java.util.UUID;

/**
 * 用户角色写入的**单一实现点**（issue #7256）。
 *
 * <p><b>为什么抽出来</b>：本写面有两处调用方（{@code RoleService#assignRoleToUser}、
 * {@code UserService#updateUserRole} 经私有方法），原先各自「{@code selectOne} 判重 + {@code insert}」。
 * 这个形状有两个病：① 并发两个请求都过判重 ⇒ 第二个撞唯一键 ⇒ **500**；
 * ② 本表唯一键是**全表**的，而删除是逻辑删除 ⇒ 「移除角色后再授权」必撞键 ⇒ **500**（本单的主症状）。</p>
 *
 * <p><b>修法</b>：唯一性下放到「活跃行」的部分唯一索引（V166），写面固定三个动作的**顺序**——
 * ① 先尝试**复活**软删行（保住首次授权时刻、且不与全表唯一键对撞）；② 复活 0 行才**条件插入**
 * （{@code ON CONFLICT … DO NOTHING}）；③ 插入影响 0 行 = 已存在 ⇒ **幂等成功**，不抛错。
 * 「顺序即安全顺序」：先插入再复活会在软删行存在时撞键。</p>
 */
@Slf4j
public final class UserRoleWriter {

    private UserRoleWriter() {
    }

    /**
     * 确保 (tenant, user, role) 有一条**活跃**授权；已存在/已软删都收敛为"现在是活跃的"（幂等）。
     *
     * @return {@code true} = 本次真的产生了变化（复活或新建）；{@code false} = 原本就活跃
     */
    public static boolean ensureGranted(UserRoleMapper userRoleMapper, Long tenantId,
                                        String userId, String roleId) {
        if (userRoleMapper.reviveSoftDeleted(tenantId, userId, roleId) > 0) {
            log.info("用户角色授权→复活软删行: tenantId={}, userId={}, roleId={}", tenantId, userId, roleId);
            return true;
        }
        int inserted = userRoleMapper.insertIfAbsent(UserRole.builder()
                .id(UUID.randomUUID().toString().replace("-", ""))
                .tenantId(tenantId)
                .userId(userId)
                .roleId(roleId)
                .build());
        if (inserted == 0) {
            // 并发对手先插入成功 ⇒ 幂等收敛（不抛 500）；这不是异常路径，是重试/双击的正常结果
            log.info("用户角色授权已存在⇒幂等收敛: tenantId={}, userId={}, roleId={}", tenantId, userId, roleId);
            return false;
        }
        log.info("用户角色授权成功: tenantId={}, userId={}, roleId={}", tenantId, userId, roleId);
        return true;
    }
}
