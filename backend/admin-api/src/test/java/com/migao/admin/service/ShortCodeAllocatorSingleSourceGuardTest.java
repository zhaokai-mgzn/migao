// case_ids: PG-018
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 类级元守卫（铁律 8）：**短码分配器只有一份实现**（issue #6867 / B1）。
 *
 * <h3>它治什么形态</h3>
 * 本仓的短码（8 位 Crockford Base32）已被**三个码空间**共用：{@code /s/}（部位码）、{@code /i/}
 * （入库标签）、{@code /o/}（加工单级，本单）。分配器
 * {@link WorkerShortLinkService#allocateUnique(java.util.function.Predicate)} 把
 * 「随机 + 查重 + 碰撞重试 + 到顶 fail-closed」四件事抽成**唯一实现**，正是为了避免
 * 「同一个短码分配器，两个码空间的碰撞策略不同」这种**不会有任何东西变红**的缺陷。
 *
 * <p>实例判据（{@code ProductionServiceShortCodeTest}）只证明**这一轮**接线是对的；本守卫判的是
 * **形态** —— 日后再出现第二份循环（复制粘贴那段 {@code for} + 碰撞计数），**当场红**。</p>
 *
 * <h3>判据（每条可红，含对照臂）</h3>
 * <ol>
 *   <li><b>唯一实现</b>：整套 {@code allocateUnique} 定义的循环体在
 *       {@code WorkerShortLinkService} 里**恰好一处**；</li>
 *   <li><b>不得复制</b>：另两个分配消费者（{@code ProductionService} / {@code InboundLabelService}）
 *       的生产源码里**零**「重试循环」形态；</li>
 *   <li><b>消费者真走唯一实现</b>：两个消费者各自必须**逐字**出现对
 *       {@code WorkerShortLinkService.allocateUnique(} 的调用（摘掉即红 —— 防「绕过分配器直接
 *       {@code randomCode()}」）；</li>
 *   <li><b>判别力自证</b>：把坏形态喂进判据函数 ⇒ 在内存里当场红；喂干净输入 ⇒ 绿（对照臂）。</li>
 * </ol>
 *
 * <p><b>边界（如实登记）</b>：本判据是**文本面**的（不看字节码），也不跑 Spring 上下文 ——
 * 它保证「不存在第二份循环」，不保证「那份循环被跑到了」（后者是实例判据的事）。</p>
 */
@DisplayName("#6867 B1 类级守卫：短码分配器唯一实现（不新写循环）")
class ShortCodeAllocatorSingleSourceGuardTest {

    private static final String WORKER_SHORT_LINK =
            "backend/admin-api/src/main/java/com/migao/admin/service/WorkerShortLinkService.java";
    private static final String PRODUCTION_SERVICE =
            "backend/admin-api/src/main/java/com/migao/admin/service/ProductionService.java";
    private static final String INBOUND_LABEL_SERVICE =
            "backend/admin-api/src/main/java/com/migao/admin/service/InboundLabelService.java";

    /** 分配器的重试循环（碰撞重试的**形态**；复制第二份 = 第二条真相源）。 */
    private static final String WORKER_RETRY_LOOP = "for (int i = 0; i < MAX_ALLOCATE_ATTEMPTS; i++)";

    /** 消费者必须逐字出现的调用点。 */
    private static final String CALL_SITE = "WorkerShortLinkService.allocateUnique(";

    /**
     * 「自己在分配短码」的两种形态（**任一**出现即红，不依赖循环怎么写）：
     * ① 复制了分配上限常量（真值只许来自 {@code WorkerShortLinkService}）；
     * ② 自己调了随机码生成器（绕过分配器 = 不查重、不重试）。
     *
     * <p>⚠️ 这里**不**用「{@code for} 循环 + 计数器变量名」当判据 —— 第一版正是这么写的，
     * 而注入式红证当场抓到它是**假判据**：把循环写成 {@code for (int i = 0; i < 8; i++)}
     * （换了上界、不引用常量）就能**悄悄绕过**，测试照样绿。判据必须钉**语义动作**
     * （用没用随机器 / 有没有复制上限），不钉某个变量名的写法。</p>
     */
    private static final String[] SECOND_ALLOCATOR_SHAPES = {
        "MAX_ALLOCATE_ATTEMPTS",
        "randomCode()",
    };

    private static Path findRepoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve("backend/admin-api/src/main/resources/db/migration"))) {
                return cur;
            }
            cur = cur.getParent();
        }
        return null;
    }

    private static String read(String relative) throws IOException {
        Path root = findRepoRoot();
        if (root == null) {
            throw new IOException("找不到仓库根目录: " + relative);
        }
        return Files.readString(root.resolve(relative), StandardCharsets.UTF_8);
    }

    /** 判据函数（可被自证喂内存样本）：出现次数。 */
    static int occurrences(String source, String needle) {
        int count = 0;
        int at = source.indexOf(needle);
        while (at >= 0) {
            count++;
            at = source.indexOf(needle, at + needle.length());
        }
        return count;
    }

    /** 判据函数：该源码里「第二份分配器」的形态命中了几种（0 = 干净）。 */
    static int secondAllocatorShapes(String source) {
        int hit = 0;
        for (String shape : SECOND_ALLOCATOR_SHAPES) {
            if (source.contains(shape)) {
                hit++;
            }
        }
        return hit;
    }

    @Test
    @DisplayName("🔴 分配器的重试循环在 WorkerShortLinkService 里**恰好一处**（反空跑锚点）")
    void theRetryLoopLivesExactlyOnce() throws IOException {
        String source = read(WORKER_SHORT_LINK);
        assertThat(occurrences(source, WORKER_RETRY_LOOP))
                .as("「随机 + 查重 + 碰撞重试 + 到顶 fail-closed」必须只有一份实现（%s）", WORKER_SHORT_LINK)
                .isEqualTo(1);
        // 反空跑锚点：那份实现真的在（文本漂移 ⇒ 这个锚先红，而不是让上面的 == 1 变成 == 0）
        assertThat(source).contains("public static String allocateUnique(java.util.function.Predicate<String> isTaken)");
    }

    @Test
    @DisplayName("🔴 消费者（加工单级 / 入库标签）**零**「第二份分配器」形态（复制 ⇒ 红，与循环怎么写无关）")
    void consumersDoNotCopyTheAllocator() throws IOException {
        for (String consumer : new String[]{PRODUCTION_SERVICE, INBOUND_LABEL_SERVICE}) {
            String source = read(consumer);
            assertThat(secondAllocatorShapes(source))
                    .as("%s 不得自带分配动作（不得引用分配上限常量 / 不得自己调 randomCode）", consumer)
                    .isZero();
            assertThat(source)
                    .as("%s 必须真走唯一实现（摘掉调用点 ⇒ 红）", consumer)
                    .contains(CALL_SITE);
        }
    }

    @Test
    @DisplayName("🔴 加工单级短码**真走**唯一实现（摘掉调用点 ⇒ 红）")
    void theOrderLevelCodeGoesThroughTheSingleImplementation() throws IOException {
        String source = read(PRODUCTION_SERVICE);
        assertThat(source)
                .as("加工单级短码的分配必须调 WorkerShortLinkService.allocateUnique（不得自行 randomCode）")
                .contains(CALL_SITE);
        // 短码规格不得在本类新定：字母表 / 长度常量只许来自 WorkerShortLinkService（引用，不是复制）
        assertThat(source).as("字母表不得在消费方复制一份")
                .doesNotContain("public static final String ALPHABET")
                .doesNotContain("private static final String ALPHABET");
    }

    @Test
    @DisplayName("判别力自证：**两种**坏形态在内存里各自判红；干净输入 ⇒ 绿（对照臂）")
    void theGuardHasDiscriminatingPower() {
        String clean = "class A { String x() { return WorkerShortLinkService.allocateUnique(p); } }";
        assertThat(secondAllocatorShapes(clean)).isZero();

        // 坏形态 ①：换了个上界的自写循环（**第一版判据放过的形态** —— 它的循环头里没有常量名）
        String boundChanged = "class A { String x() { for (int i = 0; i < 8; i++) { "
                + "String c = WorkerShortLinkService.randomCode(); if (ok(c)) return c; } throw new IllegalStateException(); } }";
        assertThat(secondAllocatorShapes(boundChanged))
                .as("自写循环 + 绕过分配器取随机码必须判红（否则守卫退化成绿）")
                .isEqualTo(1);

        // 坏形态 ②：复制了分配上限常量（即便调的是别的生成器）
        String copiedConstant = "class A { int n = MAX_ALLOCATE_ATTEMPTS; }";
        assertThat(secondAllocatorShapes(copiedConstant))
                .as("复制分配上限常量必须判红")
                .isEqualTo(1);

        // 坏形态 ③：在唯一实现内部也被自己命中（本类只在 WorkerShortLinkService 用 `occurrences`，故对照臂单列）
        assertThat(occurrences(WORKER_RETRY_LOOP + " " + WORKER_RETRY_LOOP, WORKER_RETRY_LOOP)).isEqualTo(2);
    }
}
