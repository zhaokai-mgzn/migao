package com.migao.admin.mapper;

import com.migao.admin.entity.Notification;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
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
     * 按幂等键查重（issue #7524）：同一事件 × 同一业务对象 × 同一收件人只落一条。
     * 唯一索引 uk_notifications_dedupe 是最终保证；这里先查一次，避免撞索引把事务打成 aborted。
     */
    @Select("SELECT COUNT(*) FROM notifications WHERE tenant_id = #{tenantId} AND dedupe_key = #{dedupeKey}")
    Long countByDedupeKey(@Param("tenantId") Long tenantId, @Param("dedupeKey") String dedupeKey);
}
