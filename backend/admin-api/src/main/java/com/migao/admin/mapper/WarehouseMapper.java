package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.Warehouse;
import org.apache.ibatis.annotations.Mapper;

/** 仓库（issue #7373）：只继承 BaseMapper —— 「默认仓唯一」由部分唯一索引兜住，不在 SQL 里重复写。 */
@Mapper
public interface WarehouseMapper extends BaseMapper<Warehouse> {
}
