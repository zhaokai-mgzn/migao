package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingPositionOperation;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 工序实例 Mapper（V49，issue #3995）：扫码报工的推进单元
 */
@Mapper
public interface ProcessingPositionOperationMapper extends BaseMapper<ProcessingPositionOperation> {

    /**
     * 报工推进的**原子有序更新**（issue #4116 §5-1/5-3）：仅当该行仍处于「读到的旧值」时才累加。
     *
     * <p>为什么不能用 {@code updateById}（丢更新窗口）：两条**并发**报工（扫码重试 / 另一台设备）
     * 各自 SELECT 到同一 {@code done_qty}，各自算出新值再 UPDATE ⇒ 后写者覆盖先写者，
     * 一次报工凭空消失、计件台账（{@code production_work_logs}）与进度（{@code done_qty}）对不上。
     * 幂等键只挡「同键重放」，挡不住两个不同键或未带键的并发请求 —— 这是**另一个**洞，必须由
     * 「读到的旧值」谓词关闭：谓词不成立（行已被别的请求推进）= 影响行数 0 ⇒ 调用方 fail-closed。</p>
     *
     * <p>单调不回退：{@code done_qty < #{expectedDoneQty}} 排除「把进度改小」的迟到写入。
     * 谓词逐字对应调用方 SELECT 出的旧值（{@code done_qty} / {@code status}），
     * 故影响行数 1 = 「本请求的报工真的生效了」，不会被别人的写入冒充。</p>
     *
     * @param expectedDoneQty 读到的旧 done_qty（CAS 期望值）
     * @param expectedStatus  读到的旧 status（CAS 期望值）
     * @param doneQty         推进后的累计合格数量（调用方已按 §5-3 上限校验）
     * @return 1 = 本次推进生效；0 = 该行已被并发请求推进（或工序不存在/软删/跨租户）
     */
    @Update("UPDATE processing_position_operations SET done_qty = #{doneQty}, status = 'done', "
            + "updated_at = #{updatedAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 "
            + "AND done_qty = #{expectedDoneQty} AND status = #{expectedStatus} "
            + "AND done_qty < #{doneQty}")
    int advanceDoneQtyIfUnchanged(@Param("id") String id,
                                  @Param("tenantId") Long tenantId,
                                  @Param("expectedDoneQty") BigDecimal expectedDoneQty,
                                  @Param("expectedStatus") String expectedStatus,
                                  @Param("doneQty") BigDecimal doneQty,
                                  @Param("updatedAt") OffsetDateTime updatedAt);

    /**
     * 完工时刻快照（V92 列 {@code done_at}，切片 ② / issue #4698；设计 §4.3 / §5.2）。
     *
     * <p><b>A 模式</b>（「做完扫一次 = 完工」）的唯一必需新时序列：卡点判据（切片 ③）读它算
     * 「上道几点完成、等了多久」。🔴 语义 = <b>本道真正做完的那一刻</b>（{@code done_qty ≥ qty}，
     * 与 {@code ProductionService.isDone} 同口径）—— <b>不</b>用 {@code updated_at} 冒充
     * （它会被任何后续更新污染：改单价 / 补报身份 / 重排都会写它 ⇒「完成时刻」静默漂移）。</p>
     *
     * <p><b>幂等由 SQL 机械保证</b>（不靠调用方自觉）：{@code COALESCE(done_at, #{doneAt})} ——
     * 只有第一次落笔生效，同键重放 / 二次完成 / 并发重复调用都**不会**改写已记下的完成时刻。
     * 谓词 {@code done_qty >= qty} 保证「部分报工（6/11 米）」<b>不</b>落 {@code done_at}：
     * 部分报工也把 {@code status} 置 {@code done}（既有偏离），但没做完就不是完工时刻。</p>
     *
     * <p>🔴 只写 {@code done_at} 一列：{@code done_qty} / {@code status} 由
     * {@link #advanceDoneQtyIfUnchanged} 的 CAS 独占，{@code unit_price} / {@code factor} /
     * 报工历史是工资凭证（红线）—— 本语句**绝不**出现它们。</p>
     *
     * @return 1 = 本次落笔（或已由前一次落笔，COALESCE 空操作）；0 = 未做完 / 已软删 / 跨租户
     */
    @Update("UPDATE processing_position_operations SET done_at = COALESCE(done_at, #{doneAt}) "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 "
            + "AND COALESCE(done_qty, 0) >= COALESCE(qty, 0)")
    int recordCompletionIfDone(@Param("id") String id,
                               @Param("tenantId") Long tenantId,
                               @Param("doneAt") OffsetDateTime doneAt);

    /**
     * 报工身份快照（V98，issue #4733）：把「谁报的」写进工序实例（V92 预留的
     * {@code worker_id}/{@code worker_name}），与 {@code production_work_logs} 的那两列**同源**。
     *
     * <p>🔴 只写 {@code worker_id} / {@code worker_name} / {@code started_at} / {@code updated_at}
     * —— <b>绝不</b>出现 {@code done_qty} / {@code status} / {@code unit_price} / {@code factor}：
     * 进度推进由 {@link #advanceDoneQtyIfUnchanged} 的 CAS 独占，单价/系数是工资凭证快照（红线）。
     * 单独一条 UPDATE 而不是并进 CAS，是为了**不动** CAS 的谓词与 SET 子句（并发语义一字不改）。</p>
     *
     * <p>🔴 <b>2026-09-21 语义改判（issue #4967）：扫码 = 开工 / 领活</b> ⇒ 本语句同时把
     * {@code started_at}（V92 已建的「C 模式预留」列）<b>转正</b>为默认路径写入 —— 扫码那一刻
     * 就是「谁领走了这道活」的时点。写入形态用 {@code COALESCE(started_at, #{startedAt})}：
     * <b>只有第一次领活落笔</b>，重扫 / 续报 / 换人再扫都**不改写**已记下的开工时刻
     * （与 {@link #recordCompletionIfDone} 同款幂等形态：幂等由 SQL 机械保证、不靠调用方自觉）。</p>
     *
     * <p>⚠️ 商家侧报工（{@code ProductionService#report}，无工人 session ⇒ 身份可能两项皆空）
     * 仍在身份非空时才调本方法 ⇒ 该路径**不**落 {@code started_at}（没有「谁领的」可言，不猜）。
     * 工人扫码路径的身份由 session 保证非空 ⇒ 恒写入（见 {@code ProductionService#applyScanComplete}）。</p>
     *
     * @param startedAt 领活时刻（{@code COALESCE} ⇒ 已有值一字不改）
     * @return 1 = 已写入；0 = 工序不存在/已软删/跨租户（幂等空操作，不影响报工主流程）
     */
    @Update("UPDATE processing_position_operations SET worker_id = #{workerId}, "
            + "worker_name = #{workerName}, started_at = COALESCE(started_at, #{startedAt}), "
            + "updated_at = #{updatedAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0")
    int recordReporter(@Param("id") String id,
                       @Param("tenantId") Long tenantId,
                       @Param("workerId") String workerId,
                       @Param("workerName") String workerName,
                       @Param("startedAt") OffsetDateTime startedAt,
                       @Param("updatedAt") OffsetDateTime updatedAt);

    /**
     * 未定价实例的**显式补价**（issue #4709 C）：只把 {@code unit_price IS NULL} 的行补成给定价。
     *
     * <p>🔴 红线 ① 由**谓词**机械保证（不靠调用方自觉）：{@code AND unit_price IS NULL} ⇒
     * 已有价的行（{@code > 0} 或 {@code 0}）**永远**匹配不到 —— 并发下「商家刚在矩阵里定的价」
     * 也不会被本次补价覆盖（影响行数 0 = 没补，调用方据此不记账）。</p>
     *
     * <p>🔴 红线 ②④ 由 **SET 子句**机械保证：只写 {@code unit_price} 与 {@code updated_at} ——
     * <b>绝不</b>出现 {@code done_qty} / {@code status} / {@code factor}（补价不是报工，
     * 不得清零或推进任何生产进度，也不得动计件系数）。</p>
     *
     * @return 1 = 本行本次被补价；0 = 该行已有价 / 已软删 / 跨租户（调用方据此决定是否记账）
     */
    @Update("UPDATE processing_position_operations SET unit_price = #{unitPrice}, "
            + "updated_at = #{updatedAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 "
            + "AND unit_price IS NULL")
    int fillUnpricedUnitPrice(@Param("id") String id,
                              @Param("tenantId") Long tenantId,
                              @Param("unitPrice") BigDecimal unitPrice,
                              @Param("updatedAt") OffsetDateTime updatedAt);

    /**
     * 补价动作的**按行回滚**（issue #4709 C）：把该行还原成未定价（{@code unit_price = NULL}）。
     *
     * <p>🔴 谓词 {@code AND unit_price = #{expectedUnitPrice}} 是「不覆盖后续改动」的保证：
     * 只还原**当前值仍等于账本记录的那次补价**的行 —— 之后被别的动作改过、或已被重新实例化
     * （{@code deleted = 1}）的行一律不碰。{@code expectedUnitPrice} 来自账本，故商家自己定的价
     * （不在账本里）**永远**匹配不到。</p>
     *
     * <p>🔴 同样只写 {@code unit_price} 与 {@code updated_at}：{@code factor} / {@code done_qty} /
     * {@code status} / 报工历史一字不动（红线 ②④）。</p>
     *
     * @return 1 = 本行已还原；0 = 当前值不是账本记录的补价 / 已软删 / 跨租户（幂等空操作）
     */
    @Update("UPDATE processing_position_operations SET unit_price = NULL, "
            + "updated_at = #{updatedAt} "
            + "WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 "
            + "AND unit_price = #{expectedUnitPrice}")
    int revertFilledUnitPrice(@Param("id") String id,
                              @Param("tenantId") Long tenantId,
                              @Param("expectedUnitPrice") BigDecimal expectedUnitPrice,
                              @Param("updatedAt") OffsetDateTime updatedAt);
}