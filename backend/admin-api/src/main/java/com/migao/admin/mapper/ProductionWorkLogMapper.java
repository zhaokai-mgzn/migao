package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionWorkLog;
import org.apache.ibatis.annotations.Mapper;

/**
 * 报工记录 Mapper（V49，issue #3995）：报工三态 + 计件明细
 */
@Mapper
public interface ProductionWorkLogMapper extends BaseMapper<ProductionWorkLog> {
}
