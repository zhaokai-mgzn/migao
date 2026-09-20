package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 加工项实体类
 * 对应表：processing_items
 * 说明：布艺行业核心加工项，如打孔、挂钩等
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "processing_items", autoResultMap = true)
public class ProcessingItem {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    private String name;

    private String categoryId;

    /**
     * 加工数量单位（issue #4882）：语义 = 「**加工数量**的单位」，默认 {@code 米}
     * —— 加工项目录已无单价与计价方式（用户裁定），它不再是「计价单位」。
     */
    private String unit;

    private Integer minQuantity;

    private Integer maxQuantity;

    private String description;

    @TableField(typeHandler = com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler.class)
    private Object options;

    private Integer processingDays;

    /**
     * **加工项显式声明的工艺**（V78，issue #4452）—— 商家建加工项时声明它代表哪个工艺
     * （韩褶/打孔/穿杆/平幔…），是路线键「工艺」维的**受控来源**。
     *
     * <p><b>为什么要有这一列</b>：此前工艺维靠 {@code contains} 猜**加工项名**（「打孔」含
     * 「打孔」⇒ 工艺=打孔）。而加工项目录是**商家可自定义的业务数据** ⇒ 判据绑在研发改的关键词表上，
     * 商家每加一个自定义名就多一分**静默错配**（{@code craft-routing-customization.md} §4 P2 实证：
     * 纱帘订单拿到布帘 11 道工序，**工序与工资全错**）。改声明 ⇒ 结果随之变；改名字 ⇒ 结果不变。</p>
     *
     * <p>可空：留空 = **商家没声明**（不是「工艺=空」）⇒ 存量单走信号表兜底，新单落
     * {@code route_source=partial/default} 并在异常订单清单里可见（**不猜**）。</p>
     */
    private String craftHint;

    private Boolean aiRecommended;

    private String status;

    @TableField(fill = FieldFill.INSERT)
    private OffsetDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;
}
