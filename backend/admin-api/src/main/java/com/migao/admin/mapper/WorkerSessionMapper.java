package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
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
 * ⇒ **除 {@link #selectActiveById} 外**，本 Mapper 的每条 SQL 都带
 * {@code tenant_id = <TenantContext>}；上下文缺失时插件抛
 * {@code Tenant context not initialized}（fail-closed，不静默跨租户）。</p>
 *
 * <p>🔴 <b>唯一的例外是 {@link #selectActiveById}</b>（issue #4864）：会话解析**必须**先拿到行
 * 才能知道租户，而租户拦截器要求先有租户 ⇒ 死循环（线上形态 = 工人端除 {@code /login} 外
 * 全链路 401）。例外只开在这一条**按主键**的查询上，安全性论证见该方法的 javadoc ——
 * 不满足那三条论证时**不得**扩大这个例外。</p>
 */
@Mapper
public interface WorkerSessionMapper extends BaseMapper<WorkerSession> {

    /**
     * 按 id 查活跃会话（未软删、未结束）。
     *
     * <p>🔴 <b>{@code @InterceptorIgnore(tenantLine = "true")}：本查询不注入 {@code tenant_id}
     * （issue #4864）</b>。因为这条查询**就是用来解出租户的那一步** —— 请求里唯一携带的凭据是
     * {@code X-Worker-Session-Id}，租户在读到行之前**不可能**存在（要租户才能读、要读才能有租户）。
     * 改前它被租户拦截器拦下并抛 {@code Tenant context not initialized}，被
     * {@link com.migao.admin.security.WorkerSessionFilter} 的 catch 吞成「未认证」⇒
     * {@code /api/worker/**} 除 {@code /login} 外**全部 401**。</p>
     *
     * <p><b>为什么不会造成跨租户读</b>（三条同时成立才成立，缺一不可）：</p>
     * <ol>
     *   <li><b>键是主键且不可猜</b>：{@code id} 由服务端 {@code UUID.randomUUID()} 生成
     *       （32 位十六进制、V98 里是 {@code PRIMARY KEY}）⇒ 按主键**至多命中一行**；
     *       本方法没有「列表 / 通配 / 范围」形态可供枚举 ⇒ 忽略租户过滤**不会扩大结果集**，
     *       拿到它的人本来就持有了该会话凭据本身。</li>
     *   <li><b>租户只来自这一行、绝不来自请求</b>：调用方
     *       （{@link com.migao.admin.worker.WorkerSessionService}）读完行**立即**把
     *       {@code TenantContext} 设成该行的 {@code tenant_id} ⇒ 本线程此后的**所有**查询
     *       （{@code touch} / {@code endSession} / 业务读面）恢复租户过滤。</li>
     *   <li><b>请求已带租户时必须一致</b>：线程上若已有 {@code TenantContext}（商家 JWT /
     *       Service Token），会话租户与之不符 ⇒ 一律当无效会话拒绝（见
     *       {@code WorkerSessionService} 里那条 fail-closed 判定）⇒ 不存在
     *       「拿别的租户的 session id 换租户」这条路。</li>
     * </ol>
     *
     * @return 会话行；不存在/已结束 ⇒ {@code null}（调用方 fail-closed 拒绝）
     */
    @InterceptorIgnore(tenantLine = "true")
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
