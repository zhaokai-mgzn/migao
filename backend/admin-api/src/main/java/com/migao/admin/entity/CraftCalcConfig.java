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

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 算料公式<b>租户级配置</b>（V80，issue #4528 = 包 E）。对应表：{@code craft_calc_configs}。
 *
 * <p><b>为什么需要它</b>：用户 2026-09-19 裁定「我提供的韩折的公式<b>可能不是行业通用的</b>，
 * 可能得<b>支持每个商家自定义配置</b>」—— 包 D（#4527）已把公式参数做成「可注入 + 默认值」
 * （{@code curtain_calc.DEFAULT_CRAFT_CALC_CONFIG}），但没有消费者，商家改不了口径。
 * 本表就是那个消费者。</p>
 *
 * <p><b>缺行 = 用默认值</b>（读面 {@code source='default'}）—— <b>不做开租播种</b>：
 * 默认值的唯一来源是算料引擎的 {@code DEFAULT_CRAFT_CALC_CONFIG}
 * （{@code GET /api/internal/production/craft-calc-config}），库里再种一份
 * = <b>第二份会漂的默认值</b>（引擎改默认、库里还是旧值 ⇒ 两条路径算不同米数）。</p>
 *
 * <p><b>列名 = 引擎配置键，逐字同名</b>（{@link #toConfigMap()} 因此零映射）：
 * 映射表就是「第二份键名口径」的滋生地（同 {@code CraftCalcController} 头注释的键名纪律）。</p>
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "craft_calc_configs", autoResultMap = true)
public class CraftCalcConfig {

    @TableId(type = IdType.ASSIGN_UUID)
    private String id;

    private Long tenantId;

    /** 单色每折吃布（米）；引擎默认 0.25 */
    private BigDecimal perFoldSingle;

    /** 拼色「拼次 → 每折吃布（米）」；JSONB，键为拼次的**字符串形态**（JSON 对象键恒为字符串） */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object perFoldMixedTimes;

    /** 单开余量（米）；引擎默认 0.2 */
    private BigDecimal marginSingle;

    /** 多开余量（米）；引擎默认 0.3 */
    private BigDecimal marginMulti;

    /** 褶倍下限（护栏，行业美学红线）；引擎默认 1.5 */
    private BigDecimal minFullness;

    /** 工艺档位 {@code {档位名: {fullness, label}}}；JSONB */
    @TableField(typeHandler = JacksonTypeHandler.class)
    private Object tiers;

    /** 兜底公式：{@code pleat} 韩折公式（折数法）/ {@code fullness} 褶倍数公式（倍数法） */
    private String defaultFormula;

    /** 定宽买高上下卷边（米）；引擎默认 0.3 */
    private BigDecimal sideMargin;

    /** 用料向上进位步长（米）；引擎默认 0.1 */
    private BigDecimal metersRoundingStep;

    private String status;

    private OffsetDateTime createdAt;

    private OffsetDateTime updatedAt;

    private Integer deleted;

    /**
     * 本行 → **算料引擎配置对象**（键与 {@code DEFAULT_CRAFT_CALC_CONFIG} 逐字同名，顺序固定）。
     *
     * <p>唯一用处 = 随算料请求发给 ai-agent（{@code CraftCalcClient}）+ 读面回显。
     * 键名/顺序写死在这里是**有意**的：它就是「列 ↔ 引擎键」的唯一映射点，
     * 跨源漂移由 {@code tests/unit_ci_workflows/test_craft_calc_config_contract.py} 逐键比对
     * （引擎配置键集 / 迁移列 / schema.sql 列 / 本类字段 / 本方法键集，任一处漂 ⇒ 红）。</p>
     */
    public Map<String, Object> toConfigMap() {
        Map<String, Object> config = new LinkedHashMap<>();
        config.put("per_fold_single", perFoldSingle);
        config.put("per_fold_mixed_times", perFoldMixedTimes);
        config.put("margin_single", marginSingle);
        config.put("margin_multi", marginMulti);
        config.put("min_fullness", minFullness);
        config.put("tiers", tiers);
        config.put("default_formula", defaultFormula);
        config.put("side_margin", sideMargin);
        config.put("meters_rounding_step", metersRoundingStep);
        return config;
    }
}
