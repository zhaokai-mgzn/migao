package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 余料台账实体（V122，issue #5146）—— 一行 = 一块**实物余料**。
 *
 * <h2>🔴 本实体**没有**任何计价字段（这是本单最要害的一条口径）</h2>
 * 用户裁定逐字「**这个废布不算在企业资产了**」⇒ 余料**零价值**：台账只记**实物可用性**
 * （尺寸 / 来源订单 / 来源批次 / 缸号 / 状态），不计价、不进库存金额、不出现在任何库存/资产读面。
 * 判据 = 加余料登记前后 {@code Σ product_skus.cost_amount} 与 {@code Σ product_skus.stock}
 * **逐值不变**（真库 {@code RemnantNonAssetRealDbTest}）+ 余料两表在库存/资产读面里的引用数为零
 * （静态 {@code RemnantNonAssetGuardTest}）。
 *
 * <h2>{@code recoveredAmount} 不是「余料值多少钱」</h2>
 * 它是「这块布当初已随计价口径 {@code M = P × 每幅长} 被客户付过钱、现在被用掉多少米」的
 * **内部成本冲减量**，归属是**用它的那张单**（{@link #usedByOrderNo}），不是余料的资产属性。
 * 所以本单的「成本回收」**不是向客户再要一次钱** —— 与用户裁定「**不能损失客户**」天然不冲突
 * （对客售价 / 加工费 / 成品尺寸一字不动）。
 *
 * <h2>回收与报废为什么是同一行的列，而不是两张表</h2>
 * 一块余料**只能被用掉一次**（用掉后状态即 {@code used}，尺寸不再可切）⇒ 余料 ↔ 回收是 <b>1:1</b>。
 * 1:1 用列表达少一层 join、少一个「两表不一致」的失效形态，且「回收额随行不可变」天然成立
 * （{@link #recoveredUnitCost} 是**当时**该批次均价的快照 ⇒ 事后改价不改历史读数）。
 * <b>代价照实登记</b>：将来若要「一块余料分多次用掉」（部分使用），本形态需扩表。本单不做部分使用。
 *
 * <h2>状态机（取值集合在 DB 约束里，不只写在 Java 常量里）</h2>
 * <ul>
 *   <li>{@link #STATUS_CUSTOMER_TAKEN} 客户带走（特殊选项 {@code 余料带回-布/-纱}）——
 *       <b>不进可用池、不参与匹配、不计回收</b>；</li>
 *   <li>{@link #STATUS_AVAILABLE} 可用（匹配只在它里面找）；</li>
 *   <li>{@link #STATUS_USED} 已用（回收四列 + 用它的那张单非空）；</li>
 *   <li>{@link #STATUS_SCRAPPED} 已报废（报废三列非空；与回收互斥）。</li>
 * </ul>
 * 迁移里的 {@code ck_fabric_remnant_lifecycle} 把「状态 ↔ 留痕列」的对应关系钉住
 * —— 账实一致不是靠读面自觉，是靠落库时不可能写出自相矛盾的行。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("fabric_remnants")
public class FabricRemnant {

    /** 状态：客户带走（余料归客户）—— **不进可用池、不参与匹配、不计回收** */
    public static final String STATUS_CUSTOMER_TAKEN = "customer_taken";
    /** 状态：可用 —— 匹配只在它里面找 */
    public static final String STATUS_AVAILABLE = "available";
    /** 状态：已用 —— 回收记账落在这里 */
    public static final String STATUS_USED = "used";
    /** 状态：已报废 —— 留痕（谁 / 何时 / 为什么） */
    public static final String STATUS_SCRAPPED = "scrapped";

    /** 余料形态：门幅余料（行内没占满门幅剩下的竖带） */
    public static final String KIND_WIDTH = "width";
    /** 余料形态：端部余料（行内短块尾部剩下的横带） */
    public static final String KIND_END = "end";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 排料清单里这一块余料的确定序号 —— 幂等闸 {@code uk_fabric_remnants_piece} 的键之一 */
    private Integer pieceSeq;

    private String sourceOrderNo;

    private String sourceProcessingOrderNo;

    private Long sourceBatchId;

    private String sourceBatchNo;

    /** 缸号**快照**（源 {@code stock_batches.dye_lot}）—— 同缸号优先匹配防色差靠它 */
    private String dyeLot;

    private String productId;

    private Long skuId;

    private String skuCode;

    /** 见 {@link #KIND_WIDTH} / {@link #KIND_END} */
    private String pieceKind;

    /** 沿**卷长**方向的长度（米）= 这一块被领下来时算的米数方向 */
    private BigDecimal lengthM;

    /** 沿**门幅**方向可用的宽度（米） */
    private BigDecimal widthM;

    /** 见 {@link #STATUS_CUSTOMER_TAKEN} / {@link #STATUS_AVAILABLE} / {@link #STATUS_USED} / {@link #STATUS_SCRAPPED} */
    private String status;

    // ── 回收记账（status = used 时全非空；**只**在此时非空）──
    /** 用掉这块余料的那张单（内部成本冲减的归属；**对客金额不受影响**） */
    private String usedByOrderNo;
    private String usedByOrderItemId;
    /** 用在哪一个小件上（= {@code remnant_small_item_specs.item_key} = 工序名） */
    private String usedByItemKey;
    /** 用掉米数 = {@link #lengthM}（这一段的钱当初已随计价口径被客户付过） */
    private BigDecimal recoveredMeters;
    /** **当时**该批次均价快照（源 {@code stock_batches.unit_cost}，NUMERIC(12,4) 与 V119 同型） */
    private BigDecimal recoveredUnitCost;
    /** = {@link #recoveredMeters} × {@link #recoveredUnitCost}（DB 约束逐值钉住，不是读面现算） */
    private BigDecimal recoveredAmount;
    private OffsetDateTime recoveredAt;
    private String recoveredBy;

    // ── 报废留痕（status = scrapped 时全非空；与回收互斥）──
    private String scrapReason;
    private OffsetDateTime scrappedAt;
    private String scrappedBy;

    private OffsetDateTime createdAt;

    @TableLogic
    private Integer deleted;

    /**
     * 面积（平方米）= {@link #lengthM} × {@link #widthM} —— **派生，不落库**。
     *
     * <p>落库就是第三个数，与两条边之间迟早对不上（且余料不代表任何金额 ⇒ 面积没有独立语义，
     * 只是给人看的一眼摘要）。缺任一条边 ⇒ {@code null}（不造值）。</p>
     */
    public BigDecimal getAreaM2() {
        return lengthM == null || widthM == null ? null : lengthM.multiply(widthM);
    }
}
