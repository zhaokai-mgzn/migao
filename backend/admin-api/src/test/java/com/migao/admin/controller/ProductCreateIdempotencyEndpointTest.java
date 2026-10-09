// case_ids: PR-128
package com.migao.admin.controller;

import com.migao.admin.dto.ProductCreateRequest;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.service.ClientRequestIdService;
import com.migao.admin.service.ProductService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 建品写面的**端点接线**判据（issue #6209）：{@code X-Client-Request-Id} 必须从 HTTP 层
 * 真的接到服务上。
 *
 * <p>为什么单独一条：服务方法接好了幂等、端点却丢了请求头 —— 现场读数与「从没接幂等」**逐字相同**
 * （{@code client_request_keys} 0 行、每次 200 各建一份）。服务级判据看不见这一层，
 * 只有驱动真 MockMvc 才判得出来。</p>
 *
 * <p>两条判据：① 带头 ⇒ 头值逐字传到 {@code ProductService#createProduct}；
 * ② 不带头 ⇒ 传 {@code null}（老客户端路径不变，服务侧走原路径）。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("建品端点幂等键接线（issue #6209）：请求头必须真的接到服务上")
class ProductCreateIdempotencyEndpointTest extends BaseControllerTest {

    private static final String BASE = "/api/admin/products";
    private static final String KEY = "e1-product-create-key";

    private MockMvc mockMvc;

    @Mock
    private ProductService productService;

    @InjectMocks
    private ProductController productController;

    @BeforeEach
    void setUp() {
        super.baseSetUp();
        mockMvc = buildMockMvc(productController);
        ProductResponse created = new ProductResponse();
        created.setId("prod-6209");
        created.setName("线②验收重复提交");
        when(productService.createProduct(any(ProductCreateRequest.class), anyLong(), any())).thenReturn(created);
    }

    @Override
    @org.junit.jupiter.api.AfterEach
    void baseTearDown() {
        super.baseTearDown();
    }

    private static final String BODY = "{\"name\":\"线②验收重复提交\",\"basePrice\":9,"
            + "\"stock\":1,\"unit\":\"米\",\"pricingType\":\"per_meter\",\"status\":\"draft\"}";

    @Test
    @DisplayName("带 X-Client-Request-Id ⇒ 头值逐字传到服务（幂等才有对象可去重）")
    void theHeaderReachesTheServiceVerbatim() throws Exception {
        mockMvc.perform(post(BASE)
                        .header(ClientRequestIdService.HEADER, KEY)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(BODY))
                .andExpect(status().isOk());

        ArgumentCaptor<String> key = ArgumentCaptor.forClass(String.class);
        verify(productService).createProduct(any(ProductCreateRequest.class), anyLong(), key.capture());
        assertThat(key.getValue()).as("端点必须把 X-Client-Request-Id 原样交给服务（丢了 = 现场读数与从没接幂等逐字相同）")
                .isEqualTo(KEY);
    }

    @Test
    @DisplayName("不带头 ⇒ 传 null（老客户端路径一字不变）")
    void withoutTheHeaderTheServiceSeesNull() throws Exception {
        mockMvc.perform(post(BASE)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(BODY))
                .andExpect(status().isOk());

        ArgumentCaptor<String> key = ArgumentCaptor.forClass(String.class);
        verify(productService).createProduct(any(ProductCreateRequest.class), anyLong(), key.capture());
        assertThat(key.getValue()).as("无幂等键 ⇒ null（服务侧走原路径，零 DB 往返）").isNull();
    }
}
