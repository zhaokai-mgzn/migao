package com.migao.admin.service;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.CuttingHeightConfig;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CuttingHeightConfigMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 裁高（定高）**租户级配置**服务（V140，母单 #5161；设计单
 * {@code docs/design/cutting-height-config-and-terminal.md}）。
 * 读写端点 {@code /api/admin/production/cutting-height-config}。
 *
 * <h3>三条口径（都是本包的核心）</h3>
 * <ol>
 *   <li><b>缺行 = 用默认种子</b>（{@code source='default'}）：种子只在 {@link CuttingHeightDefaults}
 *       <b>一处</b>；库里再种一份 = 第二份会漂的默认值（同族先例：{@code CraftCalcConfigService}）。</li>
 *   <li><b>配置来自商家 = 不可信输入</b> ⇒ 非法值 {@code 422 + error.details 逐条理由}，
 *       <b>不得静默回退默认值</b>（静默 = 给机器的值偏了且无人知道）。未知键同样 422
 *       （拼错的键会被静默忽略 = 商家以为改了却没改）。</li>
 *   <li><b>命中口径不复制</b>：判定在 {@link CuttingHeightCalculator}，与订单侧
 *       （{@code processingInfo.specialOptions[]} / 工艺名 / 加工项名 / 部位）**逐字**比对，
 *       与 {@code production_route_rules} 的触发口径同集合。</li>
 * </ol>
 *
 * <h3>PUT 是**全量替换**</h3>
 * 缺键 ⇒ 422 逐键报缺（不把缺的键悄悄按默认值存 —— 那正是「静默回退默认值」的形态）。
 *
 * <h3>变更留痕（§22 P6）</h3>
 * 每次写都把 {@code 改前 → 改后} 交给 {@link TenantParamAuditService}；审计写失败**不让配置保存失败**
 * （口径 B = best-effort，同算料配置）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CuttingHeightConfigService {

    /** 无活跃行 ⇒ 用的是**默认种子**（读面 {@code source} 取值）。 */
    public static final String SOURCE_DEFAULT = "default";

    /** 本租户有活跃行 ⇒ 用的是商家配置。 */
    public static final String SOURCE_STORED = "stored";

    /** 配置体的合法键（PUT 全量替换 ⇒ 缺键/多键都 422）。 */
    static final Set<String> CONFIG_KEYS = new LinkedHashSet<>(List.of("items", "rounding"));

    private static final Set<String> ITEM_KEYS = new LinkedHashSet<>(List.of(
            "key", "name", "value", "direction", "height_join", "hit", "hit_expr", "enabled", "order"));
    private static final Set<String> HIT_KEYS = new LinkedHashSet<>(List.of(
            "trigger_kind", "trigger_value", "position"));
    private static final Set<String> REQUEST_KEYS = new LinkedHashSet<>(List.of(
            "position", "cutting_mode", "finished_height", "craft", "special_options", "processing_items", "is_shaped"));
    private static final Set<String> DIRECTIONS = Set.of("add", "subtract");
    private static final Set<String> ROUNDING_MODES = Set.of("half_up", "down", "up");

    /** 增量项取值的安全带（米）：偏离这个量级的多半是填错单位（mm / cm 当米），宁可拒绝。 */
    private static final BigDecimal MAX_ITEM_VALUE = new BigDecimal("10");

    /** 成品高的安全带（米）。 */
    private static final BigDecimal MAX_FINISHED_HEIGHT = new BigDecimal("20");

    private final CuttingHeightConfigMapper cuttingHeightConfigMapper;
    private final TenantParamAuditService tenantParamAuditService;

    /** 读本租户生效的裁高配置（无行 ⇒ 默认种子 + {@code source='default'}）。 */
    public Map<String, Object> get(Long tenantId) {
        requireTenant(tenantId);
        CuttingHeightConfig row = cuttingHeightConfigMapper.selectActiveByTenant(tenantId);
        if (row == null) {
            return response(SOURCE_DEFAULT, CuttingHeightDefaults.config());
        }
        return response(SOURCE_STORED, row.toConfigMap());
    }

    /**
     * 写本租户裁高配置（upsert，**全量替换**）。
     *
     * @throws BusinessException 422 + {@code error.details:[{field,message}]} 逐条理由
     */
    public Map<String, Object> put(Long tenantId, Map<String, Object> body) {
        requireTenant(tenantId);
        Map<String, Object> config = validate(body);
        CuttingHeightConfig row = cuttingHeightConfigMapper.selectActiveByTenant(tenantId);
        // 🔴 改前的值必须在覆盖**之前**取到（§22 P6 留痕的「A → B」那一半）。
        //    无行 ⇒ 空映射 ⇒ 每个键的改前值都是 null（= 本租户当时在用默认种子）。
        //    刻意**不**在这里去「取默认种子来当改前值」：那会让审计账本里出现一份**从未存过**的值。
        Map<String, Object> before = row == null ? Map.of() : row.toConfigMap();
        String operationId = TenantParamAuditService.newOperationId();
        OffsetDateTime now = OffsetDateTime.now();
        if (row == null) {
            row = CuttingHeightConfig.builder()
                    .id("chc-" + tenantId)      // 确定性 id：单行表 + 便于日志/审计定位
                    .tenantId(tenantId)
                    .status("active")
                    .deleted(0)
                    .createdAt(now)
                    .build();
            apply(row, config);
            row.setUpdatedAt(now);
            cuttingHeightConfigMapper.insert(row);
            log.info("裁高配置新建: tenantId={} items={} operationId={}",
                    tenantId, itemCount(config), operationId);
        } else {
            apply(row, config);
            row.setUpdatedAt(now);
            cuttingHeightConfigMapper.updateById(row);
            log.info("裁高配置更新: tenantId={} items={} operationId={}",
                    tenantId, itemCount(config), operationId);
        }
        // §22 P6 变更留痕（口径 B = best-effort）：本调用**恒不抛**（失败由审计腿自己大声记日志）。
        tenantParamAuditService.recordChanges(tenantId, TenantParamAuditService.DOMAIN_CUTTING_HEIGHT,
                TenantParamAuditService.OPERATION_PUT, operationId, before, row.toConfigMap());
        return response(SOURCE_STORED, row.toConfigMap());
    }

    /**
     * 预演一次裁剪高度（配置页「改动可预演」+ 一体机裁高计算器的同一个算面）。
     *
     * <p><b>只读</b>：不改配置、不落库、不写机器 —— 本版**不做下发**（用户 2026-09-29 裁定①）。
     * 请求里的订单侧取值（工艺 / 特殊选项 / 加工项 / 是否定型）**逐字**传进来，本层**不重算**它们。</p>
     */
    public Map<String, Object> preview(Long tenantId, Map<String, Object> body) {
        requireTenant(tenantId);
        Map<String, Object> in = body == null ? Map.of() : body;
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        for (String key : in.keySet()) {
            if (!REQUEST_KEYS.contains(key)) {
                details.add(BusinessException.detail(key, "不是预演请求键；合法键：" + REQUEST_KEYS));
            }
        }
        String position = text(in.get("position"));
        BigDecimal finishedHeight = decimal(in.get("finished_height"));
        if (position == null) {
            details.add(BusinessException.detail("position", "缺少部位（布帘 / 纱帘 / 帘头）"));
        }
        if (in.get("finished_height") == null) {
            details.add(BusinessException.detail("finished_height", "缺少成品高（米）"));
        } else if (finishedHeight == null) {
            details.add(BusinessException.detail("finished_height", "必须是数字，收到 " + in.get("finished_height")));
        } else if (finishedHeight.signum() <= 0 || finishedHeight.compareTo(MAX_FINISHED_HEIGHT) > 0) {
            details.add(BusinessException.detail("finished_height", "必须在 0 ~ " + MAX_FINISHED_HEIGHT + " 米之间"));
        }
        if (!details.isEmpty()) {
            throw BusinessException.validationError("裁高预演请求有 " + details.size() + " 处不合法", details,
                    "按逐条理由修正后重试");
        }

        CuttingHeightConfig row = cuttingHeightConfigMapper.selectActiveByTenant(tenantId);
        String source = row == null ? SOURCE_DEFAULT : SOURCE_STORED;
        Map<String, Object> config = row == null ? CuttingHeightDefaults.config() : row.toConfigMap();
        CuttingHeightCalculator.Vars vars = new CuttingHeightCalculator.Vars(
                position, finishedHeight, text(in.get("craft")),
                strings(in.get("special_options")), strings(in.get("processing_items")),
                in.get("is_shaped") instanceof Boolean b ? b : null);
        CuttingHeightCalculator.Result result = CuttingHeightCalculator.compute(config, vars);

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("source", source);
        data.put("base", result.base());
        data.put("cutting_height", result.cuttingHeight());
        data.put("rounding", Map.of("mode", result.mode(), "digits", result.digits()));
        data.put("hits", CuttingHeightCalculator.toRows(result.hits()));
        List<Map<String, Object>> misses = new ArrayList<>();
        for (CuttingHeightCalculator.Miss miss : result.misses()) {
            Map<String, Object> row2 = new LinkedHashMap<>();
            row2.put("key", miss.key());
            row2.put("name", miss.name());
            row2.put("reason", miss.reason());
            misses.add(row2);
        }
        data.put("misses", misses);
        return data;
    }

    /**
     * 校验 + 归一（数值统一成 {@link BigDecimal}），失败 ⇒ 422 带**逐条**理由。
     *
     * <p>规则：配置键必须**恰好**是 {@link #CONFIG_KEYS}（全量替换）· 项键必须在 {@link #ITEM_KEYS} 内 ·
     * {@code key}/{@code name} 非空且 {@code key} 不重复 · {@code value} 允许 {@code null}
     * （= 壁达的「画线」那种**有项无值**）但非空时必须 &ge;0 且 ≤ 10 · {@code direction} ∈ {add,subtract} ·
     * {@code hit} 与 {@code hit_expr} **恰好给一个**（两个都填 = 两套判据会漂） ·
     * {@code hit.trigger_kind} 在闭词表内、{@code trigger_value} 非空、{@code position} 在部位表内或 null ·
     * {@code rounding.mode} ∈ {half_up,down,up}、{@code digits} ∈ 0..3。</p>
     */
    Map<String, Object> validate(Map<String, Object> body) {
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        Map<String, Object> in = body == null ? Map.of() : body;

        for (String key : in.keySet()) {
            if (!CONFIG_KEYS.contains(key)) {
                details.add(BusinessException.detail(key,
                        "不是裁高配置键（拼错的键会被静默忽略 ⇒ 商家以为改了却没改；合法键：" + CONFIG_KEYS + "）"));
            }
        }
        for (String key : CONFIG_KEYS) {
            if (!in.containsKey(key)) {
                details.add(BusinessException.detail(key,
                        "缺少配置键（PUT 是**全量替换**：缺键会让该口径静默回到默认值 ⇒ 显式拒绝，不静默回退）"));
            }
        }

        List<Map<String, Object>> items = new ArrayList<>();
        Object rawItems = in.get("items");
        if (rawItems != null) {
            if (!(rawItems instanceof List<?> list)) {
                details.add(BusinessException.detail("items", "必须是数组"));
            } else {
                Set<String> seenKeys = new HashSet<>();
                int index = 0;
                for (Object raw : list) {
                    String field = "items[" + index + "]";
                    if (raw instanceof Map<?, ?> map) {
                        @SuppressWarnings("unchecked")
                        Map<String, Object> item = validateItem((Map<String, Object>) map, field, details, seenKeys);
                        if (item != null) {
                            items.add(item);
                        }
                    } else {
                        details.add(BusinessException.detail(field, "必须是对象"));
                    }
                    index++;
                }
            }
        }

        Map<String, Object> rounding = null;
        Object rawRounding = in.get("rounding");
        if (rawRounding != null) {
            if (!(rawRounding instanceof Map<?, ?> map)) {
                details.add(BusinessException.detail("rounding", "必须是对象 {mode, digits}"));
            } else {
                Object mode = map.get("mode");
                Object digits = map.get("digits");
                String modeText = text(mode);
                if (modeText == null || !ROUNDING_MODES.contains(modeText)) {
                    details.add(BusinessException.detail("rounding.mode",
                            "必须是 " + ROUNDING_MODES + " 之一，收到 " + mode));
                }
                BigDecimal digitValue = decimal(digits);
                if (digitValue == null || digitValue.signum() < 0 || digitValue.compareTo(new BigDecimal("3")) > 0
                        || digitValue.stripTrailingZeros().scale() > 0) {
                    details.add(BusinessException.detail("rounding.digits", "必须是 0~3 的整数，收到 " + digits));
                }
                if (details.stream().noneMatch(d -> d.getField().startsWith("rounding"))) {
                    rounding = new LinkedHashMap<>();
                    rounding.put("mode", modeText);
                    rounding.put("digits", digitValue.intValueExact());
                }
            }
        }

        if (!details.isEmpty()) {
            throw BusinessException.validationError("裁高配置有 " + details.size() + " 处不合法", details,
                    "按逐条理由修正后重试；本接口是**全量替换**，没有部分更新");
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", items);
        out.put("rounding", rounding);
        return out;
    }

    private Map<String, Object> validateItem(Map<String, Object> raw, String field,
                                             List<ApiResponse.ErrorDetail> details, Set<String> seenKeys) {
        for (String key : raw.keySet()) {
            if (!ITEM_KEYS.contains(key)) {
                details.add(BusinessException.detail(field + "." + key, "不是增量项键；合法键：" + ITEM_KEYS));
            }
        }
        String key = text(raw.get("key"));
        String name = text(raw.get("name"));
        if (key == null) {
            details.add(BusinessException.detail(field + ".key", "缺少项标识（稳定键，改它会与历史配置脱钩）"));
        } else if (!seenKeys.add(key)) {
            details.add(BusinessException.detail(field + ".key", "项标识重复：" + key + "（同一份档案里 key 必须唯一）"));
        }
        if (name == null) {
            details.add(BusinessException.detail(field + ".name", "缺少项名称"));
        }

        BigDecimal value = decimal(raw.get("value"));
        boolean valueGiven = raw.get("value") != null;
        if (valueGiven && value == null) {
            details.add(BusinessException.detail(field + ".value", "必须是数字，收到 " + raw.get("value")));
        } else if (value != null && (value.signum() < 0 || value.compareTo(MAX_ITEM_VALUE) > 0)) {
            details.add(BusinessException.detail(field + ".value",
                    "必须在 0 ~ " + MAX_ITEM_VALUE + " 米之间（多半是单位填错：mm/cm 当成米）"));
        }

        String direction = text(raw.get("direction"));
        if (direction == null) {
            direction = "add";
        } else if (!DIRECTIONS.contains(direction)) {
            details.add(BusinessException.detail(field + ".direction", "必须是 " + DIRECTIONS + " 之一"));
        }

        Object hit = raw.get("hit");
        String hitExpr = text(raw.get("hit_expr"));
        if (hit != null && hitExpr != null) {
            details.add(BusinessException.detail(field + ".hit_expr",
                    "hit 与 hit_expr 只能给一个（两个判据并存 ⇒ 迟早漂，判定二义）"));
        } else if (hit == null && hitExpr == null) {
            details.add(BusinessException.detail(field + ".hit", "缺少命中口径（hit 或 hit_expr 必须给一个）"));
        }

        Map<String, Object> normalizedHit = null;
        if (hit != null) {
            if (!(hit instanceof Map<?, ?> map)) {
                details.add(BusinessException.detail(field + ".hit", "必须是对象 {trigger_kind, trigger_value, position}"));
            } else {
                for (Object k : map.keySet()) {
                    if (!HIT_KEYS.contains(String.valueOf(k))) {
                        details.add(BusinessException.detail(field + ".hit." + k, "不是命中口径键；合法键：" + HIT_KEYS));
                    }
                }
                String kind = text(map.get("trigger_kind"));
                String triggerValue = text(map.get("trigger_value"));
                String hitPosition = text(map.get("position"));
                if (kind == null || !CuttingHeightCalculator.TRIGGER_KINDS.contains(kind)) {
                    details.add(BusinessException.detail(field + ".hit.trigger_kind",
                            "必须是 " + CuttingHeightCalculator.TRIGGER_KINDS + " 之一（与 production_route_rules 同词表），收到 " + map.get("trigger_kind")));
                }
                if (triggerValue == null) {
                    details.add(BusinessException.detail(field + ".hit.trigger_value",
                            "缺少触发值（**逐字**等于订单上的特殊选项名 / 工艺名 / 加工项名；写错一个字就不命中）"));
                }
                if (hitPosition != null && !CuttingHeightCalculator.POSITIONS.contains(hitPosition)) {
                    details.add(BusinessException.detail(field + ".hit.position",
                            "必须是 " + CuttingHeightCalculator.POSITIONS + " 之一或 null（= 不限部位）"));
                }
                if (kind != null && triggerValue != null) {
                    normalizedHit = new LinkedHashMap<>();
                    normalizedHit.put("trigger_kind", kind);
                    normalizedHit.put("trigger_value", triggerValue);
                    normalizedHit.put("position", hitPosition);
                }
            }
        }

        Map<String, Object> item = new LinkedHashMap<>();
        item.put("key", key);
        item.put("name", name);
        item.put("value", value);
        item.put("direction", direction);
        item.put("height_join", Boolean.TRUE.equals(raw.get("height_join")));
        item.put("hit", normalizedHit);
        item.put("hit_expr", hitExpr);
        item.put("enabled", !Boolean.FALSE.equals(raw.get("enabled")));
        item.put("order", intOf(raw.get("order")));
        return item;
    }

    private static void apply(CuttingHeightConfig row, Map<String, Object> config) {
        row.setItems(config.get("items"));
        row.setRounding(config.get("rounding"));
    }

    private static Map<String, Object> response(String source, Map<String, Object> config) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("source", source);
        data.put("config", config);
        return data;
    }

    private static int itemCount(Map<String, Object> config) {
        Object items = config.get("items");
        return items instanceof List<?> list ? list.size() : 0;
    }

    private static void requireTenant(Long tenantId) {
        if (tenantId == null) {
            throw BusinessException.tenantInvalid();
        }
    }

    private static String text(Object raw) {
        if (raw == null) {
            return null;
        }
        String s = String.valueOf(raw).trim();
        return s.isEmpty() ? null : s;
    }

    private static BigDecimal decimal(Object raw) {
        if (raw == null) {
            return null;
        }
        if (raw instanceof BigDecimal bd) {
            return bd;
        }
        if (raw instanceof Number n) {
            return new BigDecimal(n.toString());
        }
        try {
            return new BigDecimal(String.valueOf(raw).trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static int intOf(Object raw) {
        try {
            return Integer.parseInt(String.valueOf(raw).trim());
        } catch (RuntimeException e) {
            return 0;
        }
    }

    private static List<String> strings(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<String> out = new ArrayList<>(list.size());
        for (Object item : list) {
            String text = text(item);
            if (text != null && !out.contains(text)) {
                out.add(text);
            }
        }
        return out;
    }
}
