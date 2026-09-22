package com.migao.admin.mapper;

import com.migao.admin.dto.LowStockByColorResponse;
import com.migao.admin.entity.Product;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.ResultMap;
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
                       @Param("quantity") BigDecimal quantity,
                       @Param("amount") BigDecimal amount);

    @Update("UPDATE products SET sales_count = GREATEST(COALESCE(sales_count, 0) - #{quantity}, 0), " +
            "sales_amount = GREATEST(COALESCE(sales_amount, 0) - #{amount}, 0) WHERE id = #{productId}")
    void decreaseSales(@Param("productId") String productId,
                       @Param("quantity") BigDecimal quantity,
                       @Param("amount") BigDecimal amount);

    /**
     * 按「租户 + 货号」查商品（issue #5154）—— 批量导入的**幂等键**查询。
     *
     * <p>用显式 SQL 而不是 LambdaQueryWrapper：这里是「命中即原地更新、未命中才新建」的判定点，
     * 软删过滤（{@code deleted = 0}）与 {@code ORDER BY id LIMIT 1}（历史重复数据下取最早那条，
     * 避免每次导入更新到不同的行）必须**看得见**，不能依赖 wrapper 的默认行为。</p>
     *
     * <p>⚠️ {@code @ResultMap} 是**判据的一部分**，不是可选优化：{@code @TableName(autoResultMap = true)}
     * 只对 BaseMapper 的内置方法生效，手写 {@code @Select} 不显式绑 resultMap 就会生成一条**内联
     * ResultMap（无类型处理器）** ⇒ {@code products.images} / {@code selling_methods} 这些 JSONB 列
     * 以 **JSON 字符串**落到字段上，所有 {@code instanceof} 判据**静默为假**（#3340 / #4865 同根因）。
     * 守卫：{@code JacksonTypeHandlerMappingGuardTest}（类级扫描，删掉本行即红）。</p>
     */
    @Select("SELECT * FROM products WHERE tenant_id = #{tenantId} AND sku_code = #{skuCode} " +
            "AND deleted = 0 ORDER BY id ASC LIMIT 1")
    @ResultMap("mybatis-plus_Product")
    Product selectByTenantAndSkuCode(@Param("tenantId") Long tenantId, @Param("skuCode") String skuCode);

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
