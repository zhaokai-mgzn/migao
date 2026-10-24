// case_ids: OPS-001
package com.migao.admin.controller;

import com.migao.admin.config.MigrationRunner;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.StaticListableBeanFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * `GET /api/version/migrations`（issue #7373 复盘）—— **迁移事实**的只读出口。
 *
 * <h3>为什么需要它</h3>
 * <p>`MigrationRunner` 对非连接类失败是「跳过这条、继续跑」⇒ 库里少一张表时：服务照常 UP、
 * 部署 success、页面 500，而**没人看得见**。云上「采购单加载失败」那次，排查时最先要回答的就是
 * 「那几条迁移到底跑没跑」—— 没有任何接口能回答，只能登服务器看日志。</p>
 *
 * <h3>为什么**不**塞进 `/api/version`</h3>
 * <p>那个端点的字段面被既有判据冻结为 4 个（部署腿靠它比对 served sha）。可观测性不该去动部署契约
 * —— 所以另开一条路径，两件事各自稳定。</p>
 *
 * <h3>关键判据</h3>
 * <ul>
 *   <li>三个计数**逐字**来自 runner（不加工）；</li>
 *   <li>取不到 runner ⇒ 报 `unknown`，**不报 0**（0 会被读成「跑了且全过」）；</li>
 *   <li>只读（POST ⇒ 405）；</li>
 *   <li>不暴露迁移文件名（公开端点，文件名会泄露内部表结构）。</li>
 * </ul>
 */
@DisplayName("迁移事实端点：计数逐字 / 取不到报 unknown 而非 0 / 只读 / 不泄露文件名")
class VersionMigrationsEndpointTest extends BaseControllerTest {

    private static final String URL = "/api/version/migrations";

    private MockMvc withRunner(MigrationRunner runner) {
        ObjectProvider<MigrationRunner> provider = runner == null
                ? new StaticListableBeanFactory().getBeanProvider(MigrationRunner.class)
                : new StaticListableBeanFactory() {
                    @Override
                    public <T> ObjectProvider<T> getBeanProvider(Class<T> type) {
                        return new ObjectProvider<>() {
                            @Override
                            public T getObject(Object... args) {
                                return type.cast(runner);
                            }

                            @Override
                            public T getIfAvailable() {
                                return type.cast(runner);
                            }

                            @Override
                            public T getIfUnique() {
                                return type.cast(runner);
                            }

                            @Override
                            public java.util.Iterator<T> iterator() {
                                return java.util.List.of(type.cast(runner)).iterator();
                            }
                        };
                    }
                }.getBeanProvider(MigrationRunner.class);
        MockEnvironment env = new MockEnvironment();
        env.setProperty("spring.application.name", "admin-api");
        return buildMockMvc(new VersionController("sha-x", "tag-x", "2026-10-21T00:00:00Z", env, provider));
    }

    @Test
    @DisplayName("三个计数逐字来自 runner（真实失败 / 已知存量非幂等 / 台账已应用）")
    void countsComeFromRunner() throws Exception {
        MigrationRunner runner = mock(MigrationRunner.class);
        when(runner.getLastFailedRealCount()).thenReturn(1);
        when(runner.getLastFailedBenignCount()).thenReturn(2);
        when(runner.getLastSkippedByLedger()).thenReturn(7);

        withRunner(runner).perform(get(URL))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.migrationsFailedReal").value("1"))
                .andExpect(jsonPath("$.migrationsFailedBenign").value("2"))
                .andExpect(jsonPath("$.migrationsAppliedByLedger").value("7"));
    }

    @Test
    @DisplayName("🔴 取不到 runner ⇒ 三项都是 unknown（**不是 0**：0 会被读成「跑了且全过」）")
    void missingRunnerIsUnknownNotZero() throws Exception {
        withRunner(null).perform(get(URL))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.migrationsFailedReal").value("unknown"))
                .andExpect(jsonPath("$.migrationsFailedBenign").value("unknown"))
                .andExpect(jsonPath("$.migrationsAppliedByLedger").value("unknown"));
    }

    @Test
    @DisplayName("只读：POST 不给写面（405）")
    void readOnly() throws Exception {
        withRunner(null).perform(post(URL)).andExpect(status().isMethodNotAllowed());
    }

    @Test
    @DisplayName("不泄露迁移文件名（公开端点只说「几条」，不说「哪条」）")
    void doesNotLeakMigrationFilenames() throws Exception {
        MigrationRunner runner = mock(MigrationRunner.class);
        when(runner.getLastFailedMigrations()).thenReturn(java.util.List.of("V175__create_purchase_orders.sql"));
        when(runner.getLastFailedRealCount()).thenReturn(1);

        String body = withRunner(runner).perform(get(URL))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();
        org.assertj.core.api.Assertions.assertThat(body)
                .as("公开端点不得出现迁移文件名")
                .doesNotContain("V175")
                .doesNotContain(".sql");
    }
}
