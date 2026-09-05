package com.migao.admin.mapper;

import com.migao.admin.entity.SessionMessage;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

/**
 * 会话消息Mapper接口
 */
@Mapper
public interface SessionMessageMapper extends BaseMapper<SessionMessage> {

    /**
     * 批量取每个会话最后一条消息（#2886 性能优化：DISTINCT ON 一次查询，
     * 替代原来每会话一次 SELECT ... ORDER BY created_at DESC LIMIT 1 的 N+1）。
     */
    @Select("<script>" +
            "SELECT DISTINCT ON (session_id) session_id, content FROM session_messages " +
            "WHERE deleted = 0 AND session_id IN " +
            "<foreach collection='sessionIds' item='sid' open='(' separator=',' close=')'>#{sid}</foreach> " +
            "ORDER BY session_id, created_at DESC" +
            "</script>")
    List<Map<String, Object>> selectLastMessageBySessionIds(@Param("sessionIds") List<String> sessionIds);
}
