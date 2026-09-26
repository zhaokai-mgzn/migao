package com.migao.admin.service;

import com.migao.admin.entity.ProcessingSetPartToken;
import com.migao.admin.mapper.ProcessingSetPartTokenMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.concurrent.ThreadLocalRandom;

/**
 * 工人端**稳定短链**的人可读短码（issue #4802；设计
 * {@code docs/design/worker-h5-scan-and-report.md} §1.3 / §1.4 / §7.1①）。
 *
 * <h2>它解决什么</h2>
 * 长 token（32 位十六进制）在**纸质码 / 工牌 / 贴纸**上印不下、人工抄写极易错 ⇒
 * 印刷品写 {@code https://<稳定域名>/s/<短码>}（8 位、人可读、抄得准），
 * 由服务端 {@code GET /s/{shortCode}} **302** 换回 {@code /w/?t=<token>}。
 *
 * <h2>为什么必须服务端 302（不能靠前端 JS 跳转）</h2>
 * 用户裁定③「任意扫一扫工具都能用」⇒ 部分扫码工具**只认服务端跳转**（前端 JS 跳转对它们是白屏）。
 * 且短码 ⇒ token 要**查库**（短码本身不含 token）⇒ nginx / 静态页都做不到（设计 §1.3 落点表）。
 *
 * <h2>短码形态（设计 §1.4，逐字）</h2>
 * <ul>
 *   <li><b>8 位</b>、字符集 = <b>Crockford Base32</b>（{@code 0-9 + A-Z} 去掉 {@code I / L / O / U}）
 *       ⇒ 易混对 {@code O/0} 与 {@code I/L/1} 在**生成面不可能同时出现**（{@code O} / {@code I} / {@code L}
 *       根本不生成）；</li>
 *   <li><b>随机</b>（**不是**顺序号 —— 顺序号可枚举，等于把别人的码送出去）；</li>
 *   <li><b>唯一</b> = {@code uk_set_part_tokens_short_code}（部分唯一索引 {@code WHERE deleted = 0}）
 *       + 分配前查重（碰撞重试，**不静默造重码**）；</li>
 *   <li><b>一码两用</b>：同一串既是 URL 路径段（{@code /s/<短码>}），也是纸面印的人可读短码
 *       ⇒ 手输 = 扫码，**同一入口、零分叉**。</li>
 * </ul>
 *
 * <h2>与 {@code token} / {@code set_no} 的关系（**不是第二套编号**）</h2>
 * 短码是**同一行记录**（{@code processing_set_part_tokens}）的**第二种表示**：
 * {@code token} = 机器标识（#4687 冻结形态，本单**一字不动**）、{@code short_code} = 人可读入口。
 * 与 {@code set_no}（套号）**无关**：套号是「第几樘窗」的业务编号（一单内有序、可读）；
 * 短码是「哪一张纸」的**随机**入口（全局唯一、不可枚举）。一套 ≤3~4 个部位 ⇒ ≤3~4 个短码。
 *
 * <h2>身份 / 权限（设计 §2.4 红线）</h2>
 * 本类**只**做「短码 ⇒ (租户, token)」的换发：不返回工人身份、不返回订单/工序/价格，
 * 也不校验任何权限（印刷品上的码对**任何**持码人等价 ⇒ 权限由报工页的工人 session 把关）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WorkerShortLinkService {

    /**
     * 短码字符集 = Crockford Base32（去掉 {@code I} / {@code L} / {@code O} / {@code U}）。
     *
     * <p>{@code U} 也被去掉（Crockford 原口径：避免拼出意外单词）⇒ 本常量 = 设计 §1.4 逐字。</p>
     */
    public static final String ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

    /** 短码长度（设计 §1.4：6~8 位，取 8 —— 空间 32^8 ≈ 1.1e12）。 */
    public static final int CODE_LENGTH = 8;

    /** 报工页路径（设计 §1.3：换前端框架/改路径**只改这一跳**）。 */
    public static final String REPORT_PAGE_PATH = "/w/";

    /** 分配短码的最大尝试次数（碰撞重试上限；到顶 ⇒ 显式失败，不静默造重码）。 */
    private static final int MAX_ALLOCATE_ATTEMPTS = 8;

    private final ProcessingSetPartTokenMapper setPartTokenMapper;

    /**
     * 随机生成一个短码（**不查重** —— 查重见 {@link #allocateUnique()}）。
     *
     * @return 8 位 Crockford Base32 短码
     */
    public static String randomCode() {
        StringBuilder sb = new StringBuilder(CODE_LENGTH);
        for (int i = 0; i < CODE_LENGTH; i++) {
            sb.append(ALPHABET.charAt(ThreadLocalRandom.current().nextInt(ALPHABET.length())));
        }
        return sb.toString();
    }

    /**
     * 归一化**手输**形态：去空白 + 转大写 + Crockford **解码别名**（{@code O→0}、{@code I/L→1}）。
     *
     * <p>为什么要有别名：短码的全部意义就是「人工抄写」⇒ 工人把 {@code 0} 抄成 {@code O}、
     * 把 {@code 1} 抄成 {@code I} 是**必然发生**的形态。生成面从不产出 {@code O/I/L}
     * ⇒ 别名映射**不可能**把两个不同短码映到同一个值（不会造出歧义），只是让抄错的那一个还能用。
     * 别名是 Crockford Base32 规范自带的解码口径，**不是**本仓自造的第二套规则。</p>
     *
     * @param raw 手输/URL 取出的短码
     * @return 归一化后的短码；形态不合法（长度 ≠ 8 或含字符集外字符）⇒ {@code ""}（调用方据此 404）
     */
    public static String normalize(String raw) {
        if (!StringUtils.hasText(raw)) {
            return "";
        }
        String upper = raw.trim().toUpperCase(java.util.Locale.ROOT)
                .replace('O', '0')
                .replace('I', '1')
                .replace('L', '1');
        if (upper.length() != CODE_LENGTH) {
            return "";
        }
        for (int i = 0; i < upper.length(); i++) {
            if (ALPHABET.indexOf(upper.charAt(i)) < 0) {
                return "";
            }
        }
        return upper;
    }

    /**
     * 短码 ⇒ 承载行（**跨租户**查询：短码全局唯一，租户由短码本身解出，设计 C12）。
     *
     * <p>⚠️ 这里**必须**绕过多租户拦截器：`/s/{短码}` 是公开入口（无 JWT / 无工人 session
     * ⇒ `TenantContext` 为空 ⇒ 拦截器会抛 `Tenant context not initialized`）。
     * 绕过的安全性由**部分唯一索引**兜底（`uk_set_part_tokens_short_code`）⇒ 最多命中一行。</p>
     *
     * @param rawCode 短码（手输形态会自动归一化）
     * @return 命中行（{@code token} 为 {@code null} = 已撤销）；未知/形态不合法 ⇒ {@code null}
     */
    public ProcessingSetPartToken resolve(String rawCode) {
        String code = normalize(rawCode);
        if (code.isEmpty()) {
            return null;
        }
        return setPartTokenMapper.selectByShortCode(code);
    }

    /**
     * 分配一个**未被占用**的短码（碰撞重试，设计 §1.4「不静默造重码」）。
     *
     * <p>为什么先查重而不是「靠唯一索引报错再重试」：PG 里唯一约束冲突会让**当前事务进入 aborted
     * 状态**（后续语句全失败），而本方法在实例化事务内被调用 ⇒ 捕获异常重试会连带废掉整个实例化
     * （同族判据见 `ClientRequestIdService` 的类注释）。</p>
     *
     * <p>是 {@code static} 且**显式收 mapper 参数**：唯一调用方
     * （`ProductionService.ensurePartTokens`）已在手该 mapper，而它的构造签名被既有 6 个测试文件
     * 直接 {@code new} 装配 ⇒ 不再注入一个服务只为转发（最少代码阶梯）。**生成/查重口径只有这一份**。</p>
     *
     * @param mapper 部位码 mapper（查重用；跨租户，短码全局唯一）
     * @return 未被占用的短码
     * @throws IllegalStateException 连续 {@value #MAX_ALLOCATE_ATTEMPTS} 次碰撞（fail-closed，不造重码）
     */
    public static String allocateUnique(ProcessingSetPartTokenMapper mapper) {
        return allocateUnique(code -> mapper.selectByShortCode(code) != null);
    }

    /**
     * 分配一个**未被占用**的短码（判据由调用方给）—— 生成/查重口径的**唯一实现**。
     *
     * <p><b>为什么收一个 {@code Predicate} 而不是各码空间各写一份循环</b>（issue #5052 P2）：
     * 入库标签的码空间（{@code /i/}）与报工短链（{@code /s/}）**不是同一张表**（#5052 边界：
     * 「照其范式、不复用其表」），但「随机生成 + 查重 + 碰撞重试 + 到顶 fail-closed」这四件事
     * 必须**只有一份**：复制第二份 = 第二条真相源，日后改一处漏一处（「同一个短码分配器，
     * 两个码空间的碰撞策略不同」这种缺陷不会有任何东西变红）。</p>
     *
     * <p>{@code /s/} 的既有调用方一字不改地走上面那个重载（行为逐字相同：同一 {@code MAX_ALLOCATE_ATTEMPTS}、
     * 同一异常文案），本重载只是把那四件事抽出来给第二个码空间复用。</p>
     *
     * @param isTaken 该短码是否已被占用（跨租户查重：短码全局唯一）
     * @return 未被占用的短码
     * @throws IllegalStateException 连续 {@value #MAX_ALLOCATE_ATTEMPTS} 次碰撞（fail-closed，不造重码）
     */
    public static String allocateUnique(java.util.function.Predicate<String> isTaken) {
        for (int i = 0; i < MAX_ALLOCATE_ATTEMPTS; i++) {
            String code = randomCode();
            if (!isTaken.test(code)) {
                return code;
            }
        }
        throw new IllegalStateException(
                "短码分配连续 " + MAX_ALLOCATE_ATTEMPTS + " 次碰撞 —— 拒绝静默造重码（请检查短码空间/分配器）");
    }

    /**
     * 302 的 {@code Location}（报工页 + token + 租户）。
     *
     * <p><b>刻意用相对 Location</b>（{@code /w/?t=…}）而不是拿请求 Host 拼绝对 URL：
     * ① 请求 Host 可伪造 ⇒ 拼绝对 URL = **开放重定向**面；② 浏览器按 RFC 7231 §7.1.2
     * 用**请求 URL**（HTTPS 短链）解析相对引用 ⇒ 最终落地仍是**标准 HTTPS URL**，
     * 且换域名时这一跳不用改。</p>
     *
     * <p>为什么带上 {@code tenant_id}：短链域名（{@code app.migaozn.com}，**无**租户子域）下页面
     * 判不出租户，而工人登录（{@code POST /api/worker/login}）**必须**有租户
     * （`WorkerAuthController`：判不出 ⇒ 显式拒绝，不落默认租户）⇒ 不带它，工人扫开短链也**报不了工**。
     * 该键是报工页**既有**的回落形态（`frontend/worker-h5/src/scan-input.mjs` 的
     * {@code tenantIdFromLocation} 读 {@code ?tenant_id=}）。租户 id 非敏感（`<tenantId>.app.migaozn.com`
     * 子域形态本身就是公开约定，设计 C12）。</p>
     *
     * @param token    部位码 token（32 位十六进制，无需转义）
     * @param tenantId 租户 id（可空 ⇒ 只带 token）
     * @return 相对 Location
     */
    public static String reportPageLocation(String token, Long tenantId) {
        return REPORT_PAGE_PATH + "?t=" + token
                + (tenantId == null ? "" : "&tenant_id=" + tenantId);
    }
}
