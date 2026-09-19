package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 工艺词表 + <b>商户级默认工艺</b>（V72，issue #4432 = 母单 #4423 P2/3）。
 * 对应表：{@code production_crafts}。
 *
 * <p><b>存在的理由（规格订正，母单 #4423 评论「🔴 规格订正」）</b>：重构后路线模板
 * <b>没有工艺维</b>（工艺已降为 {@code production_route_rules} 的触发键）⇒ 缺 {@code craft} 时
 * 「从默认路线取对应维」<b>在实现上不成立</b>。而工艺决定「插入哪道工序 + 计件系数」
 * ⇒ 猜错 = <b>算错工人工资</b>。</p>
 *
 * <p>⇒ 改为<b>一次配置、全局确定</b>的商户级默认工艺，不依赖每单的字符串匹配
 * （关键词 {@code contains} 本来就是猜：商品名里出现一个「纱」字就可能把布帘单判成纱帘，
 * V58 已实证过同类错配）。<b>不得</b>写死常量 {@code 韩褶} —— 商户只做打孔时会插错工序
 * + 算错计件系数。</p>
 *
 * <p><b>不变式</b>：每租户活跃工艺中<b>恰好一条</b> {@code isDefault}
 * （部分唯一索引 {@code uk_production_crafts_tenant_default} 保证 ≤1）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_crafts", autoResultMap = true)
public class ProductionCraft {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 工艺名（逐字 = ERP 写法；与 {@code production_route_rules.trigger_value} 同词表） */
    private String name;

    /** 商户级默认工艺标记：缺 {@code craft} 时的兜底来源（每租户恰一条） */
    private Boolean isDefault;

    private String status;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
