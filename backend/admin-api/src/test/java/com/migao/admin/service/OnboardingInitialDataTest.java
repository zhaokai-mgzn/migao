// case_ids: MC-083
package com.migao.admin.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 开租「必需初始数据」清单自身的自洽判据（issue #6295）。
 *
 * <p>为什么需要它：{@link OnboardingInitialData#REQUIRED} 是**两份判据的真值源**
 * （运行期后置条件校验 {@code RegistrationService.assertRequiredInitialData} + 研发期元守卫
 * `tests/unit_ci_workflows/test_onboarding_required_seed_guard.py`）。真值源自己写坏
 * （键重复 / 锚不成形 / 清单空转）时，两处判据都可能**静默退化**（例如解析到 0 条 =
 * 「什么都没问题」）。本判据把清单的形态不变量钉在 Java 侧，Python 侧那份再做双向对账。</p>
 *
 * <p>判据（每条都能单独变红）：</p>
 * <ol>
 *   <li><b>清单不许空转</b>：{@code REQUIRED} 非空，且**至少一条 enforced**（全非 enforced =
 *       后置条件校验没有任何可校验对象 ⇒ 元守卫形同虚设）；</li>
 *   <li><b>键唯一且非空</b>（键进报错文案与豁免台账，重复 ⇒ 台账/归因互相覆盖）；</li>
 *   <li><b>锚形态</b>：{@code seedAnchor} 必须是 {@code <接收者>.<方法>} 形态
 *       （元守卫按它逐字对账；写成裸方法名 / 带行号都会让对账失效）；</li>
 *   <li><b>接收者命名约定</b>：播种协作者名字必须含 {@code Seed} 且以 {@code Service} 结尾
 *       —— 元守卫判据 2（未登记即红）就是按这个形态扫链路的，约定漂移 = 扫描面漏人；</li>
 *   <li><b>描述非空</b>（清单是给人读的：判红时要能立刻知道「不种会怎样」）；</li>
 *   <li><b>默认商品分类在清单里</b>（{@code product_category}）且默认名非空白 ——
 *       本单的主行为锚，删掉它 = 开箱缺口回归。</li>
 * </ol>
 */
@DisplayName("#6295 开租必需初始数据清单：自洽判据（真值源不许写坏）")
class OnboardingInitialDataTest {

    /** 锚形态 = `<接收者>.<方法>`（接收者 = 形如 `*Seed*Service` 的协作者；**不写行号**）。 */
    private static final Pattern ANCHOR = Pattern.compile("^[A-Za-z_$][A-Za-z0-9_$]*\\.[A-Za-z_$][A-Za-z0-9_$]*$");
    private static final Pattern SEED_RECEIVER = Pattern.compile("^[a-z][A-Za-z0-9]*Seed[A-Za-z0-9]*Service$");

    private static final List<OnboardingInitialData.Item> ITEMS = OnboardingInitialData.REQUIRED;

    @Test
    @DisplayName("判据 1：清单非空且至少一条 enforced（后置条件校验不许空转）")
    void checklistIsNotVacuous() {
        assertThat(ITEMS).as("开租必需初始数据清单不许为空（空 = 两处判据一起静默退化）").isNotEmpty();
        assertThat(ITEMS.stream().filter(OnboardingInitialData.Item::enforced).count())
                .as("至少要有一条 enforced：全非 enforced ⇒ 后置条件校验没有任何可校验对象")
                .isGreaterThan(0);
    }

    @Test
    @DisplayName("判据 2：键唯一且非空")
    void keysAreUniqueAndNonBlank() {
        Set<String> seen = new HashSet<>();
        for (OnboardingInitialData.Item item : ITEMS) {
            assertThat(item.key()).as("清单键不许为空白（它进报错文案与豁免台账）").isNotBlank();
            assertThat(seen.add(item.key())).as("清单键重复：%s（台账/归因会互相覆盖）", item.key()).isTrue();
        }
    }

    @Test
    @DisplayName("判据 3+4：锚形态 = <接收者>.<方法>，且接收者名字含 Seed 且以 Service 结尾")
    void seedAnchorsAreWellFormed() {
        for (OnboardingInitialData.Item item : ITEMS) {
            assertThat(item.seedAnchor())
                    .as("清单项 %s 的锚必须是 `<接收者>.<方法>` 形态（元守卫按它逐字对账）", item.key())
                    .matches(ANCHOR);
            String receiver = item.seedAnchor().substring(0, item.seedAnchor().indexOf('.'));
            assertThat(receiver)
                    .as("清单项 %s 的播种协作者 `%s` 必须形如 *Seed*Service"
                            + "（元守卫的「未登记即红」按这个形态扫入驻链路）", item.key(), receiver)
                    .matches(SEED_RECEIVER);
        }
    }

    @Test
    @DisplayName("判据 5：描述非空（判红时要能立刻知道「不种会怎样」）")
    void descriptionsArePresent() {
        for (OnboardingInitialData.Item item : ITEMS) {
            assertThat(item.description()).as("清单项 %s 缺描述", item.key()).isNotBlank();
        }
    }

    @Test
    @DisplayName("判据 6：默认商品分类在清单里（enforced）且默认名非空白 —— 本单的主行为锚")
    void defaultProductCategoryIsRegisteredAndNamed() {
        assertThat(OnboardingInitialData.REQUIRED)
                .as("默认商品分类必须留在清单里（删掉它 = 新租户开箱 422 回归）")
                .anyMatch(i -> OnboardingInitialData.PRODUCT_CATEGORY_KEY.equals(i.key())
                        && i.enforced()
                        && i.seedAnchor().contains("seedDefaultCategory"));
        assertThat(OnboardingInitialData.DEFAULT_PRODUCT_CATEGORY_NAME)
                .as("默认分类名必须有值（单一来源常量，不许空）").isNotBlank();
    }
}
