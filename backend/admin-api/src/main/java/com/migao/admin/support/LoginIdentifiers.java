package com.migao.admin.support;

import java.security.SecureRandom;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 登录标识契约的**唯一实现点**（issue #5485）。
 *
 * <p>三条规则在这里各只有一份实现（写面、登录面、新租户默认值三条路径全部调用本类）：
 * ① 员工用户名 {@code ^[a-z0-9][a-z0-9._-]{2,31}$}；② 企业编码 {@code ^[a-z0-9][a-z0-9-]{1,31}$}；
 * ③ 登录标识 {@code <username>@<tenantCode>} 按**最后一个 {@code @}** 切分、两侧非空。
 * 「同一真值两处投影」是本仓踩过的形态（口径必然漂移）—— 故**禁止**在 Service / Controller
 * 里再写一份正则或再写一次切分。</p>
 *
 * <p>大小写：写入与登录**统一转小写**（`users.username` / `tenants.code` 均以小写存储），
 * 因此「大小写不敏感」是由「只存小写」这一不变量保证的，不需要 {@code lower()} 索引。</p>
 */
public final class LoginIdentifiers {

    /** 员工用户名：3~32 位，首字符必须是字母或数字。 */
    public static final Pattern USERNAME_PATTERN = Pattern.compile("^[a-z0-9][a-z0-9._-]{2,31}$");

    /**
     * 企业编码：2~32 位，首字符必须是字母或数字。
     *
     * <p>🔴 <b>字符集含下划线</b>（2026-09-25 实测订正，issue #5485）：dev 库现存租户的
     * {@code tenants.code} 有 {@code tenant_7478359537} / {@code tenant_5321056468} 这种**带下划线的
     * 存量编码**（旧生成器 {@code tenant_%06d%04d} 的产物）。若按「只允许连字符」的严格集判，
     * 那两个租户的员工**永远登不进来**，而管理员连登录都进不去、也就**没有任何自救路径**；
     * 管理员在「企业基础信息」里**原样保存**时也会被自己的新校验拒掉（连带整页设置都存不了）。
     * {@code _} 与 {@code @} 不冲突（按最后一个 {@code @} 切分无歧义）⇒ 单点放宽即可，**零数据迁移**。</p>
     */
    public static final Pattern TENANT_CODE_PATTERN = Pattern.compile("^[a-z0-9][a-z0-9_-]{1,31}$");

    /** 用户名不合规时的用户可见文案（写面 422 用；登录面**不**使用它，见 {@link #AUTH_FAILED_MESSAGE}）。 */
    public static final String USERNAME_RULE =
            "用户名不合法：须为 3~32 位小写字母/数字/点/下划线/连字符，且以字母或数字开头";

    /** 企业编码不合规时的用户可见文案。 */
    public static final String TENANT_CODE_RULE =
            "企业编码不合法：须为 2~32 位小写字母/数字/下划线/连字符，且以字母或数字开头";

    /** 企业编码保留字（全平台不可占用，也不由默认值生成器产出）。 */
    public static final Set<String> RESERVED_TENANT_CODES = Set.of(
            "admin", "api", "www", "app", "platform", "support", "system", "root", "login", "auth");

    /**
     * 员工登录失败的**唯一文案**（反枚举，issue #5485）：
     * 企业编码不存在 / 用户名不存在 / 密码错误 / 状态非 active / 标识格式不合法 —— 全部同一 401 同一文案，
     * 不泄露是哪一项错。
     */
    public static final String AUTH_FAILED_MESSAGE = "账号或密码错误";

    private static final String ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz";

    /** 默认企业编码里 base 段的最大长度（+ '-' + 4 位随机 = 29 ≤ 32，保证切尾不会吃掉随机段）。 */
    private static final int BASE_MAX = 24;

    private LoginIdentifiers() {
    }

    /** 规整为存储形态（小写、去首尾空白）；{@code null} / 空白 → {@code null}。 */
    public static String normalize(String raw) {
        if (raw == null) {
            return null;
        }
        String trimmed = raw.trim();
        if (trimmed.isEmpty()) {
            return null;
        }
        return trimmed.toLowerCase(Locale.ROOT);
    }

    /** 规整后的用户名是否合规。 */
    public static boolean isValidUsername(String normalized) {
        return normalized != null && USERNAME_PATTERN.matcher(normalized).matches();
    }

    /** 规整后的企业编码是否合规（**不含**保留字判定）。 */
    public static boolean isValidTenantCode(String normalized) {
        return normalized != null && TENANT_CODE_PATTERN.matcher(normalized).matches();
    }

    /** 企业编码校验：返回 null = 通过；否则返回**可直接展示**的 422 文案。 */
    public static String validateTenantCode(String raw) {
        String code = normalize(raw);
        if (code == null) {
            return "企业编码不能为空";
        }
        if (!isValidTenantCode(code)) {
            return TENANT_CODE_RULE;
        }
        if (RESERVED_TENANT_CODES.contains(code)) {
            return "企业编码「" + code + "」为系统保留字，请换一个";
        }
        return null;
    }

    /**
     * 切分员工登录标识 {@code <username>@<tenantCode>}（按**最后一个** {@code @}）。
     *
     * @return {@code [username, tenantCode]}（已转小写）；任一侧为空或不合规 → {@code null}
     */
    public static String[] split(String identifier) {
        if (identifier == null) {
            return null;
        }
        int at = identifier.lastIndexOf('@');
        if (at <= 0 || at == identifier.length() - 1) {
            return null;
        }
        String username = normalize(identifier.substring(0, at));
        String tenantCode = normalize(identifier.substring(at + 1));
        if (!isValidUsername(username) || !isValidTenantCode(tenantCode)) {
            return null;
        }
        return new String[]{username, tenantCode};
    }

    /**
     * 由企业名生成**可读的**默认编码 base 段：只保留 {@code [a-z0-9]}，其余折叠为单个连字符。
     * 纯中文企业名 → {@code "shop"}（读音可读、且一定合规）。
     */
    public static String slug(String companyName) {
        String lower = companyName == null ? "" : companyName.toLowerCase(Locale.ROOT);
        StringBuilder sb = new StringBuilder();
        for (char c : lower.toCharArray()) {
            boolean alnum = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
            if (alnum) {
                sb.append(c);
            } else if (sb.length() > 0 && sb.charAt(sb.length() - 1) != '-') {
                sb.append('-');
            }
        }
        String slug = trimHyphens(sb.toString());
        if (slug.length() > BASE_MAX) {
            slug = trimHyphens(slug.substring(0, BASE_MAX));
        }
        return slug.isEmpty() ? "shop" : slug;
    }

    /** {@code <base>-<4 位 base36 随机>}：既是可读形态（看前缀就知道是哪家），又保证候选空间足够大。 */
    public static String defaultTenantCode(String companyName, SecureRandom random) {
        StringBuilder suffix = new StringBuilder();
        for (int i = 0; i < 4; i++) {
            suffix.append(ALPHABET.charAt(random.nextInt(ALPHABET.length())));
        }
        return slug(companyName) + "-" + suffix;
    }

    private static String trimHyphens(String value) {
        int start = 0;
        int end = value.length();
        while (start < end && value.charAt(start) == '-') {
            start++;
        }
        while (end > start && value.charAt(end - 1) == '-') {
            end--;
        }
        return value.substring(start, end);
    }
}