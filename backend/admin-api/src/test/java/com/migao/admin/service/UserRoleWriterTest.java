// case_ids: OR-045
package com.migao.admin.service;

import com.migao.admin.entity.UserRole;
import com.migao.admin.mapper.UserRoleMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 用户角色写入（issue #7256）：写面固定「复活 → 条件插入 → 撞键幂等」的顺序。
 *
 * <p>病（本单）：本表唯一键是**全表**的 {@code UNIQUE(user_id, role_id)}，而删除是逻辑删除 ⇒
 * 「移除角色」只把 deleted 置 1、行还在 ⇒ 再授权同一角色撞唯一键 ⇒ 500。
 * 并发重复授权是同一根因的另一种触发。</p>
 *
 * <p>本文件守**调用契约**（顺序、幂等收敛、id 生成）；真库侧的「移除后能再加回来」由
 * {@code UserRoleReviveRealDbTest} 守（那是 SQL 与约束的行为，mock 看不见）。</p>
 *
 * <p>红证方向：把顺序改成「先 insert 再复活」⇒ {@link #softDeletedRowIsRevivedBeforeInserting} 红；
 * 把撞键分支改成抛出 ⇒ {@link #insertConflictIsIdempotentNotAnError} 红。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("用户角色写入：复活软删行 → 条件插入 → 撞键幂等收敛")
class UserRoleWriterTest {

    private static final Long TENANT = 7L;
    private static final String USER = "u1";
    private static final String ROLE = "r1";

    @Mock private UserRoleMapper userRoleMapper;

    @Test
    @DisplayName("🔴 有软删行 ⇒ **先复活**（不插新行），并返回「本次有变化」")
    void softDeletedRowIsRevivedBeforeInserting() {
        when(userRoleMapper.reviveSoftDeleted(TENANT, USER, ROLE)).thenReturn(1);

        boolean changed = UserRoleWriter.ensureGranted(userRoleMapper, TENANT, USER, ROLE);

        assertThat(changed).as("复活 = 本次真的有变化").isTrue();
        verify(userRoleMapper, never()).insertIfAbsent(any(UserRole.class));
        InOrder order = inOrder(userRoleMapper);
        order.verify(userRoleMapper).reviveSoftDeleted(TENANT, USER, ROLE);
        order.verify(userRoleMapper, never()).insertIfAbsent(any(UserRole.class));
    }

    @Test
    @DisplayName("无软删行 + 本次插入成功 ⇒ 返回「有变化」")
    void insertsWhenNoSoftDeletedRow() {
        when(userRoleMapper.reviveSoftDeleted(TENANT, USER, ROLE)).thenReturn(0);
        when(userRoleMapper.insertIfAbsent(any(UserRole.class))).thenReturn(1);

        boolean changed = UserRoleWriter.ensureGranted(userRoleMapper, TENANT, USER, ROLE);

        assertThat(changed).isTrue();
        ArgumentCaptor<UserRole> captured = ArgumentCaptor.forClass(UserRole.class);
        verify(userRoleMapper).insertIfAbsent(captured.capture());
        UserRole row = captured.getValue();
        assertThat(row.getTenantId()).isEqualTo(TENANT);
        assertThat(row.getUserId()).isEqualTo(USER);
        assertThat(row.getRoleId()).isEqualTo(ROLE);
        assertThat(row.getId())
                .as("自定义 @Insert 不走 MyBatis-Plus 的 ASSIGN_UUID 填充 ⇒ 必须自己生成 id（否则 NOT NULL/主键报错）")
                .isNotBlank()
                .doesNotContain("-");
    }

    @Test
    @DisplayName("🔴 插入撞并发（影响 0 行）⇒ **幂等收敛**，不抛错")
    void insertConflictIsIdempotentNotAnError() {
        when(userRoleMapper.reviveSoftDeleted(TENANT, USER, ROLE)).thenReturn(0);
        when(userRoleMapper.insertIfAbsent(any(UserRole.class))).thenReturn(0);

        boolean changed = UserRoleWriter.ensureGranted(userRoleMapper, TENANT, USER, ROLE);

        assertThat(changed).as("已存在 ⇒ 本次没有变化，且**不抛 500**").isFalse();
        verify(userRoleMapper).insertIfAbsent(any(UserRole.class));
    }

    @Test
    @DisplayName("顺序即安全顺序：复活必须发生在插入**之前**（先插会撞软删行的键）")
    void reviveHappensBeforeInsert() {
        when(userRoleMapper.reviveSoftDeleted(anyLong(), anyString(), anyString())).thenReturn(1);

        UserRoleWriter.ensureGranted(userRoleMapper, TENANT, USER, ROLE);

        InOrder order = inOrder(userRoleMapper);
        order.verify(userRoleMapper).reviveSoftDeleted(TENANT, USER, ROLE);
        order.verify(userRoleMapper, never()).insertIfAbsent(any(UserRole.class));
    }
}
