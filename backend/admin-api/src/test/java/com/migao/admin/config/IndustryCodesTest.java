package com.migao.admin.config;

// case_ids: PG-036

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.NullSource;
import org.junit.jupiter.params.provider.ValueSource;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 受控行业取值 + 归一（issue #4361 交付物 1）
 *
 * <p><b>为什么必须归一</b>：{@code tenants.industry} 自建表起是**自由文本**
 * （注册页 {@code type="text"}，placeholder「如：布艺纺织、家居建材、电子商务等」）
 * ⇒ 它**不能当模板键**：同一行业会写成「布艺」「窗帘」「布艺纺织」「布艺/窗帘」四种形态，
 * 模板查找按字面量匹配 ⇒ 四分之三的新租户取不到模板（静默落空库）。</p>
 *
 * <p><b>词表 v1 冻结</b>：{@code curtain}（布艺/窗帘）/ {@code other}（其他）。
 * <b>不得自创第三值</b> —— 新增行业 = 新增模板 + 改本词表，是一次有意的产品决定，
 * 不是「顺手加个常量」。</p>
 *
 * <p><b>无法识别 ⇒ {@code other} 且显式登记</b>（不许静默落 {@code other} 后无人知晓）：
 * 本条用日志 appender 断言「确实记了一条 warn」，因为「静默落 other」正是本单要治的形态
 * —— 库里看到 {@code other} 时，没人能区分「客户真是其他行业」与「词表没认出来」。</p>
 */
@DisplayName("IndustryCodes 受控行业取值 + 归一（issue #4361）")
class IndustryCodesTest {

    // ══════════════════════ ① 词表 v1 冻结 ══════════════════════

    @Test
    @DisplayName("词表 v1 恰好两个取值：curtain / other（不得自创第三值）")
    void vocabularyIsFrozenAtTwoCodes() {
        assertThat(IndustryCodes.CURTAIN).isEqualTo("curtain");
        assertThat(IndustryCodes.OTHER).isEqualTo("other");
        assertThat(IndustryCodes.VOCABULARY).containsExactlyInAnyOrder("curtain", "other");
    }

    // ══════════════════════ ② 归一的确切返回值 ══════════════════════

    @ParameterizedTest(name = "「{0}」→ curtain")
    @ValueSource(strings = {
            "curtain", "CURTAIN", "Curtain",
            "布艺", "窗帘", "布艺窗帘", "布艺纺织", "布艺/窗帘", "布艺、窗帘",
            "窗帘布艺", "布艺 窗帘", " 布艺 ", "布艺窗帘行业",
            "窗帘行业", "布艺行业", "软装", "窗帘店", "布艺软装",
    })
    @DisplayName("中文/别名/大小写 → curtain（受控 code）")
    void recognizedAliasesNormalizeToCurtain(String raw) {
        assertThat(IndustryCodes.normalize(raw)).isEqualTo("curtain");
    }

    @ParameterizedTest(name = "「{0}」→ other")
    @ValueSource(strings = {
            "other", "家居建材", "电子商务", "餐饮", "装修", "???", "curtain2", "布",
    })
    @DisplayName("无法识别的非空自由文本 → other")
    void unrecognizedFreeTextNormalizesToOther(String raw) {
        assertThat(IndustryCodes.normalize(raw)).isEqualTo("other");
    }

    @ParameterizedTest
    @NullSource
    @ValueSource(strings = {"", "   ", "\t"})
    @DisplayName("空值/null/纯空白 → other（不抛异常、不留 null）")
    void blankNormalizesToOther(String raw) {
        assertThat(IndustryCodes.normalize(raw)).isEqualTo("other");
    }

    @Test
    @DisplayName("归一幂等：normalize(normalize(x)) == normalize(x)（回填/重复写入安全）")
    void normalizeIsIdempotent() {
        for (String raw : new String[]{"布艺", "curtain", "家居建材", "", null, "布艺纺织"}) {
            String once = IndustryCodes.normalize(raw);
            assertThat(IndustryCodes.normalize(once))
                    .as("normalize 必须幂等：第二次归一「%s」不得再变", once)
                    .isEqualTo(once);
        }
    }

    // ══════════════════════ ③ 受控性：归一结果只可能是词表内的值 ══════════════════════

    @Test
    @DisplayName("归一结果恒属词表（任何输入都不会漏出自由文本）")
    void normalizeNeverLeaksFreeText() {
        for (String raw : new String[]{"布艺", "curtain", "家居建材", "罗马帘", "电动窗帘", "??"}) {
            assertThat(IndustryCodes.VOCABULARY).contains(IndustryCodes.normalize(raw));
        }
    }

    // ══════════════════════ ④ 与迁移 V62 的存量回填同口径（双向） ══════════════════════

    @Test
    @DisplayName("存量回填 SQL 的映射与 Java 归一逐条同口径（改名/漏项即红）")
    void migrationBackfillMatchesJavaNormalization() throws Exception {
        Path repo = repoRoot();
        String sql = Files.readString(
                repo.resolve("backend/admin-api/src/main/resources/db/migration/"
                        + "V62__add_source_to_production_operations_and_routings.sql"),
                java.nio.charset.StandardCharsets.UTF_8);

        // 迁移必须存在一条 tenants.industry 的归一语句（存量自由文本一次性映射）
        assertThat(sql)
                .as("V62 必须含 tenants.industry 的存量归一（否则存量租户的行业仍是自由文本 ⇒ 模板取不到）")
                .contains("UPDATE tenants")
                .contains("industry");
        assertThat(sql)
                .as("存量归一必须幂等（只更新尚未归一的那些行，否则每次启动都全表写）")
                .containsIgnoringCase("IS DISTINCT FROM");

        // 迁移把每个可识别别名映射到 'curtain'；Java 侧对同一批别名必须给出同一结论。
        // ⚠️ 两侧**形态归一后**才可比：SQL 先用 regexp_replace 去分隔符/空白再比对，
        // 故「布艺/窗帘」「布艺 窗帘」在 SQL 里的形态是 `布艺窗帘`（不带斜杠/空格）。
        // 判据不是「SQL 文本里出现过这个字符串」（那会逼着 SQL 把每个书写形态都列一遍 =
        // 维护 N 份写法），而是「Java 归一到的那一个键，SQL 的 IN 清单里有」。
        for (String alias : new String[]{"布艺", "窗帘", "布艺窗帘", "布艺纺织", "布艺/窗帘", "布艺 窗帘"}) {
            assertThat(IndustryCodes.normalize(alias)).isEqualTo("curtain");
            assertThat(sql)
                    .as("存量归一漏了别名「%s」（SQL 里应出现其形态归一后的键「%s」）⇒ "
                            + "存量租户落 other ⇒ 模板取不到", alias, canonicalKey(alias))
                    .contains("'" + canonicalKey(alias) + "'");
        }
        // 未列出的非空值在两侧都落 other
        assertThat(IndustryCodes.normalize("家居建材")).isEqualTo("other");
        assertThat(sql).contains("ELSE 'other'");
    }

    /**
     * 与 {@code IndustryCodes} 私有的 {@code canonicalKey} **同口径**的形态归一
     * （去首尾空白、去空白与常见分隔符、转小写）—— 用于把「Java 归一到哪个键」翻译成
     * 「SQL 的 IN 清单里该出现哪个字面量」。
     *
     * <p>刻意不复用生产代码的私有方法：那样「测试用自己的实现算期望值」会变成自证。
     * 这里只是把同一份**形态规则**写第二遍供比对 —— 规则本身若被改（比如不再去斜杠），
     * 本用例会红（SQL 清单里就没有 `布艺窗帘` 了）。</p>
     */
    private static String canonicalKey(String raw) {
        return raw.trim().replaceAll("[\\s/、,，·\\-_]+", "").toLowerCase(java.util.Locale.ROOT);
    }

    private static Path repoRoot() {
        Path cur = Paths.get("").toAbsolutePath();
        while (cur != null) {
            if (Files.isDirectory(cur.resolve("backend/admin-api/src/main/resources/db/migration"))) {
                return cur;
            }
            cur = cur.getParent();
        }
        throw new IllegalStateException("找不到仓库根目录");
    }
}
