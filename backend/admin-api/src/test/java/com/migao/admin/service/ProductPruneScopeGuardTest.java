// case_ids: PR-010, PR-021
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 🛡️ <b>类级元守卫：改品 prune 只许删「本次请求声明过的维度」（issue #5515）</b>。
 *
 * <h2>守的是什么形态（不是这一个实例）</h2>
 * 病灶形态 = <b>「请求没声明的维度」被当成「声明为空」⇒ 静默删除该维度的全部行</b>。
 * 颜色那一维删下去会经 {@code product_skus.color_id ON DELETE CASCADE} 连带删掉 SKU 行
 * （真库读数 2 → 0，见 {@code ProductUpdatePruneScopeRealDbTest}）。
 * 实例判据只钉住「颜色 / SKU 这两维今天是对的」；本守卫钉住的是<b>这个块的结构</b>：
 * {@code if (pruneMissing)} 里出现的<b>每一处 {@code deleteById}</b> 都必须落在
 * 「声明检查」（{@code xxx != null}）之内，且这对「(删除目标, 守卫条件)」必须在
 * {@link #REGISTERED_DIMENSIONS} 登记表里 —— <b>未登记即红、登记表条目归零也要删格子</b>。
 *
 * <h2>判据（每条都能单独变红）</h2>
 * <ol>
 *   <li><b>判据1·真实源码无违规</b>：prune 块里的 deleteById 全部被登记过的声明检查覆盖，
 *       且登记表与源码<b>逐格对齐</b>（少了 / 多了都红）；</li>
 *   <li><b>判据2·注入红证（守卫被摘掉）</b>：把 {@code if (skuInputs != null)} 改成 {@code if (true)}
 *       ⇒ 判据必须红（否则本守卫是空断言）；</li>
 *   <li><b>判据3·注入红证（未登记的维度）</b>：把颜色那一维的守卫换成没登记的
 *       {@code if (doorWidths != null)} ⇒ 判据必须红（未登记即红）；</li>
 *   <li><b>判据4·注释不算代码</b>：把 {@code //} 注释里出现 {@code deleteById} 注入进去 ⇒
 *       不得被当成删除点（否则守卫会被文案喂红，同族自伤见 {@code docs/wiki} 的类级固化节）。</li>
 * </ol>
 *
 * <h2>未固化 / 边界（如实登记）</h2>
 * 本守卫只覆盖 {@code ProductService} 的这一个 prune 块（锚点 = 字面量 {@code if (pruneMissing) {}）；
 * 别的服务里若有同形态（「未声明 ⇒ 删」）不会被它拦下 —— 那些面没有登记表。
 */
@DisplayName("类级元守卫：改品 prune 块只许删请求声明过的维度（issue #5515）")
class ProductPruneScopeGuardTest {

    /**
     * 登记表（**未登记即红；条目归零 ⇒ 从本表删掉那一格**）：
     * 「prune 块里的删除目标」→「必须先成立的声明检查」。
     */
    private static final Map<String, String> REGISTERED_DIMENSIONS =
            new LinkedHashMap<>(Map.of(
                    "productSkuMapper.deleteById", "colorInputs != null && skuInputs != null",
                    "productColorMapper.deleteById", "colorInputs != null"));

    private static final String PRUNE_ANCHOR = "if (pruneMissing) {";
    private static final Pattern DELETE_CALL = Pattern.compile("(\\w+Mapper)\\.deleteById\\s*\\(");
    private static final String SOURCE_PATH =
            "backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java";

    @Test
    @DisplayName("判据1·真实源码：prune 块里的每一处 deleteById 都在登记过的声明检查内（且登记表逐格对齐）")
    void pruneBlockDeletesOnlyDeclaredDimensions() throws IOException {
        String source = readProductServiceSource();
        String block = pruneBlockOf(source);
        System.out.println("[#5515 守卫] prune 块 =\n" + block);

        List<String> violations = violationsOf(source);
        assertThat(violations)
                .as("prune 块里出现「未声明就删」的删除点（病灶形态：请求没提的维度被当成声明为空）")
                .isEmpty();

        assertThat(guardedDeletesOf(source).keySet())
                .as("登记表必须与源码逐格对齐：少了 = 有条目已归零（从 %s 里删掉那一格）；"
                        + "多了 = 新维度未登记（同 PR 补登记 + 一条真库判据）", "REGISTERED_DIMENSIONS")
                .containsExactlyInAnyOrderElementsOf(REGISTERED_DIMENSIONS.keySet());
    }

    @Test
    @DisplayName("判据2·注入红证：摘掉「声明检查」（整条守卫 → if (true)）⇒ 守卫必须红")
    void removingDeclarationGuardTurnsRed() throws IOException {
        String mutated = readProductServiceSource()
                .replace("if (colorInputs != null && skuInputs != null) {", "if (true) {");
        assertThat(mutated).as("注入必须真的生效（自证坐标：找不到锚点 ⇒ 本红证是空跑）")
                .contains("if (true) {");

        List<String> violations = violationsOf(mutated);
        System.out.println("[#5515 守卫 判据2] 注入后的违规 = " + violations);
        assertThat(violations).as("摘掉声明检查后，SKU 那一处删除必须被判成「未声明就删」").isNotEmpty();
        assertThat(violations).anySatisfy(v -> assertThat(v).contains("productSkuMapper.deleteById"));
    }

    @Test
    @DisplayName("判据3·注入红证：冒出未登记的守卫条件（colorInputs → doorWidths）⇒ 未登记即红")
    void unregisteredDimensionTurnsRed() throws IOException {
        String mutated = readProductServiceSource().replace("if (colorInputs != null) {", "if (doorWidths != null) {");
        assertThat(mutated).as("注入必须真的生效（自证坐标）").contains("if (doorWidths != null) {");

        List<String> violations = violationsOf(mutated);
        System.out.println("[#5515 守卫 判据3] 注入后的违规 = " + violations);
        assertThat(violations).as("未登记的「(删除目标, 守卫条件)」组合必须红").isNotEmpty();
        assertThat(violations).anySatisfy(v -> assertThat(v).contains("未登记"));
    }

    @Test
    @DisplayName("判据4·注释不算代码：// 注释里写 deleteById 不得被当成删除点（防「被自己的文案喂红」）")
    void commentsAreNotCode() throws IOException {
        String mutated = readProductServiceSource().replace(PRUNE_ANCHOR,
                PRUNE_ANCHOR + "\n            // 文案注入：productSkuMapper.deleteById(s.getId()) 只是说明，不是代码");
        assertThat(mutated).as("注入必须真的生效（自证坐标）").contains("文案注入");

        System.out.println("[#5515 守卫 判据4] 注了带 deleteById 的注释后的违规 = " + violationsOf(mutated));
        assertThat(violationsOf(mutated))
                .as("注释里的 deleteById 不是删除点 ⇒ 不得产生违规（也不得再多出一个「登记表对不上」）")
                .isEmpty();
    }

    // ══════════════════════════════════ 守卫本体（纯函数，便于注入式自证）

    /**
     * 违规清单：prune 块里「落不到登记表的删除点」——
     * ① 不在任何声明检查内的 {@code deleteById}；② 守卫条件不含 {@code != null}；
     * ③ 「(删除目标, 守卫条件)」未登记。
     */
    private static List<String> violationsOf(String source) {
        String block = stripComments(pruneBlockOf(source));
        List<String> violations = new ArrayList<>();
        for (Map.Entry<String, String> guarded : guardedDeletesOf(source).entrySet()) {
            String deleteKey = guarded.getKey();
            String condition = guarded.getValue();
            if (!condition.contains("!= null")) {
                violations.add("未声明就删：" + deleteKey + " 落在没有声明检查的守卫里（condition=" + condition + "）");
            } else if (!REGISTERED_DIMENSIONS.containsKey(deleteKey)) {
                violations.add("未登记：" + deleteKey + " 未在 REGISTERED_DIMENSIONS 登记（新增维度必须补登记）");
            } else if (!REGISTERED_DIMENSIONS.get(deleteKey).equals(condition)) {
                violations.add("未登记：" + deleteKey + " 的守卫条件 " + condition
                        + " 与登记表（" + REGISTERED_DIMENSIONS.get(deleteKey) + "）不一致");
            }
        }
        for (String loose : looseDeleteCalls(block)) {
            violations.add("未声明就删：" + loose + " 不在 prune 块的任何声明检查内（块级兜底删除 = 病灶形态）");
        }
        return violations;
    }

    /** 删除点 → 它所在的**最外层**声明检查条件（prune 块内）。 */
    private static Map<String, String> guardedDeletesOf(String source) {
        Map<String, String> guarded = new LinkedHashMap<>();
        for (Segment segment : segmentsOf(stripComments(pruneBlockOf(source)))) {
            Matcher m = DELETE_CALL.matcher(segment.body());
            while (m.find()) {
                guarded.putIfAbsent(m.group(1) + ".deleteById", segment.condition());
            }
        }
        return guarded;
    }

    /** prune 块里**不在任何子块内**的 deleteById（块级兜底删除）。 */
    private static List<String> looseDeleteCalls(String strippedBlock) {
        List<String> loose = new ArrayList<>();
        Matcher m = DELETE_CALL.matcher(withoutSegments(strippedBlock));
        while (m.find()) {
            loose.add(m.group(1) + ".deleteById");
        }
        return loose;
    }

    private record Segment(String condition, String body) {
    }

    /** prune 块的**顶层**子块（{@code if (cond) { ... }}）：取条件与其块体。 */
    private static List<Segment> segmentsOf(String block) {
        List<Segment> segments = new ArrayList<>();
        int i = 0;
        while (i < block.length()) {
            if (block.startsWith("if (", i)) {
                int condStart = i + 4;
                int condEnd = matchParen(block, condStart - 1);
                int braceStart = block.indexOf('{', condEnd);
                int braceEnd = matchBrace(block, braceStart);
                segments.add(new Segment(
                        block.substring(condStart, condEnd).trim(),
                        block.substring(braceStart + 1, braceEnd)));
                i = braceEnd + 1;
            } else {
                i++;
            }
        }
        return segments;
    }

    /** 去掉所有顶层子块后的剩余文本（块级散落代码）。 */
    private static String withoutSegments(String block) {
        StringBuilder out = new StringBuilder();
        int i = 0;
        while (i < block.length()) {
            if (block.startsWith("if (", i)) {
                int condEnd = matchParen(block, i + 3);
                int braceStart = block.indexOf('{', condEnd);
                i = matchBrace(block, braceStart) + 1;
            } else {
                out.append(block.charAt(i));
                i++;
            }
        }
        return out.toString();
    }

    private static String pruneBlockOf(String source) {
        int anchor = source.indexOf(PRUNE_ANCHOR);
        assertThat(anchor).as("必须在 ProductService 里找到 prune 块的锚点 %s（找不到 ⇒ 守卫失锚，先修锚点）",
                PRUNE_ANCHOR).isGreaterThan(-1);
        int open = source.indexOf('{', anchor);
        int close = matchBrace(source, open);
        return source.substring(open + 1, close);
    }

    private static int matchBrace(String text, int openIdx) {
        int depth = 0;
        for (int i = openIdx; i < text.length(); i++) {
            if (text.charAt(i) == '{') {
                depth++;
            } else if (text.charAt(i) == '}') {
                depth--;
                if (depth == 0) {
                    return i;
                }
            }
        }
        throw new IllegalStateException("花括号不配对（openIdx=" + openIdx + "）");
    }

    private static int matchParen(String text, int openIdx) {
        int depth = 0;
        for (int i = openIdx; i < text.length(); i++) {
            if (text.charAt(i) == '(') {
                depth++;
            } else if (text.charAt(i) == ')') {
                depth--;
                if (depth == 0) {
                    return i;
                }
            }
        }
        throw new IllegalStateException("圆括号不配对（openIdx=" + openIdx + "）");
    }

    /** 剥掉行注释与块注释（**原文不等于代码**：注释里的 deleteById 不是删除点）。 */
    private static String stripComments(String text) {
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (ch == '/' && i + 1 < text.length() && text.charAt(i + 1) == '/') {
                while (i < text.length() && text.charAt(i) != '\n') {
                    i++;
                }
                out.append('\n');
            } else if (ch == '/' && i + 1 < text.length() && text.charAt(i + 1) == '*') {
                i += 2;
                while (i + 1 < text.length() && !(text.charAt(i) == '*' && text.charAt(i + 1) == '/')) {
                    i++;
                }
                i++;
            } else {
                out.append(ch);
            }
        }
        return out.toString();
    }

    private static String readProductServiceSource() throws IOException {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null && !Files.exists(root.resolve(SOURCE_PATH))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位 %s（守卫的真值源 = 仓库里的源文件，不是工作树的副本）", SOURCE_PATH)
                .isNotNull();
        return Files.readString(root.resolve(SOURCE_PATH));
    }
}