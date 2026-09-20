package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 一部位一码的 token 载体（V92，切片 ⓪ / issue #4698；设计 §2.3）。
 *
 * <p>码内容 = <b>单号 + 套号 + 部位</b>（token 化）；<b>工序不进码</b>（工艺一改全车间重打，设计 §2.3 码量论证）。
 * 唯一键 {@code uk_set_part_tokens_part (tenant_id, set_id, order_item_id)} ⇒ 同一部位重复打印**复用同一 token**；
 * 撤销语义与既有 {@code processing_orders.qr_token} **逐字同款**：{@code UPDATE … SET token = NULL}。</p>
 *
 * <p>与既有 {@code qr_token} 的关系（设计 §2.6）：**双读、新码优先**；旧码继续有效（不碰、不设强制失效日）。
 * 本实体只映射**解析用到的列**（{@code token} / 归属三键 / 部位种类）；{@code print_count} 等打印面列
 * 本切片无消费者 ⇒ 不映射（需要时按迁移列补）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("processing_set_part_tokens")
public class ProcessingSetPartToken {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String processingOrderId;

    /** 所属套（{@code processing_order_sets.id}）。 */
    private String setId;

    /** 部位 = 一行 {@code order_items}（= 一部位一码的「部位」）。 */
    private String orderItemId;

    /** 部位种类（布帘 / 纱帘 / 帘头；可空 —— 快照缺键时不猜）。 */
    private String positionKind;

    /** 码本体（32 位 UUID 去横线，与既有 {@code qr_token} 同格式）；{@code NULL} = 已撤销。 */
    private String token;

    private Integer deleted;
}
