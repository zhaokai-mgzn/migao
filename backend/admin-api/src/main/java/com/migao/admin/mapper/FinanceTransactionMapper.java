package com.migao.admin.mapper;

import com.migao.admin.entity.FinanceTransaction;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * 资金流水 Mapper 接口
 */
@Mapper
public interface FinanceTransactionMapper extends BaseMapper<FinanceTransaction> {
}
