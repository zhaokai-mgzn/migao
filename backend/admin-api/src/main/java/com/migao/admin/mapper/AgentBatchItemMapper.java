package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.AgentBatchItem;
import org.apache.ibatis.annotations.Mapper;

/** 批次明细 Mapper（issue #5314）。租户过滤同 {@link AgentBatchMapper}（本表自带 tenant_id）。 */
@Mapper
public interface AgentBatchItemMapper extends BaseMapper<AgentBatchItem> {
}