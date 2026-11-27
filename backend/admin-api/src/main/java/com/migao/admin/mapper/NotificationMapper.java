package com.migao.admin.mapper;

import com.migao.admin.entity.Notification;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Select;

/**
 * 通知记录 Mapper 接口
 */
@Mapper
public interface NotificationMapper extends BaseMapper<Notification> {

    /**
     * 分页查询指定接收人的通知
     */
    @Select("<script>" +
            "SELECT * FROM notifications WHERE recipient_id = #{recipientId}" +
            "<if test='status != null'> AND status = #{status}</if>" +
            "<if test='channel != null'> AND channel = #{channel}</if>" +
            "<if test='bizType != null'> AND biz_type = #{bizType}</if>" +
            " ORDER BY created_at DESC" +
            "</script>")
    IPage<Notification> selectByRecipientId(@Param("recipientId") String recipientId,
                                            @Param("status") String status,
                                            @Param("channel") String channel,
                                            @Param("bizType") String bizType,
                                            IPage<Notification> page);

    /**
     * 统计未读通知数
     */
    @Select("SELECT COUNT(*) FROM notifications WHERE recipient_id = #{recipientId} AND status != 'read'")
    Long countUnread(@Param("recipientId") String recipientId);

    /**
     * **带幂等键的原子写入**（issue #9025）：冲突时该语句<b>不报错、返回 0 行</b>。
     *
     * <p>为什么不是「先 {@code countByDedupeKey} 查一次、再 {@code insert}」：那是**非原子读**（TOCTOU）——
     * 两个实例 / 两个并发事件同时判定「未发」之后争抢部分唯一索引 {@code uk_notifications_dedupe}
     * ⇒ 后写者抛 {@code DuplicateKeyException}。而 {@code triggerByEvent} 的调用方
     * （{@code AfterSalesTicketService} / {@code OrderLifecycleService} / {@code AutoCompleteShippedScanService}）
     * 多在**业务事务**里 ⇒ PG 会把整条事务标记为 aborted ⇒ 业务写（改状态 / 过账）跟着回滚。
     * {@code ON CONFLICT … DO NOTHING} 在**语句内部**消解冲突，事务不进 aborted 状态。</p>
     *
     * <p>⚠️ {@code ON CONFLICT} 的目标必须带<b>索引谓词</b> {@code WHERE dedupe_key IS NOT NULL}：
     * {@code uk_notifications_dedupe} 是<b>部分</b>唯一索引，PG 的冲突推断要求谓词逐字匹配
     * （{@code ON CONFLICT ON CONSTRAINT} 对部分唯一索引不成立 —— 它不是 constraint）。
     * 同族先例见 {@code OutboundOrderMapper#insertIgnoreOutboundNoConflict}。</p>
     *
     * <p>⚠️ 列清单显式（issue #4608 纪律）：{@code created_at} 由 DB 默认 {@code NOW()} 填，不在此。</p>
     *
     * @return 影响行数：{@code 1} = 本次真的落库（首次）；{@code 0} = 该 (tenant_id, dedupe_key) 已存在
     *         （并发/重放命中）⇒ 调用方按「已发」处理，**不得**当失败
     */
    @Insert("INSERT INTO notifications (id, tenant_id, rule_id, template_id, recipient_id, recipient_type,"
            + " channel, title, content, biz_type, biz_id, biz_no, target_path, severity, occurred_at,"
            + " dedupe_key, status, sent_at, retry_count)"
            + " VALUES (#{n.id}, #{n.tenantId}, #{n.ruleId,jdbcType=VARCHAR},"
            + " #{n.templateId,jdbcType=VARCHAR}, #{n.recipientId}, #{n.recipientType}, #{n.channel},"
            + " #{n.title,jdbcType=VARCHAR}, #{n.content}, #{n.bizType,jdbcType=VARCHAR},"
            + " #{n.bizId,jdbcType=VARCHAR}, #{n.bizNo,jdbcType=VARCHAR}, #{n.targetPath,jdbcType=VARCHAR},"
            + " #{n.severity,jdbcType=VARCHAR}, #{n.occurredAt,jdbcType=TIMESTAMP_WITH_TIMEZONE},"
            + " #{n.dedupeKey}, #{n.status}, #{n.sentAt,jdbcType=TIMESTAMP_WITH_TIMEZONE}, #{n.retryCount})"
            + " ON CONFLICT (tenant_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING")
    int insertIfDedupeAbsent(@Param("n") Notification notification);
}
