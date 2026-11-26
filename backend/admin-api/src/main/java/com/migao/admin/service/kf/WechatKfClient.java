package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
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

    /** 客服账号列表（接入自检：确认 open_kfid 确实属于这个 corp）。 */
    public JsonNode listAccounts(String accessToken) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("offset", 0);
        body.put("limit", 100);
        JsonNode node = post(accessToken, "/cgi-bin/kf/account/list", body);
        check(node);
        return node;
    }

    /** 生成客服账号链接（「一店一码」：scene_param ≤128B；返回 url，前端转二维码）。 */
    public String createContactWay(String accessToken, String openKfId, String sceneParam) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("open_kfid", openKfId);
        if (sceneParam != null && !sceneParam.isBlank()) {
            body.put("scene_param", sceneParam);
        }
        JsonNode node = post(accessToken, "/cgi-bin/kf/add_contact_way", body);
        check(node);
        String url = node.path("url").asText(null);
        if (url == null || url.isBlank()) {
            throw new KfApiException(-1, "add_contact_way 未返回 url");
        }
        return url;
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

    /**
     * 下载媒体（issue #9200）：`/cgi-bin/media/get` 按 media_id 取二进制。
     *
     * <p>🔴 两条必须分清：**真二进制** 与 **微信的 JSON 错误体**。后者 HTTP 也可能是 200，
     * Content-Type 是 `application/json` —— 当字节直接落盘就会把 `{"errcode":40007}`
     * 存成一张坏图片，而且没有任何东西会红。⇒ 先判 Content-Type，再按 errcode 抛。</p>
     */
    public MediaFile getMedia(String accessToken, String mediaId) {
        if (accessToken == null || accessToken.isBlank()) {
            throw new IllegalArgumentException("access_token 为空");
        }
        if (mediaId == null || mediaId.isBlank()) {
            throw new IllegalArgumentException("media_id 为空");
        }
        String url = baseUrl + "/cgi-bin/media/get?access_token={token}&media_id={mediaId}";
        ResponseEntity<byte[]> resp;
        try {
            resp = restTemplate.exchange(url, HttpMethod.GET, null, byte[].class, accessToken, mediaId);
        } catch (Exception e) {
            throw new IllegalStateException("下载媒体失败: mediaId=" + mediaId, e);
        }
        byte[] body = resp.getBody();
        MediaType contentType = resp.getHeaders().getContentType();
        if (body == null || body.length == 0) {
            throw new KfApiException(-1, "下载媒体返回空响应: mediaId=" + mediaId);
        }
        if (contentType != null && MediaType.APPLICATION_JSON.includes(contentType)) {
            JsonNode err = parse(new String(body, java.nio.charset.StandardCharsets.UTF_8));
            check(err);
            throw new KfApiException(-1, "下载媒体返回 JSON 而非二进制: mediaId=" + mediaId);
        }
        String mime = contentType == null ? "application/octet-stream" : contentType.toString();
        return new MediaFile(body, mime);
    }

    /** 媒体下载结果（字节 + 服务端给的 mime）。 */
    public record MediaFile(byte[] bytes, String mime) {
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
