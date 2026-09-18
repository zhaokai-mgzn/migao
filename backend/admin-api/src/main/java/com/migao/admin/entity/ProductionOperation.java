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
 * 生产工序库（issue #3995，M4-G-2）
 * 对应表：production_operations（V49）。
 * 分组：裁剪 / 车位 / 后道 / 其他；工序按部位分设（韩褶-布 / 韩褶-纱 单价各自不同）。
 * 真值源：docs/curtain-production-rules.md §2。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_operations", autoResultMap = true)
public class ProductionOperation {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 工序名（按部位分设：精裁-布 / 韩褶-纱） */
    private String name;

    /** 车间工位分组：裁剪/车位/后道/其他 */
    private String groupName;

    /** 部位：布帘/纱帘/帘头/外帘（空=通用） */
    private String position;

    /** 计件单位：米/折/幅/孔/套/个 */
    private String unit;

    /** 计件单价（元/单位） */
    private BigDecimal unitPrice;

    /** 必完工序：全绿才可打包 → 加工单置 completed（生产完工；订单状态不动，issue #4117） */
    private Boolean isMustFinish;

    /** 生产开始标记：该工序报工即视为进入生产中 */
    private Boolean isStartMarker;

    private Integer sortOrder;

    /** active / disabled */
    private String status;

    /**
     * provenance 口径来源（V62，issue #4361）：{@code 实证} / {@code 推算} / {@code 占位待确认}。
     *
     * <p>存在的唯一理由：让「单价是占位值 / 行业推算值」这件事**在数据与界面上可见**
     * （用户裁定 2026-09-19：「照铺，但 provenance 必须可见，不许静默」）。
     * 存量行由 V62 按 id 前缀回填（{@code op-v54-*} → {@code 占位待确认}、
     * {@code op-v56-*} → {@code 推算}）；{@code 实证} = **当前空集**
     * （客户确认 #4261/#4343 后才会有 —— 这是诚实结论，不是遗漏）。
     * 新租户由模板套用写入（逐字取模板标注，不在套用路径上"顺手修正"）。</p>
     *
     * <p>{@code NULL} = 来源未知（商家自建 / 历史行）：**不许**读成「占位待确认」——
     * 未知就是未知，冒充已知正是本列要治的病。</p>
     */
    private String source;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
