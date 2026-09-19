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
 * 部位价目 + 适用性矩阵（V71，issue #4427 = 母单 #4423 P1/3；P2 / issue #4432 起有消费者）。
 * 对应表：{@code production_operation_positions}。
 *
 * <p><b>一行</b> = 一道<b>逻辑工序</b>（去部位后缀，如 精裁/三边/韩褶）× 一个<b>部位</b>
 * （布帘/纱帘/帘头）。旧模型把部位编码进工序名（{@code 精裁-布}/{@code 精裁-纱}、
 * {@code 布三边}/{@code 纱三边}）⇒ 单价绑在 35 个名字上；新模型把部位抽出来做矩阵
 * （28 × 3 = 84 行），同一道工序在不同部位可各自定价。</p>
 *
 * <p><b>{@code applicable} 存在的理由</b>：把「<b>明确不做</b>」与「<b>没定价</b>」在数据上区分开
 * —— 前者是本列 {@code FALSE}，后者是本列 {@code TRUE} + {@code unitPrice IS NULL}。
 * 例：熨烫 只做布帘（纱帘/帘头 {@code applicable=FALSE}）；帘头制作 只做帘头。</p>
 *
 * <p><b>⚠️ {@code logicalName} 不是 {@code production_operations.name}</b>：后者仍是旧名
 * （{@code 精裁-布}/{@code 布三边}…，P2 一字不动）。把逻辑名映射回该租户工序库里的
 * <b>变体名</b>由 {@code ProductionOperationQueryService} 的确定性查找规则承担
 * （见该类的 {@code variantNameOf}）—— <b>不在此实体里另存一份映射表</b>（那就是第二份口径）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_operation_positions", autoResultMap = true)
public class ProductionOperationPosition {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 逻辑工序名（去部位后缀）：与 {@code routing.py::OPERATION_LOGICAL_NAMES} 值域一致（28 个） */
    private String logicalName;

    /** 部位：布帘/纱帘/帘头 */
    private String position;

    /** 计件单价（元/单位）；{@code NULL} = 该部位明确不做（不报价） */
    private BigDecimal unitPrice;

    /** 该部位是否做这道工序；{@code false} = 明确不做（≠「没定价」） */
    private Boolean applicable;

    private String status;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
