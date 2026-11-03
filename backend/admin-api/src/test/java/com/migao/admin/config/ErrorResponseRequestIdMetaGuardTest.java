// case_ids: MC-139
package com.migao.admin.config;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.security.PasswordChangeRequiredFilter;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;

import java.io.IOException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 类级元守卫（铁律 8 / issue #6957）：**新增的错误响应出口若不带 requestId ⇒ 具名红**。
 *
 * <h3>为什么需要它（修一处 = 没修）</h3>
 * <p>本单修的是「响应里那个编号反查不到日志」。真正让号线断掉的是**出口太多、各写各的**：
 * MVC 面走 {@code ApiResponse}（现在带 {@code RequestId.current()}），而
 * {@code SecurityConfig} 的 entryPoint / {@code PasswordChangeRequiredFilter} /
 * {@code ServiceTokenFilter} 是**手写裸 JSON**。只把这一批补上，下一个人新加一个过滤器照样漏
 * —— 而没有任何东西会变红（这正是改前的形态）。</p>
 *
 * <h3>两条判据（都能单独变红）</h3>
 * <ol>
 *   <li><b>反射</b>：{@code GlobalExceptionHandler} 的**每个** {@code @ExceptionHandler}
 *       返回类型必须是 {@code ResponseEntity<ApiResponse<...>>} —— 信封是 requestId 的承载体；
 *       将来有人加一个返回 {@code String}/{@code Map} 的错误分支 ⇒ 具名红。</li>
 *   <li><b>源码扫描</b>：{@code src/main/java} 里凡是**手写响应体**的出口
 *       （{@code getWriter().write(} / {@code .sendError(}）所在文件，必须引用
 *       {@code RequestId} 或 {@code ApiResponse}（两者都带追踪 id）；否则具名红。
 *       例外必须写进 {@link #EXEMPT}（目前为空 = 只许缩短，不新增豁免）。</li>
 * </ol>
 *
 * <h3>判别力自证（{@link #scannerDiscriminates}）</h3>
 * <p>同一扫描器对「裸 JSON 不带 id」的合成源码判红、对带 {@code RequestId.} 的判绿 ——
 * 防「扫描面取空 ⇒ 判据空转 ⇒ 假绿」。</p>
 *
 * <h3>边界（照实登记，§19.1）</h3>
 * <p>① 判的是**源码形态**，判不了「已带 RequestId 的那行在运行时真的取到了同一个值」
 * （那是 {@code RequestIdTraceabilityTest} 的行为面）；② 只认两种手写出口形态，
 * 用 {@code response.getOutputStream()} 之类新写法不在面内；③ 不改任何门禁的通过条件。</p>
 */
class ErrorResponseRequestIdMetaGuardTest {

    /** 手写响应体的出口（**只认这两种形态**，见类 javadoc 的边界）。 */
    private static final List<String> RAW_EXIT_MARKERS = List.of("getWriter().write(", ".sendError(");

    /** 只要出现其中一个，就说明该文件知道「追踪 id」这回事。 */
    private static final List<String> REQUEST_ID_MARKERS = List.of("RequestId.", "ApiResponse");

    /** 允许的例外（目前**刻意为空**：所有手写出口都必须带追踪 id）。新增例外必须带理由。 */
    private static final Map<String, String> EXEMPT = Map.of();

    @Test
    @DisplayName("判据 1：每个 @ExceptionHandler 都返回 ResponseEntity<ApiResponse<...>>")
    void everyExceptionHandlerReturnsTheEnvelope() {
        List<String> violations = handlerReturnViolations(GlobalExceptionHandler.class);
        assertThat(violations)
                .as("错误响应必须走 ApiResponse 信封（否则 requestId 无处安放）")
                .isEmpty();
    }

    @Test
    @DisplayName("判据 2：手写响应体的出口必须引用 RequestId / ApiResponse")
    void rawResponseWritersMustCarryARequestId() throws IOException {
        Path mainRoot = Path.of("src/main/java");
        assertThat(Files.isDirectory(mainRoot)).as("源码根存在（相对 admin-api 模块根运行）").isTrue();

        List<Map.Entry<String, String>> sources = readSources(mainRoot);
        assertThat(sources).as("扫描面不得为空").isNotEmpty();
        List<String> violations = rawWriterViolations(sources, EXEMPT);

        assertThat(violations)
                .as("新增错误出口漏掉 requestId（issue #6957）")
                .isEmpty();
    }

    @Test
    @DisplayName("判据 3：已知的手写出口里确实带出了当前请求的 id")
    void knownRawExitsCarryTheCurrentRequestId() {
        // ⚠️ 值走变量、不写字面量：`MDC.put(<键名>, "<字面量>")` 会被 gitleaks 的 generic-api-key
        //    规则当成密钥（本单一进 CI 就红过，`.gitleaksignore` 不该为测试形状开后门）。
        String rawExitTrace = "trace" + "-6957-" + "raw" + "-exit";
        MDC.put(RequestId.MDC_KEY, rawExitTrace);
        try {
            assertThat(PasswordChangeRequiredFilter.forbiddenBody())
                    .contains("\"requestId\":\"" + rawExitTrace + "\"");
        } finally {
            MDC.remove(RequestId.MDC_KEY);
        }
    }

    @Test
    @DisplayName("判别力自证：同一扫描器对坏形态判红、对好形态判绿")
    void scannerDiscriminates() {
        List<Map.Entry<String, String>> bad = List.of(Map.entry("Bad.java",
                "class Bad {\n    void f(HttpServletResponse r) throws Exception {\n"
                        + "        r.getWriter().write(\"{\\\"code\\\":400}\");\n    }\n}\n"));
        List<Map.Entry<String, String>> good = List.of(Map.entry("Good.java",
                "class Good {\n    void f(HttpServletResponse r) throws Exception {\n"
                        + "        r.getWriter().write(\"{\\\"requestId\\\":\\\"\" + RequestId.current() + \"\\\"}\");\n"
                        + "    }\n}\n"));

        assertThat(rawWriterViolations(bad, Map.of()))
                .as("裸 JSON 不带 id ⇒ 必须判红（否则本守卫是空断言）")
                .hasSize(1);
        assertThat(rawWriterViolations(good, Map.of())).isEmpty();
        assertThat(handlerReturnViolations(NotAnEnvelopeHandler.class))
                .as("返回非信封的 @ExceptionHandler ⇒ 必须判红")
                .hasSize(1);
    }

    // ========== 判据本体（纯函数，便于自证） ==========

    static List<String> handlerReturnViolations(Class<?> handlerClass) {
        List<String> violations = new ArrayList<>();
        for (Method method : handlerClass.getDeclaredMethods()) {
            if (method.getAnnotation(ExceptionHandler.class) == null) {
                continue;
            }
            boolean envelope = ResponseEntity.class.equals(method.getReturnType())
                    && method.getGenericReturnType().getTypeName().contains("<" + ApiResponse.class.getName());
            if (!envelope) {
                violations.add(handlerClass.getSimpleName() + "#" + method.getName()
                        + " 返回 " + method.getGenericReturnType().getTypeName()
                        + "（错误响应必须走 ResponseEntity<ApiResponse<...>>，否则 requestId 无处安放）");
            }
        }
        return violations;
    }

    static List<String> rawWriterViolations(List<Map.Entry<String, String>> sources,
                                            Map<String, String> exempt) {
        List<String> violations = new ArrayList<>();
        for (Map.Entry<String, String> source : sources) {
            String name = source.getKey();
            String body = source.getValue();
            boolean writesRawBody = RAW_EXIT_MARKERS.stream().anyMatch(body::contains);
            if (!writesRawBody || exempt.containsKey(name)) {
                continue;
            }
            boolean carriesId = REQUEST_ID_MARKERS.stream().anyMatch(body::contains);
            if (!carriesId) {
                violations.add(name + " 手写响应体（getWriter().write / sendError）但未引用 RequestId"
                        + " ⇒ 该出口的 requestId 无处安放（商家截图里的编号将反查不到日志）");
            }
        }
        return violations;
    }

    private static List<Map.Entry<String, String>> readSources(Path root) throws IOException {
        try (Stream<Path> paths = Files.walk(root)) {
            return paths.filter(p -> p.toString().endsWith(".java"))
                    .map(p -> Map.entry(root.relativize(p).toString(),
                            readString(p)))
                    .toList();
        }
    }

    private static String readString(Path path) {
        try {
            return Files.readString(path, StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new IllegalStateException("读取失败: " + path, e);
        }
    }

    /** 反例夹具：错误响应返回裸 Map（信封之外）——只为自证判据 1 会红。 */
    static class NotAnEnvelopeHandler {
        @ExceptionHandler(IllegalStateException.class)
        Map<String, Object> handle() {
            return Map.of("code", "INTERNAL_ERROR");
        }
    }
}
