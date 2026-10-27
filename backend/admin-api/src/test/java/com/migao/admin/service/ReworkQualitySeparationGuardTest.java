// case_ids: PG-099
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 返工与质检**分离**（issue #7945，用户 2026-10-27 裁定）—— 类级守卫。
 *
 * <p>用户逐字：「应该只记录返工单，不产生质检数据，返工是因为布料有质量问题，而质检是因为加工厂
 * 做工有问题，两者有区别」。</p>
 *
 * <p>本文件钉住三条**结构性**判据（每条能单独变红；比「跑一遍看有没有多一行」更早拦住回归）：</p>
 * <ol>
 *   <li>质检服务**没有** {@code recordReworkReport} —— #7919 的「返工报工自动落质检」已整体删除，
 *       不是藏起来；</li>
 *   <li>报工服务**没有** {@code recordReworkQuality} —— 返工写路径不再写质检；</li>
 *   <li>返工写路径的两个服务**不持有任何质检依赖**（字段类型里没有 QualityCheck*）——
 *       想再写质检，必须先加依赖，那一步会当场红。</li>
 * </ol>
 *
 * <p>为什么用反射而不是行为断言：行为断言只能覆盖「这次走的这条路」，而这类回归的形态是
 * **在另一条路径上悄悄接回质检**。结构判据让「接回」这个动作本身变红。</p>
 */
@DisplayName("返工 / 质检分离 · 类级守卫（issue #7945）")
class ReworkQualitySeparationGuardTest {

    @Test
    @DisplayName("① 质检服务没有「返工报工自动落质检」的入口（#7919 已撤销）")
    void qualityServiceHasNoReworkReportEntry() {
        assertThat(Arrays.stream(QualityCheckService.class.getDeclaredMethods()).map(m -> m.getName()))
                .as("QualityCheckService 的写入口只允许显式质检 create")
                .doesNotContain("recordReworkReport");
    }

    @Test
    @DisplayName("② 报工服务没有 recordReworkQuality（返工不产生质检数据）")
    void productionServiceHasNoReworkQualityWriter() {
        assertThat(Arrays.stream(ProductionService.class.getDeclaredMethods()).map(m -> m.getName()))
                .as("ProductionService 的报工路径不得再写质检")
                .doesNotContain("recordReworkQuality");
    }

    @Test
    @DisplayName("③ 返工写路径的两个服务都不持有质检依赖（想接回质检 ⇒ 先加字段 ⇒ 当场红）")
    void reworkWritePathHasNoQualityDependency() {
        for (Class<?> type : List.of(ProductionReworkService.class, ProductionService.class)) {
            for (Field field : type.getDeclaredFields()) {
                assertThat(field.getType().getName())
                        .as("%s.%s 的类型不得是质检依赖", type.getSimpleName(), field.getName())
                        .doesNotContain("QualityCheck");
            }
        }
    }
}
