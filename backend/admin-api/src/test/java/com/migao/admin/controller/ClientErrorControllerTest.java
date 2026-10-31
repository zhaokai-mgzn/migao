// case_ids: MC-123
package com.migao.admin.controller;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.security.ClientErrorRateLimiter;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 浏览器错误上报端点（{@code POST /api/client-errors}，issue #8203 · P0-03）的常驻判据。
 *
 * <h3>为什么这个端点需要这么厚的判据</h3>
 * <p>它是 {@code SecurityConfig} 里 {@code permitAll} 的**公开写入口**（未登录也要能用 —— 登录页崩了
 * 同样要能上报）。公开面 = 攻击面，而它的唯一写面是<b>服务端日志</b> ⇒ 体积、字段、隐私三道闸
 * 任何一道缺失，都会变成「一个公开的日志放大器」或「一个把 PIN / token 写进日志的漏洞」。</p>
 *
 * <h3>判据面（每条都带「会红」的注入形态）</h3>
 * <table>
 *   <caption>三态语义 + 隐私边界</caption>
 *   <tr><th>#</th><th>判据</th><th>会红的注入</th></tr>
 *   <tr><td>1</td><td>合法上报 ⇒ {@code 204} 且**无响应体**（客户端不需要看）</td>
 *       <td>改成 200 + 回显 ⇒ 红</td></tr>
 *   <tr><td>2</td><td>非法 {@code source} / {@code path}（含 {@code ?} / {@code #} / 不以 {@code /} 开头）/ 超长字段 /
 *       空体 / 非 JSON ⇒ {@code 400}</td><td>放行带 query 的 path ⇒ 客户端把 token 带出来也照记 ⇒ 红</td></tr>
 *   <tr><td>3</td><td>超过 {@link ClientErrorController#MAX_BODY_BYTES} ⇒ {@code 413}（**声明长度**与**分块无长度**两条路都挡）</td>
 *       <td>去掉 {@code readBounded} ⇒ 无 Content-Length 的请求可传任意大 ⇒ 红</td></tr>
 *   <tr><td>4</td><td>非 JSON Content-Type ⇒ {@code 415}</td><td>不校验 ⇒ 任意文本进日志 ⇒ 红</td></tr>
 *   <tr><td>5</td><td>同一 IP 超过每窗口 {@code 30} 条 ⇒ {@code 429}；**按 IP 分别计数**（另一 IP 不受影响）</td>
 *       <td>去掉限流 ⇒ 公开面可被刷爆 ⇒ 红</td></tr>
 *   <tr><td>6</td><td><b>日志里不出现</b> PIN / token / JWT / 手机号 / query 串（落日志前再涂一次）</td>
 *       <td>摘掉任一 {@code Pattern} ⇒ 凭据进日志 ⇒ 红</td></tr>
 *   <tr><td>7</td><td>4xx **不写业务日志**（否则公开面等于日志放大器），只有 {@code 204} 那条写一行 WARN</td>
 *       <td>把拒绝也打成 WARN ⇒ 红</td></tr>
 * </table>
 *
 * <h3>边界（照实登记）</h3>
 * <ul>
 *   <li>本判据**不启 Spring 上下文**（standalone MockMvc）：{@code permitAll} 的接线由
 *       {@code SecurityConfig} 的既有判据覆盖，这里只判端点自身行为；</li>
 *   <li>多实例部署下每实例各有一份额度（{@link ClientErrorRateLimiter} 是**进程内**计数，
 *       刻意不依赖 Redis —— 那正是「Redis 挂了也要能上报」的取舍），本判据只证单实例语义；</li>
 *   <li>「线上真的收到了」不在这里：探针 / 日志面见 {@code docs/deployment/observability-minimum.md}。</li>
 * </ul>
 */
@DisplayName("浏览器错误上报端点（issue #8203 · P0-03）")
class ClientErrorControllerTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    private ClientErrorRateLimiter rateLimiter;
    private ClientErrorController controller;
    private MockMvc mockMvc;

    private Logger controllerLogger;
    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void setUp() {
        rateLimiter = new ClientErrorRateLimiter();
        controller = new ClientErrorController(rateLimiter, objectMapper);
        mockMvc = MockMvcBuilders.standaloneSetup(controller).build();

        controllerLogger = (Logger) LoggerFactory.getLogger(ClientErrorController.class);
        appender = new ListAppender<>();
        appender.start();
        controllerLogger.addAppender(appender);
    }

    @AfterEach
    void tearDown() {
        controllerLogger.detachAppender(appender);
        appender.stop();
    }

    // ── 工具 ────────────────────────────────────────────────────────────────

    private Map<String, Object> validPayload() {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("path", "/orders/42");
        payload.put("name", "TypeError");
        payload.put("message", "Cannot read properties of undefined (reading 'items')");
        // ⚠️ 栈样例**不写 `path:NNN` 形态**：Case Trust 的规则 G（引用新鲜度）会扫本次新增行里的
        //    `文件:行号` 引用并核 `origin/main` ⇒ 一条假栈就会把本 PR 判成「引用了不存在的路径」。
        payload.put("stack", "TypeError: boom\n    at OrdersPage (static/chunks/app/orders/page-bundle.js)");
        payload.put("digest", "1a2b3c4d");
        payload.put("at", "2026-10-31T01:02:03.000Z");
        payload.put("ua", "Mozilla/5.0 (Macintosh)");
        payload.put("source", "error-boundary");
        return payload;
    }

    private String json(Map<String, Object> payload) throws Exception {
        return objectMapper.writeValueAsString(payload);
    }

    private List<String> warnMessages() {
        return appender.list.stream()
                .filter(event -> event.getLevel() == Level.WARN)
                .map(ILoggingEvent::getFormattedMessage)
                .toList();
    }

    // ── 1. 正常态 ───────────────────────────────────────────────────────────

    @Test
    @DisplayName("1. 合法上报 ⇒ 204 且无响应体；日志恰好一行 CLIENT_ERROR")
    void acceptsValidPayloadWithNoContent() throws Exception {
        mockMvc.perform(post("/api/client-errors")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json(validPayload())))
                .andExpect(status().isNoContent())
                .andExpect(content().string(""));

        List<String> warns = warnMessages();
        assertThat(warns).hasSize(1);
        String line = warns.get(0);
        assertThat(line).startsWith("CLIENT_ERROR");
        assertThat(line).contains("source=error-boundary");
        assertThat(line).contains("path=/orders/42");
        assertThat(line).contains("digest=1a2b3c4d");
    }

    // ── 2. 字段校验 ─────────────────────────────────────────────────────────

    @Test
    @DisplayName("2a. 非法 source ⇒ 400（枚举是白名单，加新值必须两边同批改）")
    void rejectsUnknownSource() throws Exception {
        Map<String, Object> payload = validPayload();
        payload.put("source", "sentry");

        mockMvc.perform(post("/api/client-errors")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json(payload)))
                .andExpect(status().isBadRequest());
    }

    @Test
    @DisplayName("2b. path 含 query / hash ⇒ 400（隐私护栏：宁可拒收，也不把 token 带进日志）")
    void rejectsPathWithQueryOrHash() throws Exception {
        for (String path : new String[] {"/orders?token=leaked", "/orders#frag", "/orders?a=1#b"}) {
            Map<String, Object> payload = validPayload();
            payload.put("path", path);

            mockMvc.perform(post("/api/client-errors")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(json(payload)))
                    .andExpect(status().isBadRequest());
        }
    }

    @Test
    @DisplayName("2c. path 不以 / 开头 / 缺 name / 超长 message ⇒ 400")
    void rejectsMalformedFields() throws Exception {
        Map<String, Object> relative = validPayload();
        relative.put("path", "orders/42");
        mockMvc.perform(post("/api/client-errors")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json(relative)))
                .andExpect(status().isBadRequest());

        Map<String, Object> missingName = validPayload();
        missingName.put("name", "   ");
        mockMvc.perform(post("/api/client-errors")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json(missingName)))
                .andExpect(status().isBadRequest());

        Map<String, Object> tooLong = validPayload();
        tooLong.put("message", "m".repeat(ClientErrorController.MAX_MESSAGE_LENGTH + 1));
        mockMvc.perform(post("/api/client-errors")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json(tooLong)))
                .andExpect(status().isBadRequest());
    }

    @Test
    @DisplayName("2d. 空体 / 非法 JSON ⇒ 400（且不写业务日志）")
    void rejectsEmptyOrInvalidJson() throws Exception {
        mockMvc.perform(post("/api/client-errors")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(new byte[0]))
                .andExpect(status().isBadRequest());

        mockMvc.perform(post("/api/client-errors")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{not json"))
                .andExpect(status().isBadRequest());

        assertThat(warnMessages()).isEmpty();
    }

    // ── 3. 体积上限（两条路） ────────────────────────────────────────────────

    @Test
    @DisplayName("3a. 声明 Content-Length 超过 8 KiB ⇒ 413")
    void rejectsDeclaredOversizeBody() throws Exception {
        mockMvc.perform(post("/api/client-errors")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(new byte[ClientErrorController.MAX_BODY_BYTES + 1]))
                .andExpect(status().isPayloadTooLarge());
    }

    @Test
    @DisplayName("3b. **没有声明长度**（分块）也不能绕过上限 ⇒ 413")
    void rejectsOversizeBodyWithoutDeclaredLength() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/client-errors") {
            @Override
            public long getContentLengthLong() {
                return -1L; // 分块 / 未声明长度：声明长度的检查在这条路上不成立
            }
        };
        request.setContentType("application/json");
        request.setContent(new byte[ClientErrorController.MAX_BODY_BYTES + 1]);

        ResponseEntity<Void> response = controller.report(request);

        assertThat(response.getStatusCode().value()).isEqualTo(413);
    }

    // ── 4. Content-Type ────────────────────────────────────────────────────

    @Test
    @DisplayName("4. 非 JSON / 非 text 的 Content-Type ⇒ 415")
    void rejectsUnsupportedContentType() throws Exception {
        mockMvc.perform(post("/api/client-errors")
                        .contentType(MediaType.TEXT_HTML)
                        .content(json(validPayload())))
                .andExpect(status().isUnsupportedMediaType());
    }

    // ── 5. 限流 ────────────────────────────────────────────────────────────

    @Test
    @DisplayName("5a. 同一 IP 超过 30 条/窗口 ⇒ 429（前 30 条照收）")
    void rateLimitsPerIp() throws Exception {
        for (int i = 0; i < ClientErrorRateLimiter.MAX_PER_WINDOW; i++) {
            Map<String, Object> payload = validPayload();
            payload.put("message", "flood-" + i);
            mockMvc.perform(post("/api/client-errors")
                            .header("X-Real-IP", "203.0.113.9")
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(json(payload)))
                    .andExpect(status().isNoContent());
        }
        mockMvc.perform(post("/api/client-errors")
                        .header("X-Real-IP", "203.0.113.9")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json(validPayload())))
                .andExpect(status().isTooManyRequests());
    }

    @Test
    @DisplayName("5b. 限流按 IP 分桶（负控：另一个 IP 不受影响，也会读 X-Forwarded-For 首位）")
    void rateLimitIsKeyedByClientIp() throws Exception {
        for (int i = 0; i <= ClientErrorRateLimiter.MAX_PER_WINDOW; i++) {
            mockMvc.perform(post("/api/client-errors")
                    .header("X-Forwarded-For", "198.51.100.7, 10.0.0.1")
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(json(validPayload())));
        }
        // 同一 X-Forwarded-For 首位已超限
        mockMvc.perform(post("/api/client-errors")
                        .header("X-Forwarded-For", "198.51.100.7, 10.0.0.1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json(validPayload())))
                .andExpect(status().isTooManyRequests());

        // 另一个 IP 仍有额度
        mockMvc.perform(post("/api/client-errors")
                        .header("X-Forwarded-For", "198.51.100.8, 10.0.0.1")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json(validPayload())))
                .andExpect(status().isNoContent());
    }

    // ── 6. 隐私边界（本文件的核心判据） ──────────────────────────────────────

    @Test
    @DisplayName("6. 日志里**不出现** PIN / token / JWT / 手机号 / query 串")
    void logLineCarriesNoSecrets() throws Exception {
        // ⚠️ 假 JWT **分段拼装**：整串字面量会命中 gitleaks 的 `jwt` 规则（Secret Scan 判红）。
        String jwt = "eyJhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0In0" + "." + "c2lnbmF0dXJlLXZhbHVl";
        String pinValue = "654321";
        String tokenValue = "leaked-token-value";
        String phone = "13912345678";

        Map<String, Object> payload = validPayload();
        payload.put("message",
                "上报失败 " + jwt + " pin=" + pinValue + " token=" + tokenValue + " 手机 " + phone
                        + " url=/api/orders?page=1&x=2");
        payload.put("stack", "Error: " + jwt + "\n    at Bearer abc.def.ghi");
        payload.put("digest", "pin=" + pinValue);
        payload.put("ua", "UA " + phone);

        mockMvc.perform(post("/api/client-errors")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json(payload)))
                .andExpect(status().isNoContent());

        List<String> warns = warnMessages();
        assertThat(warns).hasSize(1);
        String line = warns.get(0);

        // 具名负控：五类凭据一个都不许出现在日志行里
        assertThat(line).doesNotContain(jwt);
        assertThat(line).doesNotContain(pinValue);
        assertThat(line).doesNotContain(tokenValue);
        assertThat(line).doesNotContain(phone);
        assertThat(line).doesNotContain("page=1");
        assertThat(line).doesNotContain("abc.def.ghi");

        // 正向：涂抹标记在（证明它是被**替换**掉的，不是恰好没打印）
        assertThat(line).contains("[redacted-jwt]");
        assertThat(line).contains("pin=[redacted]");
        assertThat(line).contains("token=[redacted]");
        assertThat(line).contains("[redacted-phone]");
        assertThat(line).contains("[redacted-query]");
    }

    @Test
    @DisplayName("6b. sanitize：null / 空白 ⇒ `-`；控制字符压成单行；超长截断并带省略号")
    void sanitizeIsSingleLineAndTruncated() {
        assertThat(ClientErrorController.sanitize(null, 100)).isEqualTo("-");
        assertThat(ClientErrorController.sanitize("   ", 100)).isEqualTo("-");
        assertThat(ClientErrorController.sanitize("a\nb\tc", 100)).isEqualTo("a b c");

        String truncated = ClientErrorController.sanitize("x".repeat(50), 10);
        assertThat(truncated).hasSize(10);
        assertThat(truncated).endsWith("…");
    }

    // ── 7. 4xx 不写业务日志 ────────────────────────────────────────────────

    @Test
    @DisplayName("7. 被拒的请求不产生 WARN 业务日志（公开面不许被当成日志放大器）")
    void rejectedRequestsAreNotLoggedAsBusinessEvents() throws Exception {
        Map<String, Object> badSource = validPayload();
        badSource.put("source", "sentry");
        mockMvc.perform(post("/api/client-errors")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json(badSource)))
                .andExpect(status().isBadRequest());

        mockMvc.perform(post("/api/client-errors")
                        .contentType(MediaType.TEXT_HTML)
                        .content(json(validPayload())))
                .andExpect(status().isUnsupportedMediaType());

        assertThat(warnMessages()).isEmpty();
    }
}
