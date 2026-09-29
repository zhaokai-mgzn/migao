package com.migao.admin.worker;

// case_ids: BM-006

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 工人端页面闭词表测试（V141，母单 #5161）—— 默认值**只在一处**。
 *
 * <p>判据（每条都能红）：</p>
 * <ol>
 *   <li>默认 = 全部页面（4 个，逐字）；改词表 / 加页面 ⇒ 本条与
 *       {@code WorkerPageConfigServiceTest} 的默认判据同时红（两份默认值会漂）；</li>
 *   <li>每个页面键都有商家面人话名（配置面板按它渲染；缺名 ⇒ 面板会显示机器码）；</li>
 *   <li><b>本类不提供任何权限相关 API</b>：工人页面码是**页面可见性**，不是权限码 ——
 *       一旦这里长出 {@code permissions} / {@code roles} 之类的方法，本条红（红线护栏）。</li>
 * </ol>
 */
@DisplayName("WorkerPages 工人端页面闭词表（V141 / 母单 #5161）")
class WorkerPagesTest {

    @Test
    @DisplayName("默认 = report/order/cut_calc/shipment（顺序即工人端默认页面顺序）")
    void defaultsAreTheFourWorkerPages() {
        assertThat(WorkerPages.defaultPages())
                .containsExactly("report", "order", "cut_calc", "shipment");
        assertThat(WorkerPages.ALL).containsExactlyInAnyOrderElementsOf(WorkerPages.defaultPages());
    }

    @Test
    @DisplayName("每次调用返回新列表（调用方改它不得污染默认值）")
    void defaultPagesIsNotASharedMutableInstance() {
        List<String> first = WorkerPages.defaultPages();
        assertThat(first).isNotSameAs(WorkerPages.defaultPages());
        assertThat(WorkerPages.defaultPages()).containsExactlyElementsOf(first);
    }

    @Test
    @DisplayName("每个页面键都有人话名（面板显示用；键是机器码）")
    void everyPageKeyHasAHumanLabel() {
        assertThat(WorkerPages.labels()).containsOnlyKeys(WorkerPages.defaultPages().toArray(String[]::new));
        assertThat(WorkerPages.labels().values()).allSatisfy(label -> assertThat(label).isNotBlank());
    }

    @Test
    @DisplayName("🔴 本类不得提供任何权限相关 API（页面码不是权限码）")
    void exposesNoPermissionSurface() {
        for (Method method : WorkerPages.class.getDeclaredMethods()) {
            assertThat(method.getName().toLowerCase())
                    .as("工人端页面码不是权限码（permissions 恒为 []）：%s", method.getName())
                    .doesNotContain("permission")
                    .doesNotContain("role")
                    .doesNotContain("authorit");
        }
    }
}
