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
 * 未定价实例的**显式补价**动作账（V94，issue #4709 C）。
 *
 * <p>对应表 {@code production_instance_repricing_logs}：一行 = 一个被补价的实例行，
 * {@code batchId} = 一次动作（回滚的粒度）。</p>
 *
 * <p><b>为什么必须留痕</b>：补价**故意**改写实例快照（{@code processing_position_operations.unit_price}），
 * 而该列此前只有实例化一个写方（PG-020 的结构判据逐字是「PUT 路径物理上没有写实例表的能力」）
 * ⇒ 没有账本时「这行价是商家在矩阵里定的，还是补价补出来的」永远答不出来，**可回滚**也无从谈起
 * （回滚的判据只能来自账本：否则分不清「该回滚的行」与「商家本来定的行」）。</p>
 *
 * <p><b>不记 {@code oldUnitPrice}</b>：本表只由「{@code unit_price IS NULL} ⇒ 有价」写入
 * （服务层 CAS 谓词 {@code unit_price IS NULL} 机械保证）⇒ 旧值恒 {@code NULL}，
 * 多一列恒空列只会制造「它可能是别的值」的错觉。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_instance_repricing_logs", autoResultMap = true)
public class ProductionInstanceRepricingLog {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 一次补价动作 = 一个批次（回滚粒度）。 */
    private String batchId;

    private String processingOrderId;

    /** 被补价的工序实例行（{@code processing_position_operations.id}）。 */
    private String positionOperationId;

    /** 本次补上的单价（元/单位）= 补价那一刻部位价目矩阵的当前价。 */
    private BigDecimal newUnitPrice;

    private OffsetDateTime createdAt;

    /** 回滚时刻；{@code NULL} = 未回滚。 */
    private OffsetDateTime rolledBackAt;

    private Integer deleted;
}
