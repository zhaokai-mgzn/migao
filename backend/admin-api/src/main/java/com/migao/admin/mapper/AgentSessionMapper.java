package com.migao.admin.mapper;

import com.migao.admin.entity.AgentSession;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;

/**
 * 客服会话 Mapper 接口
 */
@Mapper
public interface AgentSessionMapper extends BaseMapper<AgentSession> {

    /**
     * 抢占会话的「分配权」= 条件更新（CAS，issue #6962 P5-① 的第一道闸）。
     *
     * <p><b>为什么不是 {@code updateById}</b>：修前 {@code AgentSessionService#assignSession} 先
     * {@code selectById} 判 {@code status='waiting'}、再 {@code updateById(session)}
     * （WHERE 仅主键 ⇒ <b>无谓词</b>）⇒ 同一个 {@code sessionId} 被两个管理员同时分配时
     * <b>两个请求都成功</b>（后写者覆盖 {@code employee_id}）。</p>
     *
     * <p><b>谓词</b>：{@code id} + {@code tenant_id}（显式租户列纪律，不依赖拦截器在场）+
     * {@code status='waiting'}（本单的迁移前驱）+ {@code deleted=0}。受影响行数 {@code 0}
     * ⇒ 会话不存在 / 跨租户 / 已软删 / 已被别人分配 ⇒ 调用方 fail-closed（409 + 实际当前态）。</p>
     *
     * @return 受影响行数（{@code 0} = 没抢到分配权）
     */
    @Update("UPDATE agent_sessions SET employee_id = #{employeeId}, status = 'active', " +
            "started_at = #{startedAt}, updated_at = #{startedAt} " +
            "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'waiting' AND deleted = 0")
    int markAssignedIfWaiting(@Param("id") String id, @Param("tenantId") Long tenantId,
                              @Param("employeeId") String employeeId,
                              @Param("startedAt") OffsetDateTime startedAt);

    /**
     * <b>抢并发额度（原子闸）</b>（issue #6962 P5-① 的第二道闸）：以
     * {@code FOR NO KEY UPDATE} 锁住员工行，把「读计数 → 判额度 → 占用额度」三段压成
     * <b>一次持锁的临界区</b>。
     *
     * <p><b>⚠️ 为什么是 {@code FOR NO KEY UPDATE} 而不是 {@code FOR UPDATE}（真库实测订正，别改回去）</b>：
     * {@code agent_sessions.employee_id → agent_employees} 的<b>外键</b>使得 {@link #markAssignedIfWaiting}
     * 那条 {@code INSERT/UPDATE} 会先在外键指向的员工行上取 <b>{@code FOR KEY SHARE}</b>；而
     * {@code FOR UPDATE} 与 {@code FOR KEY SHARE} <b>互斥</b> ⇒ 清额度时对同一行升级锁会与另一个请求
     * 已成环 ⇒ PostgreSQL 死锁检测把请求打成 <b>500</b>（实测 6 并发：<b>1 成功 + 5 个 500 死锁</b>，
     * 而不是「3 成功 + 3 个 409」）。{@code FOR NO KEY UPDATE} 与 {@code FOR KEY SHARE} <b>相容</b>、
     * 与自身互斥 ⇒ 只串行化「抢额度」这一步，既不破外键语义也不死锁（改后 6 并发 = 3 成功 + 3 个 409）。</p>
     *
     * <p><b>为什么必须显式取锁、而不是「{@code UPDATE … WHERE current &lt; max}」</b>
     * （本单实测订正，别退回那个直觉形态）：{@code UPDATE} 只在<b>命中行</b>时才取行锁；并发超额时
     * 谓词不成立 ⇒ <b>两个请求都拿 0 行、都不取锁、都不阻塞</b> ⇒ 各自再在子查询里读到「尚未提交的
     * 旧计数」⇒ <b>上限照样被突破</b>（缺陷只是从「读-判-写」挪进了子查询）。{@code SELECT … FOR NO KEY UPDATE}
     * 不管额度够不够都先锁住员工行（锁持有到事务结束），后到者阻塞到前者提交、再重新求值
     * {@link #countActiveSessions} ⇒ 计数必然包含前者的占用 ⇒ 上限守得住。</p>
     *
     * <p><b>为什么计数不落在 {@code agent_employees} 的计数列上</b>：该表没有此列
     * （{@code db/init/schema.sql} 自证：只有 {@code max_concurrent_sessions}），加一列 = 第二份
     * 口径，得靠每个 {@code endSession} 点同步维护，漏一处即永久漂移。真值源 = 会话表本身。</p>
     *
     * <p><b>锁序</b>：调用方先取会话行（{@link #markAssignedIfWaiting}）、再取员工行（本方法），
     * 全局一致 ⇒ 无环、不成死锁。</p>
     *
     * @return 员工行的 {@code id}（{@code null} = 不存在 / 跨租户 / 已软删）
     */
    @Select("SELECT id FROM agent_employees " +
            "WHERE id = #{employeeId} AND tenant_id = #{tenantId} AND deleted = 0 FOR NO KEY UPDATE")
    String lockEmployeeForQuota(@Param("employeeId") String employeeId, @Param("tenantId") Long tenantId);

    /** 员工的最大并发会话数（{@code null} 列值 ⇒ 调用方按 5 兜底，与修前口径一致）。 */
    @Select("SELECT max_concurrent_sessions FROM agent_employees WHERE id = #{employeeId}")
    Integer selectMaxConcurrentSessions(@Param("employeeId") String employeeId);

    /**
     * 现取「该员工当前 active 会话数」（在 {@link #lockEmployeeForQuota} 持锁之后调用 ⇒
     * 读到的是被锁串行化后的确定值）。{@code tenant_id} + {@code deleted = 0} 显式写在谓词上。
     */
    @Select("SELECT COUNT(*) FROM agent_sessions " +
            "WHERE employee_id = #{employeeId} AND tenant_id = #{tenantId} " +
            "AND status = 'active' AND deleted = 0")
    int countActiveSessions(@Param("employeeId") String employeeId, @Param("tenantId") Long tenantId);
}
