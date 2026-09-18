package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.OffsetDateTime;

/**
 * 工艺路线模板（issue #3995，M4-G-2）
 * 对应表：production_routings（V49）。部位 × 工艺 → 基准工序序列。
 * 与 ai-agent-service app/production/routing.py 的 ROUTINGS 同构（M4-G-1）。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "production_routings", autoResultMap = true)
public class ProductionRouting {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 部位/帘种：布帘/纱帘/帘头 */
    private String curtainType;

    /** 工艺：韩褶/打孔/四爪钩/穿杆/平幔 */
    private String craft;

    /** 工序名有序序列（JSONB 数组） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object operations;

    /** active / disabled */
    private String status;

    /**
     * provenance 口径来源（V62，issue #4361）：{@code 实证} / {@code 推算} / {@code 占位待确认}。
     *
     * <p>存量行由 V62 按 id 前缀回填：{@code rt-v54-*} → {@code 占位待确认}
     * （**含 布帘×韩褶** —— #4343 已证明它与客户真实加工单 CSO260915-02615 不符：
     * 缺 4 道 / 多 1 道 / {@code 定型→熨烫} 顺序相反 / 6 道工序名库里没有）、
     * {@code rt-v58-*} → {@code 推算}（3 条纱帘，镜像布帘同工艺推导）。
     * {@code 实证} = **当前空集**（客户确认 #4261/#4343 后才会有）。</p>
     *
     * <p>{@code NULL} = 来源未知（商家自建 / 历史行）：**不许**读成「占位待确认」。</p>
     */
    private String source;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;
}
