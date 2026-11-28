// case_ids: KF-019
package com.migao.admin.service.kf;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestTemplate;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * {@link KfReplyClient} 测试（issue #9302）—— 回复生成客户端。
 *
 * <p>失败语义与 {@code KfJudgeClient}（fail-open 到规则）<b>反向</b>：这边 <b>fail-closed</b>。
 * 超时 / 非 2xx / 响应不可解析 / 空正文 ⇒ {@link Optional#empty()}，调用方据此<b>转人工</b>，
 * 绝不把半句话发给客户。</p>
 */
@DisplayName("KfReplyClient — 回复生成客户端（fail-closed）")
class KfReplyClientTest {

    private static final String URL = "http://ai-agent:8000/api/internal/kf/reply";

    private MockRestServiceServer server;
    private KfReplyClient client;

    @BeforeEach
    void setUp() {
        RestTemplate restTemplate = new RestTemplate();
        server = MockRestServiceServer.bindTo(restTemplate).build();
        client = new KfReplyClient(restTemplate);
        ReflectionTestUtils.setField(client, "baseUrl", "http://ai-agent:8000");
        ReflectionTestUtils.setField(client, "serviceToken", "test-service-token");
    }

    @Test
    @DisplayName("正常响应 ⇒ 正文 + 工具调用次数，并带 Service Token 头")
    void parsesGeneratedReply() {
        server.expect(requestTo(URL))
                .andExpect(header("X-Service-Token", "test-service-token"))
                .andRespond(withSuccess(
                        "{\"success\":true,\"data\":{\"text\":\"这款雪尼尔 68 元一米\",\"tool_calls\":2}}",
                        MediaType.APPLICATION_JSON));

        Optional<KfReplyClient.Generated> generated = client.generate(1L, "s1", "多少钱");

        assertThat(generated).isPresent();
        assertThat(generated.get().text()).isEqualTo("这款雪尼尔 68 元一米");
        assertThat(generated.get().toolCalls()).isEqualTo(2);
    }

    @Test
    @DisplayName("success=false（内核不可用）⇒ empty（调用方转人工）")
    void unavailableReturnsEmpty() {
        server.expect(requestTo(URL)).andRespond(withSuccess(
                "{\"success\":false,\"error\":{\"code\":\"KF_REPLY_UNAVAILABLE\"}}",
                MediaType.APPLICATION_JSON));

        assertThat(client.generate(1L, "s1", "多少钱")).isEmpty();
    }

    @Test
    @DisplayName("空正文 ⇒ empty（不发空话）")
    void blankTextReturnsEmpty() {
        server.expect(requestTo(URL)).andRespond(withSuccess(
                "{\"success\":true,\"data\":{\"text\":\"   \",\"tool_calls\":1}}",
                MediaType.APPLICATION_JSON));

        assertThat(client.generate(1L, "s1", "多少钱")).isEmpty();
    }

    @Test
    @DisplayName("5xx / 网络异常 ⇒ empty，不冒泡")
    void serverErrorReturnsEmpty() {
        server.expect(requestTo(URL)).andRespond(withServerError());

        assertThat(client.generate(1L, "s1", "多少钱")).isEmpty();
    }

    @Test
    @DisplayName("响应不可解析 ⇒ empty，不冒泡")
    void unparseableReturnsEmpty() {
        server.expect(requestTo(URL)).andRespond(withSuccess("not-json", MediaType.APPLICATION_JSON));

        assertThat(client.generate(1L, "s1", "多少钱")).isEmpty();
    }
}
