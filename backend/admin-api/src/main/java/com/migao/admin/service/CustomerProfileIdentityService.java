package com.migao.admin.service;

import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.mapper.CustomerProfileMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.OffsetDateTime;

/**
 * 客户档案的**身份收敛 + 订单信息补全**（issue #7711）。
 *
 * <h2>病一：同一人在客户管理里出现两条档案</h2>
 * 三处写入点各自只拿得到**一半**身份键，谁都不认识对方那条：
 * <ul>
 *   <li>建单（{@code CustomerService#createFromOrder}）只有手机号 —— 商户代录时不带 {@code userId}；</li>
 *   <li>小程序登录（{@code CustomerService#createFromSession}）只有 openid —— 原先不传 {@code users.phone}；</li>
 *   <li>授权手机号（{@code MiniPhoneBindService#bind}）**同时**知道手机号与 openid，却完全没通知客户档案。</li>
 * </ul>
 * 于是「先代录下单、后小程序登录」这类最常见的时序必然产出两条：一条 phone、一条 openid，
 * 消费额/订单数被劈成两行，客服也看不出是同一个人。
 *
 * <h2>病二：订单里填的收货/物流信息进不了档案</h2>
 * 结构化列 {@code default_receiver_*} / {@code default_logistics_*} 原先只有
 * {@code PUT /api/admin/customers/{id}} 一个写路径；订单填的地址被塞进 {@code agent_notes} 文本，
 * 物流两列只落 {@code orders}。客户第二次下单选客户时带不出地址与常用物流。
 *
 * <h2>修法（两条口径）</h2>
 * <ol>
 *   <li><b>身份收敛</b>：按「手机号 **和** 微信 openid」一起认人 —— 两个键分别命中的若不是同一行，
 *       就**合并**（keeper = 最早注册那条，与 {@code findFirstByPhone} / {@code findFirstByOpenid}
 *       的 {@code ORDER BY registered_at, id LIMIT 1} 读语义逐字一致 ⇒ 合并后既有读面取值不变）；
 *       只命中一行则把缺的那个身份键补上（补空）。</li>
 *   <li><b>补空不覆盖</b>：收货/物流/昵称等列一律 {@code COALESCE(现值, 新值)}
 *       ⇒ 客服在客户管理里维护过的值**永不**被订单覆盖，只补空。</li>
 * </ol>
 *
 * <p>🔴 <b>顺序即安全顺序</b>：合并时先迁引用 → 补空（不含身份键）→ 删除较晚那条 → **最后**才补身份键。
 * 反过来会撞 V167 的部分唯一索引（{@code uk_customer_profiles_phone} / {@code ..._openid}）：
 * keeper 拿到 loser 还占着的 openid ⇒ 唯一键冲突。</p>
 *
 * <p>🔴 跨表引用迁移用 {@link JdbcTemplate}（与 {@code PriceBookService} 同口径 ——
 * {@code customer_sku_prices} 本来就只有裸 SQL，没有实体/Mapper）。表清单来自 {@code schema.sql} 里
 * {@code customer_id} 的全部引用面；其中 {@code customer_segment_members} / {@code customer_sku_prices}
 * 带 {@code REFERENCES customer_profiles(id)} ⇒ **不迁就删不掉 loser**（外键会拦）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CustomerProfileIdentityService {

    private final CustomerProfileMapper customerProfileMapper;
    private final JdbcTemplate jdbcTemplate;

    /** 建档种子：只在**真的新建**时使用（命中既有档案时一个都不写 —— 不拿订单数据覆盖客户资料）。 */
    public record ProfileSeed(String nickname, String sourceChannel, int totalOrders) {
    }

    /**
     * 按身份键确保档案存在并**收敛成一条**（唯一入口）。
     *
     * @param phone          手机号（可为空；两键全空 ⇒ 无处认人，直接返回 null）
     * @param openid         微信 openid（可为空）
     * @param seed           建档种子（可为 null ⇒ 用渠道默认值）
     * @param createIfMissing {@code false} = 只收敛既有档案、不新建（手机号绑定路径用）
     * @return 最终生效的档案；{@code createIfMissing=false} 且两键都没命中时返回 {@code null}
     */
    @Transactional(rollbackFor = Exception.class)
    public CustomerProfile ensure(Long tenantId, String phone, String openid,
                                  ProfileSeed seed, boolean createIfMissing) {
        String p = trim(phone);
        String o = trim(openid);
        if (p == null && o == null) {
            // 无身份键 ⇒ 无法认人。不建档：旧实现在这条路上每次调用都插一条匿名档案
            // （正是「同一人两条」的同族病灶，issue #7711）。
            log.warn("客户档案收敛跳过：手机号与 openid 均为空, tenantId={}", tenantId);
            return null;
        }

        CustomerProfile byPhone = p == null ? null : customerProfileMapper.findFirstByPhone(tenantId, p);
        CustomerProfile byOpenid = o == null ? null : customerProfileMapper.findFirstByOpenid(tenantId, o);

        CustomerProfile keeper;
        if (byPhone != null && byOpenid != null && !byPhone.getId().equals(byOpenid.getId())) {
            keeper = merge(tenantId, byPhone, byOpenid);
        } else {
            keeper = byPhone != null ? byPhone : byOpenid;
        }

        if (keeper == null) {
            if (!createIfMissing) {
                return null;
            }
            return create(tenantId, p, o, seed);
        }

        fillIdentityBlanks(tenantId, keeper, p, o);
        customerProfileMapper.touchLastActiveAt(tenantId, keeper.getId());
        return keeper;
    }

    /**
     * 订单路径：把订单里填的收货/物流写进档案的**默认收货信息**（补空不覆盖）。
     *
     * <p>只写档案当前为空的那几列；客服在客户管理「收货信息」卡片里维护过的一律不动
     * （用户 2026-10-25 选定「甲」口径：补空不覆盖）。</p>
     */
    @Transactional(rollbackFor = Exception.class)
    public void fillOrderContact(CustomerProfile profile, Long tenantId, String name, String phone,
                                 String address, String logisticsType, String logisticsCompany) {
        if (profile == null) {
            return;
        }
        String n = trim(name);
        String p = trim(phone);
        String a = trim(address);
        String lt = trim(logisticsType);
        String lc = trim(logisticsCompany);

        // 逐列判「这列空着 ∧ 这列有值」—— 全都不需要补 ⇒ 一次写库都不发生（订单是高频路径）。
        boolean need = (n != null && blank(profile.getDefaultReceiverName()))
                || (p != null && blank(profile.getDefaultReceiverPhone()))
                || (a != null && blank(profile.getDefaultReceiverAddress()))
                || (lt != null && blank(profile.getDefaultLogisticsType()))
                || (lc != null && blank(profile.getDefaultLogisticsCompany()));
        if (!need) {
            return;
        }
        jdbcTemplate.update(
                "UPDATE customer_profiles SET "
                        + "default_receiver_name = COALESCE(NULLIF(BTRIM(default_receiver_name), ''), ?::text), "
                        + "default_receiver_phone = COALESCE(NULLIF(BTRIM(default_receiver_phone), ''), ?::text), "
                        + "default_receiver_address = COALESCE(NULLIF(BTRIM(default_receiver_address), ''), ?::text), "
                        + "default_logistics_type = COALESCE(NULLIF(BTRIM(default_logistics_type), ''), ?::text), "
                        + "default_logistics_company = COALESCE(NULLIF(BTRIM(default_logistics_company), ''), ?::text) "
                        + "WHERE id = ? AND tenant_id = ?",
                n, p, a, lt, lc, profile.getId(), tenantId);
        log.info("订单信息已补进客户档案（补空不覆盖）: id={}, tenantId={}", profile.getId(), tenantId);
    }

    // ==================== 建档 ====================

    private CustomerProfile create(Long tenantId, String phone, String openid, ProfileSeed seed) {
        String sourceChannel = seed != null && StringUtils.hasText(seed.sourceChannel())
                ? seed.sourceChannel() : "wechat_mini";
        CustomerProfile candidate = CustomerProfileWriter.candidate(tenantId)
                .wechatNickname(seed == null ? null : seed.nickname())
                .build();
        candidate.setSourceChannel(sourceChannel);
        // 首单建档的既有口径：订单数从 1 起算（不是 0）。
        // 🔴 这里刻意写**常量 1**（而不是 seed.totalOrders()）：total_orders 在字段真值声明里是
        // NO_TRUTH（只有建档常量种子、没有增量维护）—— 传动态值会被 `CustomerProfileFieldTruthGateTest`
        // 判成「有真值写入点」⇒ 红。口径要动就同时改声明，不许在这一处偷偷升级语义。
        if (seed != null && seed.totalOrders() > 0) {
            candidate.setTotalOrders(1);
        }

        CustomerProfileWriter.Result result;
        if (phone != null) {
            candidate.setPhone(phone);
            candidate.setWechatOpenid(openid);
            result = CustomerProfileWriter.ensureByPhone(customerProfileMapper, candidate);
        } else {
            candidate.setWechatOpenid(openid);
            result = CustomerProfileWriter.ensureByOpenid(customerProfileMapper, candidate);
        }
        if (result.created() && openid != null && phone != null) {
            fillIdentityBlanks(tenantId, result.profile(), phone, openid);
        }
        return result.profile();
    }

    // ==================== 身份键补空 ====================

    private void fillIdentityBlanks(Long tenantId, CustomerProfile profile, String phone, String openid) {
        boolean needPhone = phone != null && blank(profile.getPhone());
        boolean needOpenid = openid != null && blank(profile.getWechatOpenid());
        if (!needPhone && !needOpenid) {
            return;
        }
        jdbcTemplate.update(
                "UPDATE customer_profiles SET "
                        + "phone = COALESCE(NULLIF(BTRIM(phone), ''), ?::text), "
                        + "wechat_openid = COALESCE(NULLIF(BTRIM(wechat_openid), ''), ?::text) "
                        + "WHERE id = ? AND tenant_id = ?",
                needPhone ? phone : null, needOpenid ? openid : null, profile.getId(), tenantId);
        if (needPhone) {
            profile.setPhone(phone);
        }
        if (needOpenid) {
            profile.setWechatOpenid(openid);
        }
    }

    // ==================== 合并 ====================

    /**
     * 把「同一个人」的两条档案合成一条：keeper = **最早注册**那条（与读面 {@code findFirst*} 同序）。
     *
     * <p>删除较晚那条是**有意**的：客户管理 / 分群 / 账龄都按档案行计数，留一条「已合并」的幽灵行
     * 反而要求每条读路径都加过滤（第二份口径）。引用先迁移、空列先补空 ⇒ 不丢数据。</p>
     */
    private CustomerProfile merge(Long tenantId, CustomerProfile a, CustomerProfile b) {
        CustomerProfile keeper = earlier(a, b);
        CustomerProfile loser = keeper.getId().equals(a.getId()) ? b : a;
        log.warn("[customer-profile] 识别到同一人的两条档案，自动合并: keeper={}, loser={}, tenantId={}",
                keeper.getId(), loser.getId(), tenantId);

        moveReferences(tenantId, keeper.getId(), loser.getId());
        fillFromLoser(tenantId, keeper, loser);
        // 先删 loser 再补身份键：否则 keeper 要拿的 phone/openid 还占在 loser 身上 ⇒ 撞部分唯一索引
        customerProfileMapper.deleteById(loser.getId());
        fillIdentityBlanks(tenantId, keeper, trim(loser.getPhone()), trim(loser.getWechatOpenid()));

        CustomerProfile merged = customerProfileMapper.selectById(keeper.getId());
        return merged != null ? merged : keeper;
    }

    private void moveReferences(Long tenantId, String keeperId, String loserId) {
        // 无外键的三张：直接改挂
        jdbcTemplate.update("UPDATE sessions SET customer_id = ? WHERE tenant_id = ? AND customer_id = ?",
                keeperId, tenantId, loserId);
        jdbcTemplate.update("UPDATE agent_sessions SET customer_id = ? WHERE tenant_id = ? AND customer_id = ?",
                keeperId, tenantId, loserId);
        jdbcTemplate.update("UPDATE after_sales_tickets SET customer_id = ? WHERE tenant_id = ? AND customer_id = ?",
                keeperId, tenantId, loserId);
        // 有外键的两张：先删「keeper 已占同一唯一键」的 loser 行，再改挂其余（否则撞 UNIQUE）
        jdbcTemplate.update("DELETE FROM customer_segment_members l WHERE l.tenant_id = ? AND l.customer_id = ? "
                        + "AND EXISTS (SELECT 1 FROM customer_segment_members k "
                        + "WHERE k.segment_id = l.segment_id AND k.customer_id = ?)",
                tenantId, loserId, keeperId);
        jdbcTemplate.update("UPDATE customer_segment_members SET customer_id = ? "
                + "WHERE tenant_id = ? AND customer_id = ?", keeperId, tenantId, loserId);
        jdbcTemplate.update("DELETE FROM customer_sku_prices l WHERE l.tenant_id = ? AND l.customer_id = ? "
                        + "AND l.deleted = 0 AND EXISTS (SELECT 1 FROM customer_sku_prices k "
                        + "WHERE k.tenant_id = l.tenant_id AND k.sku_id = l.sku_id "
                        + "AND k.customer_id = ? AND k.deleted = 0)",
                tenantId, loserId, keeperId);
        jdbcTemplate.update("UPDATE customer_sku_prices SET customer_id = ? "
                + "WHERE tenant_id = ? AND customer_id = ?", keeperId, tenantId, loserId);
    }

    /** keeper 的空列从 loser 补（补空不覆盖；tags 是 JSONB，不在此处搬 —— 见 issue #7711 边界）。 */
    private void fillFromLoser(Long tenantId, CustomerProfile keeper, CustomerProfile loser) {
        jdbcTemplate.update(
                "UPDATE customer_profiles SET "
                        + "wechat_nickname = COALESCE(NULLIF(BTRIM(wechat_nickname), ''), ?::text), "
                        + "agent_notes = COALESCE(NULLIF(BTRIM(agent_notes), ''), ?::text), "
                        + "region_province = COALESCE(NULLIF(BTRIM(region_province), ''), ?::text), "
                        + "region_city = COALESCE(NULLIF(BTRIM(region_city), ''), ?::text), "
                        + "region_district = COALESCE(NULLIF(BTRIM(region_district), ''), ?::text), "
                        + "default_receiver_name = COALESCE(NULLIF(BTRIM(default_receiver_name), ''), ?::text), "
                        + "default_receiver_phone = COALESCE(NULLIF(BTRIM(default_receiver_phone), ''), ?::text), "
                        + "default_receiver_address = COALESCE(NULLIF(BTRIM(default_receiver_address), ''), ?::text), "
                        + "default_logistics_type = COALESCE(NULLIF(BTRIM(default_logistics_type), ''), ?::text), "
                        + "default_logistics_company = COALESCE(NULLIF(BTRIM(default_logistics_company), ''), ?::text) "
                        + "WHERE id = ? AND tenant_id = ?",
                trim(loser.getWechatNickname()), trim(loser.getAgentNotes()),
                trim(loser.getRegionProvince()), trim(loser.getRegionCity()), trim(loser.getRegionDistrict()),
                trim(loser.getDefaultReceiverName()), trim(loser.getDefaultReceiverPhone()),
                trim(loser.getDefaultReceiverAddress()), trim(loser.getDefaultLogisticsType()),
                trim(loser.getDefaultLogisticsCompany()), keeper.getId(), tenantId);
    }

    /** 最早注册的那条（与 {@code findFirstByPhone/ByOpenid} 的 {@code ORDER BY registered_at, id} 同序）。 */
    private static CustomerProfile earlier(CustomerProfile a, CustomerProfile b) {
        OffsetDateTime ra = a.getRegisteredAt();
        OffsetDateTime rb = b.getRegisteredAt();
        if (ra == null && rb == null) {
            return a.getId().compareTo(b.getId()) <= 0 ? a : b;
        }
        if (ra == null) {
            return b;
        }
        if (rb == null) {
            return a;
        }
        int cmp = ra.compareTo(rb);
        if (cmp == 0) {
            return a.getId().compareTo(b.getId()) <= 0 ? a : b;
        }
        return cmp < 0 ? a : b;
    }

    // ==================== 小工具 ====================

    private static boolean blank(String value) {
        return value == null || value.isBlank();
    }

    private static String trim(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }
}
