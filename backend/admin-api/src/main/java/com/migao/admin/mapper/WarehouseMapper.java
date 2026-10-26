package com.migao.admin.mapper;

import com.baomidou.mybatisplus.annotation.InterceptorIgnore;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.Warehouse;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/** 仓库（issue #7373）：只继承 BaseMapper —— 「默认仓唯一」由部分唯一索引兜住，不在 SQL 里重复写。 */
@Mapper
public interface WarehouseMapper extends BaseMapper<Warehouse> {

    /**
     * **原子建档**（V196 / issue #7750）：插入一个仓；编码/默认仓撞唯一索引 ⇒ 0 行、**不抛异常**。
     *
     * <p>为什么不用「先查后插」：唯一索引冲突会让 PG 当前事务进入 aborted 态
     * （后续任何查询都失败）⇒ 捕获 {@code DuplicateKeyException} 再重试在同事务内是**非法**的。
     * {@code ON CONFLICT DO NOTHING} 把冲突变成「0 行受影响」，事务继续可用
     * （首次打包与并发请求同时要给租户建成品仓时会走到）。</p>
     */
    @InterceptorIgnore(tenantLine = "true")
    @Insert("INSERT INTO warehouses (tenant_id, code, name, warehouse_type, is_default, status, remark, deleted) "
            + "VALUES (#{tenantId}, #{code}, #{name}, #{warehouseType}, FALSE, 'active', #{remark}, 0) "
            + "ON CONFLICT DO NOTHING")
    int claimWarehouse(@Param("tenantId") Long tenantId,
                       @Param("code") String code,
                       @Param("name") String name,
                       @Param("warehouseType") String warehouseType,
                       @Param("remark") String remark);
}
