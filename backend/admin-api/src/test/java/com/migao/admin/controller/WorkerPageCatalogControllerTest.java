package com.migao.admin.controller;

// case_ids: PG-072, PG-065, HR-001, HR-002

import com.migao.admin.security.RequirePermission;
import com.migao.admin.worker.WorkerPages;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 工人端页面目录端点测试（issue #6828）：{@code GET /api/admin/worker-pages}。
 *
 * <p>它替代的是随企业级页面开关一起退场的 {@code GET /api/admin/worker-page-config}：
 * 商家面配置**逐人菜单**时的选项来源（页键 + 人话名）仍由服务端给。</p>
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li>回**闭词表全部页**（逐值 = {@code WorkerPages.defaultPages()}）+ 逐键人话名 ——
 *       前端因此不需要维护第二份会漂的页面清单；</li>
 *   <li>读面挂 {@code production:view}（与工人档案读面同码）；</li>
 *   <li><b>只读</b>：本面没有写方法（页面开放范围由每位工人档案上的收窄决定）。</li>
 * </ol>
 */
@DisplayName("WorkerPageCatalogController 工人端页面目录（issue #6828）")
class WorkerPageCatalogControllerTest extends BaseControllerTest {

    private static final String URL = "/api/admin/worker-pages";

    private MockMvc mockMvc() {
        return buildMockMvc(new WorkerPageCatalogController());
    }

    @Test
    @DisplayName("回全部页键 + 逐键人话名（页键与人话名的唯一真值 = WorkerPages）")
    void returnsTheWholeClosedVocabularyWithLabels() throws Exception {
        mockMvc().perform(get(URL))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.pages.length()").value(WorkerPages.defaultPages().size()))
                .andExpect(jsonPath("$.data.pages[0]").value("report"))
                .andExpect(jsonPath("$.data.pages[1]").value("order"))
                .andExpect(jsonPath("$.data.pages[2]").value("cut_calc"))
                .andExpect(jsonPath("$.data.pages[3]").value("shipment"))
                .andExpect(jsonPath("$.data.labels.report").value(WorkerPages.labels().get("report")))
                .andExpect(jsonPath("$.data.labels.shipment").value(WorkerPages.labels().get("shipment")));
    }

    @Test
    @DisplayName("读面挂生产域读码 production:view（与工人档案读面同码）")
    void readFaceCarriesProductionViewCode() {
        RequirePermission code = WorkerPageCatalogController.class.getAnnotation(RequirePermission.class);
        assertThat(code).isNotNull();
        assertThat(code.value()).isEqualTo("production:view");
        assertThat(WorkerPageCatalogController.class.getAnnotation(
                org.springframework.web.bind.annotation.RequestMapping.class).value())
                .containsExactly("/api/admin/worker-pages");
    }

    @Test
    @DisplayName("🔴 只读：本面不得有写方法（页面开放范围由工人档案上的收窄决定，不在这里写）")
    void catalogIsReadOnly() throws Exception {
        for (java.lang.reflect.Method method : WorkerPageCatalogController.class.getDeclaredMethods()) {
            assertThat(method.getAnnotations())
                    .as("目录端点只读（issue #6828）：%s 不得是写面", method.getName())
                    .noneMatch(a -> a instanceof org.springframework.web.bind.annotation.PutMapping
                            || a instanceof org.springframework.web.bind.annotation.PostMapping
                            || a instanceof org.springframework.web.bind.annotation.DeleteMapping
                            || a instanceof org.springframework.web.bind.annotation.PatchMapping);
        }
        // 端到端复核：PUT 该路径不存在（405 / 404 皆可 —— 只要不是 2xx）
        assertThat(mockMvc().perform(put(URL)).andReturn().getResponse().getStatus())
                .isGreaterThanOrEqualTo(400);
    }
}
