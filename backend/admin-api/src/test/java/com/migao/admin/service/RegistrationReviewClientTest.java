package com.migao.admin.service;

import com.migao.admin.dto.RegistrationRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withBadRequest;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * RegistrationReviewClient 测试 — AI 甄别客户端
 * 覆盖：approve/reject 解析、失败语义（网络错误/业务失败/未知决策 → null，fail-closed）
 */
// case_ids: OB-001, OB-002, OB-003
@DisplayName("RegistrationReviewClient AI 甄别客户端测试")
class RegistrationReviewClientTest {

    private RestTemplate restTemplate;
    private MockRestServiceServer server;
    private RegistrationReviewClient client;

    @BeforeEach
    void setUp() {
        restTemplate = new RestTemplate();
        server = MockRestServiceServer.bindTo(restTemplate).build();
        client = new RegistrationReviewClient(restTemplate);
        ReflectionTestUtils.setField(client, "baseUrl", "http://ai-agent:8000");
        ReflectionTestUtils.setField(client, "serviceToken", "test-service-token");
    }

    private RegistrationRequest buildRequest() {
        RegistrationRequest req = new RegistrationRequest();
        req.setCompanyName("杭州锦绣布艺有限公司");
        req.setContactName("张三");
        req.setPhone("13800138000");
        req.setSmsCode("123456");
        req.setIndustry("布艺纺织");
        return req;
    }

    @Test
    @DisplayName("approve 决策解析成功")
    void approveVerdict() {
        server.expect(requestTo("http://ai-agent:8000/api/internal/registration/review"))
                .andExpect(header("X-Service-Token", "test-service-token"))
                .andRespond(withSuccess(
                        "{\"success\":true,\"data\":{\"decision\":\"approve\",\"confidence\":0.95,"
                                + "\"risk_flags\":[],\"summary\":\"合规\",\"review_source\":\"ai\"}}",
                        MediaType.APPLICATION_JSON));

        RegistrationReviewClient.ReviewVerdict verdict = client.review(buildRequest());

        assertThat(verdict).isNotNull();
        assertThat(verdict.decision()).isEqualTo("approve");
        assertThat(verdict.reviewSource()).isEqualTo("ai");
    }

    @Test
    @DisplayName("reject 决策解析成功（含风险标记）")
    void rejectVerdict() {
        server.expect(requestTo("http://ai-agent:8000/api/internal/registration/review"))
                .andRespond(withSuccess(
                        "{\"success\":true,\"data\":{\"decision\":\"reject\",\"confidence\":0.9,"
                                + "\"reason\":\"企业名称暗示无资质金融业务\","
                                + "\"risk_flags\":[{\"level\":\"high\",\"code\":\"ILLEGAL_INDUSTRY\",\"reason\":\"金融\"}],"
                                + "\"summary\":\"疑似无资质金融业务\",\"review_source\":\"ai\"}}",
                        MediaType.APPLICATION_JSON));

        RegistrationReviewClient.ReviewVerdict verdict = client.review(buildRequest());

        assertThat(verdict).isNotNull();
        assertThat(verdict.decision()).isEqualTo("reject");
        assertThat(verdict.reason()).contains("金融");
        assertThat(verdict.riskFlags()).hasSize(1);
        assertThat(verdict.riskFlags().get(0).level()).isEqualTo("high");
    }

    @Test
    @DisplayName("服务端 5xx → null（fail-closed）")
    void serverErrorReturnsNull() {
        server.expect(requestTo("http://ai-agent:8000/api/internal/registration/review"))
                .andRespond(withServerError());

        assertThat(client.review(buildRequest())).isNull();
    }

    @Test
    @DisplayName("业务成功=false → null（fail-closed）")
    void businessFailureReturnsNull() {
        server.expect(requestTo("http://ai-agent:8000/api/internal/registration/review"))
                .andRespond(withBadRequest()
                        .body("{\"success\":false,\"error\":{\"code\":\"REVIEW_ERROR\",\"message\":\"boom\"}}")
                        .contentType(MediaType.APPLICATION_JSON));

        assertThat(client.review(buildRequest())).isNull();
    }

    @Test
    @DisplayName("未知决策 → null（fail-closed）")
    void unknownDecisionReturnsNull() {
        server.expect(requestTo("http://ai-agent:8000/api/internal/registration/review"))
                .andRespond(withSuccess(
                        "{\"success\":true,\"data\":{\"decision\":\"maybe\",\"risk_flags\":[]}}",
                        MediaType.APPLICATION_JSON));

        assertThat(client.review(buildRequest())).isNull();
    }
}
