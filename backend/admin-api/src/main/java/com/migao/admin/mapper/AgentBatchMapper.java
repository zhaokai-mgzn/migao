package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.AgentBatch;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

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
 * {@code executed_at}/{@code reverted_at}）。照抄别的表的 {@code deleted = 0} 会直接 SQL 报错。</p>
 */
@Mapper
public interface AgentBatchMapper extends BaseMapper<AgentBatch> {

    /**
     * 执行权 = DB 原子条件更新（CAS，issue #6960 本单新增）。
     *
     * <p>谓词 {@code status = 'preview'}：一张批次只能被**执行一轮**。0 行 ⇒ 409，且
     * <b>一条 apply 都不会跑</b>（闸位于逐条写之前 —— 这正是「只修一处」的反面：
     * 把闸放在逐条循环之后等于没放）。</p>
     *
     * <p>{@code status = 'executing'} 是**落库**的中间态（不是内存里跳过去的）——
     * 它同时是「本批次已被某个请求claim」的可见标记；执行完再由服务层写终态
     * {@code done}/{@code partial} + 计数 + {@code executed_at}（那些值要等逐条结果出来才知道，
     * 故不在这条语句里）。</p>
     *
     * @return 影响行数：{@code 1} = 本请求抢到执行权；{@code 0} = 已被执行 / 正在执行 / 未预览 / 批次不存在
     */
    @Update("UPDATE agent_batches SET status = 'executing' "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND status = 'preview'")
    int markExecuting(@Param("id") String id, @Param("tenantId") Long tenantId);

    /**
     * 撤销权 = **与 {@link #markExecuting} 同款**的 DB 原子条件更新（CAS，issue #6960 本单新增）。
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
     * @return 影响行数：{@code 1} = 本请求抢到撤销权；{@code 0} = 已被撤销 / 正在被撤销 / 状态不可撤销 / 批次不存在
     */
    @Update("UPDATE agent_batches SET status = 'executing' "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} "
            + "AND status IN (#{revertableA}, #{revertableB})")
    int markReverting(@Param("id") String id,
                      @Param("tenantId") Long tenantId,
                      @Param("revertableA") String revertableA,
                      @Param("revertableB") String revertableB);

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
}
