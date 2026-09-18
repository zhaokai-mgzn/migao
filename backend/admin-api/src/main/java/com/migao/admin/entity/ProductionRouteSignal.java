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
 * 信号 → 路线键映射（V60，issue #4308「工艺路线商家可配」）
 * 对应表：production_route_signals。
 *
 * <p><b>为什么落库而不是留常量</b>：迁移前这条映射是 {@code ProcessingOrderService} 里的两个
 * {@code String[][]} 常量；而**加工项目录是商家可自定义的**（POC 已建过「POC-加工工艺」这类名字）
 * ⇒ 把「商家可配的业务数据」判据绑在「研发改的常量表」上，商家每加一个自定义加工项，
 * 路线派生就多一分静默错配，改常量还要走研发发版（issue #4308 P2）。</p>
 *
 * <p><b>用途拆分（本表最反直觉的一处，见 V60 迁移注释）</b>：{@code curtain_type} 非空 = 帘种行，
 * {@code craft} 非空 = 工艺行；{@code priority} 是**用途内**扫描序，不是全局序 ——
 * 迁移前的常量表里「帘头」在帘种表**最前**、在工艺表**最后**，单列 priority 表达不了两个位次。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_route_signals", autoResultMap = true)
public class ProductionRouteSignal {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 信号关键字（命中方式 = 文本 contains，与迁移前常量表同口径） */
    private String signal;

    /** 命中后给出的帘种；NULL = 本行不参与帘种扫描（本行是工艺行） */
    private String curtainType;

    /** 命中后给出的工艺；NULL = 本行不参与工艺扫描（本行是帘种行） */
    private String craft;

    /** **用途内**扫描序（越小越先） */
    private Integer priority;

    /** active / disabled */
    private String status;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
