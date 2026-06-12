package com.migao.admin.mapper;

import com.migao.admin.entity.ProductSku;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

/**
 * 商品SKU Mapper 接口
 */
@Mapper
public interface ProductSkuMapper extends BaseMapper<ProductSku> {

    @Update("UPDATE product_skus SET stock = GREATEST(COALESCE(stock, 0) - #{quantity}, 0) " +
            "WHERE id = #{skuId}")
    int deductStock(@Param("skuId") Long skuId, @Param("quantity") int quantity);

    @Update("UPDATE product_skus SET stock = COALESCE(stock, 0) + #{quantity} " +
            "WHERE id = #{skuId}")
    int restoreStock(@Param("skuId") Long skuId, @Param("quantity") int quantity);

    @Update("UPDATE product_skus SET sales_count = COALESCE(sales_count, 0) + #{quantity} " +
            "WHERE id = #{skuId}")
    void increaseSalesCount(@Param("skuId") Long skuId, @Param("quantity") int quantity);

    @Update("UPDATE product_skus SET sales_count = GREATEST(COALESCE(sales_count, 0) - #{quantity}, 0) " +
            "WHERE id = #{skuId}")
    void decreaseSalesCount(@Param("skuId") Long skuId, @Param("quantity") int quantity);
}
