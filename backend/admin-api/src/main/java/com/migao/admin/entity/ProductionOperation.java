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

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
