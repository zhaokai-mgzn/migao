// case_ids: KF-028
package com.migao.admin.service.kf;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.hamcrest.Matchers.startsWith;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * 媒体下载（`/cgi-bin/media/get`）解析（issue #9200 = 母单 #9194 子项 4）。
 *
 * <p>两个必须分清的形态：**真二进制** vs **微信的 JSON 错误体**。后者 Content-Type 也是
 * `application/json`，若按字节直接落盘，会把 `{"errcode":40007}` 存成一张坏图片 —— 而且没人会红。</p>
 */
class WechatKfMediaTest {

    private static final String BASE = "https://qyapi.weixin.qq.com";

    private static WechatKfClient client(RestTemplate rt) {
        return new WechatKfClient(rt, new ObjectMapper(), BASE);
    }

    @Test
    @DisplayName("二进制响应 ⇒ 字节与 mime 原样返回")
    void binaryIsReturned() {
        RestTemplate rt = new RestTemplate();
        MockRestServiceServer server = MockRestServiceServer.bindTo(rt).build();
        byte[] png = new byte[]{(byte) 0x89, 'P', 'N', 'G', 1, 2, 3};

        server.expect(requestTo(startsWith(BASE + "/cgi-bin/media/get")))
                .andRespond(withSuccess(png, MediaType.IMAGE_PNG));

        WechatKfClient.MediaFile file = client(rt).getMedia("tok", "mid-1");

        assertThat(file.bytes()).isEqualTo(png);
        assertThat(file.mime()).isEqualTo("image/png");
    }

    @Test
    @DisplayName("JSON 错误体（即使 HTTP 200）⇒ 抛 KfApiException，不落盘")
    void jsonErrorBodyThrows() {
        RestTemplate rt = new RestTemplate();
        MockRestServiceServer server = MockRestServiceServer.bindTo(rt).build();
        server.expect(requestTo(startsWith(BASE + "/cgi-bin/media/get")))
                .andRespond(withSuccess("{\"errcode\":40007,\"errmsg\":\"invalid media_id\"}",
                        MediaType.APPLICATION_JSON));

        assertThatThrownBy(() -> client(rt).getMedia("tok", "mid-1"))
                .isInstanceOf(KfApiException.class)
                .hasMessageContaining("invalid media_id");
    }

    @Test
    @DisplayName("空 media_id / 空 token ⇒ 直接拒绝（不发出请求）")
    void blankInputsRejected() {
        RestTemplate rt = new RestTemplate();
        MockRestServiceServer server = MockRestServiceServer.bindTo(rt).build();
        WechatKfClient c = client(rt);

        assertThatThrownBy(() -> c.getMedia("tok", " ")).isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> c.getMedia(" ", "mid-1")).isInstanceOf(IllegalArgumentException.class);
        server.verify();
    }
}
