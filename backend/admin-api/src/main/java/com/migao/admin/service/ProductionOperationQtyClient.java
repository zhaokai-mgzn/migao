package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.exception.BusinessException;
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
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 工序应做数量客户端（issue #4208 Java 接线）
 * 调 ai-agent 内部端点 {@code POST /api/internal/production/operation-qty}（Service Token 认证）。
 *
 * <p>真值源：{@code docs/curtain-production-rules.md} §3「工序实例的应做数量 = 算料引擎输出
 * （折数/孔数/用料米数/幅数），报工只确认，不手工心算」。算料口径的唯一实现是 ai-agent 的
 * {@code app/production/routing.py::_qty_for} —— **Java 侧不复制第二份算料逻辑**，
 * 本类只做「问 + 取」。</p>
 *
 * <p><b>降级策略 = fail-closed</b>（issue #4208 冻结契约 + {@code application.yml} 既有口径）：
 * 服务不可达 / 未配置 token / 外壳 {@code success != true} / 响应与请求不同构 ⇒ 抛
 * {@link BusinessException}（422 + 可行动 suggestion），由调用方中止生成加工单。
 * <b>绝不静默回退订单数量</b> —— 那正是本单要治的缺陷（「韩褶-布」显示 3 折）。</p>
 */
@Slf4j
@Component
public class ProductionOperationQtyClient {

    private static final String QTY_PATH = "/api/internal/production/operation-qty";
    private static final int CONNECT_TIMEOUT_MS = 3_000;
    private static final int READ_TIMEOUT_MS = 10_000;

    /** fail-closed 错误码（可见位置同 {@link ProcessingOrderService#ERR_ROUTING_NOT_FOUND}）。 */
    public static final String ERR_OPERATION_QTY_UNAVAILABLE = "PRODUCTION_OPERATION_QTY_UNAVAILABLE";

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final RestTemplate restTemplate;

    @Value("${ai-agent.base-url:http://localhost:8000}")
    private String baseUrl;

    @Value("${ai-agent.service-token:}")
    private String serviceToken;

    public ProductionOperationQtyClient() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(CONNECT_TIMEOUT_MS);
        factory.setReadTimeout(READ_TIMEOUT_MS);
        this.restTemplate = new RestTemplate(factory);
    }

    /** 仅供测试注入 MockRestTemplate */
    ProductionOperationQtyClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    /**
     * 逐部位解析应做数量。
     *
     * @param positions 请求体里的 {@code positions}（{@code {position_name, operations[], calc_info}}），
     *                  顺序即返回顺序（端点是纯映射，不重排）
     * @return 与入参**同序等长**的解析结果；任一条不成立 ⇒ fail-closed 抛错（不返回部分结果）
     */
    @SuppressWarnings("unchecked")
    public List<PositionQty> resolve(List<Map<String, Object>> positions) {
        if (positions == null || positions.isEmpty()) {
            return List.of();
        }
        String url = endpoint();
        if (!StringUtils.hasText(serviceToken)) {
            throw unavailable(url, "未配置 ai-agent.service-token", null);
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("X-Service-Token", serviceToken);

            ResponseEntity<String> response = restTemplate.exchange(
                    url, HttpMethod.POST, new HttpEntity<>(Map.of("positions", positions), headers), String.class);

            JsonNode root = objectMapper.readTree(response.getBody());
            if (root == null || !root.path("success").asBoolean(false)) {
                log.error("算料端点返回失败，生成加工单中止（不回退订单数量）: url={}, status={}, body={}",
                        url, response.getStatusCode(), response.getBody());
                throw unavailable(url, "算料端点返回 success != true", null);
            }
            JsonNode data = root.path("data").path("positions");
            if (!data.isArray() || data.size() != positions.size()) {
                log.error("算料端点响应与请求不同构，生成加工单中止: url={}, 请求 {} 个部位，响应 {}",
                        url, positions.size(), data.isArray() ? data.size() : -1);
                throw unavailable(url, "算料端点响应缺少 data.positions 或条数与请求不符", null);
            }
            List<PositionQty> result = new ArrayList<>(data.size());
            for (JsonNode position : data) {
                result.add(new PositionQty(
                        position.path("position_name").asText(null),
                        decimals(position.path("qty_by_operation")),
                        strings(position.path("qty_source_by_operation"))));
            }
            return result;
        } catch (BusinessException e) {
            throw e; // fail-closed 原样上抛（不吞、不降级）
        } catch (Exception e) {
            log.error("算料端点不可达，生成加工单中止（不回退订单数量）: url={}, err={}", url, e.getMessage());
            throw unavailable(url, e.getMessage(), e);
        }
    }

    private String endpoint() {
        return (StringUtils.hasText(baseUrl) ? baseUrl : "http://localhost:8000")
                .trim().replaceAll("/+$", "") + QTY_PATH;
    }

    private BusinessException unavailable(String url, String reason, Exception cause) {
        return new BusinessException(ERR_OPERATION_QTY_UNAVAILABLE,
                "算料服务（ai-agent）不可用，无法解析工序应做数量，已中止生成加工单（不回退订单数量）：" + reason,
                422,
                "请确认 ai-agent-service 已启动、且 ai-agent.base-url / ai-agent.service-token 配置正确"
                        + "（当前服务地址 " + url + "）；确认后重新生成加工单。"
                        + "应做数量必须来自算料引擎（真值源 §3），系统不会用订单数量顶替。");
    }

    private static Map<String, BigDecimal> decimals(JsonNode node) {
        Map<String, BigDecimal> values = new LinkedHashMap<>();
        node.fields().forEachRemaining(entry ->
                values.put(entry.getKey(), entry.getValue().decimalValue()));
        return values;
    }

    private static Map<String, String> strings(JsonNode node) {
        Map<String, String> values = new LinkedHashMap<>();
        node.fields().forEachRemaining(entry ->
                values.put(entry.getKey(), entry.getValue().asText()));
        return values;
    }

    /**
     * 单个部位的解析结果。
     *
     * @param positionName 部位名（端点原样回传）
     * @param qtyByOperation 工序名 → 应做数量（算料引擎输出，缺键兜底 1 —— 兜底在端点侧做，本类不猜）
     * @param qtySourceByOperation 工序名 → 口径来源（键名 = 算料输出 / {@code <键名>_x6} = 有依据的估算 /
     *                             {@code fallback} = 真兜底）
     */
    public record PositionQty(String positionName,
                              Map<String, BigDecimal> qtyByOperation,
                              Map<String, String> qtySourceByOperation) {
    }
}
