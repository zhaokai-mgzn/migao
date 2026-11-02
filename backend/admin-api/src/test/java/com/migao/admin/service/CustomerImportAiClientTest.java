// case_ids: MIG-008

package com.migao.admin.service;

import com.migao.admin.dto.MappingSuggestion;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestTemplate;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * AI 映射客户端契约（issue #8295）：失败返回 null，不阻断迁移；成功按字段解析。
 */
class CustomerImportAiClientTest {

    private RestTemplate restTemplate;
    private MockRestServiceServer server;
    private CustomerImportAiClient client;

    @BeforeEach
    void setUp() {
        restTemplate = new RestTemplate();
        server = MockRestServiceServer.bindTo(restTemplate).build();
        client = new CustomerImportAiClient(restTemplate);
        ReflectionTestUtils.setField(client, "baseUrl", "http://ai.test");
        ReflectionTestUtils.setField(client, "serviceToken", "svc-token");
    }

    @Test
    void parsesMappingsAndDegradedFlag() {
        server.expect(requestTo("http://ai.test/api/internal/migration/customer-mapping"))
                .andExpect(method(HttpMethod.POST))
                .andRespond(withSuccess("""
                        {"success":true,"data":{"mappings":[
                          {"source_index":0,"source_header":"购货单位","target_field":"displayName",
                           "confidence":0.95,"reason":"购货单位是客户名称"},
                          {"source_index":1,"source_header":"联系方式","target_field":"phone",
                           "confidence":0.8,"reason":"联系方式"}
                        ],"degraded":false,"message":""}}
                        """, MediaType.APPLICATION_JSON));

        CustomerImportAiClient.Result result = client.suggest(
                List.of("购货单位", "联系方式"), List.of(List.of("张三", "13800138000")),
                CustomerImportFields.ALL);

        assertThat(result).isNotNull();
        assertThat(result.degraded()).isFalse();
        assertThat(result.suggestions()).extracting(MappingSuggestion::targetField)
                .containsExactly("displayName", "phone");
        assertThat(result.suggestions().get(0).sourceIndex()).isZero();
        server.verify();
    }

    @Test
    void serverErrorReturnsNull() {
        server.expect(requestTo("http://ai.test/api/internal/migration/customer-mapping"))
                .andRespond(withServerError());

        CustomerImportAiClient.Result result = client.suggest(
                List.of("客户名称"), List.of(List.of("张三")), CustomerImportFields.ALL);

        assertThat(result).isNull();
    }

    @Test
    void successFalseReturnsNull() {
        server.expect(requestTo("http://ai.test/api/internal/migration/customer-mapping"))
                .andRespond(withSuccess("{\"success\":false}", MediaType.APPLICATION_JSON));

        assertThat(client.suggest(List.of("客户名称"), List.of(List.of("张三")),
                CustomerImportFields.ALL)).isNull();
    }
}
