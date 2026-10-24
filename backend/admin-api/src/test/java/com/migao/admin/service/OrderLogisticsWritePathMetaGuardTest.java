// case_ids: OR-045, OR-047
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
 * 类级元守卫（issue #7174，铁律 8）：物流写面**只许**走「条件更新 → 影响行数为 0 才建行」。
 *
 * <h2>为什么需要类级守卫而不是只写实例判据</h2>
 * 实例判据（{@code OrderLogisticsWriterTest} / {@code OrderLogisticsUpsertConcurrencyRealDbTest}）证明
 * **这一个实现**是对的；但只要有人日后又写回 `selectByOrderId + insert` 或整实体 {@code updateById}，
 * 双行竞态与「旧值盖新值」会**原样回来**，而并发探针是概率性的（未必每次都在 CI 上撞到）。
 * 本守卫把它变成**确定性的结构判据**：写面里出现那条被禁的调用链 ⇒ 直接红。
 *
 * <h2>判据（三类，都扫**源码文本**，不依赖运行）</h2>
 * <ol>
 *   <li>{@code OrderLogisticsWriter} 里**不得**出现 {@code selectByOrderId} / {@code updateById}
 *       —— 它们正是「读改写」与「整实体回写」的入口；</li>
 *   <li>写面必须经由 {@code updateShippingDetails}（条件更新），且该 SQL 必须同时带
 *       {@code order_id} / {@code tenant_id} / {@code deleted = 0} 三谓词（少一个就不是"这一行"的原子读数）；</li>
 *   <li>首次发货时刻的守卫必须留在 SQL 里：{@code shipped_at = COALESCE(shipped_at, created_at)}
 *       —— 换成应用层"读出来判空再写"就又变回读改写。</li>
 * </ol>
 *
 * <p>红证方向：① 把 {@code upsert} 的更新分支改回 {@code updateById(latest)} ⇒ 判据 1 红；
 * ② 把 SQL 里的 {@code AND deleted = 0} 删掉 ⇒ 判据 2 红；③ 把 COALESCE 换成
 * {@code shipped_at = #{shippedAt}} ⇒ 判据 3 红。</p>
 */
@DisplayName("7174 类级守卫：物流写面不得回到读改写 / 整实体回写")
class OrderLogisticsWritePathMetaGuardTest {

    /** 判据对象所在的模块根：**自适应**（surefire 的工作目录可能是模块根、也可能是仓库根）——
     *  写死相对层级会在换一处跑法时静默指向不存在的路径（那会变成"文件不存在"的假红/假绿）。 */
    private static final Path REPO_ROOT = moduleRoot();

    private static Path moduleRoot() {
        Path cwd = Paths.get("").toAbsolutePath();
        for (Path candidate : new Path[]{cwd, cwd.resolve("backend/admin-api"), cwd.getParent()}) {
            if (candidate != null && Files.exists(candidate.resolve("src/main/java/com/migao/admin/service"))) {
                return candidate;
            }
        }
        return cwd;   // 交给判据里的存在性断言去具名报红
    }
    private static final Path WRITER = REPO_ROOT.resolve(
            "src/main/java/com/migao/admin/service/OrderLogisticsWriter.java");
    private static final Path MAPPER = REPO_ROOT.resolve(
            "src/main/java/com/migao/admin/mapper/OrderLogisticsMapper.java");

    /** 注意：真值取自**生产源码**；文件路径漂移 ⇒ 判红（不是空跑通过）。 */
    private static String source(Path path) throws IOException {
        assertThat(Files.exists(path)).as("判据对象必须存在：%s（路径漂移 ⇒ 判红）", path).isTrue();
        return Files.readString(path, StandardCharsets.UTF_8);
    }

    @Test
    @DisplayName("🔴 判据 1：OrderLogisticsWriter 不得再调用 selectByOrderId / updateById")
    void writerNeverUsesReadModifyWriteCalls() throws IOException {
        String writer = source(WRITER);
        assertThat(writer)
                .as("写面不得出现 selectByOrderId（读改写的第一步）")
                .doesNotContain("selectByOrderId");
        assertThat(writer)
                .as("写面不得出现 updateById（整实体回写 ⇒ 旧值盖新值）")
                .doesNotContain("updateById");
        assertThat(writer)
                .as("写面必须经由条件更新 updateShippingDetails")
                .contains("updateShippingDetails");
    }

    @Test
    @DisplayName("🔴 判据 2：条件更新的 SQL 必须同时带 order_id / tenant_id / deleted = 0 三谓词")
    void conditionalUpdateKeepsAllThreePredicates() throws IOException {
        String mapper = source(MAPPER);
        int start = mapper.indexOf("updateShippingDetails");
        assertThat(start).as("mapper 里必须存在 updateShippingDetails（判据对象缺失 ⇒ 红）").isGreaterThan(0);
        // 取该注解附近的 SQL 文本（到下一个方法签名/注解结束为止，取 2500 字符足够覆盖整段 SQL）
        String window = mapper.substring(Math.max(0, start - 2500), start + 200);
        assertThat(window).as("条件更新必须带 order_id 谓词").contains("order_id = #{orderId}");
        assertThat(window).as("条件更新必须带 tenant_id 谓词（多租户写面）").contains("tenant_id = #{tenantId}");
        assertThat(window).as("条件更新必须带 deleted = 0 谓词（逻辑删除行不参与）").contains("deleted = 0");
    }

    @Test
    @DisplayName("🔴 判据 3：首次发货时刻仍在 SQL 里守（COALESCE(shipped_at, created_at)），不下沉到应用层")
    void shippedAtInvariantStaysInSql() throws IOException {
        String mapper = source(MAPPER);
        assertThat(mapper)
                .as("shipped_at 只许在为空时补、且取值 = 该行 created_at（issue #6276 口径）")
                .contains("shipped_at = COALESCE(shipped_at, created_at)");
        String writer = source(WRITER);
        assertThat(writer)
                .as("应用层不得自己写首次发货时刻（写 now() = 采用被否掉的「最近一次改物流时刻」口径）")
                .doesNotContain("setShippedAt(OffsetDateTime.now())");
    }
}
