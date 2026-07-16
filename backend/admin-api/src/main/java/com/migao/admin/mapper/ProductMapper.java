package com.migao.admin.mapper;

import com.migao.admin.dto.LowStockByColorResponse;
import com.migao.admin.entity.Product;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.math.BigDecimal;
import java.util.List;

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

    /**
     * 按颜色+规格维度查询低库存 SKU（JOIN product_skus + products + product_colors）
     * #1396: 增加 p.status = 'on_sale' 过滤，排除已下架商品下的 SKU
     */
    @Select("SELECT ps.id AS skuId, ps.product_id AS productId, p.name AS productName, " +
            "COALESCE(ps.sku_code, p.sku_code) AS skuCode, " +
            "ps.color_id AS colorId, COALESCE(ps.color_name, pc.color_name) AS colorName, " +
            "ps.door_width AS doorWidth, ps.stock AS stock, ps.price AS price " +
            "FROM product_skus ps " +
            "JOIN products p ON ps.product_id = p.id AND p.deleted = 0 AND p.status = 'on_sale' " +
            "LEFT JOIN product_colors pc ON ps.color_id = pc.id " +
            "WHERE ps.stock <= #{threshold} AND ps.stock >= 0 " +
            "ORDER BY ps.stock ASC, p.name ASC " +
            "LIMIT #{limit}")
    List<LowStockByColorResponse> findLowStockByColor(@Param("threshold") int threshold, @Param("limit") int limit);

    /**
     * 统计待补库存 SKU 数（排除已删除 + 已下架商品下的 SKU）
     * #1396: 口径统一 — 与 findLowStockByColor 使用相同的过滤条件
     */
    @Select("SELECT COUNT(*) FROM product_skus ps " +
            "JOIN products p ON ps.product_id = p.id " +
            "WHERE p.deleted = 0 AND p.status = 'on_sale' " +
            "AND ps.tenant_id = #{tenantId} " +
            "AND ps.stock >= 0 AND ps.stock <= #{threshold}")
    long countLowStockSkus(@Param("tenantId") Long tenantId, @Param("threshold") int threshold);
}
