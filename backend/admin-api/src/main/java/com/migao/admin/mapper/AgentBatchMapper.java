package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.AgentBatch;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;
import java.util.List;

/**
 * 批次 Mapper（issue #5314）。标准 CRUD 由 {@code TenantLineInnerInterceptor}
 * 自动注入租户过滤 ⇒ {@code selectById} 天然看不见别的租户的批次（跨租户 = NOT_FOUND）。
 *
 * <p>执行 / 撤销的**准入闸**是条件更新（CAS，issue #6960）：改前
 * {@code AgentBatchService#execute} 与 {@code #revert} 都是「先读批次判状态 → 逐条 apply →
 * 再无条件 {@code updateById}」⇒ 两个并发 execute 都能读到 {@code preview} 并各 apply 一轮
 * （对同一批商品**重复 apply**）；并发 revert 同形。把判断与写入压进**同一条语句**后，
 * 后到者（阻塞到先到者提交后按新版本行重估）影响行数 0 ⇒ 当场 409，apply 一轮都不跑。</p>
 *
 * <p>⚠️ 谓词里**没有** {@code deleted}：{@code agent_batches} 的 DDL 里没有这一列
 * （逐字核对 {@code db/init/schema.sql} 的 {@code CREATE TABLE agent_batches} —— 只有
 * {@code id}/{@code tenant_id}/{@code batch_type}/{@code status}/{@code item_count}/
 * {@code success_count}/{@code fail_count}/{@code created_by}/{@code created_at}/
 * {@code executed_at}/{@code reverted_at}/{@code executor_id}/{@code heartbeat_at}）。
 * 照抄别的表的 {@code deleted = 0} 会直接 SQL 报错。</p>
 *
 * <h2>执行租约（issue #8285，迁移 V208）</h2>
 * <p>进程内线程池 job 的「谁在跑」只活在内存里 ⇒ JVM 崩溃 / 强杀后无法与「真的还在跑」区分，
 * 多实例下更不能安全地做全量回收（B 实例会误杀 A 实例正在跑的批次）。本 Mapper 承载租约的
 * <b>三条 SQL 事实</b>（判断全落在语句里，不靠调用方自觉）：</p>
 * <ol>
 *   <li><b>claim 即写租约</b>：{@link #markExecuting} / {@link #markReverting} 把
 *       {@code executor_id} + {@code heartbeat_at} 与状态迁移写在**同一条** UPDATE 里 ——
 *       不存在「已是 executing 但心跳为空」的中间窗口（那个窗口会被回收器当成崩溃遗留）。</li>
 *   <li><b>心跳刷新 = 带 executor 谓词的条件写</b>（{@link #heartbeat}）：1 行 = 租约仍属本 job；
 *       0 行 = 已被回收 / 被吊销 ⇒ 服务层**立刻停手**（不再 apply，也不落终态）。</li>
 *   <li><b>回收 = 一条带时效谓词的原子 UPDATE</b>（{@link #markStaleExecutingPartial}）：
 *       {@code status='executing' AND (heartbeat_at IS NULL OR heartbeat_at < 截止时刻)} ⇒ {@code partial}。
 *       谓词同时给出三条保证：① 心跳新鲜 ⇒ 0 行（活 job 不被误杀）；② 状态已不是 executing ⇒ 0 行
 *       （**幂等** + **不覆盖终态**）；③ 只改批次行、**不碰明细**（不伪造 item 成功，可撤销仍逐条还原）。</li>
 * </ol>
 * <p>⇒ 终态 CAS（{@link #markExecutedDone} 一族）因此多带一个 {@code executor_id} 谓词（fencing token）：
 * 被回收的僵尸 job 即使还活着，也写不回 {@code done}（否则「回收成 partial → 用户撤销 → 批次又被置回
 * executing」之后，僵尸终态写会把撤销结果覆盖成 done）。</p>
 */
@Mapper
public interface AgentBatchMapper extends BaseMapper<AgentBatch> {

    /**
     * 执行权 = DB 原子条件更新（CAS，issue #6960）。
     *
     * <p>谓词 {@code status = 'preview'}：一张批次只能被**执行一轮**。0 行 ⇒ 409，且
     * <b>一条 apply 都不会跑</b>（闸位于逐条写之前 —— 这正是「只修一处」的反面：
     * 把闸放在逐条循环之后等于没放）。</p>
     *
     * <p>{@code status = 'executing'} 是**落库**的中间态（不是内存里跳过去的）——
     * 它同时是「本批次已被某个请求 claim」的可见标记；执行完再由服务层写终态
     * {@code done}/{@code partial} + 计数 + {@code executed_at}（那些值要等逐条结果出来才知道，
     * 故不在这条语句里）。</p>
     *
     * <p>🔴 租约（issue #8285）：{@code executor_id} + {@code heartbeat_at} 与状态迁移写在**同一条**语句里
     * ⇒ 不存在「executing 但心跳为空」的窗口（回收器把「为空」当崩溃遗留）。</p>
     *
     * @return 影响行数：{@code 1} = 本请求抢到执行权；{@code 0} = 已被执行 / 正在执行 / 未预览 / 批次不存在
     */
    @Update("UPDATE agent_batches SET status = 'executing', executor_id = #{executorId}, "
            + "heartbeat_at = #{heartbeatAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'preview'")
    int markExecuting(@Param("id") String id,
                      @Param("tenantId") Long tenantId,
                      @Param("executorId") String executorId,
                      @Param("heartbeatAt") OffsetDateTime heartbeatAt);

    /**
     * 撤销权 = **与 {@link #markExecuting} 同款**的 DB 原子条件更新（CAS，issue #6960）。
     *
     * <p>可撤销的准入状态只有 {@code done} / {@code partial}（契约：非此二者、或已
     * {@code reverted} / {@code revert_partial} 的批次不可撤销）⇒ 谓词是「状态 ∈ 契约里的那一对」，
     * 由服务层把这一对状态传进来（**不在这里写死**：契约改了而 SQL 静默漂移 = 第二份会烂的口径）。</p>
     *
     * <p>抢到之后先把状态置成 {@code executing}（= 「已被某个请求 claim」），逐条还原完再由服务层写
     * 终态 {@code reverted} / {@code revert_partial} + {@code reverted_at}。选 {@code executing}
     * 而不是新加一个 {@code reverting}：后者要改 DB 的 {@code ck_agent_batch_status} 约束
     * （迁移 + 存量面），而本单的判据只要求「并发下恰一轮」—— 用**已存在的列与取值**就够，
     * 不为一个中间态扩数据库口径。</p>
     *
     * <p>租约同 {@link #markExecuting}：撤销也是一条后台 job，也要有 executor + 心跳，
     * 否则「撤销到一半崩了」的批次同样无法被安全回收（它会永远停在 {@code executing}）。</p>
     *
     * @return 影响行数：{@code 1} = 本请求抢到撤销权；{@code 0} = 已被撤销 / 正在被撤销 / 状态不可撤销 / 批次不存在
     */
    @Update("UPDATE agent_batches SET status = 'executing', executor_id = #{executorId}, "
            + "heartbeat_at = #{heartbeatAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} "
            + "AND status IN (#{revertableA}, #{revertableB})")
    int markReverting(@Param("id") String id,
                      @Param("tenantId") Long tenantId,
                      @Param("revertableA") String revertableA,
                      @Param("revertableB") String revertableB,
                      @Param("executorId") String executorId,
                      @Param("heartbeatAt") OffsetDateTime heartbeatAt);

    /**
     * 执行中的进度（issue #8283）：只写计数，不碰 status / executed_at。
     *
     * <p>谓词带 {@code status='executing'} ⇒ 批次已进入终态（或已被人工处置）时本条更新自然失效，
     * 不会把终态计数改回去。逐条写只发生在同一个 job 线程内，不需要 CAS。</p>
     *
     * @return 影响行数：{@code 1} = 仍在执行；{@code 0} = 已不在执行态（忽略即可）
     */
    @Update("UPDATE agent_batches SET success_count = #{successCount}, fail_count = #{failCount} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'executing'")
    int updateProgress(@Param("id") String id,
                       @Param("tenantId") Long tenantId,
                       @Param("successCount") int successCount,
                       @Param("failCount") int failCount);

    /**
     * 心跳刷新 + **租约校验**（issue #8285）：{@code heartbeat_at = 现在}，同时用
     * {@code executor_id} 谓词确认「这一批仍归我跑」。
     *
     * <p>为什么合并成一条：0 行同时表达「已被回收」「已被别人抢到」「已进终态」三种事实，而调用方要做的
     * 动作是同一个 —— **立刻停手**。拆成「先查再写」会多一个判断与写入之间的窗口，还会多一次往返。</p>
     *
     * <p>⚠️ 它**不写 status**（SET 侧只有 heartbeat_at）⇒ 不被
     * {@code AgentBatchStatusCasMetaGuardTest} 当成状态迁移写面；但它确实是「执行权」的一部分，
     * 所以同样带 {@code tenant_id} 与来源态谓词。</p>
     *
     * @return 影响行数：{@code 1} = 租约仍是本 job 的（已续期）；{@code 0} = 已失去执行权 ⇒ 停手
     */
    @Update("UPDATE agent_batches SET heartbeat_at = #{heartbeatAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'executing' "
            + "AND executor_id = #{executorId}")
    int heartbeat(@Param("id") String id,
                  @Param("tenantId") Long tenantId,
                  @Param("executorId") String executorId,
                  @Param("heartbeatAt") OffsetDateTime heartbeatAt);

    /**
     * 🔴 **崩溃回收**（issue #8285）：把「心跳超时或从未心跳」的 {@code executing} 批次收回成
     * {@code partial}（可撤销）。一条语句同时给出判据 1/2/4 的三条（见类注释 ③）：
     * <ul>
     *   <li><b>活 job 不被误杀</b>：{@code heartbeat_at >= 截止时刻} ⇒ 0 行；</li>
     *   <li><b>幂等 + 不覆盖终态</b>：谓词 {@code status='executing'} ⇒ 第二次跑 / 已 {@code done} /
     *       已 {@code partial} / 已 {@code reverted} / 已 {@code revert_partial} 一律 0 行；</li>
     *   <li><b>不伪造 item 成功</b>：只写批次行，明细表一条都不碰（{@code old_value} 仍是撤销的唯一依据）。</li>
     * </ul>
     *
     * <p>{@code executor_id = NULL} 是刻意的：回收后这批「无主」，且僵尸 job 的心跳 / 终态写（都带
     * {@code executor_id} 谓词）当场 0 行 ⇒ 它停手，而不是把 {@code partial} 覆盖回 {@code done}。</p>
     *
     * <p>{@code executed_at = COALESCE(executed_at, #{now})}：不覆盖既有值（正常执行完的批次已有），
     * 只把「回收时刻」记在从没跑完过的批次上 —— 页面上不再显示一个永远为空的完成时间。</p>
     *
     * <p>租户显式给出（不靠拦截器替我加）：调度线程逐租户循环，谓词与上下文由调用方钉成同一个值。</p>
     *
     * @param staleBefore 截止时刻（= 现在 − 超时）；小于它的心跳视为已死
     * @return 影响行数（本轮真正被回收的批次数）
     */
    @Update("UPDATE agent_batches SET status = 'partial', executor_id = NULL, "
            + "executed_at = COALESCE(executed_at, #{now}) "
            + "WHERE tenant_id = #{tenantId} AND status = 'executing' "
            + "AND (heartbeat_at IS NULL OR heartbeat_at < #{staleBefore})")
    int markStaleExecutingPartial(@Param("tenantId") Long tenantId,
                                  @Param("staleBefore") OffsetDateTime staleBefore,
                                  @Param("now") OffsetDateTime now);

    /**
     * 回收器的**取数面**：当前有 {@code executing} 批次的租户 id（与 {@code OrderMapper#selectShippedTenantIds}
     * 同一套口径）。
     *
     * <p>为什么要跨租户：回收跑在调度线程上，没有请求上下文；而判定必须**逐租户**做（写面带
     * {@code tenant_id} 谓词、拦截器也要读租户上下文）⇒ 先取「可能有哪些租户」这张超集清单，再逐租户回收。
     * 用 {@code DISTINCT tenant_id} 而不是遍历全部租户：活跃批次是个小集合。</p>
     *
     * <p>{@code @InterceptorIgnore(tenantLine = "true")} 是必须的（本查询**故意跨租户**，它的产物就是租户 id
     * 列表），留下的 WHERE 是纯字面条件、不读租户上下文 ⇒ 禁用拦截器**不削弱隔离**。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Select("SELECT DISTINCT tenant_id FROM agent_batches WHERE status = 'executing'")
    List<Long> selectExecutingTenantIds();

    /**
     * 执行终态 CAS（issue #8283）：{@code executing → done}，并落计数 + {@code executed_at}。
     *
     * <p>为什么终态也要条件写：后台 job 与前台的并发处置（回收 / 人工改态）可能同时发生；只按主键
     * {@code updateById} 会把对方刚写的终态覆盖回去。谓词带 {@code status='executing'} ⇒ 只有仍由
     * 本 job 持有的批次才能落终态，0 行时服务层只记日志、不覆盖。</p>
     *
     * <p>🔴 再加 {@code executor_id} 谓词（issue #8285 的 fencing）：{@code status='executing'} 单独一条
     * **挡不住僵尸 job** —— 被回收成 {@code partial} 之后批次还能被用户撤销（又置回 {@code executing}，
     * 但 executor 已换人），此时上一个 job 的终态写会命中并把它改成 {@code done}。带上 executor 后
     * 它只可能命中自己那一轮。</p>
     */
    @Update("UPDATE agent_batches SET status = 'done', success_count = #{successCount}, "
            + "fail_count = #{failCount}, executed_at = #{executedAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'executing' "
            + "AND executor_id = #{executorId}")
    int markExecutedDone(@Param("id") String id,
                         @Param("tenantId") Long tenantId,
                         @Param("successCount") int successCount,
                         @Param("failCount") int failCount,
                         @Param("executedAt") OffsetDateTime executedAt,
                         @Param("executorId") String executorId);

    /** 执行终态 CAS（部分失败）：{@code executing → partial}，语义同 {@link #markExecutedDone}。 */
    @Update("UPDATE agent_batches SET status = 'partial', success_count = #{successCount}, "
            + "fail_count = #{failCount}, executed_at = #{executedAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'executing' "
            + "AND executor_id = #{executorId}")
    int markExecutedPartial(@Param("id") String id,
                            @Param("tenantId") Long tenantId,
                            @Param("successCount") int successCount,
                            @Param("failCount") int failCount,
                            @Param("executedAt") OffsetDateTime executedAt,
                            @Param("executorId") String executorId);

    /** 撤销终态 CAS：{@code executing → reverted}（fencing 谓词同 {@link #markExecutedDone}）。 */
    @Update("UPDATE agent_batches SET status = 'reverted', reverted_at = #{revertedAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'executing' "
            + "AND executor_id = #{executorId}")
    int markReverted(@Param("id") String id,
                     @Param("tenantId") Long tenantId,
                     @Param("revertedAt") OffsetDateTime revertedAt,
                     @Param("executorId") String executorId);

    /** 撤销终态 CAS（部分失败）：{@code executing → revert_partial}，语义同 {@link #markReverted}。 */
    @Update("UPDATE agent_batches SET status = 'revert_partial', reverted_at = #{revertedAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'executing' "
            + "AND executor_id = #{executorId}")
    int markRevertPartial(@Param("id") String id,
                          @Param("tenantId") Long tenantId,
                          @Param("revertedAt") OffsetDateTime revertedAt,
                          @Param("executorId") String executorId);
}
