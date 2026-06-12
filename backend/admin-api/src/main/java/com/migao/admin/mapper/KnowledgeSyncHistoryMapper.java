package com.migao.admin.mapper;

import com.migao.admin.entity.KnowledgeSyncHistory;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * 知识库同步历史 Mapper 接口
 */
@Mapper
public interface KnowledgeSyncHistoryMapper extends BaseMapper<KnowledgeSyncHistory> {
}
