package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.entity.CraftCalcConfig;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CraftCalcConfigMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestTemplate;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 算料试算客户端（issue #4421 Java 接线）
 * 调 ai-agent 内部端点 {@code POST /api/internal/production/craft-calc}（Service Token 认证）。
 *
 * <p>真值源：{@code docs/curtain-fabric-quote-rules.md} §8（韩折折数法）/ §8.1（两种用料计算方法）/ §9（工艺档位）/
 * §11（算例）。用料口径 = 用户 2026-09-19 裁定：**逐片**（每片宽 = 成品宽 ÷ 开数，总用料 = 每片用料 × 开数），
 * 用料米数**向上进位到 0.1**；公式**由工艺推导**（韩褶 ⇒ 韩折公式＝折数法；打孔 ⇒ 褶倍数公式＝倍数法，默认 2 倍），
 * `formula` 入参为显式覆盖。**每折吃布随款式/拼次变化**（单色 0.25 / 拼色·拼1次 0.65 / 拼色·拼2次 1.2 米，纸质速查表表头）。
 * 算料口径的唯一实现是 ai-agent 的 {@code app/tools/curtain_calc.py} ——
 * <b>Java 侧不复制第二份算料逻辑</b>（同 {@link ProductionOperationQtyClient} 口径），
 * 本类只做「问 + 取」。<b>公式串 {@code formula_text} 亦由 ai-agent 后端产出</b>，
 * 本类只搬运 —— Java / TS 侧自拼公式 = 第二份算料逻辑。</p>
 *
 * <p><b>租户级配置注入（issue #4528 = 包 E）</b>：算料请求随带本租户的
 * {@code craft_calc_configs} 配置（{@code config} 键）；<b>本租户没有配置行 ⇒ 不传</b>
 * （算料引擎用它的默认值 ⇒ 未配置租户的结果与包 D 合并后**逐值一致**）。
 * 默认值/公式的唯一实现仍在 {@code curtain_calc.py} —— 本类只做「问 + 取 + 带上配置」。</p>
 *
 * <p><b>降级策略 = fail-closed</b>（同 {@code ProductionOperationQtyClient}）：
 * 服务不可达 / 未配置 token / 外壳 {@code success != true} / 响应缺 {@code fabric_meters}
 * 或 {@code formula_text} ⇒ 抛 {@link BusinessException}（422 + 可行动 suggestion）。
 * <b>绝不静默给 0 米或空公式</b> —— 那会让商家按 0 下单。</p>
 */
@Slf4j
@Component
public class CraftCalcClient {

    private static final String CALC_PATH = "/api/internal/production/craft-calc";
    /** 引擎**默认**配置（issue #4528）：缺配置行的租户由它给值（Java 侧不抄第二份默认值）。 */
    private static final String DEFAULTS_PATH = "/api/internal/production/craft-calc-config";
    private static final int CONNECT_TIMEOUT_MS = 3_000;
    private static final int READ_TIMEOUT_MS = 10_000;

    /** fail-closed 错误码（可见位置同 {@link ProductionOperationQtyClient#ERR_OPERATION_QTY_UNAVAILABLE}）。 */
    public static final String ERR_CRAFT_CALC_UNAVAILABLE = "CRAFT_CALC_UNAVAILABLE";

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final RestTemplate restTemplate;
    private final CraftCalcConfigMapper craftCalcConfigMapper;

    @Value("${ai-agent.base-url:http://localhost:8000}")
    private String baseUrl;

    @Value("${ai-agent.service-token:}")
    private String serviceToken;

    public CraftCalcClient(CraftCalcConfigMapper craftCalcConfigMapper) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(CONNECT_TIMEOUT_MS);
        factory.setReadTimeout(READ_TIMEOUT_MS);
        this.restTemplate = new RestTemplate(factory);
        this.craftCalcConfigMapper = craftCalcConfigMapper;
    }

    /** 仅供测试注入 MockRestTemplate / MockMapper */
    CraftCalcClient(RestTemplate restTemplate, CraftCalcConfigMapper craftCalcConfigMapper) {
        this.restTemplate = restTemplate;
        this.craftCalcConfigMapper = craftCalcConfigMapper;
    }

    /**
     * 试算用料（不落库）。
     *
     * @param request 请求体（{@code {width, height?, open_count?, mounting?, craft_tier?, style?, formula?, craft?}}）。
     *                <b>原样透传</b>：缺省值由 ai-agent 端点给，本类不替调用方编造（防第二份默认口径）
     * @return 算料结果（数值 + 后端产出的可读公式串）
     */
    public CraftCalcResult calc(Map<String, Object> request) {
        if (request == null || request.get("width") == null) {
            throw unavailable(endpoint(), "缺少必填入参 width（窗宽，米）", null);
        }
        String url = endpoint(CALC_PATH);
        if (!StringUtils.hasText(serviceToken)) {
            throw unavailable(url, "未配置 ai-agent.service-token", null);
        }
        Map<String, Object> payload = withTenantConfig(request);
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("X-Service-Token", serviceToken);

            ResponseEntity<String> response = restTemplate.exchange(
                    url, HttpMethod.POST, new HttpEntity<>(payload, headers), String.class);

            JsonNode root = objectMapper.readTree(response.getBody());
            if (root == null || !root.path("success").asBoolean(false)) {
                log.error("算料试算端点返回失败: url={}, status={}, body={}",
                        url, response.getStatusCode(), response.getBody());
                throw unavailable(url, "算料试算端点返回 success != true", null);
            }
            JsonNode data = root.path("data");
            if (data.path("fabric_meters").isMissingNode() || data.path("fabric_meters").isNull()) {
                log.error("算料试算端点响应缺 data.fabric_meters，拒绝把 0 当用料: url={}, body={}",
                        url, response.getBody());
                throw unavailable(url, "算料试算端点响应缺少 data.fabric_meters（拒绝把 0 当用料）", null);
            }
            if (!StringUtils.hasText(data.path("formula_text").asText(null))) {
                log.error("算料试算端点响应缺 data.formula_text，拒绝自拼公式: url={}, body={}",
                        url, response.getBody());
                throw unavailable(url, "算料试算端点响应缺少 data.formula_text（公式串必须由后端产出，Java 侧不自拼）", null);
            }
            return new CraftCalcResult(
                    data.path("fabric_meters").decimalValue(),
                    data.path("pleat_count").asInt(),
                    data.path("per_panel_pleats").asInt(),
                    data.path("per_fold").decimalValue(),
                    data.path("fullness").decimalValue(),
                    data.path("fullness_actual").isMissingNode() || data.path("fullness_actual").isNull()
                            ? null : data.path("fullness_actual").decimalValue(),
                    data.path("formula_used").asText(null),
                    data.path("formula_text").asText(null),
                    data.path("source").asText(null),
                    data.path("craft_tier").asText(null),
                    data.path("warning").asText(""));
        } catch (BusinessException e) {
            throw e; // fail-closed 原样上抛（不吞、不降级）
        } catch (Exception e) {
            log.error("算料试算端点不可达: url={}, err={}", url, e.getMessage());
            throw unavailable(url, e.getMessage(), e);
        }
    }

    private String endpoint() {
        return endpoint(CALC_PATH);
    }

    private String endpoint(String path) {
        return (StringUtils.hasText(baseUrl) ? baseUrl : "http://localhost:8000")
                .trim().replaceAll("/+$", "") + path;
    }

    /**
     * 算料请求 + **本租户配置**（issue #4528 = 包 E）。
     *
     * <p>三条口径：</p>
     * <ol>
     *   <li><b>缺行 ⇒ 不加 {@code config} 键</b>：算料引擎用它的默认值 ⇒ 未配置租户的算料结果
     *       与包 D 合并后**逐值一致**（把默认值从 Java 侧发过去 = 第二份会漂的默认值）；</li>
     *   <li><b>不改调用方的 map</b>：返回新 map（请求对象可能是上游复用的，就地改会污染它）；</li>
     *   <li><b>无租户上下文 ⇒ 不查不注入</b>（内部/无租户调用保持 #4528 之前的行为，
     *       不猜一个租户去读别人的配置）。</li>
     * </ol>
     */
    private Map<String, Object> withTenantConfig(Map<String, Object> request) {
        Long tenantId = TenantContext.getTenantId();
        if (tenantId == null) {
            return request;
        }
        CraftCalcConfig row = craftCalcConfigMapper.selectActiveByTenant(tenantId);
        if (row == null) {
            return request;
        }
        Map<String, Object> payload = new LinkedHashMap<>(request);
        payload.put("config", row.toConfigMap());
        return payload;
    }

    /**
     * 算料引擎的**默认配置**（issue #4528）—— 缺配置行的租户读面用它 + {@code source='default'}。
     *
     * <p>为什么不在这里写一份默认常量：默认值就是算料口径的一部分，唯一实现在
     * {@code curtain_calc.DEFAULT_CRAFT_CALC_CONFIG}；Java 侧再抄一份 = <b>第二份会漂的默认值</b>
     * （引擎改默认、这里没跟 ⇒ 页面显示的「系统默认值」与实际算料口径不一致）。</p>
     *
     * @throws BusinessException 422（fail-closed）：不可达 / 未配置 token / 外壳失败 / 缺 {@code data.config}
     */
    public Map<String, Object> defaultConfig() {
        String url = endpoint(DEFAULTS_PATH);
        if (!StringUtils.hasText(serviceToken)) {
            throw unavailable(url, "未配置 ai-agent.service-token", null);
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("X-Service-Token", serviceToken);
            ResponseEntity<String> response = restTemplate.exchange(
                    url, HttpMethod.GET, new HttpEntity<>(headers), String.class);
            JsonNode root = objectMapper.readTree(response.getBody());
            if (root == null || !root.path("success").asBoolean(false)) {
                log.error("算料默认配置端点返回失败: url={}, body={}", url, response.getBody());
                throw unavailable(url, "算料默认配置端点返回 success != true", null);
            }
            JsonNode config = root.path("data").path("config");
            if (!config.isObject() || config.isEmpty()) {
                log.error("算料默认配置端点响应缺 data.config，拒绝凭空造默认值: url={}, body={}",
                        url, response.getBody());
                throw unavailable(url, "算料默认配置端点响应缺少 data.config（拒绝凭空造一份默认值）", null);
            }
            return objectMapper.convertValue(config, new com.fasterxml.jackson.core.type.TypeReference<>() {
            });
        } catch (BusinessException e) {
            throw e; // fail-closed 原样上抛（不吞、不降级）
        } catch (Exception e) {
            log.error("算料默认配置端点不可达: url={}, err={}", url, e.getMessage());
            throw unavailable(url, e.getMessage(), e);
        }
    }

    private BusinessException unavailable(String url, String reason, Exception cause) {
        BusinessException e = new BusinessException(ERR_CRAFT_CALC_UNAVAILABLE,
                "算料服务（ai-agent）不可用，无法试算用料米数，已中止本次试算（不给 0 米）：" + reason,
                422,
                "请确认 ai-agent-service 已启动、且 ai-agent.base-url / ai-agent.service-token 配置正确"
                        + "（当前服务地址 " + url + "）；确认后重新试算。"
                        + "用料米数必须来自算料引擎（真值源 §8 折数法），系统不会用 0 或前端自拼的公式顶替。");
        if (cause != null) {
            e.initCause(cause);
        }
        return e;
    }

    /**
     * 试算结果。
     *
     * @param fabricMeters 用料米数（折数法：`每折吃布 × 折数 + 余量`）
     * @param pleatCount 折数（按开数取整后的总折数）
     * @param perPanelPleats 每片折数
     * @param perFold 每折吃布（米）：单色 0.25 / 拼色·拼1次 0.65 / 拼色·拼2次 1.2（用户 2026-09-19 裁定）
     * @param fullness **理论**倍数（档位名义值，standard 2.0 / economy 1.8）
     * @param fullnessActual **实际**倍数（用料 ÷ 窗宽；与理论倍数语义不同，展示取实际值）
     * @param formulaUsed 算式（{@code fixed_height_pleats} / {@code fixed_width_pleats}）
     * @param formulaText 可读公式串（**ai-agent 后端产出**，前端直接展示，不得自拼）
     * @param source 取值来源（{@code formula} / 人工指定 / 客户自报）
     * @param craftTier 工艺档位
     * @param warning 非阻塞告警（如转定宽买高）
     */
    public record CraftCalcResult(BigDecimal fabricMeters,
                                  int pleatCount,
                                  int perPanelPleats,
                                  BigDecimal perFold,
                                  BigDecimal fullness,
                                  BigDecimal fullnessActual,
                                  String formulaUsed,
                                  String formulaText,
                                  String source,
                                  String craftTier,
                                  String warning) {
    }
}
