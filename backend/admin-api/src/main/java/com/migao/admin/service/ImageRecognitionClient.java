package com.migao.admin.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
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

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 图片识别客户端（issue #5321 包 1 · 页面快通道）
 * 调 ai-agent 内部端点 {@code POST /api/internal/vision/recognize}（Service Token 认证）。
 *
 * <p><b>为什么走内部端点而不是让 admin-web 直连 ai-agent</b>：与 {@link CraftCalcClient} /
 * {@link BriefingGenerateClient} / {@link KnowledgeDistillClient} 同一条既有范式 ——
 * 商家侧只认 admin-api（JWT + 权限码 + 租户上下文），AI 能力一律由 admin-api 用
 * {@code X-Service-Token} 反调 ai-agent。<b>不另立第二套内部调用约定</b>。</p>
 *
 * <p><b>单一真值</b>：字段 schema、消歧规则、{@code [图片识别]} 标注、vision 调用全在
 * ai-agent 的 {@code backend/ai-agent-service/app/vision/}；本类只做「问 + 取 + 原样搬运」
 * —— Java 侧<b>不复制第二份字段表、不做第二次消歧</b>（那正是「一套字段两个页面填」的形态）。</p>
 *
 * <p><b>降级策略</b>：能区分「没认出来」与「端点没说」两类，且**只有后者**算故障：</p>
 * <ul>
 *   <li>{@code success=true} + {@code data.degraded=true} ⇒ <b>正常返回</b>（vision 失败 / 一格都没
 *       认出来是**合法结果**，前端据此提示「请手工填写或换一张更清晰的图片」）；</li>
 *   <li>不可达 / 未配置 token / 外壳 {@code success != true} / 响应缺 {@code data.fields} 数组
 *       ⇒ 抛 {@link BusinessException}（422 + 可行动 suggestion）。
 *       「端点没说」静默读成「没认出来」会让商家以为图不行而反复重拍，故必须可区分。</li>
 * </ul>
 *
 * <p>🔴 <b>不落库</b>：本类只读，不碰任何 Mapper / Service 写路径；
 * 识别结果只填表，<b>提交永远是人的动作</b>。</p>
 */
@Slf4j
@Component
public class ImageRecognitionClient {

    private static final String RECOGNIZE_PATH = "/api/internal/vision/recognize";
    private static final String INTERPRET_PATH = "/api/internal/vision/interpret";
    private static final int CONNECT_TIMEOUT_MS = 3_000;

    /** 视觉调用比纯算料慢（要抓图 + 多模态推理）⇒ 读超时给足（ai-agent 侧上限 60s）。 */
    static final int RECOGNIZE_READ_TIMEOUT_MS = 75_000;

    /**
     * 推理端点的读超时（issue #6367 包 P2）—— <b>比 recognize 宽</b>，理由与判据：
     *
     * <p>上游 {@code /api/internal/vision/interpret} = **vision 一次 + 黄金策主模型文本推理一次**
     * （用户裁定「推理复用黄金策主模型」，见 issue #6367 的收口），是同一条链上**两次串行**的
     * 远端等待；而 {@code recognize} = 一次 vision。⇒ 若沿用 75s，长尾会在**上游还在正常干活**时
     * 被本侧掐断，对外表现为「图片识别服务不可用」——商家看到的是**假故障**，且会反复重拍。</p>
     *
     * <p>为什么取 <b>120s</b>：① 主模型一次完整推理的耗时量级与简报/长文生成同档
     * （同族 AI 端点读超时 = 简报 60s / recognize 75s）⇒ 75s + 一次推理的余量约 45s，
     * 落在同档上限附近；② **不无限等**：ai-agent 侧单次请求本身有上限，本侧再宽也只是把
     * 「网关先回 504」这个情况暴露成可行动错误（本类统一映射为 422 + suggestion），不会把请求拖成黑洞。
     * ③ 判据 = {@code ImageRecognitionInterpretTest#interpretTimeoutIsWiderThanRecognizeButBounded}
     * （比 recognize 严丝合缝地宽、且 ≤ 180s）；改小到 ≤ 75s 或改成「无限等」都会红。</p>
     */
    static final int INTERPRET_READ_TIMEOUT_MS = 120_000;

    /** fail-closed 错误码（可见位置同 {@link CraftCalcClient#ERR_CRAFT_CALC_UNAVAILABLE}）。 */
    public static final String ERR_IMAGE_RECOGNITION_UNAVAILABLE = "IMAGE_RECOGNITION_UNAVAILABLE";

    /** 同页填充计划的组件名（与 ai-agent {@code app/vision/deep_channel.py::PAGE_FILL_COMPONENT} 同源）。 */
    private static final String PAGE_FILL_COMPONENT = "page_fill";

    private final ObjectMapper objectMapper = new ObjectMapper();
    /** 识别（一次 vision）用；超时 {@link #RECOGNIZE_READ_TIMEOUT_MS}。 */
    private final RestTemplate restTemplate;
    /** 推理（vision + 主模型一次）用；超时 {@link #INTERPRET_READ_TIMEOUT_MS}（更宽，理由见该常量）。 */
    private final RestTemplate interpretRestTemplate;

    @Value("${ai-agent.base-url:http://localhost:8000}")
    private String baseUrl;

    @Value("${ai-agent.service-token:}")
    private String serviceToken;

    public ImageRecognitionClient() {
        this.restTemplate = new RestTemplate(factory(RECOGNIZE_READ_TIMEOUT_MS));
        this.interpretRestTemplate = new RestTemplate(factory(INTERPRET_READ_TIMEOUT_MS));
    }

    private static SimpleClientHttpRequestFactory factory(int readTimeoutMs) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(CONNECT_TIMEOUT_MS);
        factory.setReadTimeout(readTimeoutMs);
        return factory;
    }

    /**
     * 仅供测试注入 MockRestTemplate。
     *
     * <p>两个参数**必须分开传**（不是冗余）：它们是两条超时不同的链路，合成一个会让
     * 「推理端超时更宽」这件事变得不可测（也就会悄悄退化回 75s）。</p>
     */
    ImageRecognitionClient(RestTemplate restTemplate, RestTemplate interpretRestTemplate) {
        this.restTemplate = restTemplate;
        this.interpretRestTemplate = interpretRestTemplate;
    }

    /**
     * 识别图片 → 结构化字段（**不落库**）。
     *
     * @param targetType {@code product} / {@code order}（调用方已校验取值）
     * @param images     已上传的图片 URL 列表（原样透传；无效 URL 由 ai-agent 侧统一过滤 + CDN 重写，
     *                   Java 侧不预先筛 —— 两处各筛一次必然漂移）
     * @return 识别结果（字段表 + 逐字段来源标注 + 降级标记），**原样搬运**
     * @throws BusinessException 422：端点不可达 / 未配置 token / 外壳失败 / 响应缺 {@code data.fields}
     */
    public ImageRecognitionResult recognize(String targetType, List<String> images) {
        String url = endpoint();
        if (!StringUtils.hasText(serviceToken)) {
            throw unavailable(url, "未配置 ai-agent.service-token", null);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        // 租户上下文随请求带给 ai-agent（与其它内部端点同口径：无租户上下文 ⇒ 不编造，见下）
        Long tenantId = TenantContext.getTenantId();
        payload.put("tenant_id", tenantId == null ? 0L : tenantId);
        payload.put("target_type", targetType);
        payload.put("images", images == null ? List.of() : images);

        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("X-Service-Token", serviceToken);

            ResponseEntity<String> response = restTemplate.exchange(
                    url, HttpMethod.POST, new HttpEntity<>(payload, headers), String.class);

            JsonNode root = objectMapper.readTree(response.getBody());
            if (root == null || !root.path("success").asBoolean(false)) {
                log.error("图片识别端点返回失败: url={}, status={}, body={}",
                        url, response.getStatusCode(), response.getBody());
                throw unavailable(url, "图片识别端点返回 success != true", null);
            }
            JsonNode data = root.path("data");
            JsonNode fields = data.path("fields");
            if (!fields.isArray()) {
                log.error("图片识别端点响应缺 data.fields，拒绝把「端点没说」当成「没认出来」: url={}, body={}",
                        url, response.getBody());
                throw unavailable(url, "图片识别端点响应缺少 data.fields 数组（空数组 = 没认出来，键必须存在）", null);
            }
            // 字段对象**原样搬运**（键名即契约：key/label/value/source/reason/reference）——
            // Java 侧不重建字段表，`[图片识别]` 标注由 ai-agent 给（第二份标注 = 会漂的第二份口径）。
            // `reference` = 图上抄到但**没采纳**的原文（issue #6529，只有订单侧 `items` 会带）：前端只用它
            // 查目录 / 展示，**绝不据此填表** —— 本侧同样只搬不改。
            List<Map<String, Object>> passthrough = new ArrayList<>();
            for (JsonNode field : fields) {
                @SuppressWarnings("unchecked")
                Map<String, Object> mapped = objectMapper.convertValue(field, Map.class);
                passthrough.add(mapped);
            }
            return new ImageRecognitionResult(
                    data.path("target_type").asText(targetType),
                    passthrough,
                    data.path("degraded").asBoolean(false));
        } catch (BusinessException e) {
            throw e; // fail-closed 原样上抛（不吞、不降级）
        } catch (Exception e) {
            log.error("图片识别端点不可达: url={}, err={}", url, e.getMessage());
            throw unavailable(url, e.getMessage(), e);
        }
    }

    /**
     * 识别 + 黄金策推理 → 同页填充计划（**不落库**；issue #6367 包 P2）。
     *
     * <p>与 {@link #recognize} <b>同族</b>：同一个 client、同一套 service token 与 {@code baseUrl}、
     * 同一套 fail-closed 判定口径；差别只有两处，都必须显式可见：① 上游路径
     * {@code /api/internal/vision/interpret}；② 读超时更宽（{@link #INTERPRET_READ_TIMEOUT_MS}，
     * 因为多了一次主模型推理）。</p>
     *
     * @param targetType {@code product} / {@code order}（调用方已校验取值）
     * @param images     已上传的图片 URL 列表（原样透传，口径同 recognize）
     * @param hint       商家补充提示（**可选**）。空/空白 ⇒ <b>请求体里不出现 {@code hint} 键</b>：
     *                   上游把 {@code hint} 当一次真实文本提示，发空串会白烧一次推理且污染输入。
     * @return page_fill 计划（<b>原样搬运</b>：字段表、{@code [米宝解读]} 标注、候选、note 都由 ai-agent 给）
     * @throws BusinessException 422：端点不可达 / 未配置 token / 外壳失败 / 缺 {@code data.fields}
     *                           / {@code component != page_fill}
     */
    public PageFillResult interpret(String targetType, List<String> images, String hint) {
        String url = endpoint(INTERPRET_PATH);
        if (!StringUtils.hasText(serviceToken)) {
            throw unavailable(url, "未配置 ai-agent.service-token", null);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        Long tenantId = TenantContext.getTenantId();
        payload.put("tenant_id", tenantId == null ? 0L : tenantId);
        payload.put("target_type", targetType);
        payload.put("images", images == null ? List.of() : images);
        if (StringUtils.hasText(hint)) {
            payload.put("hint", hint.trim());
        }

        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("X-Service-Token", serviceToken);

            ResponseEntity<String> response = interpretRestTemplate.exchange(
                    url, HttpMethod.POST, new HttpEntity<>(payload, headers), String.class);

            JsonNode root = objectMapper.readTree(response.getBody());
            if (root == null || !root.path("success").asBoolean(false)) {
                log.error("图片推理端点返回失败: url={}, status={}, body={}",
                        url, response.getStatusCode(), response.getBody());
                throw unavailable(url, "图片推理端点返回 success != true", null);
            }
            JsonNode data = root.path("data");
            String component = data.path("component").asText(null);
            JsonNode fields = data.path("fields");
            // 「端点没说」不得静默读成「没推理出来」：缺字段 ⇒ 422（同 recognize 的判据）
            if (!fields.isArray() || !PAGE_FILL_COMPONENT.equals(component)) {
                log.error("图片推理端点响应不是 page_fill 计划，拒绝当成空计划: url={}, component={}, body={}",
                        url, component, response.getBody());
                throw unavailable(url, "图片推理端点响应缺少 data.fields 数组或 component != page_fill"
                        + "（空数组 = 没推理出来，键与组件名必须存在）", null);
            }
            List<Map<String, Object>> passthrough = new ArrayList<>();
            for (JsonNode field : fields) {
                @SuppressWarnings("unchecked")
                Map<String, Object> mapped = objectMapper.convertValue(field, Map.class);
                passthrough.add(mapped);
            }
            return new PageFillResult(component, data.path("target_type").asText(targetType), passthrough);
        } catch (BusinessException e) {
            throw e; // fail-closed 原样上抛（不吞、不降级）
        } catch (Exception e) {
            log.error("图片推理端点不可达/超时: url={}, err={}", url, e.getMessage());
            throw unavailable(url, e.getMessage(), e);
        }
    }

    private String endpoint() {
        return endpoint(RECOGNIZE_PATH);
    }

    private String endpoint(String path) {
        return (StringUtils.hasText(baseUrl) ? baseUrl : "http://localhost:8000")
                .trim().replaceAll("/+$", "") + path;
    }

    private BusinessException unavailable(String url, String reason, Exception cause) {
        BusinessException e = new BusinessException(ERR_IMAGE_RECOGNITION_UNAVAILABLE,
                "图片识别服务（ai-agent）不可用，本次识别已中止：" + reason,
                422,
                "请确认 ai-agent-service 已启动、且 ai-agent.base-url / ai-agent.service-token 配置正确"
                        + "（当前服务地址 " + url + "）；也可以直接手工填写表单 —— "
                        + "识别只是预填，不填也能提交。");
        if (cause != null) {
            e.initCause(cause);
        }
        return e;
    }

    /**
     * 识别结果。
     *
     * @param targetType 识别 target（回显 ai-agent 的值；缺省回落为请求值）
     * @param fields     字段表：每项 {@code {key, label, value, source, reason}}。
     *                   {@code value} 非空 ⇒ {@code source == "[图片识别]"}；
     *                   {@code value == null} ⇒ 该格**故意留空**、{@code reason} 说明原因。
     *                   <b>原样搬运</b>，Java 侧不改写。
     * @param degraded   true = vision 失败 / 一格都没认出来（**合法结果**，不是错误）；
     *                   前端据此提示「请手工填写或换一张更清晰的图片」。
     */
    public record ImageRecognitionResult(String targetType,
                                         List<Map<String, Object>> fields,
                                         boolean degraded) {
    }

    /**
     * 推理结果 = **page_fill 计划**（issue #6367 包 P2，原样搬运 ai-agent 的
     * {@code build_page_fill()} 输出）。
     *
     * @param component  恒 {@code page_fill}（形状守卫：不认得的组件名 ⇒ 422，不当成计划用）
     * @param targetType 识别 target（回显 ai-agent 的值；缺省回落为请求值）
     * @param fields     字段表：每项 {@code {key, label, value, source, reason, candidates, note, note_source}}。
     *                   {@code source} ∈ {@code {"[图片识别]", "[米宝解读]"}}（来源可区分是硬要求）；
     *                   空列表 = 一格都没推理出来（**合法结果**，前端提示手工填写）。
     */
    public record PageFillResult(String component,
                                 String targetType,
                                 List<Map<String, Object>> fields) {
    }
}