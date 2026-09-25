// case_ids: PR-081
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 类级元守卫（issue #5550）：{@code processing_info} 归一化结果的**每一处解引用**都必须先处理 null。
 *
 * <h2>为什么要有它（只修一处 = 没修）</h2>
 * 2026-09-25 的 P0：池看板**恒 500**，根因是 `buildSnapshot` 里
 * {@code str(pi.get("saleForm"))} —— {@code pi} 来自归一化函数，而 `order_items.processing_info`
 * **可为 NULL**（真库实证：待派池 29 行里 15 行是 NULL），于是必 NPE。
 * 同一形态在 {@code RemnantService.specialOptionsOf} 里**一模一样地存在**
 * （{@code normalize(...).get("specialOptions")} 直连解引用）—— 同一类缺陷，两处实例。
 *
 * <p>⇒ 只补两条实例断言是不够的：**下一次新调用点照样能这么写**。本判据把「这一类」变成会红的：
 * 普查 {@code src/main/java} 下**所有**对归一化入口的调用，逐条要求 null 处理面；
 * 新增/搬动的调用点若没判 null ⇒ **当场红**，报告里给文件:行 + 出口。</p>
 *
 * <h2>判据（两条形态，各自能单独变红）</h2>
 * <ol>
 *   <li><b>直连解引用</b>：调用结果**不落变量**就接 {@code .get(...)} 等解引用
 *       ⇒ 没有放 null 判定的位置 ⇒ 红（红证 = {@code RemnantService} 修复前的写法）；
 *   <li><b>变量形态</b>：结果落到变量后，**紧邻窗口内**必须出现该变量的 null 判定
 *       ⇒ 红（红证 = {@code ProcessingOrderService.buildSnapshot} 修复前的写法：{@code pi} 落变量、
 *       窗口内没有任何 {@code pi == null}）。
 * </ol>
 *
 * <p><b>非空跑自证</b>（机制存活读数）：普查面必须**真的**扫到调用点，且两个归一化入口的名字
 * 在 main 源码里各至少出现一次 —— 函数改名/搬走而本判据没跟着改 ⇒ 这里先红，
 * 而不是静默退化成「什么都没扫到 ⇒ 绿」。</p>
 *
 * <p><b>出口（真可行动）</b>：给归一化结果补 null 判定，形如
 * {@code if (info == null) { return List.of(); }} / {@code if (pi == null) { continue; }}
 * —— 语义是「缺值 = 没有这些键」，不是造一个空值下去（#5177/#4909 的既有口径：缺键就缺、不造值）。</p>
 *
 * <p><b>未固化项（如实登记）</b>：射程 = 这两个归一化入口的调用点；其它「返回 null 的解析助手」
 * （各自语义不同）不在本判据内。</p>
 */
@DisplayName("类级元守卫：#5550 processing_info 归一化结果的解引用必须先判 null")
class ProcessingInfoNullSafetyMetaGuardTest {

    /** 归一化的两个入口 —— 两份**自称同语义**的实现（见 {@code OrderLineCraftFields.normalize} 的注释）。 */
    private static final List<String> NORMALIZERS = List.of(
            "OrderLineCraftFields.normalize(",
            "normalizeProcessingInfo(");

    /** 解引用形态：调用结果被直接接上这些方法（没有中间变量 ⇒ 没有放 null 判定的位置）。 */
    private static final List<String> DEREFERENCES = List.of(
            ".get(", ".containsKey(", ".isEmpty(", ".size(", ".keySet(", ".entrySet(");

    /** 变量形态的窗口：赋值行之后多少行内必须出现该变量的 null 判定。 */
    private static final int NULL_CHECK_WINDOW = 6;

    @Test
    @DisplayName("归一化结果的每个调用点都必须有 null 处理面（未登记的新调用点 ⇒ 红）")
    void everyNormalizationCallSiteHandlesNull() throws IOException {
        Path srcMain = repoRoot().resolve("backend/admin-api/src/main/java");
        List<String> offenders = new ArrayList<>();
        List<String> census = new ArrayList<>();

        for (Path file : javaSources(srcMain)) {
            List<String> lines = Files.readAllLines(file);
            for (int i = 0; i < lines.size(); i++) {
                String line = lines.get(i);
                String normalizer = NORMALIZERS.stream().filter(line::contains).findFirst().orElse(null);
                if (normalizer == null) {
                    continue;
                }
                String where = repoRoot().relativize(file) + ":" + (i + 1);
                census.add(where);

                // ① 直连解引用：`normalize(...).get(...)`
                int callAt = line.indexOf(normalizer);
                if (DEREFERENCES.stream().anyMatch(d -> line.indexOf(d, callAt) >= 0)) {
                    offenders.add(where + " 直连解引用（没有放 null 判定的位置）：" + line.trim());
                    continue;
                }

                // ② 变量形态：`X = ...normalize(...)` ⇒ 窗口内必须有 X 的 null 判定
                String variable = assignedVariable(line, callAt);
                if (variable == null) {
                    continue; // 结果未落变量（作实参传递等）⇒ 本行无解引用面
                }
                Pattern nullTest = Pattern.compile(
                        "\\b" + Pattern.quote(variable) + "\\s*(==|!=)\\s*null"
                                + "|null\\s*(==|!=)\\s*" + Pattern.quote(variable) + "\\b");
                boolean checked = false;
                for (int j = i; j < Math.min(lines.size(), i + 1 + NULL_CHECK_WINDOW); j++) {
                    if (nullTest.matcher(lines.get(j)).find()) {
                        checked = true;
                        break;
                    }
                }
                if (!checked) {
                    offenders.add(where + " 归一化结果 `" + variable + "` 在 " + NULL_CHECK_WINDOW
                            + " 行内没有任何 null 判定，却可能被解引用：" + line.trim());
                }
            }
        }

        // 非空跑自证：普查面必须真的有东西可普查（改名/搬走 ⇒ 先在这里红）
        assertThat(census).as("普查面为空 ⇒ 本判据是空跑（归一化入口改名/搬走了？先把 NORMALIZERS 对齐）")
                .isNotEmpty();
        for (String normalizer : NORMALIZERS) {
            assertThat(scannedSourceContains(normalizer, srcMain))
                    .as("归一化入口 %s 在 main 源码里一次都没出现 ⇒ 本判据扫的是空气", normalizer)
                    .isTrue();
        }

        assertThat(offenders)
                .as("processing_info 归一化结果被解引用却没判 null —— 存量行（processing_info 为 NULL）"
                        + "会让读面 NPE 500（issue #5550）。出口：补 `if (x == null) { return/continue; }`。\n"
                        + String.join("\n", offenders))
                .isEmpty();
    }

    /** `X = ... <call> ...` ⇒ 返回 X；非赋值形态（含 `==` / 无等号 / 调用在等号左侧之前）⇒ null。 */
    private static String assignedVariable(String line, int callAt) {
        int eq = line.indexOf('=');
        if (eq <= 0 || eq + 1 >= line.length() || line.charAt(eq + 1) == '=' || eq <= line.lastIndexOf("==", eq)) {
            return null;
        }
        if (callAt < eq) {
            return null;
        }
        Matcher matcher = Pattern.compile("([A-Za-z_$][\\w$]*)\\s*$").matcher(line.substring(0, eq));
        return matcher.find() ? matcher.group(1) : null;
    }

    private static boolean scannedSourceContains(String needle, Path srcMain) throws IOException {
        for (Path file : javaSources(srcMain)) {
            if (Files.readString(file).contains(needle)) {
                return true;
            }
        }
        return false;
    }

    private static List<Path> javaSources(Path srcMain) throws IOException {
        try (Stream<Path> walk = Files.walk(srcMain)) {
            return walk.filter(p -> p.toString().endsWith(".java")).sorted(Comparator.naturalOrder()).toList();
        }
    }

    /** 与 {@code OrderUrgencyFieldsTest} 同款：从 surefire 的 cwd（模块目录）向上找仓库根。 */
    private static Path repoRoot() {
        Path root = Paths.get(System.getProperty("user.dir")).toAbsolutePath();
        while (root != null
                && !Files.exists(root.resolve("backend/admin-api/src/main/resources/db/init/schema.sql"))) {
            root = root.getParent();
        }
        assertThat(root).as("必须能定位仓库根").isNotNull();
        return root;
    }
}