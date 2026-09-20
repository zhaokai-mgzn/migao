package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 工序实例：加工单 × 部位 × 工序（issue #3995，M4-G-2）
 * 对应表：processing_position_operations（V49）。扫码报工的推进单元；
 * 应做数量 = 算料引擎输出，报工只确认不心算（真值源 §3）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "processing_position_operations", autoResultMap = true)
public class ProcessingPositionOperation {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String processingOrderId;

    /**
     * 套归属（V92，issue #4698 切片 ⓪）：指向 {@code processing_order_sets.id}。
     *
     * <p><b>可空</b> = 本列引入前的存量实例行（与 {@link #orderItemId} 同款「留空不猜」；
     * V92 回填只写 {@code order_item_id} 非空的行）。扫码解析的推断按它取「本套的全部工序」
     * （切片 ①：部位级优先 → 套级回落，设计 §3.2）。</p>
     */
    private String setId;

    /**
     * 部位**展示名** = 加工产物名[+色号]（如 {@code 布艺遮光帘A 米白}）—— **不是帘种**。
     *
     * <p>⚠️ 本条注释此前写「部位：布帘/纱帘/帘头/外帘」，**与实现相反**（issue #4621 改判）。
     * 取值来自 {@code ProcessingOrderService#buildPositionPayload} 的
     * {@code positionName = productName (+ " " + colorName)}；设计文档
     * {@code docs/design/position-instance-routing-model.md} 逐字写
     * {@code position_name = productName[+colorName]}、「主定位键 = {@code (order_item_id, position_kind)}；
     * {@code position_name} 只是**展示名**」。照旧注释取「帘种」会拼出
     * 「三边 · 布艺遮光帘A 米白」这种名字（且与进度表分组标题、任务卡的「部位」列重复）。</p>
     *
     * <p><b>要帘种请取 {@link #positionKind}</b>（= 快照 {@code curtainType}：布帘/纱帘/帘头）。
     * 可空（存量/派生 payload 缺键 ⇒ null）。</p>
     */
    private String positionName;

    /**
     * **工序实例的主定位键**（issue #4388 / #4373 裁定）：指向 {@code order_items.id}（= 一樘窗的一行）。
     *
     * <p>为什么必须有它：{@code position_name} 是**展示名**（加工产物名[+色号]）——
     * 同商品同色号的两个窗**同名** ⇒ 只靠名字无法区分（今天读面会把它们并成一个部位）。
     * {@code (order_item_id, seq)} 才是实例的唯一归属。</p>
     *
     * <p>⚠️ **可空**：本列（V69）引入**之前**生成的存量行没有该值（无法可靠回填 ——
     * `position_name` 是可读名，回填只能靠猜）⇒ 读面按 {@code position_name} 兜底分组（行为逐字不变）。</p>
     */
    private String orderItemId;

    /**
     * 部位**种类**（可读定位，issue #4388）：`布帘` / `纱帘` / `帘头`（= 快照 {@code curtainType}）。
     *
     * <p>与 {@link #orderItemId} 的分工：前者解决「哪一樘窗的哪一行」，本列解决「哪一件帘」
     * （可读定位 + 冗余校验）。可空（同 {@link #orderItemId}：存量行没有）。</p>
     *
     * <p><b>web 面「工序显示名」取本列</b>（issue #4621）：显示名 = {@code 逻辑名 · 本列}
     * （如 {@code 三边 · 布帘}）；**不要**用 {@link #positionName}（那是展示名，见其 javadoc）。</p>
     */
    private String positionKind;

    /** 部位内工序顺序 */
    private Integer seq;

    private String operationName;

    /** 车间工位分组：裁剪/车位/后道/其他 */
    private String groupName;

    /** 计件单位：米/折/幅/孔/套/个 */
    private String unit;

    /** 应做数量（算料引擎输出） */
    private BigDecimal qty;

    /**
     * 应做数量的口径来源（issue #4208）：键名（{@code fabric_meters}/{@code pleat_count}/{@code holes}）
     * = 算料输出直接供数；{@code <键名>_x6} = 按每米 6 孔的有依据估算；{@code fallback} = 真兜底 1。
     * 存在的唯一理由：让「算料输出」与「兜底」在数据上可区分（兜底不静默）。
     */
    private String qtySource;

    /** 实例快照单价（调价不影响历史报工） */
    private BigDecimal unitPrice;

    /** 特殊选项计件系数（如 一分为二 ×1.7；选项名 = ERP 名，issue #4389） */
    private BigDecimal factor;

    /** 必完工序：全绿 → 加工单置 completed（生产完工；订单状态不动，issue #4117） */
    private Boolean isMustFinish;

    /** 生产开始标记 */
    private Boolean isStartMarker;

    /** pending 待做 / done 已报工 */
    private String status;

    /** 合格累计数量（仅正常报工累加） */
    private BigDecimal doneQty;

    /**
     * 完成时刻（V92，issue #4698）：**A 模式唯一必需的新增时序列**（「做完扫一次 = 完工」）。
     *
     * <p>⚠️ 不得用 {@code updatedAt} 冒充 —— 它会被任何更新污染（设计 §12 D8）。
     * 写入方是切片 ②（报工主闭环）；本切片（① 只读面）只读它来回答「本套何时完成」。</p>
     */
    private OffsetDateTime doneAt;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
