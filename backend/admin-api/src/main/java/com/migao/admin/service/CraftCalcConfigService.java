package com.migao.admin.service;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.CraftCalcConfig;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CraftCalcConfigMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 算料公式**租户级配置**服务（issue #4528 = 包 E；读写端点 {@code /api/admin/production/craft-calc-config}）。
 *
 * <h3>两条口径（都是本包的核心）</h3>
 * <ol>
 *   <li><b>缺行 = 用默认值</b>：本租户没有活跃行 ⇒ 读面返回**算料引擎的默认值** +
 *       {@code source='default'}。默认值<b>不在这里写死</b> —— 引擎的
 *       {@code DEFAULT_CRAFT_CALC_CONFIG} 是唯一来源（{@link CraftCalcClient#defaultConfig()}）。
 *       在 Java 侧再抄一份常量 = <b>第二份会漂的默认值</b>（issue #4528 明确「不做开租播种」的同一理由）。</li>
 *   <li><b>配置来自商家 = 不可信输入</b> ⇒ 非法值 {@code 422 + error.details 逐条理由}，
 *       <b>不得静默回退默认值</b>（静默 = 算错钱且无人知道）。校验在**写面**做，
 *       算料路径拿到的永远是已校验过的行。</li>
 * </ol>
 *
 * <h3>PUT 是**全量替换**（不是部分更新）</h3>
 * 缺键 ⇒ 422 逐键报缺，<b>不</b>把缺的键悄悄按默认值存 —— 那正是「静默回退默认值」的形态：
 * 商家以为只改了一项、其实另一项被重置（或反过来以为改了却没改）。未知键同样 422
 * （拼错的键被静默忽略 = 商家以为改了却没改）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CraftCalcConfigService {

    /** 无活跃行 ⇒ 用的是**引擎默认值**（读面 {@code source} 取值）。 */
    public static final String SOURCE_DEFAULT = "default";

    /** 本租户有活跃行 ⇒ 用的是商家配置。 */
    public static final String SOURCE_STORED = "stored";

    /** 读面 {@code defaults_source}：引擎默认值**取到了**（逐键「我改过没有」可用）。 */
    public static final String DEFAULTS_SOURCE_ENGINE = "engine";

    /**
     * 读面 {@code defaults_source}：引擎默认值**本次取不到** ⇒ 逐键对比**不可用**（**显式**告知）。
     *
     * <p>🔴 与 {@code source='default'} 的 fail-closed **不是一回事**：缺行时取不到默认值 ⇒ **422**
     * （那时默认值就是返回值本身，凭空造一份 = 让商家按错的口径改配置）；而这里默认值只是**读面的注解**，
     * 取不到不影响 {@code config} 本身的正确性 ⇒ 不拖垮读面，但必须**说出来**（前端据此显式显示
     * 「默认值暂不可用」，**不得**把「拿不到」画成「就是默认值」）。</p>
     */
    public static final String DEFAULTS_SOURCE_UNAVAILABLE = "unavailable";

    /**
     * 褶倍下限的**行业美学红线**：配置可配但**不可关**（低于它 ⇒ 422）。
     *
     * <p>与算料引擎 {@code curtain_calc.MIN_FULLNESS}（= 引擎默认配置的 {@code min_fullness}）
     * <b>同值</b>；这里是**护栏常量**（写面拒绝），不是公式参数 —— 引擎自身只校验「正数」，
     * 关掉下限的责任在不可信输入的边界上（本服务）。</p>
     *
     * <p>跨源漂移守卫 = {@code tests/unit_ci_workflows/test_craft_calc_config_contract.py}
     * 逐值读 {@code curtain_calc.py} 比对（引擎改红线而 Java 没跟 ⇒ 红）。</p>
     */
    public static final BigDecimal MIN_FULLNESS_RED_LINE = new BigDecimal("1.5");

    /** 公式枚举（与引擎 {@code curtain_calc.FORMULA_LABELS} 的键同集合；同上守卫）。 */
    public static final Set<String> FORMULAS = Set.of("pleat", "fullness");

    /**
     * 配置键（**恰好** = 引擎 {@code DEFAULT_CRAFT_CALC_CONFIG} 的键集，逐字同名；同上守卫）。
     *
     * <p>顺序即读面/写面的键顺序（{@code LinkedHashMap} 保序 ⇒ 响应可预测）。</p>
     */
    public static final List<String> CONFIG_KEYS = List.of(
            "per_fold_single", "per_fold_mixed_times", "margin_single", "margin_multi",
            "min_fullness", "tiers", "default_formula", "hem_margin",
            "meters_rounding_step", "oversize_width_threshold", "oversize_height_threshold");

    /** 必须是**正数**的标量键（引擎 {@code _POSITIVE_CONFIG_KEYS} 同集合）。 */
    private static final List<String> NUMERIC_KEYS = List.of(
            "per_fold_single", "margin_single", "margin_multi", "min_fullness",
            "hem_margin", "meters_rounding_step",
            "oversize_width_threshold", "oversize_height_threshold");

    private final CraftCalcConfigMapper craftCalcConfigMapper;
    private final CraftCalcClient craftCalcClient;

    /** 读本租户的**生效**算料配置（**不带**引擎默认值 —— 既有调用方口径逐字节不变）。 */
    public Map<String, Object> get(Long tenantId) {
        return get(tenantId, false);
    }

    /**
     * 读本租户的**生效**算料配置。
     *
     * @param withDefaults 是否**额外**附上**引擎默认值**（§22 P3「逐键我改过没有」，issue #5131 增量 2）。
     *        🔴 **默认 false** 是有意的：既有调用方（算料配置页）走 {@code get(tenantId)} ⇒ 响应**逐字节不变**、
     *        也**不新增**「读配置要依赖引擎可达性」这条依赖；只有「参数总览」显式要时才去取。
     * @return {@code {source, config}}；{@code withDefaults=true} 时**再加** {@code defaults} +
     *         {@code defaults_source}（见 {@link #putEngineDefaultsBestEffort}）。
     *         {@code source='stored'} = 商家配置行；{@code source='default'} = 本租户没有配置行，
     *         值取自**算料引擎默认值**（未配置租户的算料结果因此与包 D 合并后的默认结果**逐值一致**）。
     * @throws BusinessException 422 —— **缺行**时取引擎默认值失败（ai-agent 不可达等）：
     *         <b>fail-closed</b>，绝不返回一份凭空的默认值（那会让商家按错的口径改配置）。
     *         ⚠️ **有行**时取默认值失败**不** 422（那条路径今天不依赖引擎可达性，见下）。
     */
    public Map<String, Object> get(Long tenantId, boolean withDefaults) {
        requireTenant(tenantId);
        CraftCalcConfig row = craftCalcConfigMapper.selectActiveByTenant(tenantId);
        if (row != null) {
            Map<String, Object> data = response(SOURCE_STORED, row.toConfigMap());
            if (withDefaults) {
                putEngineDefaultsBestEffort(data);
            }
            return data;
        }
        Map<String, Object> defaults = craftCalcClient.defaultConfig();
        Map<String, Object> data = response(SOURCE_DEFAULT, defaults);
        if (withDefaults) {
            // 缺行时 config 本身就是默认值 ⇒ 同一份直接作为 defaults（**不第二次调用引擎**）
            data.put("defaults", defaults);
            data.put("defaults_source", DEFAULTS_SOURCE_ENGINE);
        }
        return data;
    }

    /**
     * 把**引擎默认值**挂到读面响应上（§22 P3「默认值可见」的**逐键**形态）—— **尽力取，且显式**。
     *
     * <p>🔴 **为什么是尽力而为、而不是 fail-closed**：本字段是**读面注解**，不是参与者。有配置行的读
     * 今天**不依赖**引擎可达性（值来自库）—— 若为它引入 fail-closed，就把一个**新失败面**加到了
     * 本来能工作的读面上（引擎抖一下 ⇒ 商家连自己的配置都看不了）。</p>
     *
     * <p>🔴 **但绝不静默**：取不到 ⇒ {@code defaults_source='unavailable'}（且**不带** {@code defaults} 键），
     * 前端据此**显式**显示「默认值暂不可用」，而不是把「拿不到」画成「就是默认值」。</p>
     */
    private void putEngineDefaultsBestEffort(Map<String, Object> data) {
        try {
            data.put("defaults", craftCalcClient.defaultConfig());
            data.put("defaults_source", DEFAULTS_SOURCE_ENGINE);
        } catch (RuntimeException e) {
            log.warn("取引擎默认值失败 ⇒ 逐键「我改过没有」本次不可用（读面其余字段照常）: error={}",
                    e.getMessage());
            data.put("defaults_source", DEFAULTS_SOURCE_UNAVAILABLE);
        }
    }

    /**
     * 写本租户配置（**upsert**：无行则建，有行则全量替换）。
     *
     * @throws BusinessException 422 + {@code error.details:[{field,message}]} 逐条理由
     */
    public Map<String, Object> put(Long tenantId, Map<String, Object> body) {
        requireTenant(tenantId);
        Map<String, Object> config = validate(body);
        CraftCalcConfig row = craftCalcConfigMapper.selectActiveByTenant(tenantId);
        OffsetDateTime now = OffsetDateTime.now();
        if (row == null) {
            row = CraftCalcConfig.builder()
                    .id("ccc-" + tenantId)      // 确定性 id：单行表 + 便于日志/审计定位
                    .tenantId(tenantId)
                    .status("active")
                    .deleted(0)
                    .createdAt(now)
                    .build();
            apply(row, config);
            row.setUpdatedAt(now);
            craftCalcConfigMapper.insert(row);
            log.info("算料配置新建: tenantId={} perFoldSingle={} minFullness={}",
                    tenantId, config.get("per_fold_single"), config.get("min_fullness"));
        } else {
            apply(row, config);
            row.setUpdatedAt(now);
            craftCalcConfigMapper.updateById(row);
            log.info("算料配置更新: tenantId={} perFoldSingle={} minFullness={}",
                    tenantId, config.get("per_fold_single"), config.get("min_fullness"));
        }
        return response(SOURCE_STORED, row.toConfigMap());
    }

    // ══════════════════════════════════════════════════════════════════════
    // 护栏（不可信输入边界）—— 逐条理由，全部拒绝，不静默回退默认值
    // ══════════════════════════════════════════════════════════════════════

    /**
     * 校验 + 归一（数值统一成 {@link BigDecimal}），失败 ⇒ 422 带**逐条**理由。
     *
     * <p>规则（与算料引擎 {@code resolve_craft_calc_config} 同口径，<b>更严的一处是护栏</b>）：
     * 数值键 &gt; 0 · {@code per_fold_mixed_times} 非空且键为正整数、值 &gt; 0 ·
     * {@code tiers} 非空且每档 {@code fullness} &gt; 0 且 ≥ {@code min_fullness} ·
     * {@code min_fullness} ≥ 行业红线 · {@code default_formula} 在枚举内。</p>
     *
     * <p>⚠️ 与 issue 文本的两处**照实差异**（以实现为准，见 PR 边界节）：
     * ① issue 写 {@code margin_* ≥ 0}，而引擎 {@code _POSITIVE_CONFIG_KEYS} 要求 <b>&gt; 0</b>
     * （0 会被引擎拒绝 ⇒ 存进去也算不出料）⇒ 这里跟引擎；
     * ② issue 写 {@code meters_rounding_step = 0.1}，而引擎接受任意正步长
     * （引擎自测就用 0.05）⇒ 这里只要求 &gt; 0，不做「必须等于 0.1」的第二份口径。</p>
     */
    Map<String, Object> validate(Map<String, Object> body) {
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        Map<String, Object> in = body == null ? Map.of() : body;

        for (String key : in.keySet()) {
            if (!CONFIG_KEYS.contains(key)) {
                details.add(BusinessException.detail(key,
                        "不是算料配置键（拼错的键会被静默忽略 ⇒ 商家以为改了却没改；合法键：" + CONFIG_KEYS + "）"));
            }
        }
        for (String key : CONFIG_KEYS) {
            if (!in.containsKey(key)) {
                details.add(BusinessException.detail(key,
                        "缺少配置键（PUT 是**全量替换**：缺键会让该口径静默回到默认值 ⇒ 显式拒绝，不静默回退）"));
            }
        }

        Map<String, Object> out = new LinkedHashMap<>();
        for (String key : NUMERIC_KEYS) {
            BigDecimal value = toNumber(in.get(key));
            if (in.get(key) == null) {
                continue;   // 缺键已在上面报过，不重复报
            }
            if (value == null) {
                details.add(BusinessException.detail(key, "必须是数字，收到 " + in.get(key)));
            } else if (value.signum() <= 0) {
                details.add(BusinessException.detail(key,
                        "必须大于 0，收到 " + value.toPlainString() + "（0/负会让该口径静默失效，算料引擎也会拒）"));
            } else {
                out.put(key, value);
            }
        }

        Object minFullnessRaw = out.get("min_fullness");
        BigDecimal minFullness = minFullnessRaw instanceof BigDecimal b ? b : MIN_FULLNESS_RED_LINE;
        if (minFullnessRaw instanceof BigDecimal b && b.compareTo(MIN_FULLNESS_RED_LINE) < 0) {
            details.add(BusinessException.detail("min_fullness",
                    "不得低于行业红线 " + MIN_FULLNESS_RED_LINE.toPlainString() + "（可配但**不可关**："
                            + "低于它 = 用料不足且无人知道），收到 " + b.toPlainString()));
        }

        Object mixedRaw = in.get("per_fold_mixed_times");
        if (mixedRaw instanceof Map<?, ?> mixed && !mixed.isEmpty()) {
            Map<String, Object> normalized = new LinkedHashMap<>();
            for (Map.Entry<?, ?> e : mixed.entrySet()) {
                String timesKey = String.valueOf(e.getKey());
                int times = parseIntOrZero(timesKey);
                if (times <= 0) {
                    details.add(BusinessException.detail("per_fold_mixed_times." + timesKey,
                            "拼次必须是正整数（键），收到 " + timesKey));
                    continue;
                }
                BigDecimal perFold = toNumber(e.getValue());
                if (perFold == null || perFold.signum() <= 0) {
                    details.add(BusinessException.detail("per_fold_mixed_times." + timesKey,
                            "每折吃布必须大于 0，收到 " + e.getValue()));
                    continue;
                }
                normalized.put(String.valueOf(times), perFold);
            }
            if (!normalized.isEmpty()) {
                out.put("per_fold_mixed_times", normalized);
            }
        } else if (mixedRaw != null) {
            details.add(BusinessException.detail("per_fold_mixed_times",
                    "必须是非空映射 {拼次: 每折吃布(米)}，收到 " + mixedRaw));
        }

        Object tiersRaw = in.get("tiers");
        if (tiersRaw instanceof Map<?, ?> tiers && !tiers.isEmpty()) {
            for (Map.Entry<?, ?> e : tiers.entrySet()) {
                String name = String.valueOf(e.getKey());
                if (!(e.getValue() instanceof Map<?, ?> tier)) {
                    details.add(BusinessException.detail("tiers." + name,
                            "必须是对象 {fullness, label}，收到 " + e.getValue()));
                    continue;
                }
                BigDecimal fullness = toNumber(tier.get("fullness"));
                if (fullness == null || fullness.signum() <= 0) {
                    details.add(BusinessException.detail("tiers." + name + ".fullness",
                            "必须是大于 0 的数字，收到 " + tier.get("fullness")));
                } else if (fullness.compareTo(minFullness) < 0) {
                    details.add(BusinessException.detail("tiers." + name + ".fullness",
                            "不得低于褶倍下限 min_fullness=" + minFullness.toPlainString()
                                    + "（档位低于下限 = 该档算出的帘子用料不足），收到 " + fullness.toPlainString()));
                }
            }
            out.put("tiers", tiersRaw);
        } else if (tiersRaw != null) {
            details.add(BusinessException.detail("tiers",
                    "必须是非空映射 {档位名: {fullness, label}}，收到 " + tiersRaw));
        }

        Object formula = in.get("default_formula");
        if (formula != null && !FORMULAS.contains(String.valueOf(formula))) {
            details.add(BusinessException.detail("default_formula",
                    "必须是 " + FORMULAS + " 之一（pleat 韩褶公式＝褶数法 / fullness 褶倍数公式＝倍数法），收到 " + formula));
        } else if (formula != null) {
            out.put("default_formula", String.valueOf(formula));
        }

        if (!details.isEmpty()) {
            throw BusinessException.validationError(
                    "算料配置有 " + details.size() + " 处不合法，已整份拒绝（**不静默回退默认值** —— "
                            + "静默 = 商家以为改了、系统按默认算 ⇒ 算错钱且无人知道）",
                    details,
                    "请按逐条理由修正后重新提交；各键语义与默认值见 "
                            + "GET /api/admin/production/craft-calc-config（source='default' 的那一份）。");
        }
        return out;
    }

    // ══════════════════════════════════════════════════════════════════════
    // 内部
    // ══════════════════════════════════════════════════════════════════════

    private static void apply(CraftCalcConfig row, Map<String, Object> config) {
        row.setPerFoldSingle((BigDecimal) config.get("per_fold_single"));
        row.setPerFoldMixedTimes(config.get("per_fold_mixed_times"));
        row.setMarginSingle((BigDecimal) config.get("margin_single"));
        row.setMarginMulti((BigDecimal) config.get("margin_multi"));
        row.setMinFullness((BigDecimal) config.get("min_fullness"));
        row.setTiers(config.get("tiers"));
        row.setDefaultFormula((String) config.get("default_formula"));
        row.setMetersRoundingStep((BigDecimal) config.get("meters_rounding_step"));
    }

    private static Map<String, Object> response(String source, Map<String, Object> config) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("source", source);
        data.put("config", config);
        return data;
    }

    private static void requireTenant(Long tenantId) {
        if (tenantId == null) {
            throw BusinessException.tenantInvalid();
        }
    }

    private static BigDecimal toNumber(Object raw) {
        if (raw instanceof BigDecimal b) {
            return b;
        }
        if (raw instanceof Number n) {
            return new BigDecimal(n.toString());
        }
        if (raw instanceof String s && !s.isBlank()) {
            try {
                return new BigDecimal(s.trim());
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }

    private static int parseIntOrZero(String raw) {
        try {
            return Integer.parseInt(raw.trim());
        } catch (NumberFormatException e) {
            return 0;
        }
    }
}
