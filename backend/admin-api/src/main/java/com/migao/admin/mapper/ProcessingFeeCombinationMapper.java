package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingFeeCombination;
import org.apache.ibatis.annotations.Mapper;

/**
 * 加工费组合定价 Mapper（V68，issue #4386）
 */
@Mapper
public interface ProcessingFeeCombinationMapper extends BaseMapper<ProcessingFeeCombination> {
}
