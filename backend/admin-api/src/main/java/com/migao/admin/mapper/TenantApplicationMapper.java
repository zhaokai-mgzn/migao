package com.migao.admin.mapper;

import com.migao.admin.entity.TenantApplication;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;

/**
 * 企业入驻申请 Mapper 接口
 */
@Mapper
public interface TenantApplicationMapper extends BaseMapper<TenantApplication> {

    /**
     * 审批通过权的**原子闸**（CAS，issue #6954）：只有当前仍是 {@code pending} 才置 {@code approved}。
     *
     * <p><b>为什么不能用「先读 status 判 pending，再 {@code updateById} 收尾」</b>：
     * {@code RegistrationService#approveApplication} 在收尾写之前会**先建租户 + 管理员 + 初始数据**
     * （读判 → 副作用 → 收尾 {@code updateById}）。读与写之间的窗口里，并发的第二个请求会读到同一个
     * {@code pending} 并通过判断 ⇒ **两边的租户都真的建出来**，后写覆盖前写 ⇒ 一个租户变成
     * **无主租户**（不可逆副作用）。条件更新的「判断」与「写入」是**同一条语句**，PostgreSQL 对命中行
     * 加行锁并持有到事务结束 ⇒ 并发的第二个请求要么阻塞到前者提交、要么看到 0 行受影响。</p>
     *
     * <p><b>调用点必须在任何副作用之前</b>（本单的核心口径）：拿到 1 行才谈得上建租户；
     * 先建后判 = 窗口白留（伤害已经发生，判出来也回不去）。</p>
     *
     * <p>{@code reviewed_at} 与状态**同一句**写入：「谁在何时把它审结」不能与状态迁移分成两次写
     * （中间态无法追责）。{@code updated_at = NOW()} 也必须显式写 —— 手写 SQL 不经
     * {@code MyMetaObjectHandler} 的 {@code updateFill}（{@code @TableField(fill = INSERT_UPDATE)}
     * 只对 MyBatis-Plus 自动生成的 SQL 生效）。</p>
     *
     * <p>⚠️ <b>本表没有 {@code deleted} 列</b>（{@code tenant_applications} 无软删语义）⇒
     * 谓词**不得**带 {@code deleted = 0}（带上就是 SQL 报错，不是更安全）。</p>
     *
     * @return 影响行数：{@code 1} = 本请求抢到审批权；{@code 0} = 已被审结（approved / rejected）/ 单不存在
     */
    @Update("UPDATE tenant_applications SET status = 'approved', reviewed_by = #{reviewerId}, "
            + "reviewed_at = #{reviewedAt}, reject_reason = NULL, review_source = #{reviewSource}, "
            + "risk_flags = #{riskFlags}, review_summary = #{reviewSummary}, updated_at = NOW() "
            + "WHERE id = #{id} AND status = 'pending'")
    int approveIfPending(@Param("id") Long id,
                         @Param("reviewerId") String reviewerId,
                         @Param("reviewedAt") OffsetDateTime reviewedAt,
                         @Param("reviewSource") String reviewSource,
                         @Param("riskFlags") String riskFlags,
                         @Param("reviewSummary") String reviewSummary);

    /**
     * 驳回权的**原子闸**（CAS，issue #6954）：只有当前仍是 {@code pending} 才置 {@code rejected}。
     *
     * <p><b>为什么必须与 {@link #approveIfPending} 同款</b>：两者争的是**同一份审批权**。
     * 若只有 approve 带 CAS 而 reject 仍走无谓词 {@code updateById}，则「并发 approve × reject」下
     * reject 会**覆写**已通过的那次审结 ⇒ 终态 {@code rejected} 而租户、管理员、初始数据
     * **已经建在库里**（租户在、申请单说没通过：自相矛盾的终态，且无人能登录）。</p>
     *
     * <p>{@code reject_reason} 与状态同句写入（同「不可分两次写」口径）；
     * {@code updated_at} 必须显式写（手写 SQL 不经 {@code updateFill}）；
     * 谓词不带 {@code deleted = 0}（本表无该列）。</p>
     *
     * @return 影响行数：{@code 1} = 本请求抢到驳回权；{@code 0} = 已被审结 / 单不存在
     */
    @Update("UPDATE tenant_applications SET status = 'rejected', reviewed_by = #{reviewerId}, "
            + "reviewed_at = #{reviewedAt}, reject_reason = #{reason}, review_source = #{reviewSource}, "
            + "risk_flags = #{riskFlags}, review_summary = #{reviewSummary}, updated_at = NOW() "
            + "WHERE id = #{id} AND status = 'pending'")
    int rejectIfPending(@Param("id") Long id,
                        @Param("reviewerId") String reviewerId,
                        @Param("reason") String reason,
                        @Param("reviewedAt") OffsetDateTime reviewedAt,
                        @Param("reviewSource") String reviewSource,
                        @Param("riskFlags") String riskFlags,
                        @Param("reviewSummary") String reviewSummary);
}
