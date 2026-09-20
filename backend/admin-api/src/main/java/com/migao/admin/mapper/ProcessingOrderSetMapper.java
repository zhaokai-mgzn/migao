package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProcessingOrderSet;
import org.apache.ibatis.annotations.Mapper;

/**
 * 套号载体 Mapper（V92，切片 ⓪ / issue #4698）：一单 × 一套 = 一行。
 * 本切片只读（解析时按 {@code set_id} 取套号做归属校验与响应）。
 */
@Mapper
public interface ProcessingOrderSetMapper extends BaseMapper<ProcessingOrderSet> {
}
