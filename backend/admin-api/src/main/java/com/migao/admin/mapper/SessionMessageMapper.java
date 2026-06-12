package com.migao.admin.mapper;

import com.migao.admin.entity.SessionMessage;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * 会话消息Mapper接口
 */
@Mapper
public interface SessionMessageMapper extends BaseMapper<SessionMessage> {
}
