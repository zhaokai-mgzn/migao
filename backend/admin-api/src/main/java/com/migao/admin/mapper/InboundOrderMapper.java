package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.InboundOrder;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;

/**
 * InboundOrder Mapper（V111，issue #5034；V117 / issue #5148 追加过账原子闸）
 */
@Mapper
public interface InboundOrderMapper extends BaseMapper<InboundOrder> {

    /**
     * 过账的**原子闸**：条件更新（CAS）—— 只有当前仍是 {@code draft} 才置 {@code posted}。
     *
     * <p>为什么不用「先读 status 判 draft，再 {@code updateById} 写」：读与写之间有窗口，
     * 双击 / 并发会让两个请求**都**通过判断 ⇒ 各自加一遍库存（库存加两次、台账两条）。
     * 条件更新的「判断」与「写入」是**同一条语句**，PostgreSQL 对命中行加行锁并持有到事务结束
     * ⇒ 并发的第二个请求要么阻塞到前者提交、要么看到 0 行受影响。</p>
     *
     * <p>{@code posted_at} / {@code posted_by} 与状态**同一句**写入：库存是资金级数据，
     * 「谁在何时把它改成已过账」不能与状态迁移分成两次写（中间态无法追责）。</p>
     *
     * <p>谓词带 {@code deleted = 0}：MyBatis-Plus 的 {@code @TableLogic} 只对自动生成的 SQL 生效，
     * 手写 SQL 必须自己带上（软删的单不得过账）。</p>
     *
     * @return 影响行数：{@code 1} = 本请求抢到过账权；{@code 0} = 已被过账 / 已作废 / 单不存在
     */
    @Update("UPDATE inbound_orders SET status = 'posted', posted_at = #{postedAt}, posted_by = #{operator}, "
            + "updated_at = NOW() WHERE id = #{id} AND tenant_id = #{tenantId} "
            + "AND status = 'draft' AND deleted = 0")
    int markPosted(@Param("id") String id,
                   @Param("tenantId") Long tenantId,
                   @Param("operator") String operator,
                   @Param("postedAt") OffsetDateTime postedAt);
}
