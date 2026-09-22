package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.FabricRemnant;
import org.apache.ibatis.annotations.Mapper;

/**
 * 余料台账 Mapper（V122，issue #5146）。
 *
 * <p>写入一律走 {@code RemnantService}（它保证「状态 ↔ 留痕列」自洽、且回收绝不写批次消耗台账）；
 * 本接口只加一条**匹配候选**查询 —— 匹配要的排序（同缸号优先 → 同色优先 → 尺寸最小者优先）
 * 放在 SQL 里而不是 Java 里，是为了「一个查询定序」而不是「查回来再拼一遍顺序」。</p>
 */
@Mapper
public interface FabricRemnantMapper extends BaseMapper<FabricRemnant> {

    /**
     * 匹配候选（**只扫可用池** —— {@code status = 'available'}）。
     *
     * <p>谓词分三层，各有判据：</p>
     * <ol>
     *   <li>{@code status = 'available'} ⇒ <b>客户带走的余料天然不在候选里</b>
     *       （判据 7：它不进池、不参与匹配、不计回收 —— 红证 = 把它混进池则匹配命中）；</li>
     *   <li>{@code length_m >= need} 且 {@code width_m >= need} ⇒ <b>尺寸不足者不出现在候选里</b>
     *       （判据 5「不凭空推荐」的第一道网；第二道在 Java 里用
     *       {@code RemnantItemSize#fits} 复核 —— SQL 与实体两处判据一致，防「查询写宽了」）；</li>
     *   <li>同商品（{@code product_id}）⇒ 不同商品的余料不可能互相替代。</li>
     * </ol>
     *
     * <p>排序（判据 3「同缸号、同色优先，防色差」的落点）：</p>
     * <ol>
     *   <li>{@code 同缸号} 优先（{@code dye_lot} 相等；缸号为空的行永不排前）；</li>
     *   <li>其次 {@code 同色}（{@code sku_code} 相等）；</li>
     *   <li>再按 {@code length_m} **升序** —— 先用掉小块的（best-fit 精神：余料越小越接近废料，
     *       大块留给大件）；平局按 {@code id} 升序保证**确定性**。</li>
     * </ol>
     *
     * <p>⚠️ 排序里的 {@code CASE WHEN} 而不是 {@code (dye_lot = ?) DESC}：PG 的
     * {@code NULL = x} 得 NULL，而 {@code ORDER BY … DESC} 默认 {@code NULLS FIRST}
     * ⇒ 缸号为空的行会被排到最前面（正好把「优先」颠倒）。这是写法上的坑，不是口味问题。</p>
     *
     * <p>硬底线（{@code 同缸号 或 同色}，不同色直接淘汰）**有意放在 Java 里** ——
     * 它是业务判定（防色差的底线）而不是取数范围，放服务层才能被单测逐值判红，
     * 也才能与「返回给用户的淘汰原因」用同一份真值。</p>
     */
    @org.apache.ibatis.annotations.Select(
            "SELECT * FROM fabric_remnants "
                    + "WHERE tenant_id = #{tenantId} AND deleted = 0 AND status = 'available' "
                    + "AND product_id = #{productId} "
                    + "AND length_m >= #{needLengthM} AND width_m >= #{needWidthM} "
                    + "ORDER BY CASE WHEN dye_lot IS NOT NULL AND dye_lot = #{dyeLot} THEN 0 ELSE 1 END, "
                    + "CASE WHEN sku_code IS NOT NULL AND sku_code = #{skuCode} THEN 0 ELSE 1 END, "
                    + "length_m ASC, id ASC")
    java.util.List<FabricRemnant> findMatchCandidates(
            @org.apache.ibatis.annotations.Param("tenantId") Long tenantId,
            @org.apache.ibatis.annotations.Param("productId") String productId,
            @org.apache.ibatis.annotations.Param("dyeLot") String dyeLot,
            @org.apache.ibatis.annotations.Param("skuCode") String skuCode,
            @org.apache.ibatis.annotations.Param("needLengthM") java.math.BigDecimal needLengthM,
            @org.apache.ibatis.annotations.Param("needWidthM") java.math.BigDecimal needWidthM);
}
