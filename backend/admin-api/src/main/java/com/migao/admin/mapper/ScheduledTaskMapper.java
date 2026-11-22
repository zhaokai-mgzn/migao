package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import com.migao.admin.entity.ScheduledTask;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Result;
import org.apache.ibatis.annotations.Results;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 定时任务（issue #6486 包 1）。对应表：{@code scheduled_tasks}。
 *
 * <p>查询口径**只写一处**（与 {@code CuttingHeightConfigMapper#selectActiveByTenant} 同款理由）：
 * 扫描器与商家读面共用这里的 where 条件 —— 各写一遍迟早一处漏 {@code deleted = 0}
 * （软删行被当成生效待办 = 静默投递一条已取消的提醒）。</p>
 *
 * <p>🔴 <b>扫描面只有一条路：原子领取</b>（集群 P0-2 / issue #9019，{@link #claimDueByTenant}）。改前是
 * 「{@code selectList(pending)} → 逐条发通知 → 改状态」的纯 read-modify-write ⇒ 多实例同秒读到
 * 同一批 pending 会各发一条（员工收到重复提醒，且事后两行都是 fired，从数据上分辨不出）。
 * 现在「判定 + 占位 + 取回」在<b>一条</b>语句里完成，拿不到行 = 别的实例先领走 ⇒ 静默跳过。</p>
 */
@Mapper
public interface ScheduledTaskMapper extends BaseMapper<ScheduledTask> {

    /**
     * 🔴 <b>原子领取本租户到期待办（集群 P0-2 / issue #9019）：一条语句完成「判定 + 占位 + 取回」。</b>
     *
     * <p><b>为什么必须是这个形态</b>（不是"看着优雅"）：</p>
     * <ul>
     *   <li><b>每一行只会被一个实例领走</b>：{@code WHERE status='pending'} 由 PG 在<b>行锁下重估</b>
     *       ⇒ 两个实例（乃至 N 个 pod）并发领同一批时，同一行只有一个事务能改到；另一侧读到 0 行，
     *       静默跳过（不是报错）。子查询的 {@code FOR UPDATE SKIP LOCKED} 让输家<b>不阻塞</b>
     *       （跨机房 RTT 下也不变成串行点）。</li>
     *   <li><b>副作用绑定"真正领到"</b>：{@code RETURNING} 只回本次真被占位的行 ⇒ 站内通知只对它们发
     *       （否则集群下每个实例各发一遍 —— 这正是改前的缺陷）。</li>
     *   <li><b>有界</b>：子查询 {@code ORDER BY fire_at LIMIT #{limit}} ⇒ 一次不把全租户积压拉进内存；
     *       超出的仍是 {@code pending}，下一轮继续（<b>不丢，只延后</b>）。</li>
     *   <li><b>单机与集群同一套代码</b>：不需要 leader 选举 / 分布式锁 / 开关 —— 互斥来自这条 SQL 本身。</li>
     * </ul>
     *
     * <p>{@code @InterceptorIgnore(tenantLine = "true")} + <b>显式</b> {@code tenant_id = #{tenantId}}：
     * 定制 SQL 的租户条件由调用方显式给出（与 {@code OrderMapper#autoCompleteShippedOrders} 同一套口径），
     * 不靠拦截器替我加 —— 少一层"条件到底加没加"的不可见性。</p>
     *
     * <p>🔴 <b>为什么是 {@code @Select} + CTE 而不是 {@code @Update}</b>（实测，不是口味）：
     * MyBatis 的 {@code @Update} 只接受 int/long/boolean/void —— 想拿 {@code RETURNING} 的行，
     * 声明 {@code List<ScheduledTask>} 会当场抛 {@code BindingException: unsupported return type}。
     * 写成 {@code WITH claimed AS (UPDATE … RETURNING …) SELECT … FROM claimed} 就同时拿到两样东西：
     * <b>仍然只有一条 SQL 语句</b>（CTE 里 UPDATE 与 SELECT 同一快照、同一事务），且返回类型合法。</p>
     *
     * <p>🔴 <b>为什么是 {@code WITH picked AS (SELECT … LIMIT n FOR UPDATE SKIP LOCKED)} 再
     * {@code UPDATE … FROM picked}</b>（真库实测，不是口味）：写成
     * {@code WHERE id IN (SELECT … ORDER BY … LIMIT n FOR UPDATE SKIP LOCKED)} 时 PG 会把带
     * 锁定子句的子查询**压平**，{@code LIMIT} 失效 —— 实测「LIMIT 1」一次领走全部 6 行
     * （见 {@code ScheduledTaskMultiInstanceClaimRealDbTest} 的判据 ④：领 1 条必须只得 1 条）。
     * CTE 形态把「选哪几行」先定下来（{@code picked}），UPDATE 只按 id 收口，{@code LIMIT} 才真正生效。</p>
     *
     * <p>只 {@code RETURNING} 投递真正用到的列（避开 JSONB 的 typeHandler 面）：投递读
     * {@code criterion} / {@code actionLabel} / {@code subjectId} / {@code subjectType}。</p>
     *
     * @param tenantId  只领本租户（多租户隔离的**显式**条件）
     * @param now       业务「现在」（{@code fire_at <= now} ⇒ 已到期）
     * @param limit     单轮单租户上限（疲劳控制）
     * @param claimedBy 本实例标识（写进 {@code claimed_by}，后续终态 CAS 的 fencing token）
     * @return 本次**真正被本实例领走**的行（0 行 = 本轮无到期 / 全被别的实例先领走）
     */
    @InterceptorIgnore(tenantLine = "true")
    // JSONB 字段必须显式绑 typeHandler：手写 select 不绑 ⇒ 列落成字符串 ⇒ instanceof 判据静默为假
    //（issue #3340 / #4865 同根因；判据见 JacksonTypeHandlerMappingGuardTest）
    @Results(id = "scheduledTaskClaim", value = {
            @Result(column = "impact", property = "impact", typeHandler = JacksonTypeHandler.class),
            @Result(column = "payload", property = "payload", typeHandler = JacksonTypeHandler.class)
    })
    @Select("WITH picked AS ("
            + "SELECT id FROM scheduled_tasks "
            + "WHERE tenant_id = #{tenantId} AND status = 'pending' AND deleted = 0 AND fire_at <= #{now} "
            + "ORDER BY fire_at LIMIT #{limit} FOR UPDATE SKIP LOCKED"
            + "), claimed AS ("
            + "UPDATE scheduled_tasks t SET status = 'firing', claimed_by = #{claimedBy}, "
            + "claimed_at = #{now}, updated_at = #{now} "
            + "FROM picked p WHERE t.id = p.id AND t.status = 'pending' AND t.deleted = 0 "
            + "RETURNING t.id, t.tenant_id, t.subject_type, t.subject_id, t.action_label, t.criterion"
            + ") SELECT id, tenant_id, subject_type, subject_id, action_label, criterion FROM claimed")
    List<ScheduledTask> claimDueByTenant(@Param("tenantId") Long tenantId,
                                        @Param("now") OffsetDateTime now,
                                        @Param("limit") int limit,
                                        @Param("claimedBy") String claimedBy);

    /**
     * 投递成功 ⇒ 置 {@code fired}（集群 P0-2 的**终态 CAS**）。
     *
     * <p>谓词里带 {@code status='firing' AND claimed_by=#{claimedBy}}（fencing token）：
     * 租约超时被回收、又被别的实例重新领走时，<b>僵尸实例即使还活着也写不回 fired</b>
     * （否则会把别人的投递结果覆盖成自己的）。0 行 = 租约已失效，调用方只记一条 incident，不重试。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE scheduled_tasks SET status = 'fired', fired_at = #{now}, updated_at = #{now} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'firing' "
            + "AND claimed_by = #{claimedBy} AND deleted = 0")
    int markFiredIfClaimed(@Param("id") String id,
                           @Param("tenantId") Long tenantId,
                           @Param("claimedBy") String claimedBy,
                           @Param("now") OffsetDateTime now);

    /**
     * 投递失败 ⇒ 置 {@code failed}（同样带 fencing 谓词，理由见 {@link #markFiredIfClaimed}）。
     *
     * <p>失败**不留在 pending**：留着会被下一轮反复重投、反复打扰用户（与改前同一口径）。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE scheduled_tasks SET status = 'failed', updated_at = #{now} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'firing' "
            + "AND claimed_by = #{claimedBy} AND deleted = 0")
    int markFailedIfClaimed(@Param("id") String id,
                            @Param("tenantId") Long tenantId,
                            @Param("claimedBy") String claimedBy,
                            @Param("now") OffsetDateTime now);

    /**
     * 租约回收（集群 P0-2 的**补偿腿**）：领取后实例崩溃 ⇒ 行停在 {@code firing}，谁来收回？
     *
     * <p>一条**跨租户**原子 UPDATE + 时效谓词（与 {@code AgentBatchMapper#markStaleExecutingPartial}
     * 同款范式）：{@code status='firing' AND claimed_at < 死线} ⇒ 放回 {@code pending} 并清空领取标记。
     * 谓词同时给出三条保证：① 领取已终态 ⇒ 0 行（幂等）；② 领取还新鲜 ⇒ 0 行（活实例不被误回收）；
     * ③ 只改状态与领取标记，**不碰业务字段**。</p>
     *
     * <p>{@code @InterceptorIgnore} 是必须的：回收跑在调度线程上、**没有请求上下文**（与
     * {@code AgentBatchMapper#selectExecutingTenantIds} 同一套口径）；留下的 WHERE 是纯字面条件 + 时间谓词，
     * 不读租户上下文 ⇒ 禁用拦截器**不削弱隔离**（回收的对象天然是「所有租户里已超时的领取」）。</p>
     *
     * <p>回收到 pending 后会被下一轮重新领取并**再投一次** —— 员工不会因此收到重复提醒，
     * 因为通知插入带幂等键 {@code scheduled_task:{taskId}}（V187 唯一索引兜底）。</p>
     *
     * @param staleBefore 死线 = 业务「现在」− 租约超时
     * @param now         业务「现在」（写 updated_at）
     * @return 本轮放回 pending 的行数（0 = 没有僵尸领取）
     */
    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE scheduled_tasks SET status = 'pending', claimed_by = NULL, claimed_at = NULL, "
            + "updated_at = #{now} "
            + "WHERE status = 'firing' AND deleted = 0 "
            + "AND (claimed_at IS NULL OR claimed_at < #{staleBefore})")
    int reclaimStaleClaims(@Param("staleBefore") OffsetDateTime staleBefore,
                           @Param("now") OffsetDateTime now);

    /**
     * 本租户的待办列表（读面）。
     *
     * @param status 为 {@code null} 时不按状态过滤（全量）
     */
    default List<ScheduledTask> selectByTenant(Long tenantId, String status, int limit) {
        LambdaQueryWrapper<ScheduledTask> q = new LambdaQueryWrapper<ScheduledTask>()
                .eq(ScheduledTask::getTenantId, tenantId)
                .eq(ScheduledTask::getDeleted, 0);
        if (status != null && !status.isBlank()) {
            q.eq(ScheduledTask::getStatus, status);
        }
        q.orderByAsc(ScheduledTask::getFireAt).last("LIMIT " + limit);
        return selectList(q);
    }

    /**
     * 幂等键命中检查（同租户 + 同 dedup_key + 未删）。命中 ⇒ 调用方**不重复建单**。
     */
    default ScheduledTask selectByDedupKey(Long tenantId, String dedupKey) {
        return selectOne(new LambdaQueryWrapper<ScheduledTask>()
                .eq(ScheduledTask::getTenantId, tenantId)
                .eq(ScheduledTask::getDedupKey, dedupKey)
                .eq(ScheduledTask::getDeleted, 0)
                .last("LIMIT 1"));
    }
}
