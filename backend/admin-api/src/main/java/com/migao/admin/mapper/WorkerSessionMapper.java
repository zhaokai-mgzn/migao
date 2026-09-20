package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.WorkerSession;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;

/**
 * 工人登录态 Mapper（V98，issue #4733）。
 *
 * <p>租户条件由 {@code TenantLineInnerInterceptor} 自动注入（{@code worker_sessions} 不在忽略清单里）
 * ⇒ 解析 session 时**必须**先有租户上下文，否则插件抛
 * {@code Tenant context not initialized}（fail-closed，不静默跨租户）。</p>
 */
@Mapper
public interface WorkerSessionMapper extends BaseMapper<WorkerSession> {

    /**
     * 按 id 查活跃会话（未软删、未结束）。
     *
     * @return 会话行；不存在/已结束 ⇒ {@code null}（调用方 fail-closed 拒绝）
     */
    @Select("SELECT id, tenant_id, worker_id, worker_no, worker_name, device_label, started_at, "
            + "last_seen_at, idle_expires_at, ended_at, end_reason, created_at, updated_at, deleted "
            + "FROM worker_sessions WHERE id = #{id} AND deleted = 0 AND ended_at IS NULL")
    WorkerSession selectActiveById(@Param("id") String id);

    /**
     * 刷新活跃时刻并顺延闲置过期（每次成功请求一次）。
     *
     * <p>谓词 {@code ended_at IS NULL AND deleted = 0} 是「已切换/已登出的会话不得被复活」的机械保证。</p>
     *
     * @return 1 = 已顺延；0 = 会话已被结束/软删（调用方 fail-closed）
     */
    @Update("UPDATE worker_sessions SET last_seen_at = #{lastSeenAt}, idle_expires_at = #{idleExpiresAt}, "
            + "updated_at = #{lastSeenAt} "
            + "WHERE id = #{id} AND deleted = 0 AND ended_at IS NULL")
    int touch(@Param("id") String id,
              @Param("lastSeenAt") OffsetDateTime lastSeenAt,
              @Param("idleExpiresAt") OffsetDateTime idleExpiresAt);

    /**
     * 结束会话（登出 / 闲置超时 / 快速切换 / 停用撤销）。
     *
     * <p>谓词 {@code ended_at IS NULL} ⇒ 幂等：重复结束不改首次的 {@code ended_at} 与 {@code end_reason}
     * （「谁先结束的」不被后来的动作覆盖）。</p>
     *
     * @return 1 = 本次结束生效；0 = 已经是结束态（幂等空操作）
     */
    @Update("UPDATE worker_sessions SET ended_at = #{endedAt}, end_reason = #{endReason}, "
            + "updated_at = #{endedAt} "
            + "WHERE id = #{id} AND deleted = 0 AND ended_at IS NULL")
    int endSession(@Param("id") String id,
                   @Param("endedAt") OffsetDateTime endedAt,
                   @Param("endReason") String endReason);
}
