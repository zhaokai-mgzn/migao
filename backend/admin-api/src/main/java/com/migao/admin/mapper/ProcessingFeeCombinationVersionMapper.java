package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingFeeCombinationVersion;
import org.apache.ibatis.annotations.Mapper;

/**
 * 加工费组合定价版本账 Mapper（V66，issue #4386）
 */
@Mapper
public interface ProcessingFeeCombinationVersionMapper extends BaseMapper<ProcessingFeeCombinationVersion> {
}
