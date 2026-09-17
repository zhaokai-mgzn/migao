package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingPositionOperation;
import org.apache.ibatis.annotations.Mapper;

/**
 * 工序实例 Mapper（V49，issue #3995）：扫码报工的推进单元
 */
@Mapper
public interface ProcessingPositionOperationMapper extends BaseMapper<ProcessingPositionOperation> {
}
