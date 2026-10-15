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
import java.time.OffsetDateTime;
import java.util.List;

/**
 * 商品Mapper接口
 */
@Mapper
public interface ProductMapper extends BaseMapper<Product> {

    /**
     * 商品状态迁移的**唯一写面**（issue #6961）：判断与写入压进同一条语句 ⇒ 并发下只有一个赢家。
     *
     * <p>范式照抄 {@code ProcessingOrderMapper#markStatusIfFrom}（#6955）与
     * {@code InboundOrderMapper#markPosted}（#6928）：谓词 = {@code id} + {@code tenant_id}
     * + {@code deleted = 0} + **状态机授权的前驱态**，按<b>受影响行数</b>判定谁抢到迁移权
     * （0 行 ⇒ 调用方 fail-closed 409，文案带<b>实际当前态</b>）。</p>
     *
     * <p>修前的形态是「先 {@code selectById} 读旧 status 过状态机、再 {@code updateById}
     * （WHERE 仅主键 ⇒ 无谓词）」⇒ 校验在<b>读</b>之后、写入没有谓词：并发 on/off_sale
     * <b>两个请求都成功</b>，终态由后写者决定。列 {@code status} / {@code tenant_id} /
     * {@code deleted} 的存在性已对 {@code db/init/schema.sql} 的 {@code products} DDL 自证。</p>
     *
     * <p>先判「前驱态为空」再判 {@code status = #{fromStatus}}：{@code status} 可空
     * （历史行 / 建品未填），而 <b>PG 里 {@code status = NULL} 求值为 NULL（永假）</b> ——
     * 少了这一支，那些行会被误判成「被别人抢先改过」。⚠️ 这一支**必须**用布尔参数
     * {@code #{fromStatusIsNull} = TRUE}，<b>不能</b>写成 {@code #{fromStatus} IS NULL}：后者
     * PG 会报「无法确定参数 $N 的数据类型」（`PARAMETER-TYPE-UNAMBIGUOUS` 的同族，
     * 真库实测逐字：`错误: 无法确定参数 $7 的数据类型`）。软删（{@code deleted}）同样被
     * {@code @TableLogic} 的行级谓词覆盖，此处显式写出以对齐范式。</p>
     *
     * @return 受影响行数：0 = 不存在 / 跨租户 / 已软删 / 前驱态不符（调用方据此判 409）
     */
    @Update("UPDATE products SET status = #{targetStatus}, edited_by = #{editedBy}, edited_at = #{editedAt}, "
            + "updated_at = #{editedAt} WHERE id = #{id} AND tenant_id = #{tenantId} AND deleted = 0 "
            + "AND ((#{fromStatusIsNull} = TRUE AND status IS NULL) OR status = #{fromStatus})")
    int updateStatusIfFrom(@Param("id") String id,
                           @Param("tenantId") Long tenantId,
                           @Param("fromStatus") String fromStatus,
                           @Param("fromStatusIsNull") boolean fromStatusIsNull,
                           @Param("targetStatus") String targetStatus,
                           @Param("editedBy") String editedBy,
                           @Param("editedAt") OffsetDateTime editedAt);

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
