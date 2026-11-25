package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.migao.admin.entity.KfOutbox;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.OffsetDateTime;
import java.util.List;

@Mapper
public interface KfOutboxMapper {

    @InterceptorIgnore(tenantLine = "true")
    @Insert("INSERT INTO kf_outbox (tenant_id, session_id, msgid, parts, status) "
            + "VALUES (#{tenantId}, #{sessionId}, #{msgid}, CAST(#{parts} AS jsonb), 'pending') "
            + "ON CONFLICT (msgid) DO NOTHING")
    int enqueue(@Param("tenantId") Long tenantId,
                @Param("sessionId") String sessionId,
                @Param("msgid") String msgid,
                @Param("parts") String parts);

    /** pending 或 sending 超时 ⇒ 领取；msgid 已由 enqueue 唯一约束保证幂等。 */
    @InterceptorIgnore(tenantLine = "true")
    @Select("WITH picked AS ("
            + "SELECT id FROM kf_outbox "
            + "WHERE status = 'pending' OR (status = 'sending' AND sending_at < #{staleBefore}) "
            + "ORDER BY created_at LIMIT #{limit} FOR UPDATE SKIP LOCKED"
            + ") UPDATE kf_outbox o SET status = 'sending', lease_owner = #{leaseOwner}, "
            + "attempts = attempts + 1, sending_at = NOW() "
            + "FROM picked p WHERE o.id = p.id "
            + "RETURNING o.id, o.tenant_id, o.session_id, o.msgid, CAST(o.parts AS text) AS parts, "
            + "o.status, o.attempts, o.lease_owner")
    List<KfOutbox> claimDue(@Param("staleBefore") OffsetDateTime staleBefore,
                            @Param("limit") int limit,
                            @Param("leaseOwner") String leaseOwner);

    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE kf_outbox SET status = 'accepted', sent_msgid = #{sentMsgid}, fail_type = NULL "
            + "WHERE id = #{id} AND status = 'sending'")
    int markAccepted(@Param("id") Long id, @Param("sentMsgid") String sentMsgid);

    /** msg_send_fail 事件：按企微返回的 sent_msgid 回写终态；找不到返回 0（调用方记孤儿事件）。 */
    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE kf_outbox SET status = 'failed', fail_type = #{failType} "
            + "WHERE sent_msgid = #{sentMsgid} AND status = 'accepted'")
    int markFailedBySentMsgid(@Param("sentMsgid") String sentMsgid, @Param("failType") Integer failType);

    @InterceptorIgnore(tenantLine = "true")
    @Update("UPDATE kf_outbox SET status = #{status}, fail_type = #{failType} "
            + "WHERE id = #{id} AND status = 'sending'")
    int markFailed(@Param("id") Long id,
                   @Param("status") String status,
                   @Param("failType") Integer failType);
}
