package com.migao.admin.controller;

// case_ids: UI-129

import com.migao.admin.exception.BusinessException;
import com.migao.admin.service.ProductImageGenerationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * ProductImageController 单测（issue #7335）。
 *
 * <p>判据：</p>
 * <ol>
 *   <li>{@code POST /api/admin/products/ai-images} 返回 {@code {success,data}}，
 *       {@code data} 恰好 {@code url}/{@code model} 两个键 —— <b>没有任何商品写痕迹</b>；</li>
 *   <li>缺样图 / 缺用途 ⇒ 400 且<b>不调用</b>生成服务；</li>
 *   <li>依赖面恰好 {@link ProductImageGenerationService}（无 ProductService / Mapper）；</li>
 *   <li>服务层 422 原样透传（不吞成 200 + 空 URL）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("ProductImageController（issue #7335）")
class ProductImageControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/products/ai-images";

    @Mock
    private ProductImageGenerationService service;

    @InjectMocks
    private ProductImageController controller;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = buildMockMvc(controller);
    }

    @Test
    @DisplayName("成功：data 恰好 url/model（无 id/saved/created 等落库痕迹）")
    void generate_returnsUrlAndModelOnly() throws Exception {
        when(service.generate(anyString(), anyString(), anyString()))
                .thenReturn(Map.of("url", "https://oss/permanent.png", "model", "qwen-image-3.0"));

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"imageUrl":"https://oss/sample.png","productName":"回归布帘","kind":"main"}
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.length()").value(2))
                .andExpect(jsonPath("$.data.url").value("https://oss/permanent.png"))
                .andExpect(jsonPath("$.data.model").value("qwen-image-3.0"))
                .andExpect(jsonPath("$.data.id").doesNotExist())
                .andExpect(jsonPath("$.data.saved").doesNotExist());
    }

    @Test
    @DisplayName("缺 imageUrl ⇒ 400，且不调用生成服务")
    void missingSample_rejected() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"productName":"回归布帘","kind":"main"}
                        """))
                .andExpect(status().isUnprocessableEntity());
        verifyNoInteractions(service);
    }

    @Test
    @DisplayName("缺 kind ⇒ 400，且不调用生成服务")
    void missingKind_rejected() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"imageUrl":"https://oss/sample.png","productName":"回归布帘"}
                        """))
                .andExpect(status().isUnprocessableEntity());
        verifyNoInteractions(service);
    }

    @Test
    @DisplayName("服务层 422 原样透传（不吞成 200）")
    void serviceFailure_propagates() throws Exception {
        when(service.generate(anyString(), anyString(), anyString()))
                .thenThrow(new BusinessException("AI_PRODUCT_IMAGE_UNAVAILABLE", "生成服务不可用", 422));

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"imageUrl":"https://oss/sample.png","productName":"回归布帘","kind":"main"}
                        """))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false));
        verify(service).generate("https://oss/sample.png", "回归布帘", "main");
    }

    @Test
    @DisplayName("依赖面：只有生成服务（不碰商品写路径）")
    void dependencySurfaceHasNoWriters() {
        var instanceFields = java.util.Arrays.stream(ProductImageController.class.getDeclaredFields())
                .filter(f -> !java.lang.reflect.Modifier.isStatic(f.getModifiers()))
                .toList();
        assertThat(instanceFields).hasSize(1);
        assertThat(instanceFields.get(0).getType()).isEqualTo(ProductImageGenerationService.class);
    }
}
