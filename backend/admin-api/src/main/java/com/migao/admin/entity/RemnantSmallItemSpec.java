package com.migao.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.OffsetDateTime;

/**
 * 小件用料尺寸表实体（V122，issue #5146）—— 一行 = **一个小件需要的一块布有多大**。
 *
 * <h2>它是**可配参数**，不是硬编码常量表</h2>
 * 用户裁定逐字：「**小件用料尺寸表，可以整个参数配置，未来让企业自定义**」。
 * ⇒ 尺寸是本租户的参数（挂在**既有企业参数中心**的「余料回收」域，`migao-dev-flow` §22 P1/P2/P3），
 * 不是 Java 里的常量 —— 常量表意味着「每家企业再进一次代码」。
 *
 * <h2>🔴 缺行 = 未配置（**默认值为空**，不编业务数值）</h2>
 * 本仓口径是「缺行 = 用默认值」，而本参数的默认值**就是空**：没配就是**没启用**。
 * 未配置时余料匹配**不产生任何推荐**，且读面**显式说明**原因（判据 4「未配置不静默」）——
 * 不是静默返回空列表，也不是凭空给一个推荐。
 *
 * <h2>{@link #itemKey} 为什么是**工序名**</h2>
 * 特殊选项 → 条件工序的那张表（{@code production_option_routings}）已经在用工序名当键，
 * 而它逐字同真值源 {@code backend/ai-agent-service/app/production/routing.py} 的
 * {@code SPECIAL_OPTION_ROUTINGS[opt]["operation"]}。另造一套「小件名」= 第二份会漂移的口径
 * ⇒ 本表直接用同一套键（{@code 绑带-布} / {@code 帘头制作} / {@code 抱枕} …）。
 * 「配置即启用」也来自这里：**某工序有尺寸行** ⇒ 它就是本租户启用余料匹配的小件。
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName("remnant_small_item_specs")
public class RemnantSmallItemSpec {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long tenantId;

    /** 小件配置键 = 该小件对应的**工序名**（逐字同 {@code production_operations.name}） */
    private String itemKey;

    /** 这一块布沿**卷长**方向需要的长度（米） */
    private BigDecimal lengthM;

    /** 这一块布沿**门幅**方向需要的宽度（米） */
    private BigDecimal widthM;

    private String note;

    private String operator;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    @TableLogic
    private Integer deleted;

    /**
     * 这块余料**装得下**该小件吗（尺寸判定 = 两条边都不小于需求）。
     *
     * <p>口径：**不旋转**（余料的方向由排料决定，转 90° 就等于重切）、**不放宽**（不足即不足）。
     * 判据 5「不凭空推荐」的机械落点：余料尺寸 &lt; 小件用料 ⇒ 这里返回 {@code false} ⇒ 不推荐。</p>
     *
     * <p>任一侧规模缺失（余料/尺寸任一条边为空）⇒ {@code false}（**不猜**：拿不存在的数据
     * 凑出一个「装得下」比不推荐坏得多）。</p>
     */
    public boolean fits(BigDecimal remnantLengthM, BigDecimal remnantWidthM) {
        if (lengthM == null || widthM == null || remnantLengthM == null || remnantWidthM == null) {
            return false;
        }
        return remnantLengthM.compareTo(lengthM) >= 0 && remnantWidthM.compareTo(widthM) >= 0;
    }
}
