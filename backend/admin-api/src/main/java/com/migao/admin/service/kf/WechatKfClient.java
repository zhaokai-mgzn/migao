package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 微信客服服务端 API 客户端（issue #9171）。
 *
 * <p>只做「HTTP + JSON + errcode 判定」，不做 token 缓存、不做重试、不碰业务。
 * 超时：connect 2s / read 8s（与设计 §5.2 的 AI 调用预算对齐）。</p>
 */
public class WechatKfClient {

    static final String DEFAULT_BASE_URL = "https://qyapi.weixin.qq.com";

    private final RestTemplate restTemplate;
    private final ObjectMapper objectMapper;
    private final String baseUrl;

    public WechatKfClient() {
        this(defaultRestTemplate(), new ObjectMapper(), DEFAULT_BASE_URL);
    }

    WechatKfClient(RestTemplate restTemplate, ObjectMapper objectMapper, String baseUrl) {
        this.restTemplate = restTemplate;
        this.objectMapper = objectMapper;
        this.baseUrl = baseUrl;
    }

    /** 自建应用换 access_token（第三方应用走 suite_access_token + permanent_code，另行封装）。 */
    public String getAccessToken(String corpId, String corpSecret) {
        String url = baseUrl + "/cgi-bin/gettoken?corpid={corpId}&corpsecret={secret}";
        JsonNode node = get(url, corpId, corpSecret);
        check(node);
        String token = node.path("access_token").asText(null);
        if (token == null || token.isBlank()) {
            throw new KfApiException(-1, "gettoken 未返回 access_token");
        }
        return token;
    }

    /** 增量拉取消息；has_more 的循环由调用方负责（空 msg_list 也要推进，见设计 §5）。 */
    public JsonNode syncMsg(String accessToken, String openKfId, String cursor, String token, int limit) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("open_kfid", openKfId);
        if (cursor != null && !cursor.isBlank()) {
            body.put("cursor", cursor);
        }
        if (token != null && !token.isBlank()) {
            body.put("token", token);
        }
        body.put("limit", limit);
        JsonNode node = post(accessToken, "/cgi-bin/kf/sync_msg", body);
        check(node);
        return node;
    }

    /** 发送文本；msgid 是幂等键（≤32B，客服账号内唯一），由调用方生成。 */
    public String sendText(String accessToken, String openKfId, String externalUserId,
                           String content, String msgId) {
        Map<String, Object> text = new LinkedHashMap<>();
        text.put("content", content);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("touser", externalUserId);
        body.put("open_kfid", openKfId);
        body.put("msgid", msgId);
        body.put("msgtype", "text");
        body.put("text", text);
        JsonNode node = post(accessToken, "/cgi-bin/kf/send_msg", body);
        check(node);
        return node.path("msgid").asText(msgId);
    }

    /** 变更会话状态：target 2=接待池 / 3=人工 / 4=结束（1 官方未文档化，MVP 不用）。 */
    public JsonNode transServiceState(String accessToken, String openKfId, String externalUserId, int target) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("open_kfid", openKfId);
        body.put("external_userid", externalUserId);
        body.put("service_state", target);
        JsonNode node = post(accessToken, "/cgi-bin/kf/service_state/trans", body);
        check(node);
        return node;
    }

    /** 查询会话状态：0 未处理 / 1 智能助手 / 2 排队 / 3 人工 / 4 结束。 */
    public JsonNode getServiceState(String accessToken, String openKfId, String externalUserId) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("open_kfid", openKfId);
        body.put("external_userid", externalUserId);
        JsonNode node = post(accessToken, "/cgi-bin/kf/service_state/get", body);
        check(node);
        return node;
    }

    private JsonNode get(String url, Object... vars) {
        String raw = restTemplate.getForObject(url, String.class, vars);
        return parse(raw);
    }

    private JsonNode post(String accessToken, String path, Map<String, Object> body) {
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            String json = objectMapper.writeValueAsString(body);
            String raw = restTemplate.postForObject(baseUrl + path + "?access_token={token}",
                    new HttpEntity<>(json, headers), String.class, accessToken);
            return parse(raw);
        } catch (KfApiException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException("调用微信客服接口失败: " + path, e);
        }
    }

    private JsonNode parse(String raw) {
        try {
            return objectMapper.readTree(raw == null ? "{}" : raw);
        } catch (Exception e) {
            throw new IllegalStateException("微信客服返回非 JSON", e);
        }
    }

    private static void check(JsonNode node) {
        int errcode = node.path("errcode").asInt(0);
        if (errcode != 0) {
            throw new KfApiException(errcode, node.path("errmsg").asText(""));
        }
    }

    private static RestTemplate defaultRestTemplate() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(2000);
        factory.setReadTimeout(8000);
        return new RestTemplate(factory);
    }
}
