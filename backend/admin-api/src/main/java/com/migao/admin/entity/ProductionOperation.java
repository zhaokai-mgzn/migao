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

    /**
     * 工序作用域（V67，issue #4384 A1）：{@code position} = 部位级（默认，每部位一次）/
     * {@code set} = 套级（**每樘窗一次**）。
     *
     * <p>存在的理由（真值源 {@code docs/curtain-production-rules.md} §8）：**外帘**是加工单打印行
     * 部位、**不是**路线键；但 V54/V58 种子里 {@code 外帘打卷}/{@code 外帘装袋}/{@code 外帘发货}
     * 的 {@code position='外帘'} 却**逐条出现在每一条部位路线**里（含纱帘路线）⇒ 一樘「布 + 纱」时
     * 这 3 道各实例化 **2 次**（{@code unit='套'}、{@code qty=1}）⇒ 打卷/装袋/发货 **各 ¥1.0 双付**。
     * 用户裁定（2026-09-19）：**套级工序先按「每樘窗一次」实现**，打卷是否每帘一次**留成可配**。</p>
     *
     * <p>⚠️ 本列**只是标记**：套级去重（A2，{@code ProcessingOrderService.buildPositionPayload}）
     * 不在 #4384 A1 包内（等包 D #4387 合入后单独做）⇒ 今天置 {@code set} 只改读面/写面/界面口径，
     * **尚未改变实例化行为**。</p>
     */
    private String scope;

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
