package com.migao.admin.config;

import lombok.extern.slf4j.Slf4j;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * 受控行业取值 + 归一（issue #4361 交付物 1）。
 *
 * <p><b>为什么必须归一</b>：{@code tenants.industry} 是**自由文本**（注册页 {@code type="text"}，
 * placeholder「如：布艺纺织、家居建材、电子商务等」）⇒ 同一行业会写成「布艺」「窗帘」「布艺纺织」
 * 「布艺/窗帘」四种形态。而「开租按行业套用生产模板」要求它当**模板键** ⇒
 * 字面量匹配会让四分之三的新租户取不到模板（**静默落空库**，且失败不报错）。</p>
 *
 * <p><b>词表 v1 冻结</b>：{@code curtain}（布艺/窗帘）/ {@code other}（其他）。
 * <b>不得自创第三值</b> —— 新增行业 = 新增模板 + 改本词表，是一次有意的产品决定。
 * 词表外的任何输入一律落 {@code other}，且**显式记日志**（见 {@link #normalize}）。</p>
 *
 * <p><b>两个写面都调本类</b>（只在注册路径归一 = 受控词表可被绕过）：
 * {@code RegistrationService.approveApplication}（注册审批建租户）与
 * {@code SettingsController.updateSettings}（{@code PUT /api/admin/settings} 接受任意字符串）。
 * 存量自由文本由迁移 V62 按**同口径**一次性回填（两侧一致性由 {@code IndustryCodesTest} 钉）。</p>
 *
 * <p><b>为什么不静默落 {@code other}</b>：库里看到 {@code other} 时，没人能区分
 * 「客户真是其他行业」与「词表没认出来」—— 前者是正常业务，后者是需要扩词表的信号。
 * 记一条 warn 让后者可追查（同 {@code NON_PIECEWORK_OPTIONS} 的「让两类可区分」口径）。</p>
 */
@Slf4j
public final class IndustryCodes {

    /** 布艺/窗帘行业（v1 唯一的行业模板）。 */
    public static final String CURTAIN = "curtain";

    /** 其他行业（无模板 ⇒ 开租不套用生产种子）。 */
    public static final String OTHER = "other";

    /** 词表 v1（冻结；{@code normalize} 的输出恒属本集合）。 */
    public static final Set<String> VOCABULARY = Set.of(CURTAIN, OTHER);

    /**
     * 别名 → 受控 code（词表 v1）。
     *
     * <p>键一律先做「去空白 + 去分隔符 + 转小写」归一（见 {@link #canonicalKey}），
     * 故「布艺/窗帘」「布艺、窗帘」「布艺 窗帘」共用同一条目。</p>
     */
    private static final Map<String, String> ALIASES = aliases();

    private IndustryCodes() {
    }

    private static Map<String, String> aliases() {
        Map<String, String> map = new LinkedHashMap<>();
        // 英文 code 本身
        map.put(CURTAIN, CURTAIN);
        // 行业口语别名（注册页 placeholder 与客户实际写法）
        for (String alias : List.of(
                "布艺", "窗帘", "布艺窗帘", "窗帘布艺", "布艺纺织", "纺织",
                "窗帘行业", "布艺行业", "布艺窗帘行业", "窗帘布艺行业",
                "软装", "布艺软装", "窗帘店", "窗帘加工", "窗帘布艺加工",
                "家居布艺", "遮光帘", "窗帘定制")) {
            map.put(canonicalKey(alias), CURTAIN);
        }
        map.put(OTHER, OTHER);
        return Map.copyOf(map);
    }

    /**
     * 归一为受控 code：可识别的别名 → {@link #CURTAIN}；空值或无法识别 → {@link #OTHER}。
     *
     * <p>幂等（{@code normalize(normalize(x)) == normalize(x)}）：受控 code 本身也在别名表里，
     * 故回填/重复写入安全。</p>
     *
     * @param raw 原始行业文本（注册申请/设置页/存量库值），可为 {@code null}
     * @return {@link #CURTAIN} 或 {@link #OTHER}，**恒属 {@link #VOCABULARY}**
     */
    public static String normalize(String raw) {
        if (raw == null || raw.isBlank()) {
            log.info("行业取值为空 ⇒ 归一为 {}（该租户不会被套用生产模板；如需套用请把行业写成「布艺」或「窗帘」）",
                    OTHER);
            return OTHER;
        }
        String key = canonicalKey(raw);
        String code = ALIASES.get(key);
        if (code != null) {
            return code;
        }
        // 无法识别 ⇒ other，但**显式登记**（不静默：否则库里看到 other 时分不清
        // 「客户真是其他行业」与「词表没认出来」）
        log.warn("行业取值「{}」不在受控词表 {} 内 ⇒ 归一为 {}（该租户不会被套用行业模板；"
                        + "若这是本店真实行业，请扩词表 + 加模板，而不是让每个租户各写一种写法）",
                raw, VOCABULARY, OTHER);
        return OTHER;
    }

    /**
     * 别名匹配键：去首尾空白、去所有空白与常见分隔符（{@code / 、 , ， · - _}）、转小写。
     *
     * <p>只做**形态**归一（不做同义词猜测）——「窗帘」与「布艺」能合并是因为它们都在别名表里，
     * 不是因为这里做了模糊匹配。模糊匹配会把「窗帘配件」也吞成布艺，那是猜。</p>
     */
    private static String canonicalKey(String raw) {
        return raw.trim()
                .replaceAll("[\\s/、,，·\\-_]+", "")
                .toLowerCase(Locale.ROOT);
    }
}
