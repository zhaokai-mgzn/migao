// case_ids: MC-105
package com.migao.admin.controller;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * {@code GET /api/version} 端点契约测试（issue #6951；同族 #6746 / #6611 / #6554）。
 *
 * <h3>这个端点为什么存在</h3>
 * <p>部署形态下 {@code /actuator/health} 与 {@code /actuator/info} 被 nginx 屏蔽
 * （{@code deploy/swas/nginx.conf} 的 {@code location ~ ^/(actuator|v3/api-docs|swagger-ui)(/|$)}
 * ⇒ {@code return 404}）⇒ **探活面 ≠ 探版本面**：线上只能探到「服务活着」，
 * 探不到「跑的是哪个 build」。判据消费方 = {@code deploy/scripts/served-version-verify.sh}
 * （部署腿在部署后断言「线上 sha == 本次部署的 sha」）。</p>
 *
 * <h3>本文件钉什么（每条都是「会红」的形态）</h3>
 * <ol>
 *   <li><b>字段值逐字来自构建期注入</b>：{@code sha}/{@code tag}/{@code builtAt} 原样出，
 *       不截断、不加工、不重排 —— 它们就是判据比对的**那个字符串**；</li>
 *   <li><b>字段面恰好 4 个</b>（{@code app}/{@code sha}/{@code tag}/{@code builtAt}）
 *       ⇒ 往响应里加任何东西（主机名 / 路径 / 环境变量 / 配置）当场红；</li>
 *   <li><b>未注入时 {@code sha} 是空串（不是 404、不是异常、更不是假值）</b>：消费方据此判
 *       「探不到」(exit 3) —— 端点若在这里 500 或返回占位串，判据就会在**老镜像**上退化成假绿；</li>
 *   <li><b>只读</b>：{@code POST /api/version} ⇒ 405（不给写面）；</li>
 *   <li><b>不泄露</b>：注入一杯「显眼标记」当构建身份，断言响应里**只**出现它们，且不出现
 *       {@code /opt/migao-deploy} 这类实例路径（本端点是无鉴权面，泄露面必须显式受限）。</li>
 * </ol>
 *
 * <p>⚠️ 说明（照实登记）：{@code permitAll} 那一半（{@code SecurityConfig}）与「端点挂在 nginx 已放行的
 * {@code /api/} 前缀下」由 CI 侧判据 {@code tests/unit_ci_workflows/test_served_version_verify.py}
 * 承担（它读 `SecurityConfig` / `nginx.conf` 文本，本类在 standalone MockMvc 下没有过滤链、
 * 判不了鉴权面）；两处**不重复实现**同一个断言。</p>
 */
@DisplayName("VersionController 版本探针端点（issue #6951）")
class VersionControllerTest extends BaseControllerTest {

    private static final String URL = "/api/version";
    private static final String SHA = "6f3aec2b8c0d9e1f2a3b4c5d6e7f8091a2b3c4d5";
    private static final String TAG = "sha-6f3aec2";
    private static final String BUILT_AT = "2026-10-16T00:22:01Z";

    /** 构建一个注入了给定构建身份的控制器；`app` 来自 Spring Environment（与线上同源）。 */
    private MockMvc mvcWith(String sha, String tag, String builtAt) {
        MockEnvironment env = new MockEnvironment();
        env.setProperty("spring.application.name", "admin-api");
        // 迁移事实走独立端点（`/api/version/migrations`）：本端点的字段面**保持 4 个**，
        // 装配时给一个空 provider 即可（空 ⇒ 该端点报 unknown，且不在本响应里出现）
        return buildMockMvc(new VersionController(sha, tag, builtAt, env,
                new org.springframework.beans.factory.support.StaticListableBeanFactory()
                        .getBeanProvider(com.migao.admin.config.MigrationRunner.class)));
    }

    @Test
    @DisplayName("① 三个构建期注入值**原样**出（判据比对的就是这三个字符串）")
    void buildIdentityIsReturnedVerbatim() throws Exception {
        mvcWith(SHA, TAG, BUILT_AT)
                .perform(get(URL))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.app").value("admin-api"))
                .andExpect(jsonPath("$.sha").value(SHA))
                .andExpect(jsonPath("$.tag").value(TAG))
                .andExpect(jsonPath("$.builtAt").value(BUILT_AT));
    }

    @Test
    @DisplayName("② 字段面**恰好** 4 个：多一个键就是泄露面变了（本判据会红）")
    void responseHasExactlyTheFiveWhitelistedKeys() throws Exception {
        MvcResult result = mvcWith(SHA, TAG, BUILT_AT)
                .perform(get(URL))
                .andExpect(status().isOk())
                .andReturn();

        @SuppressWarnings("unchecked")
        Map<String, Object> body = objectMapper.readValue(
                result.getResponse().getContentAsString(), LinkedHashMap.class);

        assertThat(body.keySet())
                .as("响应字段白名单 = app/sha/tag/builtAt；加字段必须重新过一遍「会不会泄露」")
                .containsExactly("app", "sha", "tag", "builtAt");
        assertThat(body.values())
                .as("四个字段都是非 null 字符串")
                .allSatisfy(v -> assertThat(v).isInstanceOf(String.class));
    }

    @Test
    @DisplayName("③ 未注入构建身份 ⇒ sha 是**空串**（消费方据此判「探不到」，不许 500 / 不许占位假值）")
    void missingBuildIdentityYieldsEmptyShaNotAnError() throws Exception {
        mvcWith("", "", "")
                .perform(get(URL))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.sha").value(""))
                .andExpect(jsonPath("$.tag").value(""))
                .andExpect(jsonPath("$.builtAt").value(""));
    }

    @Test
    @DisplayName("③′ 空白形态的注入值被 trim（带空格的注入值不会污染判据的比对面）")
    void injectedValuesAreTrimmed() throws Exception {
        mvcWith("  " + SHA + "  ", " " + TAG + " ", " " + BUILT_AT + " ")
                .perform(get(URL))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.sha").value(SHA))
                .andExpect(jsonPath("$.tag").value(TAG))
                .andExpect(jsonPath("$.builtAt").value(BUILT_AT));
    }

    @Test
    @DisplayName("④ 只读：POST /api/version ⇒ 405（版本探针不给写面）")
    void endpointIsReadOnly() throws Exception {
        mvcWith(SHA, TAG, BUILT_AT)
                .perform(post(URL).contentType(APPLICATION_JSON).content("{}"))
                .andExpect(status().isMethodNotAllowed());
    }

    @Test
    @DisplayName("⑤ 不泄露：响应里只许出现注入的构建身份，不出现实例路径 / 环境变量形态")
    void responseDoesNotLeakInstanceDetails() throws Exception {
        // 「显眼标记」当构建身份：任何把实例细节塞进响应的改法（拼路径 / 带 env / 带主机名）都会命中它
        String conspicuous = "/opt/migao-deploy";
        MvcResult result = mvcWith(conspicuous, conspicuous, conspicuous)
                .perform(get(URL))
                .andExpect(status().isOk())
                .andReturn();
        String body = result.getResponse().getContentAsString();

        List<String> allowedOccurrences = List.of("app", "sha", "tag", "builtAt",
                "admin-api", conspicuous);
        // 判据形态：body 里除「白名单键名 + 注入值 + 应用名」之外，不许出现别的**值形态**标记
        for (String forbidden : List.of("MIGAO_BUILD", "RDS_", "REDIS_", ".env", "PASSWORD",
                "SECRET", "TOKEN", "localhost", "127.0.0.1", "hostname")) {
            assertThat(body)
                    .as("响应体里出现了 %s 形态的内容 ⇒ 泄露面超了（本端点无鉴权）", forbidden)
                    .doesNotContain(forbidden);
        }
        assertThat(body)
                .as("响应体只应由白名单键名与注入值构成")
                .contains(allowedOccurrences.toArray(new String[0]));
    }
}
