package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.ProductionOperationPriceVersion;
import org.apache.ibatis.annotations.Mapper;

/**
 * 工序计件单价版本 Mapper（V55，issue #4204）
 *
 * <p>唯一写方 = {@code ProductionOperationCommandService.update}（改价时追加一行）；
 * 读口径 = 按 created_at 最新的一行即当前价。</p>
 */
@Mapper
public interface ProductionOperationPriceVersionMapper extends BaseMapper<ProductionOperationPriceVersion> {
}
