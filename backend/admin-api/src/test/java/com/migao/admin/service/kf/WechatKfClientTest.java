// case_ids: KF-003
package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.startsWith;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class WechatKfClientTest {

    private static final String BASE = "https://qyapi.weixin.qq.com";

    @Test
    @DisplayName("gettoken / sync_msg / send_text 正常解析")
    void happyPath() {
        RestTemplate rt = new RestTemplate();
        MockRestServiceServer server = MockRestServiceServer.bindTo(rt).build();
        WechatKfClient client = new WechatKfClient(rt, new ObjectMapper(), BASE);

        server.expect(requestTo(startsWith(BASE + "/cgi-bin/gettoken")))
                .andRespond(withSuccess("{\"errcode\":0,\"access_token\":\"tok\",\"expires_in\":7200}",
                        MediaType.APPLICATION_JSON));
        server.expect(requestTo(BASE + "/cgi-bin/kf/sync_msg?access_token=tok"))
                .andExpect(content().string(containsString("\"open_kfid\":\"wk-1\"")))
                .andExpect(content().string(containsString("\"limit\":100")))
                .andRespond(withSuccess("{\"errcode\":0,\"has_more\":0,\"msg_list\":[]}",
                        MediaType.APPLICATION_JSON));
        server.expect(requestTo(BASE + "/cgi-bin/kf/send_msg?access_token=tok"))
                .andExpect(content().string(containsString("\"msgid\":\"m-1\"")))
                .andExpect(content().string(containsString("\"content\":\"你好\"")))
                .andRespond(withSuccess("{\"errcode\":0,\"msgid\":\"m-1\"}", MediaType.APPLICATION_JSON));

        assertThat(client.getAccessToken("corp", "secret")).isEqualTo("tok");
        assertThat(client.syncMsg("tok", "wk-1", null, null, 100).path("has_more").asInt()).isZero();
        assertThat(client.sendText("tok", "wk-1", "wm-1", "你好", "m-1")).isEqualTo("m-1");

        server.verify();
    }

    @Test
    @DisplayName("errcode != 0 ⇒ 抛 KfApiException（带 errcode）")
    void apiError() {
        RestTemplate rt = new RestTemplate();
        MockRestServiceServer server = MockRestServiceServer.bindTo(rt).build();
        WechatKfClient client = new WechatKfClient(rt, new ObjectMapper(), BASE);

        server.expect(requestTo(startsWith(BASE + "/cgi-bin/kf/service_state/get")))
                .andRespond(withSuccess("{\"errcode\":95014,\"errmsg\":\"user not activated\"}",
                        MediaType.APPLICATION_JSON));

        assertThatThrownBy(() -> client.getServiceState("tok", "wk-1", "wm-1"))
                .isInstanceOfSatisfying(KfApiException.class, e -> assertThat(e.getErrcode()).isEqualTo(95014));
        server.verify();
    }

    @Test
    @DisplayName("接入自检：账号列表 + 生成客服链接")
    void onboardingApis() {
        RestTemplate rt = new RestTemplate();
        MockRestServiceServer server = MockRestServiceServer.bindTo(rt).build();
        WechatKfClient client = new WechatKfClient(rt, new ObjectMapper(), BASE);

        server.expect(requestTo(BASE + "/cgi-bin/kf/account/list?access_token=tok"))
                .andRespond(withSuccess("{\"errcode\":0,\"account_list\":[{\"open_kfid\":\"wk-1\"}]}",
                        MediaType.APPLICATION_JSON));
        server.expect(requestTo(BASE + "/cgi-bin/kf/add_contact_way?access_token=tok"))
                .andExpect(content().string(containsString("\"scene_param\":\"tenant:1\"")))
                .andRespond(withSuccess("{\"errcode\":0,\"url\":\"https://kf.example/q\"}",
                        MediaType.APPLICATION_JSON));

        assertThat(client.listAccounts("tok").path("account_list").get(0).path("open_kfid").asText())
                .isEqualTo("wk-1");
        assertThat(client.createContactWay("tok", "wk-1", "tenant:1"))
                .isEqualTo("https://kf.example/q");
        server.verify();
    }

}
