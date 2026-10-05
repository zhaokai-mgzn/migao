package com.migao.admin.controller;

// case_ids: PR-008

import com.migao.admin.dto.ImageRecognitionInterpretRequest;
import com.migao.admin.dto.PageFillPlan;
import com.migao.admin.exception.PermissionDeniedException;
import com.migao.admin.security.PermissionInterceptor;
import com.migao.admin.service.ImageRecognitionClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.core.annotation.AnnotatedElementUtils;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * {@code POST /api/admin/image-recognition/interpret}（issue #6367 包 P2）判据。
 *
 * <p>与既有 {@link ImageRecognitionControllerTest}（{@code recognize}）**同族**：本文件只判
 * 「新增的 interpret 端点」，既有端点的判据一字不动。</p>
 *
 * <ol>
 *   <li><b>同族同权限</b>：方法级注解与 {@code recognize} <b>逐字一致</b>
 *       （同一个 {@code @PostMapping} 空值 + 同一个 {@code @RequestBody(required=false)}），
 *       且权限仍走「按 target 取写码」那一份 {@link PermissionInterceptor} 判定；</li>
 *   <li>{@code hint} 可选、≤200 字：缺省/空 ⇒ 不发起远端调用前的任何编造；&gt;200 ⇒ <b>400 + 可行动文案</b>；</li>
 *   <li>响应 = 冻结契约 {@code {component, target_type, fields}}（<b>不是</b> recognize 的
 *       {@code targetType/degraded} 形状，也不是三键）；</li>
 *   <li>🔴 <b>不落库</b>：非静态依赖仍<b>恰好</b>是「识别客户端 + 权限判定」两个。</li>
 * </ol>
 *
 * <p>红证（实现前）：{@code ImageRecognitionClient.interpret} / {@code PageFillPlan} 不存在
 * ⇒ 本文件编译失败（找不到符号）。</p>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("ImageRecognitionController interpret 端点（issue #6367 包 P2）")
class ImageRecognitionInterpretControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/image-recognition/interpret";

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
        when(imageRecognitionClient.interpret(anyString(), anyList(), any()))
                .thenReturn(frozenPlan());
    }

    /** 冻结夹具：一格识别来的 + 一格**米宝解读**来的（两种来源必须可分辨）。 */
    private static ImageRecognitionClient.PageFillResult frozenPlan() {
        Map<String, Object> recognized = new LinkedHashMap<>();
        recognized.put("key", "color");
        recognized.put("label", "颜色");
        recognized.put("value", "雾霾蓝");
        recognized.put("source", "[图片识别]");
        recognized.put("reason", null);
        recognized.put("candidates", null);
        recognized.put("note", null);
        recognized.put("note_source", null);

        Map<String, Object> interpreted = new LinkedHashMap<>();
        interpreted.put("key", "material");
        interpreted.put("label", "材质");
        interpreted.put("value", "雪尼尔");
        interpreted.put("source", "[米宝解读]");
        interpreted.put("reason", null);
        interpreted.put("candidates", null);
        interpreted.put("note", "雪尼尔通常用于客厅遮光帘");
        interpreted.put("note_source", "[米宝解读]");

        return new ImageRecognitionClient.PageFillResult("page_fill", "product", List.of(recognized, interpreted));
    }

    @Test
    @DisplayName("🔴 同族：注解**形态**与 recognize 一致，路径 = 它 + /interpret（不新立第二套约定）")
    void interpretHasSameAnnotationShapeAsRecognize() throws Exception {
        Method recognize = ImageRecognitionController.class.getMethod("recognize", com.migao.admin.dto.ImageRecognitionRequest.class);
        Method interpret = ImageRecognitionController.class.getMethod("interpret", ImageRecognitionInterpretRequest.class);

        PostMapping recognizeMapping = recognize.getAnnotation(PostMapping.class);
        PostMapping interpretMapping = interpret.getAnnotation(PostMapping.class);
        assertThat(interpretMapping).isNotNull();
        // 路径 = recognize 的前缀 + /interpret（同一个类级 @RequestMapping 下，不另起命名空间）。
        // ⚠️ 两边都只写 `value`、都不写 `path`（形态一致）；@AliasFor 会把 value 映进 path，
        // 故这里读**原始注解**而非 merged 注解（merged 会把 path 变成 ["/interpret"]）。
        assertThat(String.join("", recognizeMapping.value()) + "/interpret")
                .as("interpret 必须挂在既有的 /api/admin/image-recognition 之下")
                .isEqualTo(String.join("", interpretMapping.value()));
        assertThat(interpretMapping.path()).isEqualTo(recognizeMapping.path());
        // 方法级注解**组成**一致：两边都只有 @PostMapping + @RequestBody（多一个都算新立约定）
        assertThat(interpret.getAnnotations())
                .extracting(java.lang.annotation.Annotation::annotationType)
                .containsExactlyInAnyOrderElementsOf(
                        java.util.Arrays.asList(recognize.getAnnotations()).stream()
                                .map(java.lang.annotation.Annotation::annotationType).toList());

        RequestBody recognizeBody = recognize.getParameters()[0].getAnnotation(RequestBody.class);
        RequestBody interpretBody = interpret.getParameters()[0].getAnnotation(RequestBody.class);
        assertThat(interpretBody).isNotNull();
        assertThat(interpretBody.required())
                .as("@RequestBody(required) 必须与 recognize 逐字一致")
                .isEqualTo(recognizeBody.required());
    }

    @Test
    @DisplayName("冻结契约：data 恰好三个键 component/target_type/fields（与 ai-agent 的 page_fill 同形）")
    void interpret_returnsFrozenPageFillShape() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"product","images":["https://oss.example.com/a.jpg"],"hint":"客厅雪尼尔，韩褶，遮光"}
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.length()").value(3))
                .andExpect(jsonPath("$.data.component").value("page_fill"))
                .andExpect(jsonPath("$.data.target_type").value("product"))
                .andExpect(jsonPath("$.data.fields[0].key").value("color"))
                .andExpect(jsonPath("$.data.fields[0].source").value("[图片识别]"))
                .andExpect(jsonPath("$.data.fields[1].source").value("[米宝解读]"))
                .andExpect(jsonPath("$.data.fields[1].note_source").value("[米宝解读]"))
                // 不是 recognize 的形状（键名不得漂成 camelCase）
                .andExpect(jsonPath("$.data.targetType").doesNotExist())
                .andExpect(jsonPath("$.data.degraded").doesNotExist())
                .andExpect(jsonPath("$.data.id").doesNotExist());
    }

    @Test
    @DisplayName("hint 透传给客户端（可选输入不当成新指令面，原样往下带）")
    void interpret_passesHintThrough() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"product","images":["https://oss.example.com/a.jpg"],"hint":"客厅雪尼尔，韩褶，遮光"}
                        """))
                .andExpect(status().isOk());

        verify(imageRecognitionClient).interpret(eq("product"),
                eq(List.of("https://oss.example.com/a.jpg")), eq("客厅雪尼尔，韩褶，遮光"));
    }

    @Test
    @DisplayName("缺 hint ⇒ 透传 null（控制器不编造空串）")
    void interpret_missingHintIsNull() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"product","images":["https://oss.example.com/a.jpg"]}
                        """))
                .andExpect(status().isOk());

        verify(imageRecognitionClient).interpret(eq("product"), anyList(), eq(null));
    }

    @Test
    @DisplayName("hint 恰好 200 字 ⇒ 放行（边界含端点）")
    void interpret_hintAtLimitPasses() throws Exception {
        String hint = "雪".repeat(200);
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(
                                Map.of("targetType", "product",
                                        "images", List.of("https://oss.example.com/a.jpg"),
                                        "hint", hint))))
                .andExpect(status().isOk());
    }

    @Test
    @DisplayName("🔴 hint > 200 字 ⇒ 400 + 可行动文案，且不发起远端调用（不白烧一次 vision + 一次推理）")
    void interpret_overlongHintIsRejected() throws Exception {
        String hint = "雪".repeat(201);
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(
                                Map.of("targetType", "product",
                                        "images", List.of("https://oss.example.com/a.jpg"),
                                        "hint", hint))))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("IMAGE_RECOGNITION_INVALID_HINT"))
                .andExpect(jsonPath("$.suggestion").isNotEmpty());

        verify(imageRecognitionClient, never()).interpret(anyString(), anyList(), any());
    }

    @Test
    @DisplayName("product ⇒ product:create、order ⇒ order:create（与 recognize 同一份按 target 取写码）")
    void interpret_permissionIsByTarget() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"product","images":["https://oss.example.com/a.jpg"]}
                        """))
                .andExpect(status().isOk());
        verify(permissionInterceptor).requirePermission("product:create");

        when(imageRecognitionClient.interpret(eq("order"), anyList(), any()))
                .thenReturn(new ImageRecognitionClient.PageFillResult("page_fill", "order", List.of()));
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"order","images":["https://oss.example.com/a.jpg"]}
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.target_type").value("order"));
        verify(permissionInterceptor).requirePermission("order:create");
        verify(permissionInterceptor, never()).requirePermission("invoice:create");
    }

    @Test
    @DisplayName("未知 target ⇒ 400 且不调客户端、不查权限（fail-closed，不猜 target）")
    void interpret_unknownTargetFailsClosed() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"invoice","images":["https://oss.example.com/a.jpg"]}
                        """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("IMAGE_RECOGNITION_INVALID_TARGET"));

        verify(imageRecognitionClient, never()).interpret(anyString(), anyList(), any());
        verify(permissionInterceptor, never()).requirePermission(anyString());
    }

    @Test
    @DisplayName("空图片列表 ⇒ 400 且不调客户端（口径与 recognize 一致）")
    void interpret_emptyImagesFailsClosed() throws Exception {
        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"product","images":[]}
                        """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("IMAGE_RECOGNITION_INVALID_IMAGES"));

        verify(imageRecognitionClient, never()).interpret(anyString(), anyList(), any());
    }

    @Test
    @DisplayName("上游 degraded / 空 fields ⇒ 如实透传（不编造、不 500）")
    void interpret_degradedIsPassedThrough() throws Exception {
        when(imageRecognitionClient.interpret(anyString(), anyList(), any()))
                .thenReturn(new ImageRecognitionClient.PageFillResult("page_fill", "product", List.of()));

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"product","images":["https://oss.example.com/a.jpg"]}
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.fields").isEmpty())
                .andExpect(jsonPath("$.data.component").value("page_fill"));
    }

    @Test
    @DisplayName("客户端可行动 422 原样透传（不吞、不 500 裸抛）")
    void interpret_upstreamUnavailableStaysActionable() throws Exception {
        when(imageRecognitionClient.interpret(anyString(), anyList(), any()))
                .thenThrow(new com.migao.admin.exception.BusinessException(
                        ImageRecognitionClient.ERR_IMAGE_RECOGNITION_UNAVAILABLE,
                        "图片识别服务（ai-agent）不可用，本次识别已中止：Read timed out",
                        422, "请确认 ai-agent-service 已启动；也可以直接手工填写表单"));

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"product","images":["https://oss.example.com/a.jpg"]}
                        """))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.error.code").value("IMAGE_RECOGNITION_UNAVAILABLE"))
                .andExpect(jsonPath("$.suggestion").isNotEmpty());
    }

    @Test
    @DisplayName("权限不足 ⇒ 403（写码不因为走了新端点而被绕过）")
    void interpret_permissionDeniedIs403() throws Exception {
        doThrow(new PermissionDeniedException("权限不足，需要权限: product:create", "product:create"))
                .when(permissionInterceptor).requirePermission("product:create");

        mockMvc.perform(post(URL).contentType(MediaType.APPLICATION_JSON).content("""
                        {"targetType":"product","images":["https://oss.example.com/a.jpg"]}
                        """))
                .andExpect(status().isForbidden());

        verify(imageRecognitionClient, never()).interpret(anyString(), anyList(), any());
    }

    @Test
    @DisplayName("🔴 不落库：非静态依赖仍恰好是「识别客户端 + 权限判定」两个")
    void interpretControllerHasNoPersistenceDependency() {
        List<Class<?>> dependencyTypes = new java.util.ArrayList<>();
        for (java.lang.reflect.Field field : ImageRecognitionController.class.getDeclaredFields()) {
            if (!java.lang.reflect.Modifier.isStatic(field.getModifiers())) {
                dependencyTypes.add(field.getType());
            }
        }
        assertThat(dependencyTypes)
                .as("推理结果只填表、不落库：控制器不得持有任何 Mapper / 写 Service / Repository")
                .containsExactlyInAnyOrder(ImageRecognitionClient.class, PermissionInterceptor.class);
    }
}
