// case_ids: KF-025
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
 * KfJudgeClient 测试 — 语义判定客户端（issue #9196 / 母单 #9194 子项 1）。
 *
 * <p>失败语义与 {@code RegistrationReviewClient} 同族但**反向**：那边 fail-closed（驳回），
 * 这边 fail-open 到**规则结论**（返回 {@link Optional#empty()}，由调用方回退规则）——
 * 判定服务不可用时拒答客户是更坏的故障。</p>
 */
@DisplayName("KfJudgeClient 语义判定客户端")
class KfJudgeClientTest {

    private static final String URL = "http://ai-agent:8000/api/internal/kf/judge";

    private MockRestServiceServer server;
    private KfJudgeClient client;

    @BeforeEach
    void setUp() {
        RestTemplate restTemplate = new RestTemplate();
        server = MockRestServiceServer.bindTo(restTemplate).build();
        client = new KfJudgeClient(restTemplate);
        ReflectionTestUtils.setField(client, "baseUrl", "http://ai-agent:8000");
        ReflectionTestUtils.setField(client, "serviceToken", "test-service-token");
    }

    @Test
    @DisplayName("escalate=true 解析为升级，并带 Service Token 头")
    void parsesEscalateVerdict() {
        server.expect(requestTo(URL))
                .andExpect(header("X-Service-Token", "test-service-token"))
                .andRespond(withSuccess(
                        "{\"success\":true,\"data\":{\"intent\":\"human_request\",\"risk\":\"high\","
                                + "\"emotion\":\"angry\",\"confidence\":0.93,\"escalate\":true,"
                                + "\"reason\":\"客户要求人工\"}}",
                        MediaType.APPLICATION_JSON));

        Optional<KfJudgeClient.Verdict> v = client.judge(1L, "s-1", "我要人工");

        assertThat(v).isPresent();
        assertThat(v.get().escalate()).isTrue();
        assertThat(v.get().intent()).isEqualTo("human_request");
        assertThat(v.get().risk()).isEqualTo("high");
        assertThat(v.get().emotion()).isEqualTo("angry");
        assertThat(v.get().confidence()).isEqualTo(0.93);
        server.verify();
    }

    @Test
    @DisplayName("success=false ⇒ 空结果（调用方回退规则）")
    void businessFailureIsEmpty() {
        server.expect(requestTo(URL)).andRespond(withSuccess(
                "{\"success\":false,\"error\":{\"code\":\"KF_JUDGE_UNAVAILABLE\"}}",
                MediaType.APPLICATION_JSON));

        assertThat(client.judge(1L, "s-1", "这款多少钱")).isEmpty();
    }

    @Test
    @DisplayName("data 缺 escalate 字段 ⇒ 按不升级处理，但仍返回结论")
    void missingEscalateDefaultsFalse() {
        server.expect(requestTo(URL)).andRespond(withSuccess(
                "{\"success\":true,\"data\":{\"intent\":\"price\",\"confidence\":0.7}}",
                MediaType.APPLICATION_JSON));

        Optional<KfJudgeClient.Verdict> v = client.judge(1L, "s-1", "这款多少钱");
        assertThat(v).isPresent();
        assertThat(v.get().escalate()).isFalse();
    }

    @Test
    @DisplayName("空 data ⇒ 空结果")
    void emptyDataIsEmpty() {
        server.expect(requestTo(URL)).andRespond(withSuccess(
                "{\"success\":true}", MediaType.APPLICATION_JSON));

        assertThat(client.judge(1L, "s-1", "这款多少钱")).isEmpty();
    }

    @Test
    @DisplayName("5xx / 不可解析 ⇒ 空结果，不抛错")
    void transportAndParseFailuresAreEmpty() {
        server.expect(requestTo(URL)).andRespond(withServerError());
        assertThat(client.judge(1L, "s-1", "这款多少钱")).isEmpty();

        server.reset();
        server.expect(requestTo(URL)).andRespond(withSuccess("not-json", MediaType.APPLICATION_JSON));
        assertThat(client.judge(1L, "s-1", "这款多少钱")).isEmpty();
    }

    @Test
    @DisplayName("空文本 ⇒ 直接空结果，不出站（省一次模型调用）")
    void blankTextSkipsHttp() {
        assertThat(client.judge(1L, "s-1", "   ")).isEmpty();
        server.verify();
    }
}
