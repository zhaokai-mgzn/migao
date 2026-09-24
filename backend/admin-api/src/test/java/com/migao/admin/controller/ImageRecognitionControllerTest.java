package com.migao.admin.controller;

// case_ids: PR-008, OR-008

import com.migao.admin.exception.BusinessException;
import com.migao.admin.security.PermissionInterceptor;
import com.migao.admin.service.ImageRecognitionClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * ImageRecognitionController 图片识别端点测试（issue #5321 包 1 · 页面快通道）。
 *
 * <p>判据：</p>
 * <ol>
 *   <li>端点 {@code POST /api/admin/image-recognition} 返回 {@code {success,data}} 外壳，
 *       {@code data} 恰好三个键（{@code targetType}/{@code fields}/{@code degraded}）
 *       —— <b>没有任何 id / 落库痕迹</b>；</li>
 *   <li><b>权限按 target 取写码</b>：{@code product} ⇒ {@code product:create}、
 *       {@code order} ⇒ {@code order:create}（同一份 {@link PermissionInterceptor} 判定）；
 *       未知 target ⇒ 400 且<b>不发起远端调用</b>（fail-closed，不猜 target）；</li>
 *   <li>空图片列表 ⇒ 400 且<b>不发起远端调用</b>（不白烧一次 vision）；</li>
 *   <li>🔴 <b>不落库 / 不提交</b>：本控制器的非静态依赖<b>恰好</b>是
 *       {@link ImageRecognitionClient} + {@link PermissionInterceptor} ——
 *       一旦有人塞进任何 Mapper / 写 Service（识别结果顺手落库），本用例变红；</li>
 *   <li>客户端 fail-closed 的 422 原样透传（不吞成「没认出来」）。</li>
 * </ol>
 *
 * <p>红证（实现前）：{@code ImageRecognitionController} 不存在 ⇒ 本文件编译失败（找不到符号）。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("ImageRecognitionController 图片识别端点（issue #5321）")
class ImageRecognitionControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/image-recognition";

    @Mock
    private ImageRecognitionClient imageRecognitionClient;
    @Mock
    private PermissionInterceptor permissionInterceptor;

    @InjectMocks
    private ImageRecognitionController controller;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = buildMockMvc(controller);
        when(imageRecognitionClient.recognize(anyString(), anyList())).thenReturn(frozenProduct());
    }

    /** 冻结夹具：一个预填格（带 `[图片识别]`）+ 一个**故意留空**格（带 reason）。 */
    private static ImageRecognitionClient.ImageRecognitionResult frozenProduct() {
        Map<String, Object> filled = new LinkedHashMap<>();
        filled.put("key", "name");
        filled.put("label", "商品名称");
        filled.put("value", "雪尼尔遮光窗帘");
        filled.put("source", "[图片识别]");
        filled.put("reason", null);

        Map<String, Object> blanked = new LinkedHashMap<>();
        blanked.put("key", "door_width");
        blanked.put("label", "门幅");
        blanked.put("value", null);
        blanked.put("source", null);
        blanked.put("reason", "图片未标注门幅");

        return new ImageRecognitionClient.ImageRecognitionResult(
                "product", List.of(filled, blanked), false);
    }

    @Test
    @DisplayName("冻结夹具：data 恰好三个键（targetType/fields/degraded），逐字段标注原样搬运")
    void recognize_returnsFieldsAndMarkersOnly() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"product","images":["https://oss.example.com/a.jpg"]}
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.length()").value(3))
                .andExpect(jsonPath("$.data.targetType").value("product"))
                .andExpect(jsonPath("$.data.degraded").value(false))
                .andExpect(jsonPath("$.data.fields[0].key").value("name"))
                .andExpect(jsonPath("$.data.fields[0].value").value("雪尼尔遮光窗帘"))
                .andExpect(jsonPath("$.data.fields[0].source").value("[图片识别]"))
                .andExpect(jsonPath("$.data.fields[1].key").value("door_width"))
                .andExpect(jsonPath("$.data.fields[1].reason").value("图片未标注门幅"))
                // 端点侧不得出现任何落库痕迹（判据 4 的返回面半边）
                .andExpect(jsonPath("$.data.id").doesNotExist())
                .andExpect(jsonPath("$.data.saved").doesNotExist())
                .andExpect(jsonPath("$.data.created").doesNotExist());
    }

    @Test
    @DisplayName("targetType=product ⇒ 只要求 product:create（建品写码，不是读码）")
    void recognize_productTargetRequiresProductCreate() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"product","images":["https://oss.example.com/a.jpg"]}
                        """))
                .andExpect(status().isOk());

        verify(permissionInterceptor).requirePermission("product:create");
    }

    @Test
    @DisplayName("targetType=order ⇒ 只要求 order:create（订单写码；两 target 的码互不顶替）")
    void recognize_orderTargetRequiresOrderCreate() throws Exception {
        when(imageRecognitionClient.recognize(eq("order"), anyList()))
                .thenReturn(new ImageRecognitionClient.ImageRecognitionResult("order", List.of(), true));

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"order","images":["https://oss.example.com/a.jpg"]}
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.degraded").value(true));

        verify(permissionInterceptor).requirePermission("order:create");
        verify(permissionInterceptor, never()).requirePermission("product:create");
    }

    @Test
    @DisplayName("未知 targetType ⇒ 400 且不调客户端、不查权限（fail-closed，不猜 target）")
    void recognize_unknownTargetFailsClosed() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"invoice","images":["https://oss.example.com/a.jpg"]}
                        """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("IMAGE_RECOGNITION_INVALID_TARGET"));

        verify(imageRecognitionClient, never()).recognize(anyString(), anyList());
        verify(permissionInterceptor, never()).requirePermission(anyString());
    }

    @Test
    @DisplayName("缺 targetType ⇒ 400（不回落成默认 target —— 猜错 = 拿商品字段表填订单）")
    void recognize_missingTargetFailsClosed() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"images":["https://oss.example.com/a.jpg"]}
                        """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("IMAGE_RECOGNITION_INVALID_TARGET"));

        verify(imageRecognitionClient, never()).recognize(anyString(), anyList());
    }

    @Test
    @DisplayName("空图片列表 ⇒ 400 且不调客户端（不白烧一次 vision 调用）")
    void recognize_emptyImagesFailsClosed() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"product","images":[]}
                        """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("IMAGE_RECOGNITION_INVALID_IMAGES"));

        verify(imageRecognitionClient, never()).recognize(anyString(), anyList());
    }

    @Test
    @DisplayName("客户端 fail-closed 的 422 原样透传（不吞成「没认出来」让商家反复重拍）")
    void recognize_clientUnavailablePropagates() throws Exception {
        when(imageRecognitionClient.recognize(anyString(), anyList()))
                .thenThrow(new BusinessException(
                        ImageRecognitionClient.ERR_IMAGE_RECOGNITION_UNAVAILABLE,
                        "图片识别服务（ai-agent）不可用，本次识别已中止：connection refused",
                        422, "请确认 ai-agent-service 已启动"));

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"product","images":["https://oss.example.com/a.jpg"]}
                        """))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("IMAGE_RECOGNITION_UNAVAILABLE"));
    }

    @Test
    @DisplayName("🔴 不落库：非静态依赖恰好是「识别客户端 + 权限判定」两个（塞进任何写 Service 即变红）")
    void controllerHasNoPersistenceDependency() {
        List<Class<?>> dependencyTypes = new ArrayList<>();
        for (Field field : ImageRecognitionController.class.getDeclaredFields()) {
            if (!Modifier.isStatic(field.getModifiers())) {
                dependencyTypes.add(field.getType());
            }
        }
        assertThat(dependencyTypes)
                .as("识别结果只填表、不落库：控制器不得持有任何 Mapper / 写 Service / Repository")
                .containsExactlyInAnyOrder(ImageRecognitionClient.class, PermissionInterceptor.class);
        assertThat(Arrays.stream(ImageRecognitionController.class.getDeclaredMethods())
                .map(java.lang.reflect.Method::getName).toList())
                .as("控制器只有这一个业务入口（不提供任何保存/提交端点）")
                .contains("recognize")
                .doesNotContain("save", "submit", "create");
    }
}