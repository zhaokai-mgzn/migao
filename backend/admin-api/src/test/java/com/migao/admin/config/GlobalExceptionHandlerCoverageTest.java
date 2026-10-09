// case_ids: API-008, MC-090
package com.migao.admin.config;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.MissingPathVariableException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.multipart.support.MissingServletRequestPartException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.bind.ServletRequestBindingException;

import java.io.IOException;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 类级元守卫（铁律 8）：**让「新增异常类型却忘了登记到处理器」再也不可能悄悄发生**（issue #5982）。
 *
 * <p>病（#5982 的机制级归因）：{@code config/GlobalExceptionHandler} 只对**它认得**的异常给具名分支，
 * 认不得的一律落兜底 {@code Exception} ⇒ <b>500</b>。请求绑定失败（缺必填 {@code @RequestParam}、
 * 参数类型不符）本是**客户端错误**，却报成服务端故障。修一个类型只修了这一处 ——
 * 下一个没登记的异常类型会照样落 500，**而没有任何东西会变红**。</p>
 *
 * <p>本守卫由三张表 + 一条行为判据构成：</p>
 * <ol>
 *   <li><b>分支台账</b> {@link #BRANCH_LEDGER} ⇄ 反射出的 {@code @ExceptionHandler} 目标类型
 *       <b>双向相等</b>（兜底 {@code Exception.class} 除外）⇒ ① 台账里有、处理器没有 = 红（= #5982 形态）；
 *       ② 处理器有、台账里没有 = 红（新增分支没登记）。</li>
 *   <li><b>契约台账</b> {@link #BINDING_FAMILY}（请求绑定失败族）：每个成员要么有具名分支，
 *       要么在 {@link #EXEMPT_BASELINE} 里有理由地登记。</li>
 *   <li><b>豁免台账只许缩短</b>：现取豁免 ⊆ 冻结基线；每条必须有理由；已被处理的「陈旧豁免」判红；
 *       {@code MissingRequestHeaderException} 的豁免附带**可判前置**（本仓必须 0 处必填
 *       {@code @RequestHeader}）—— 将来有人加了必填请求头，这条豁免当场失效并判红。</li>
 * </ol>
 *
 * <p>判据本体是纯函数（{@link #ledgerViolations} / {@link #familyViolations} /
 * {@link #exemptionViolations}），因此「本守卫自己会不会红」可以就地自证（见
 * {@link #guardDiscriminates()}）—— 防御「反射取空 ⇒ 判据空转 ⇒ 假绿」。</p>
 *
 * <p><b>未固化项（照实登记，§19.1）</b>：① 静态判据判不了「一个全新 Spring 异常类型在运行时首次出现
 * 而无人登记」（没有任何静态信号）；本守卫只保证**已登记/已处理的两个集合恒等** + 绑定族无裸露成员。
 * ② 源码扫描只覆盖 {@code @RequestHeader} / {@code @RequestParam} 注解的**字面形态**（书写风格变了
 * 即可能漏判 —— 漏判方向是假绿，不是假红）。</p>
 */
@DisplayName("GlobalExceptionHandler 覆盖台账（#5982）：分支/绑定族/豁免三表一致，绑定失败不落 500")
class GlobalExceptionHandlerCoverageTest {

    /**
     * 分支台账：处理器**具名分支**的目标类型（兜底 {@code Exception.class} 不在此表 ——
     * 它是「其余全部」，登记它等于把台账变成同义反复）。
     * 新增/删除任何 {@code @ExceptionHandler} 都必须同步本表，否则红。
     */
    private static final Set<String> BRANCH_LEDGER = Set.of(
            "com.migao.admin.exception.BusinessException",
            "org.springframework.web.bind.MethodArgumentNotValidException",
            "jakarta.validation.ConstraintViolationException",
            "org.springframework.security.core.AuthenticationException",
            "org.springframework.security.access.AccessDeniedException",
            "java.lang.IllegalArgumentException",
            "java.lang.IllegalStateException",
            "org.springframework.web.HttpRequestMethodNotSupportedException",
            "org.springframework.web.servlet.NoHandlerFoundException",
            "org.springframework.http.converter.HttpMessageNotReadableException",
            "org.springframework.web.HttpMediaTypeNotSupportedException",
            // ↓ #5982 本单补的两个分支
            "org.springframework.web.bind.MissingServletRequestParameterException",
            "org.springframework.web.method.annotation.MethodArgumentTypeMismatchException",
            // ↓ #6008：同族漏掉的第三个（缺必填 multipart 部分）
            "org.springframework.web.multipart.support.MissingServletRequestPartException",
            // ↓ #6210：数据库完整性约束违例（外键 / 唯一 / 非空 / 检查）—— 客户端引用了库里不存在的行；
            //   改前**无**具名分支 ⇒ 落兜底 500，且 log.error(…, e) 把约束名写进日志。
            //   行为判据（4xx + 日志脱敏 / 不脱敏两侧）= GlobalExceptionHandlerDataIntegrityTest（用例 MC-090）
            "org.springframework.dao.DataIntegrityViolationException"
    );

    /** 请求绑定失败族：Spring 在「把 HTTP 请求绑定到控制器方法参数」时抛出的异常家族。 */
    private static final Set<String> BINDING_FAMILY = Set.of(
            MissingServletRequestParameterException.class.getName(),
            MethodArgumentTypeMismatchException.class.getName(),
            // ↓ #6008：同族里被漏掉的那个成员 —— 本仓有**可达**的 multipart 端点
            // （`POST /api/admin/inbound-orders/opening-import` 的 `file`），客户端少传一个 part 曾落兜底 500
            MissingServletRequestPartException.class.getName(),
            HttpMessageNotReadableException.class.getName(),
            MissingRequestHeaderException.class.getName(),
            MissingPathVariableException.class.getName(),
            ServletRequestBindingException.class.getName()
    );

    /**
     * 豁免台账（**冻结基线，只许缩短**）—— 现取豁免必须是它的子集。
     * 每条都是「有意不处理 + 为什么可以」的结论，不是遗漏。
     */
    private static final Map<String, String> EXEMPT_BASELINE = Map.of(
            MissingRequestHeaderException.class.getName(),
            "本仓 0 处必填 @RequestHeader（现取：main 源码全部 @RequestHeader 都写了 required=false）"
                    + "⇒ 该异常不可达；前置由 requiredRequestHeaderCount() 判，非空即本条豁免失效并判红",
            MissingPathVariableException.class.getName(),
            "缺 @PathVariable 是**服务端**映射配置错误（Spring 语义即 500），报 500 正确，不该降成 400",
            ServletRequestBindingException.class.getName(),
            "父类兜底会把 MissingPathVariableException 一并变成 400（语义错误）⇒ 有意不做父类分支；"
                    + "未覆盖的其它子类仍落 500（残余，见类注释「未固化项」）"
    );

    // ======================== 判据 ========================

    @Test
    @DisplayName("分支台账 ⇄ @ExceptionHandler 目标类型 双向相等（多一个/少一个都判红并具名）")
    void handlerBranchLedgerMatchesReflection() {
        Set<String> declared = declaredBranchTargets();
        Set<String> named = new TreeSet<>(declared);
        named.remove(Exception.class.getName());

        // 防御空转：反射拿不到东西时下面两条会「两个空集相等」而假绿
        assertThat(declared)
                .as("反射未取到任何 @ExceptionHandler（判据会空转，先修反射口径）")
                .isNotEmpty();
        assertThat(declared)
                .as("兜底分支 Exception 必须仍在（它被削掉 = 未知异常会漏出原始堆栈）")
                .contains(Exception.class.getName());

        assertThat(ledgerViolations(named, BRANCH_LEDGER)).isEmpty();
    }

    @Test
    @DisplayName("请求绑定族：每个成员要么有具名分支、要么在豁免台账里有理由（裸露成员判红）")
    void bindingFamilyIsHandledOrExplicitlyExempt() {
        assertThat(familyViolations(BINDING_FAMILY, handledBranchTargets(), EXEMPT_BASELINE)).isEmpty();
    }

    @Test
    @DisplayName("豁免台账只许缩短 + 理由可判：超基线/陈旧豁免/必填请求头出现 各自判红")
    void exemptionsOnlyShrinkAndStayJustified() throws IOException {
        Map<String, String> current = new LinkedHashMap<>();
        for (String type : BINDING_FAMILY) {
            if (!handledBranchTargets().contains(type)) {
                current.put(type, EXEMPT_BASELINE.get(type));
            }
        }

        HeaderScan scan = scanRequestHeaders();
        // 防御空转：扫不到任何 @RequestHeader ⇒ 前置判据会「因为 0 而通过」
        assertThat(scan.total())
                .as("源码扫描未命中任何 @RequestHeader（扫描口径坏了，前置判据会空转）")
                .isGreaterThan(0);

        assertThat(exemptionViolations(current, EXEMPT_BASELINE, handledBranchTargets(), scan.required()))
                .isEmpty();
        assertThat(current.keySet())
                .as("现取豁免必须是冻结基线的子集（只许缩短）")
                .isSubsetOf(EXEMPT_BASELINE.keySet());
    }

    @Test
    @DisplayName("行为判据：绑定失败一律 4xx（不是 500），未知异常仍 500（双向对照）")
    void bindingFailuresNeverFallThroughTo500() throws Exception {
        MockMvc mvc = MockMvcBuilders.standaloneSetup(new ProbeController())
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();

        // 缺必填参数（真 Spring 分发链抛出的就是 MissingServletRequestParameterException）
        mvc.perform(post("/probe/required-param"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("BAD_REQUEST"))
                .andExpect(jsonPath("$.error.details[0].field").value("importRunId"));

        // 参数类型不符（MethodArgumentTypeMismatchException）
        mvc.perform(get("/probe/typed").param("openingId", "不是数字"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("BAD_REQUEST"))
                .andExpect(jsonPath("$.error.details[0].field").value("openingId"));

        // 缺必填 multipart 部分（MissingServletRequestPartException）—— issue #6008：
        // 真 Spring 分发链在 @RequestPart 未标 required=false 而请求缺该 part 时抛的就是它。
        mvc.perform(multipart("/probe/part"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error.code").value("BAD_REQUEST"))
                .andExpect(jsonPath("$.error.details[0].field").value("file"));

        // 反向对照：无具名分支的异常（裸 RuntimeException）仍是 500 —— 证明上面三个 400 是
        // 「具名分支生效」，不是「什么东西都返 400」。
        // ⚠️ 别拿 IllegalStateException 当对照：它**有**具名分支（400）
        mvc.perform(get("/probe/boom"))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.error.code").value("INTERNAL_ERROR"));
    }

    @Test
    @DisplayName("判别力自证：四类坏形态在内存里各自判红（防判据退化成恒绿）")
    void guardDiscriminates() {
        Set<String> handled = handledBranchTargets();

        // ① 台账有、处理器没有（= #5982 形态：删掉分支）
        Set<String> withoutMissingParam = new TreeSet<>(handled);
        withoutMissingParam.remove(MissingServletRequestParameterException.class.getName());
        assertThat(ledgerViolations(withoutMissingParam, BRANCH_LEDGER))
                .anyMatch(v -> v.contains("MissingServletRequestParameterException"));

        // ② 处理器有、台账没有（新增分支没登记）
        Set<String> withUnregistered = new TreeSet<>(handled);
        withUnregistered.add("org.springframework.web.HttpSessionRequiredException");
        assertThat(ledgerViolations(withUnregistered, BRANCH_LEDGER))
                .anyMatch(v -> v.contains("HttpSessionRequiredException"));

        // ③ 豁免超基线（只许缩短被违反）
        Map<String, String> expanded = new LinkedHashMap<>(EXEMPT_BASELINE);
        expanded.put("org.springframework.web.HttpSessionRequiredException", "顺手加的");
        assertThat(exemptionViolations(expanded, EXEMPT_BASELINE, handled, 0))
                .anyMatch(v -> v.contains("只许缩短") && v.contains("HttpSessionRequiredException"));

        // ④ 必填 @RequestHeader 出现 ⇒ MissingRequestHeaderException 的豁免失效
        assertThat(exemptionViolations(EXEMPT_BASELINE, EXEMPT_BASELINE, handled, 1))
                .anyMatch(v -> v.contains("MissingRequestHeaderException"));

        // ⑤ 族里新增了成员却没人给具名分支 ⇒ **族判据**具名判红（= #6008 的形态本身）
        Set<String> withoutPart = new TreeSet<>(handled);
        withoutPart.remove(MissingServletRequestPartException.class.getName());
        assertThat(familyViolations(BINDING_FAMILY, withoutPart, EXEMPT_BASELINE))
                .anyMatch(v -> v.contains("MissingServletRequestPartException"));

        // 对照：合法输入不判红（证明上面五条不是「什么输入都报」）
        assertThat(ledgerViolations(handled, BRANCH_LEDGER)).isEmpty();
        assertThat(exemptionViolations(EXEMPT_BASELINE, EXEMPT_BASELINE, handled, 0)).isEmpty();
    }

    // ======================== 判据本体（纯函数，便于自证判别力） ========================

    static List<String> ledgerViolations(Set<String> handled, Set<String> ledger) {
        List<String> violations = new ArrayList<>();
        for (String type : ledger) {
            if (!handled.contains(type)) {
                violations.add("处理器缺具名分支（该异常会落兜底 500）: " + type);
            }
        }
        for (String type : handled) {
            if (!ledger.contains(type)) {
                violations.add("分支未登记到台账: " + type);
            }
        }
        return violations;
    }

    static List<String> familyViolations(Set<String> family, Set<String> handled, Map<String, String> exempt) {
        List<String> violations = new ArrayList<>();
        for (String type : family) {
            if (!handled.contains(type) && !exempt.containsKey(type)) {
                violations.add("请求绑定族成员既无具名分支也未在豁免台账登记: " + type);
            }
        }
        return violations;
    }

    static List<String> exemptionViolations(Map<String, String> current, Map<String, String> frozenBaseline,
                                            Set<String> handled, int requiredHeaderCount) {
        List<String> violations = new ArrayList<>();
        current.forEach((type, reason) -> {
            if (reason == null || reason.isBlank()) {
                violations.add("豁免缺理由: " + type);
            }
            if (!frozenBaseline.containsKey(type)) {
                violations.add("豁免超出冻结基线（只许缩短）: " + type);
            }
            if (handled.contains(type)) {
                violations.add("陈旧豁免（已有具名分支，请从台账删除）: " + type);
            }
            if (MissingRequestHeaderException.class.getName().equals(type) && requiredHeaderCount > 0) {
                violations.add("本仓出现必填 @RequestHeader（现取 " + requiredHeaderCount
                        + " 处）⇒ 该异常已可达，缺必填请求头会 500；请补分支或撤销豁免: " + type);
            }
        });
        return violations;
    }

    // ======================== 反射 / 源码扫描 ========================

    /** 处理器声明的全部 {@code @ExceptionHandler} 目标类型（含兜底 {@code Exception.class}）。 */
    static Set<String> declaredBranchTargets() {
        Set<String> targets = new TreeSet<>();
        for (Method method : GlobalExceptionHandler.class.getDeclaredMethods()) {
            ExceptionHandler annotation = method.getAnnotation(ExceptionHandler.class);
            if (annotation == null || method.isSynthetic()) {
                continue;
            }
            for (Class<?> type : annotation.value()) {
                targets.add(type.getName());
            }
        }
        return targets;
    }

    /** 处理器声明的**具名**分支目标类型（去掉兜底 {@code Exception.class}）。 */
    static Set<String> handledBranchTargets() {
        Set<String> targets = new TreeSet<>(declaredBranchTargets());
        targets.remove(Exception.class.getName());
        return targets;
    }

    /** main 源码里 {@code @RequestHeader} 的（总数, 必填数）—— 豁免台账的可判前置。 */
    static HeaderScan scanRequestHeaders() throws IOException {
        Pattern annotation = Pattern.compile("@RequestHeader\\s*(\\(([^()]*)\\))?");
        int total = 0;
        int required = 0;
        try (Stream<Path> files = Files.walk(mainSourceRoot())) {
            for (Path file : files.filter(p -> p.toString().endsWith(".java")).toList()) {
                String text = stripComments(Files.readString(file));
                Matcher matcher = annotation.matcher(text);
                while (matcher.find()) {
                    total++;
                    String args = matcher.group(2);
                    if (args == null || !args.replace(" ", "").contains("required=false")) {
                        required++;
                    }
                }
            }
        }
        return new HeaderScan(total, required);
    }

    private static String stripComments(String text) {
        return text.replaceAll("(?s)/\\*.*?\\*/", "").replaceAll("//[^\n]*", "");
    }

    private static Path mainSourceRoot() {
        for (String candidate : List.of("src/main/java", "backend/admin-api/src/main/java")) {
            Path path = Path.of(candidate);
            if (Files.isDirectory(path)) {
                return path;
            }
        }
        throw new IllegalStateException(
                "找不到 admin-api 主源码根（试过 src/main/java 与 backend/admin-api/src/main/java）");
    }

    record HeaderScan(int total, int required) {
    }

    /** 探针控制器：让 Spring **自己**抛出绑定异常（不手造异常对象）。 */
    @RestController
    static class ProbeController {

        @PostMapping("/probe/required-param")
        String requiredParam(@RequestParam("importRunId") String importRunId) {
            return importRunId;
        }

        @GetMapping("/probe/typed")
        String typed(@RequestParam("openingId") Long openingId) {
            return String.valueOf(openingId);
        }

        @PostMapping("/probe/part")
        String part(@RequestPart("file") MultipartFile file) {
            return "ok:" + file.getOriginalFilename();
        }

        @GetMapping("/probe/boom")
        String boom() {
            throw new RuntimeException("探针：无具名分支的异常必须仍走兜底 500");
        }
    }
}
