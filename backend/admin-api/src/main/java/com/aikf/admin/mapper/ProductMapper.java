package com.aikf.admin.mapper;

import com.aikf.admin.entity.Product;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.math.BigDecimal;

/**
 * 商品Mapper接口
 */
@Mapper
public interface ProductMapper extends BaseMapper<Product> {

    @Update("UPDATE products SET sales_count = COALESCE(sales_count, 0) + #{quantity}, " +
            "sales_amount = COALESCE(sales_amount, 0) + #{amount} WHERE id = #{productId}")
    void increaseSales(@Param("productId") String productId,
                       @Param("quantity") Integer quantity,
                       @Param("amount") BigDecimal amount);

    @Update("UPDATE products SET sales_count = GREATEST(COALESCE(sales_count, 0) - #{quantity}, 0), " +
            "sales_amount = GREATEST(COALESCE(sales_amount, 0) - #{amount}, 0) WHERE id = #{productId}")
    void decreaseSales(@Param("productId") String productId,
                       @Param("quantity") Integer quantity,
                       @Param("amount") BigDecimal amount);
}
