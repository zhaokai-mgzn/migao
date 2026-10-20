package com.migao.admin.service;

import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.*;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.*;
import com.migao.admin.support.fieldtruth.CustomerProfileTruthMask;
import com.migao.admin.support.fieldtruth.FieldTruth;
import com.migao.admin.support.fieldtruth.FieldTruthRegistry;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.lang.reflect.Field;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 客户服务类
 * 处理客户档案管理、标签管理、客户分群等业务逻辑
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CustomerService extends ServiceImpl<CustomerProfileMapper, CustomerProfile> {

    private final CustomerProfileMapper customerProfileMapper;

    /** 业务「今天」/业务时区单点（issue #3802）：账龄分档的基准日不许多头算。 */
    private final com.migao.admin.time.BusinessClock businessClock;
    private final CustomerTagMapper customerTagMapper;
    private final CustomerSegmentMapper customerSegmentMapper;
    private final CustomerSegmentMemberMapper customerSegmentMemberMapper;
    private final OrderMapper orderMapper;
    private final SessionMapper sessionMapper;
    private final SessionMessageMapper sessionMessageMapper;

    /**
     * craft_mode 允许值（单一事实源 = V47 迁移的列注释 / {@link CustomerProfile#getCraftMode()} javadoc）。
     * 非法值一律显式拒绝：静默落库会让「工艺画像」在下游算料/报价时按未知模式运行（issue #4115）。
     */
    private static final Set<String> CRAFT_MODES = Set.of("standard", "economy", "self_quoted");

    // ==================== 客户列表与详情 ====================

    /**
     * 分页查询客户列表
     *
     * @param page          页码
     * @param size          每页大小
     * @param sourceChannel 来源渠道筛选
     * @param vipLevel      VIP等级筛选
     * @param keyword       关键词搜索（昵称/手机号）
     * @param tenantId      租户ID
     * @return 分页响应
     */
    public PageResponse<CustomerProfile> getCustomerPage(long page, long size,
                                                          String sourceChannel, String vipLevel,
                                                          String keyword, Long tenantId) {
        return getCustomerPage(page, size, sourceChannel, vipLevel, keyword, tenantId, null);
    }

    /**
     * 客户列表 + **数据范围**（issue #7372 段 2）。
     *
     * <p>口径（用户 2026-10-21 裁定）：「加『客户负责人』字段，未指派的按『有单的客户』兜底」⇒
     * `owner_user_id = 我` **或**（`owner_user_id IS NULL` 且我有该客户（按 phone 关联）的单）。
     * 没有兜底的话，存量客户全是未指派 ⇒ 业务员上线当天看不见任何客户，看起来像数据丢了。</p>
     *
     * @param scopeOwnerId 非 null ⇒ 本人范围（值 = 当前用户 id）；null ⇒ 不收窄（租户级）
     */
    public PageResponse<CustomerProfile> getCustomerPage(long page, long size,
                                                          String sourceChannel, String vipLevel,
                                                          String keyword, Long tenantId,
                                                          String scopeOwnerId) {
        LambdaQueryWrapper<CustomerProfile> wrapper = new LambdaQueryWrapper<>();
        if (StringUtils.hasText(scopeOwnerId)) {
            // 本人范围：我负责的 + 未指派但我出过单的（子查询按 phone 归属，与账龄口径同键）
            wrapper.and(w -> w.eq(CustomerProfile::getOwnerUserId, scopeOwnerId)
                    .or()
                    .apply("(owner_user_id IS NULL AND EXISTS ("
                            + "SELECT 1 FROM orders o WHERE o.tenant_id = customer_profiles.tenant_id"
                            + " AND o.deleted = 0 AND o.created_by = {0}"
                            + " AND o.customer_phone = customer_profiles.phone))", scopeOwnerId));
        }

        // 来源渠道筛选
        if (StringUtils.hasText(sourceChannel)) {
            wrapper.eq(CustomerProfile::getSourceChannel, sourceChannel);
        }

        // VIP等级筛选
        if (StringUtils.hasText(vipLevel)) {
            wrapper.eq(CustomerProfile::getVipLevel, vipLevel);
        }

        // 关键词搜索
        // 第三列 = 默认收货电话（issue #4436，跟随 #4419）：发货页按**订单收货电话**反查客户档案，
        // 而收货电话可以≠账户手机号（送到工地/仓库、联系人是另一人 —— 正是收货信息要支持的场景）。
        // 不把这一列纳入搜索 ⇒ 那类订单在发货页查不到客户 ⇒ 常用物流方式/公司静默带不出。
        if (StringUtils.hasText(keyword)) {
            wrapper.and(w -> w.like(CustomerProfile::getWechatNickname, keyword)
                    .or()
                    .like(CustomerProfile::getPhone, keyword)
                    .or()
                    .like(CustomerProfile::getDefaultReceiverPhone, keyword));
        }

        wrapper.orderByDesc(CustomerProfile::getCreatedAt);

        Page<CustomerProfile> customerPage = new Page<>(page, size);
        Page<CustomerProfile> resultPage = customerProfileMapper.selectPage(customerPage, wrapper);

        // tags 口径统一（#3665 冒烟 B2）：列表与详情必须同形态（标签对象数组）。
        // customer_profiles.tags 存的是标签 ID 数组，原样下发会让前端拿到字符串数组，
        // 与 CustomerTag[] 类型契约不符（冒烟期只能页内容忍 → 空 chip + React key 警告）。
        // 复用详情同一套解析实现（resolveCustomerTags），租户标签按页缓存避免 N+1。
        Map<Long, List<CustomerTag>> tenantTagCache = new HashMap<>();
        for (CustomerProfile record : resultPage.getRecords()) {
            record.setTags(resolveCustomerTags(record, tenantTagCache));
            // 暴露面（issue #5362）：声明「无真值」的字段一律回 null（未知），
            // 不得把 DB 列默认值 0 / 30 / 'new' 当成真数据下发（页面与 Agent 同受约束）
            CustomerProfileTruthMask.apply(record);
        }

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(),
                resultPage.getSize(), resultPage.getRecords());
    }

    /**
     * 查询客户详情（含标签、订单历史、会话历史）
     *
     * @param customerId 客户ID
     * @return 客户详情Map
     */
    public Map<String, Object> getCustomerDetail(String customerId) {
        return getCustomerDetail(customerId, null);
    }

    /**
     * 客户详情 + **数据范围**（issue #7372 段 2）：范围外 ⇒ 与「不存在」**同一个 404**（不 403，
     * 不泄露「这个客户存在」）。
     *
     * <p>判据与列表**同一条**（{@link #ownedByMe}）：列表筛掉的和详情拦掉的必须是同一批，
     * 否则会出现「列表里没有、拼 id 却打得开」这种半成品。</p>
     */
    public Map<String, Object> getCustomerDetail(String customerId, String scopeOwnerId) {
        CustomerProfile profile = customerProfileMapper.selectById(customerId);
        if (profile == null) {
            throw BusinessException.notFound("客户");
        }
        if (StringUtils.hasText(scopeOwnerId) && !ownedByMe(profile, scopeOwnerId)) {
            throw BusinessException.notFound("客户");
        }

        // 暴露面（issue #5362）：Agent 的 customer_manage(detail) 读的就是这份 profile
        CustomerProfileTruthMask.apply(profile);

        Map<String, Object> detail = new HashMap<>();
        detail.put("id", profile.getId());
        detail.put("profile", profile);

        // 查询客户已关联标签（按 profile.tags 中的标签 ID 过滤，而非返回租户全部标签）
        detail.put("tags", resolveCustomerTags(profile, new HashMap<>()));

        // 查询订单历史（最近10条）
        LambdaQueryWrapper<Order> orderWrapper = new LambdaQueryWrapper<>();
        orderWrapper.eq(Order::getCustomerPhone, profile.getPhone())
                .orderByDesc(Order::getCreatedAt)
                .last("LIMIT 10");
        List<Order> orders = orderMapper.selectList(orderWrapper);
        detail.put("orders", orders);

        // 查询会话历史（最近10条），附带最后一条消息与是否 AI 对话
        LambdaQueryWrapper<Session> sessionWrapper = new LambdaQueryWrapper<>();
        sessionWrapper.eq(Session::getCustomerId, customerId)
                .orderByDesc(Session::getCreatedAt)
                .last("LIMIT 10");
        List<Session> sessions = sessionMapper.selectList(sessionWrapper);
        List<Map<String, Object>> sessionItems = new ArrayList<>();
        for (Session session : sessions) {
            Map<String, Object> item = new HashMap<>();
            item.put("id", session.getId());
            item.put("channel", session.getChannel());
            item.put("createdAt", session.getCreatedAt());
            item.put("isAI", Boolean.TRUE.equals(session.getAiEnabled()));
            // 取最后一条消息作为摘要
            SessionMessage lastMsg = sessionMessageMapper.selectOne(
                    new LambdaQueryWrapper<SessionMessage>()
                            .eq(SessionMessage::getSessionId, session.getId())
                            .orderByDesc(SessionMessage::getCreatedAt)
                            .last("LIMIT 1"));
            item.put("lastMessage", lastMsg != null && StringUtils.hasText(lastMsg.getContent())
                    ? lastMsg.getContent() : "");
            sessionItems.add(item);
        }
        detail.put("sessions", sessionItems);

        return detail;
    }

    // ==================== 客户档案管理 ====================

    /**
     * 创建客户档案
     *
     * @param profile 客户档案实体
     * @return 创建的客户档案
     */
    @Transactional(rollbackFor = Exception.class)
    public CustomerProfile createCustomer(CustomerProfile profile) {
        // 检查手机号唯一性（如果有手机号）。
        // issue #7257：读侧改用 findFirstByPhone —— 历史重复行存在时 selectOne 会抛 TooManyResultsException（500）
        if (StringUtils.hasText(profile.getPhone())
                && customerProfileMapper.findFirstByPhone(profile.getTenantId(), profile.getPhone()) != null) {
            throw BusinessException.validationError("该手机号已存在客户档案");
        }

        // 设置默认值
        if (profile.getVipLevel() == null) {
            profile.setVipLevel("normal");
        }
        if (profile.getCustomerStatus() == null) {
            profile.setCustomerStatus("active");
        }
        if (profile.getLifecycleStage() == null) {
            profile.setLifecycleStage("new");
        }
        if (profile.getTotalOrders() == null) {
            profile.setTotalOrders(0);
        }
        if (profile.getTotalConsumption() == null) {
            profile.setTotalConsumption(BigDecimal.ZERO);
        }
        if (profile.getRegisteredAt() == null) {
            profile.setRegisteredAt(OffsetDateTime.now());
        }

        // issue #7257：撞唯一键（并发下对手先建）⇒ 收敛成同一句 422，而不是把 DataIntegrityViolation 冒成 500
        CustomerProfileWriter.Result result = CustomerProfileWriter.ensureByPhone(customerProfileMapper, profile);
        if (!result.created()) {
            throw BusinessException.validationError("该手机号已存在客户档案");
        }
        log.info("创建客户档案成功: id={}, phone={}", result.profile().getId(), result.profile().getPhone());
        return result.profile();
    }

    /**
     * 从会话中自动创建客户档案
     *
     * @param tenantId       租户ID
     * @param wechatOpenid   微信OpenID
     * @param wechatNickname 微信昵称
     * @param sourceChannel  来源渠道
     * @return 客户档案
     */
    @Transactional(rollbackFor = Exception.class)
    public CustomerProfile createFromSession(Long tenantId, String wechatOpenid,
                                              String wechatNickname, String sourceChannel) {
        // issue #7257：建档收口到单一实现点（回读 → 撞键不插 → 撞并发回读对手那条）。
        // 原先是「selectOne 判空 + insert」的读改写：本表没有唯一约束 ⇒ 并发会静默建出两条档案。
        if (!StringUtils.hasText(wechatOpenid)) {
            CustomerProfile anonymous = CustomerProfileWriter.candidate(tenantId)
                    .wechatNickname(wechatNickname)
                    .build();
            anonymous.setSourceChannel(sourceChannel != null ? sourceChannel : "wechat_mini");
            // openid 为空 ⇒ 无处去重（保持原有行为），但建行仍只从写面发生
            return CustomerProfileWriter.createAnonymous(customerProfileMapper, anonymous);
        }
        CustomerProfile candidate = CustomerProfileWriter.candidate(tenantId)
                .wechatNickname(wechatNickname)
                .build();
        // 显式赋值（而不是塞进 builder 链）：本表有「字段级真值守卫」（issue #5362），它按
        // `CustomerProfile x = …` + `x.setXxx(v)` 与 `CustomerProfile.builder()` 链两种形态扫写入点；
        // 写面抽到 CustomerProfileWriter 之后 builder 链换了入口，故真值级写入在这里显式表达。
        candidate.setWechatOpenid(wechatOpenid);
        candidate.setSourceChannel(sourceChannel != null ? sourceChannel : "wechat_mini");
        CustomerProfileWriter.Result result = CustomerProfileWriter.ensureByOpenid(customerProfileMapper, candidate);
        log.info("从会话建档{}: id={}, wechatOpenid={}", result.created() ? "成功" : "命中既有档案",
                result.profile().getId(), wechatOpenid);
        return result.profile();
    }

    /**
     * 从订单信息自动创建/更新客户档案
     * 首次下单时自动建档；若已存在同手机号的客户，则刷新最后活跃时间并返回。
     *
     * @param tenantId        租户ID
     * @param customerName    客户姓名（用于昵称兜底）
     * @param customerPhone   客户手机号（去重主键）
     * @param customerAddress 客户收货地址（无统一地址字段，记录到 agentNotes）
     * @return 客户档案
     */
    @Transactional(rollbackFor = Exception.class)
    public CustomerProfile createFromOrder(Long tenantId, String customerName,
                                            String customerPhone, String customerAddress) {
        // 手机号为空无法去重，跳过建档
        if (!StringUtils.hasText(customerPhone)) {
            log.warn("createFromOrder 跳过：customerPhone 为空, tenantId={}", tenantId);
            return null;
        }

        // issue #7257：同一条写面（回读 → 撞键不插 → 撞并发回读对手那条）
        CustomerProfile candidate = CustomerProfileWriter.candidate(tenantId)
                .wechatNickname(customerName)
                .phone(customerPhone)
                .agentNotes(StringUtils.hasText(customerAddress) ? "首单收货地址：" + customerAddress : null)
                .build();
        candidate.setSourceChannel("order");
        // 首单建档的既有口径：订单数从 1 起算（不是 0）—— 原先写在 builder 链里，抽出写面后显式表达
        candidate.setTotalOrders(1);
        CustomerProfileWriter.Result result = CustomerProfileWriter.ensureByPhone(customerProfileMapper, candidate);
        log.info("从订单建档{}: id={}, phone={}, tenantId={}",
                result.created() ? "成功" : "命中既有档案", result.profile().getId(), customerPhone, tenantId);
        return result.profile();
    }

    /**
     * 更新客户档案
     *
     * @param customerId 客户ID
     * @param profile    更新的字段
     * @return 更新后的客户档案
     */
    @Transactional(rollbackFor = Exception.class)
    public CustomerProfile updateCustomer(String customerId, CustomerProfile profile) {
        CustomerProfile existing = customerProfileMapper.selectById(customerId);
        if (existing == null) {
            throw BusinessException.notFound("客户");
        }

        // 更新非空字段
        if (StringUtils.hasText(profile.getPhone())) {
            existing.setPhone(profile.getPhone());
        }
        if (StringUtils.hasText(profile.getWechatNickname())) {
            existing.setWechatNickname(profile.getWechatNickname());
        }
        if (StringUtils.hasText(profile.getGender())) {
            existing.setGender(profile.getGender());
        }
        if (StringUtils.hasText(profile.getRegionProvince())) {
            existing.setRegionProvince(profile.getRegionProvince());
        }
        if (StringUtils.hasText(profile.getRegionCity())) {
            existing.setRegionCity(profile.getRegionCity());
        }
        if (StringUtils.hasText(profile.getRegionDistrict())) {
            existing.setRegionDistrict(profile.getRegionDistrict());
        }
        if (StringUtils.hasText(profile.getVipLevel())) {
            existing.setVipLevel(profile.getVipLevel());
        }
        if (StringUtils.hasText(profile.getCustomerStatus())) {
            existing.setCustomerStatus(profile.getCustomerStatus());
        }
        if (profile.getAgentNotes() != null) {
            existing.setAgentNotes(profile.getAgentNotes());
        }
        if (profile.getTags() != null) {
            existing.setTags(profile.getTags());
        }
        if (profile.getCustomFields() != null) {
            existing.setCustomFields(profile.getCustomFields());
        }
        // --- 工艺画像与常用物流（issue #4115：这 4 列曾是「工具可写 + 服务层静默丢弃」的缺口）---
        // craftMode 是枚举列（VARCHAR(16)，无 DB CHECK），非法值必须在写入前显式拒绝：
        // 静默存进未知模式 = 下游算料/报价按未知模式运行，且工具会谎报「已更新」。
        if (StringUtils.hasText(profile.getCraftMode())) {
            existing.setCraftMode(requireValidCraftMode(profile.getCraftMode()));
        }
        if (profile.getCraftProfile() != null) {
            existing.setCraftProfile(profile.getCraftProfile());
        }
        if (StringUtils.hasText(profile.getDefaultLogisticsType())) {
            existing.setDefaultLogisticsType(profile.getDefaultLogisticsType());
        }
        if (StringUtils.hasText(profile.getDefaultLogisticsCompany())) {
            existing.setDefaultLogisticsCompany(profile.getDefaultLogisticsCompany());
        }
        // --- 默认收货信息（issue #4419，V70）---
        // 与上面同口径：只在**显式非空**时覆盖（空白/缺省一律不动既有值）——
        // 客户管理页只提交改动过的字段，空白若当成「清空」会把已录地址误抹掉。
        if (StringUtils.hasText(profile.getDefaultReceiverName())) {
            existing.setDefaultReceiverName(profile.getDefaultReceiverName());
        }
        if (StringUtils.hasText(profile.getDefaultReceiverPhone())) {
            existing.setDefaultReceiverPhone(profile.getDefaultReceiverPhone());
        }
        if (StringUtils.hasText(profile.getDefaultReceiverAddress())) {
            existing.setDefaultReceiverAddress(profile.getDefaultReceiverAddress());
        }

        customerProfileMapper.updateById(existing);
        // 暴露面（issue #5362）：PUT 的响应同样是「对外返回体」
        CustomerProfileTruthMask.apply(existing);
        log.info("更新客户档案成功: id={}", customerId);
        return existing;
    }

    /**
     * 校验工艺画像模式（craftMode）。
     *
     * @param craftMode 待写入的模式值
     * @return 合法值原样返回
     * @throws BusinessException 非法值 → HTTP 400 + VALIDATION_ERROR + LLM 可执行的修复建议
     *                           （不得静默吞掉，也不得落库存未知模式；issue #4115）
     */
    private static String requireValidCraftMode(String craftMode) {
        if (!CRAFT_MODES.contains(craftMode)) {
            throw new BusinessException(
                    "VALIDATION_ERROR",
                    "无效的 craftMode（工艺画像模式）: " + craftMode,
                    400,
                    "craftMode 只能是 standard（跟随企业固定工艺）/ economy（主动省料）/ "
                            + "self_quoted（自报用料）之一；请改用合法值后重试，其余字段不受影响");
        }
        return craftMode;
    }

    // ==================== 客户标签管理 ====================

    /**
     * 查询租户下所有标签
     *
     * @param tenantId 租户ID
     * @return 标签列表
     */
    public List<CustomerTag> getCustomerTags(Long tenantId) {
        LambdaQueryWrapper<CustomerTag> wrapper = new LambdaQueryWrapper<>();
        wrapper.orderByDesc(CustomerTag::getCreatedAt);
        return customerTagMapper.selectList(wrapper);
    }

    /**
     * 给客户添加标签（写入 customer_profiles.tags JSONB 的标签 ID 列表）
     *
     * @param customerId 客户ID
     * @param tagId      标签ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void addTagToCustomer(String customerId, String tagId) {
        CustomerProfile profile = customerProfileMapper.selectById(customerId);
        if (profile == null) {
            throw BusinessException.notFound("客户");
        }
        // 校验标签存在
        CustomerTag tag = customerTagMapper.selectById(tagId);
        if (tag == null) {
            throw BusinessException.notFound("客户标签");
        }
        List<String> tagIds = new ArrayList<>(readTagIds(profile.getTags()));
        if (tagIds.contains(tagId)) {
            log.info("客户已存在该标签，跳过: customerId={}, tagId={}", customerId, tagId);
            return;
        }
        tagIds.add(tagId);
        profile.setTags(tagIds);
        customerProfileMapper.updateById(profile);
        log.info("客户添加标签成功: customerId={}, tagId={}", customerId, tagId);
    }

    /**
     * 移除客户标签（从 customer_profiles.tags JSONB 删除标签 ID）
     *
     * @param customerId 客户ID
     * @param tagId      标签ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void removeTagFromCustomer(String customerId, String tagId) {
        CustomerProfile profile = customerProfileMapper.selectById(customerId);
        if (profile == null) {
            throw BusinessException.notFound("客户");
        }
        List<String> tagIds = new ArrayList<>(readTagIds(profile.getTags()));
        if (!tagIds.remove(tagId)) {
            log.info("客户不存在该标签，幂等跳过: customerId={}, tagId={}", customerId, tagId);
            return;
        }
        profile.setTags(tagIds);
        customerProfileMapper.updateById(profile);
        log.info("客户移除标签成功: customerId={}, tagId={}", customerId, tagId);
    }

    /**
     * 解析 customer_profiles.tags JSONB 为标签 ID 列表（兼容 null / 单字符串 / 字符串列表）
     */
    @SuppressWarnings("unchecked")
    private List<String> readTagIds(Object tags) {
        if (tags == null) {
            return List.of();
        }
        if (tags instanceof List) {
            List<?> list = (List<?>) tags;
            return list.stream()
                    .filter(item -> item != null)
                    .map(String::valueOf)
                    .toList();
        }
        return List.of(String.valueOf(tags));
    }

    /**
     * 把档案里的标签 ID 列表解析为标签对象列表（列表与详情**唯一**口径，见 #3665 冒烟 B2）。
     *
     * 「客户 tags 是对象数组」这一 API 契约的单一实现点：getCustomerPage 与 getCustomerDetail
     * 都必须经此方法产出，避免两处各写一套再次分叉（冒烟实证：列表下发字符串 ID 数组、
     * 详情下发对象数组，前端只能靠页内容忍）。
     *
     * @param profile       客户档案（tags 可为原始 ID 数组）
     * @param tenantTagCache 租户 ID → 标签列表 的页内缓存，避免列表逐行查标签；传 null 则不缓存
     * @return 客户已关联的标签对象列表（顺序与档案中 ID 顺序无关；未打标时为空列表）
     */
    private List<CustomerTag> resolveCustomerTags(CustomerProfile profile,
                                                  Map<Long, List<CustomerTag>> tenantTagCache) {
        List<String> linkedTagIds = readTagIds(profile.getTags());
        if (linkedTagIds.isEmpty()) {
            // 无标签：直接空列表，省一次标签表查询（与详情原有 `linkedTagIds.isEmpty() ? List.of()` 一致）
            return List.of();
        }
        Long tenantId = profile.getTenantId();
        List<CustomerTag> allTags = tenantTagCache == null
                ? getCustomerTags(tenantId)
                : tenantTagCache.computeIfAbsent(tenantId, this::getCustomerTags);
        return allTags.stream()
                .filter(t -> linkedTagIds.contains(t.getId()))
                .toList();
    }

    /**
     * 创建客户标签
     *
     * @param tag 标签实体
     * @return 创建的标签
     */
    @Transactional(rollbackFor = Exception.class)
    public CustomerTag createTag(CustomerTag tag) {
        // 验证标签名称唯一性
        LambdaQueryWrapper<CustomerTag> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(CustomerTag::getName, tag.getName())
                .eq(CustomerTag::getTenantId, tag.getTenantId());
        CustomerTag existing = customerTagMapper.selectOne(wrapper);
        if (existing != null) {
            throw BusinessException.validationError("标签名称已存在: " + tag.getName());
        }

        if (tag.getTagType() == null) {
            tag.setTagType("manual");
        }
        if (tag.getHitCount() == null) {
            tag.setHitCount(0);
        }

        customerTagMapper.insert(tag);
        log.info("创建客户标签成功: id={}, name={}", tag.getId(), tag.getName());
        return tag;
    }

    /**
     * 更新客户标签
     *
     * @param tagId 标签ID
     * @param tag   更新的标签数据
     * @return 更新后的标签
     */
    @Transactional(rollbackFor = Exception.class)
    public CustomerTag updateTag(String tagId, CustomerTag tag) {
        CustomerTag existing = customerTagMapper.selectById(tagId);
        if (existing == null) {
            throw BusinessException.notFound("标签");
        }
        if (StringUtils.hasText(tag.getName())) {
            existing.setName(tag.getName());
        }
        if (StringUtils.hasText(tag.getColor())) {
            existing.setColor(tag.getColor());
        }
        if (tag.getDescription() != null) {
            existing.setDescription(tag.getDescription());
        }
        customerTagMapper.updateById(existing);
        log.info("更新客户标签成功: id={}, name={}", tagId, existing.getName());
        return existing;
    }

    /**
     * 删除客户标签
     *
     * @param tagId 标签ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteTag(String tagId) {
        CustomerTag tag = customerTagMapper.selectById(tagId);
        if (tag == null) {
            throw BusinessException.notFound("标签");
        }
        // issue #6956 · 现象 C：并发双删只许一次成功（0 行 = 已被别人删掉）
        if (customerTagMapper.deleteById(tagId) == 0) {
            throw BusinessException.notFound("标签");
        }
        log.info("删除客户标签成功: id={}", tagId);
    }

    // ==================== 客户分群 ====================

    /**
     * 查询客户分群列表
     *
     * @param tenantId 租户ID
     * @return 分群列表
     */
    public List<CustomerSegment> getSegments(Long tenantId) {
        LambdaQueryWrapper<CustomerSegment> wrapper = new LambdaQueryWrapper<>();
        wrapper.orderByDesc(CustomerSegment::getCreatedAt);
        return customerSegmentMapper.selectList(wrapper);
    }

    /**
     * 创建客户分群规则
     * TODO: 实现基于规则的自动分群计算
     *
     * @param segment 分群规则实体
     * @return 创建的分群
     */
    @Transactional(rollbackFor = Exception.class)
    public CustomerSegment createSegment(CustomerSegment segment) {
        if (segment.getCustomerCount() == null) {
            segment.setCustomerCount(0);
        }
        customerSegmentMapper.insert(segment);
        log.info("创建客户分群成功: id={}, name={}", segment.getId(), segment.getName());
        // TODO: 触发分群计算任务
        return segment;
    }

    /**
     * 查询分群下的客户列表
     *
     * @param segmentId 分群ID
     * @param page      页码
     * @param size      每页大小
     * @return 客户分页列表
     */
    public PageResponse<CustomerProfile> getSegmentMembers(String segmentId, long page, long size) {
        LambdaQueryWrapper<CustomerSegmentMember> memberWrapper = new LambdaQueryWrapper<>();
        memberWrapper.eq(CustomerSegmentMember::getSegmentId, segmentId);
        List<CustomerSegmentMember> members = customerSegmentMemberMapper.selectList(memberWrapper);

        if (members.isEmpty()) {
            return PageResponse.of(0L, page, size, List.of());
        }

        List<String> customerIds = members.stream()
                .map(CustomerSegmentMember::getCustomerId)
                .collect(Collectors.toList());

        LambdaQueryWrapper<CustomerProfile> profileWrapper = new LambdaQueryWrapper<>();
        profileWrapper.in(CustomerProfile::getId, customerIds)
                .orderByDesc(CustomerProfile::getCreatedAt);

        Page<CustomerProfile> customerPage = new Page<>(page, size);
        Page<CustomerProfile> resultPage = customerProfileMapper.selectPage(customerPage, profileWrapper);

        // 暴露面（issue #5362）：同一个实体走哪条读路径都要遮蔽
        resultPage.getRecords().forEach(CustomerProfileTruthMask::apply);

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(),
                resultPage.getSize(), resultPage.getRecords());
    }

    // ==================== 具名跨域视图 · 客户画像（族 3 · 包 3，issue #5456）====================

    /**
     * 客户画像视图的**装配腿**（按需消费入口：{@code GET /api/admin/customers/profile-view}，
     * 权限码 {@code customer:view}）。
     *
     * <p>产出与族 3 跨域视图内核**同一形状**的确定性快照（自描述 + 有界 + 行数组），外加本单新增的
     * **真值声明运输**：</p>
     *
     * <ul>
     *   <li><b>字段集与真值侧现取</b>：{@link FieldTruthRegistry#customerProfile()} —— 装配与消费两侧
     *       都不持有第二份真值判断（哪些字段有真值由 issue #5362 的声明说了算，这里只做运输）；</li>
     *   <li><b>值与页面同源</b>：{@link CustomerProfileTruthMask#apply}（读面遮蔽的唯一实现）
     *       + 与客户列表同一套标签解析 ⇒ 同一实体走哪条读路径都是同一个形态；</li>
     *   <li><b>有界 + 截断显式</b>：多取一行只用于判定截断（与简报表快照同口径，行数上限复用
     *       {@code DailyBriefingService.SNAPSHOT_ROW_LIMIT}）；</li>
     *   <li><b>租户隔离</b>：显式带 tenantId（叠加 TenantLineInnerInterceptor 的 tenant_id 注入）。</li>
     * </ul>
     *
     * <p>🔴 <b>为什么这条腿不并进简报表快照</b>（{@code DailyBriefingService.aggregateSnapshot}）：
     * 那边的权限码是 {@code dashboard:view}，而客户档案含联系方式等 PII ⇒ 并进去等于让「看板」权限
     * 读到客户 PII。本腿与客户列表/详情同码（{@code customer:view}）—— Agent 能力 ≡ 页面权限
     * （issue #5246）。判据见
     * {@code backend/ai-agent-service/tests/test_briefing_customer_profile.py} 的
     * `TestFieldLedgerIsNotOwnedByTheView::test_dashboard_snapshot_stays_free_of_customer_rows`。</p>
     *
     * @param tenantId 租户（隔离关口；每条查询显式带它）
     * @param limit    行数上限（&lt;1 收敛到 1、超过内核上限收敛到内核上限）
     */
    public Map<String, Object> profileViewSnapshot(Long tenantId, int limit) {
        FieldTruth.Declaration declaration = FieldTruthRegistry.customerProfile();
        int bound = Math.max(1, Math.min(limit, DailyBriefingService.SNAPSHOT_ROW_LIMIT));

        List<CustomerProfile> profiles = customerProfileMapper.selectList(
                new LambdaQueryWrapper<CustomerProfile>()
                        .eq(CustomerProfile::getTenantId, tenantId)
                        .orderByDesc(CustomerProfile::getCreatedAt)
                        .orderByDesc(CustomerProfile::getId)
                        // 多取一行只为判定截断（多出来的那行不进快照）——与简报表快照同一口径
                        .last("LIMIT " + (bound + 1)));
        boolean truncated = profiles.size() > bound;
        if (truncated) {
            profiles = profiles.subList(0, bound);
        }

        Map<Long, List<CustomerTag>> tenantTagCache = new HashMap<>();
        List<Map<String, Object>> rows = new ArrayList<>(profiles.size());
        for (CustomerProfile profile : profiles) {
            profile.setTags(resolveCustomerTags(profile, tenantTagCache));
            // 🔴 值的单点来源：无真值的字段在读面一律 null（未知），不得让 DB 默认值流出去
            CustomerProfileTruthMask.apply(profile);
            rows.add(profileRow(profile, declaration));
        }

        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("limit", bound);
        meta.put("count", rows.size());
        meta.put("truncated", truncated);

        String array = declaration.table();
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("row_fields", Map.of(array, declaration.declaredFields()));
        snapshot.put("row_meta", Map.of(array, meta));
        // 🔴 真值声明的**运输**（issue #5456 判据 4 的机械形态）：由声明现取，这里不写任何字段名
        snapshot.put("field_truth", Map.of(array, declaration.payload()));
        snapshot.put(array, rows);
        return snapshot;
    }

    /**
     * 一行客户档案：**按声明的字段名逐字段取值**（`{@code 字段名 → 值}`）。
     *
     * <p>🔴 为什么不用 Jackson 的 Bean 名：{@code getRScore()} 这类「前两个字母都大写」的 getter 会被
     * Jackson 的默认命名策略折叠成全小写（{@code rscore}），而 #5362 的声明用的是**实体字段名**
     * （{@code rScore}）⇒ 键集对不上时，视图侧会把这些字段永远读成「整行缺键」（落 `incomplete`）。
     * 实测形态见 {@code CustomerProfileViewSnapshotTest} 的「行键集 ≡ 声明字段集」这条判据
     * （它在改成本实现前**真的红过**：实得 {@code fscore / mscore / rscore}）。</p>
     *
     * <p>按声明遍历 + 反射读字段 ⇒ 键集**由构造保证**等于声明的字段集（不手写映射表、不另造 DTO）。
     * issue #5459 已把**实体侧**的线上键名统一到声明名（那三个缩写字段在 getter 上显式标注，
     * 判据 {@code CustomerProfileWireKeyParityTest}），但本条腿**不依赖**那些注解 ——
     * 实体的命名配置日后被改坏时，行键集仍由本构造保证，不会跟着漂移。</p>
     */
    private static Map<String, Object> profileRow(CustomerProfile profile,
                                                  FieldTruth.Declaration declaration) {
        Map<String, Object> row = new LinkedHashMap<>();
        for (String field : declaration.declaredFields()) {
            try {
                Field declared = declaration.entity().getDeclaredField(field);
                declared.setAccessible(true);
                row.put(field, declared.get(profile));
            } catch (NoSuchFieldException | IllegalAccessException e) {
                // 声明与实体漂移 ⇒ 显式失败（不静默少一个键：那会让视图把该字段读成「缺键」）
                throw new IllegalStateException("实体字段读不出（声明与实体漂移）：" + field, e);
            }
        }
        return row;
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 客户授信与往来（issue #7370，P0-2 段 1）
    // 口径：NULL = 未启用授信（存量客户零回归）；0 = 启用但零额度；正数 = 额度（闭区间）。
    // 判定谓词在 CreditPolicy（纯函数，逐格有判据）；本类只做「取数 + 调它 + 落库」。
    // ══════════════════════════════════════════════════════════════════════════════

    /**
     * 该客户的已欠合计（未结清订单金额）。
     *
     * <p>口径 = `paid_at IS NULL` 且未取消的订单金额之和；逐笔核销（P0-2 段 3）上线后换成
     * 「Σ订单 - Σ核销收款 + Σ退款」，本方法签名不变。
     */
    public BigDecimal creditOutstanding(Long tenantId, String phone) {
        if (!StringUtils.hasText(phone)) {
            return BigDecimal.ZERO;
        }
        BigDecimal value = orderMapper.selectOutstandingTotal(tenantId, phone);
        return value == null ? BigDecimal.ZERO : value;
    }

    /** 授信读数：未启用授信 ⇒ creditLimit/available 为 null（与「额度 0」可区分）。 */
    public com.migao.admin.dto.CreditStatusResponse creditStatus(String customerId) {
        CustomerProfile profile = customerProfileMapper.selectById(customerId);
        if (profile == null) {
            throw BusinessException.notFound("客户");
        }
        BigDecimal limit = profile.getCreditLimit();
        BigDecimal outstanding = creditOutstanding(profile.getTenantId(), profile.getPhone());
        BigDecimal available = limit == null
                ? null
                : CreditPolicy.evaluate(limit, outstanding, BigDecimal.ZERO).available();
        return com.migao.admin.dto.CreditStatusResponse.builder()
                .customerId(customerId)
                .creditLimit(limit)
                .paymentTermsDays(profile.getPaymentTermsDays())
                .outstanding(outstanding)
                .available(available)
                .build();
    }

    /**
     * 下单闸门：超出授信额度 ⇒ 拒绝（提示含额度 / 已欠 / 本单 / 尚缺）。
     * 未建档客户或未启用授信 ⇒ 放行（与存量行为逐字一致）。
     */
    public void assertWithinCredit(Long tenantId, String phone, BigDecimal amount) {
        if (!StringUtils.hasText(phone)) {
            return;
        }
        // issue #7257 纪律：客户档案**读侧不用 selectOne**（历史重复行会抛 TooManyResults ⇒ 500）
        // ⇒ 走单一读实现点 findFirstByPhone（与建档写面的判重同一口径）。
        CustomerProfile profile = customerProfileMapper.findFirstByPhone(tenantId, phone);
        if (profile == null || profile.getCreditLimit() == null) {
            return;
        }
        BigDecimal outstanding = creditOutstanding(tenantId, phone);
        CreditPolicy.Decision decision = CreditPolicy.evaluate(profile.getCreditLimit(), outstanding, amount);
        if (!decision.allowed()) {
            log.info("[credit] 超授信被拒 | tenant={} customer={} limit={} outstanding={} amount={} excess={}",
                    tenantId, profile.getId(), profile.getCreditLimit(), outstanding, amount, decision.excess());
            throw BusinessException.validationError(String.format(
                    "超出客户授信额度：本单 ¥%s + 已欠 ¥%s > 额度 ¥%s，尚缺 ¥%s。"
                            + "请先收款/冲账，或由管理员在客户详情调整授信额度。",
                    amount.toPlainString(), outstanding.toPlainString(),
                    profile.getCreditLimit().toPlainString(), decision.excess().toPlainString()));
        }
    }

    /** 设置/清空授信（显式 null = 停用授信）。 */
    public com.migao.admin.dto.CreditStatusResponse updateCreditSettings(
            String customerId, com.migao.admin.dto.CreditSettingsRequest request) {
        CustomerProfile profile = customerProfileMapper.selectById(customerId);
        if (profile == null) {
            throw BusinessException.notFound("客户");
        }
        BigDecimal limit = request.getCreditLimit();
        Integer terms = request.getPaymentTermsDays();
        if (limit != null && limit.signum() < 0) {
            throw BusinessException.validationError("授信额度不得为负：" + limit.toPlainString());
        }
        if (terms != null && (terms < 0 || terms > 365)) {
            throw BusinessException.validationError("账期天数须在 0~365 之间：" + terms);
        }
        profile.setCreditLimit(limit);
        profile.setPaymentTermsDays(terms);
        customerProfileMapper.updateById(profile);
        log.info("[credit] 授信设置 | tenant={} customer={} limit={} terms={}",
                profile.getTenantId(), customerId, limit, terms);
        return creditStatus(customerId);
    }

    // ══════════════════════════════════════════════════════════════════════════════
    // 应收账龄（issue #7370，P0-2 段 2）
    // 分档规则钉在纯函数 ReceivableAging（逐格判据）；本方法只做「取数 → 分档 → 汇总」。
    // ══════════════════════════════════════════════════════════════════════════════

    /**
     * 应收账龄：全局合计 + 按客户分行，各五档（未到期 / 1-30 / 31-60 / 61-90 / 90+）。
     *
     * <p>到期日 = 下单日的**业务日期** + 该客户账期天数（{@code null}/0 ⇒ 现结，到期日 = 下单日）。
     * 「业务日期」由 {@link BusinessClock} 给出（容器是 UTC，直接取 {@code LocalDate.ofInstant(UTC)} 会差一天）。</p>
     *
     * <p>恒等式（判据复算）：{@code totalOutstanding == Σ五档 == Σ客户行}。</p>
     */
    public com.migao.admin.dto.ReceivableAgingResponse receivableAging(Long tenantId) {
        LocalDate today = businessClock.today();
        List<com.migao.admin.dto.ReceivableAgingRow> rows = orderMapper.selectReceivableRows(tenantId);
        // 业务日期换算**只在这里**做（容器是 UTC：取 UTC 日期会让「当天」差一天，见 #3802/#6200）——
        // 换算用 BusinessClock.zone()，下游纯函数只做日期运算（不引时区 ⇒ 逐格可测）。
        for (com.migao.admin.dto.ReceivableAgingRow row : rows) {
            if (row.getCreatedAt() != null) {
                row.setBusinessDate(LocalDate.ofInstant(row.getCreatedAt().toInstant(), businessClock.zone()));
            }
        }
        return ReceivableAging.summarize(rows, termsByPhone(tenantId, rows), today);
    }

    /** 该租户下「电话 → 账期天数」；读侧不用 selectOne（#7257：历史重复行会抛 TooManyResults）。 */
    private Map<String, Integer> termsByPhone(Long tenantId, List<com.migao.admin.dto.ReceivableAgingRow> rows) {
        Set<String> phones = new LinkedHashSet<>();
        for (com.migao.admin.dto.ReceivableAgingRow row : rows) {
            if (StringUtils.hasText(row.getCustomerPhone())) {
                phones.add(row.getCustomerPhone());
            }
        }
        if (phones.isEmpty()) {
            // 空集**不返回不可变表**（issue #6219：调用方一旦用空键索引就 NPE 500）⇒ 返回可变表
            return new HashMap<>();
        }
        List<CustomerProfile> profiles = customerProfileMapper.selectList(
                new LambdaQueryWrapper<CustomerProfile>()
                        .eq(CustomerProfile::getTenantId, tenantId)
                        .in(CustomerProfile::getPhone, phones));
        Map<String, Integer> terms = new HashMap<>();
        for (CustomerProfile profile : profiles) {
            if (profile.getPhone() != null && !terms.containsKey(profile.getPhone())) {
                terms.put(profile.getPhone(), profile.getPaymentTermsDays());
            }
        }
        return terms;
    }



    /**
     * 指派 / 撤回客户负责人（issue #7372 段 2）—— 这一列**唯一**的写入点。
     *
     * <p>为什么必须有这个入口：没有写入点，`owner_user_id` 永远只有 `NULL`（未指派），
     * 数据范围 `self` 就只能靠「出过单」兜底 ⇒ 「把客户分给某人」这件事在系统里**不存在**。
     * 有了它，兜底才只是兜底，而不是唯一规则。</p>
     *
     * @param ownerUserId 新负责人 id；**null / 空白 = 撤回指派**（回到「未指派」，重新走兜底）
     */
    public void assignOwner(String customerId, String ownerUserId) {
        CustomerProfile profile = customerProfileMapper.selectById(customerId);
        if (profile == null) {
            throw BusinessException.notFound("客户");
        }
        String normalized = org.springframework.util.StringUtils.hasText(ownerUserId)
                ? ownerUserId.trim() : null;
        // 走实体 setter + updateById（本仓既有写法）：字段真值判据按 setter 识别写入点，
        // 用 Lambda 的 `.set(...)` 会被判成「零写入点」而红（那是判据的射程，改判据不如按既有写法写）
        profile.setOwnerUserId(normalized);
        customerProfileMapper.updateById(profile);
    }

    /**
     * 客户是否属于该用户的**本人范围**（issue #7372 段 2）：与列表 SQL **同一口径**，
     * 不另写第二份规则。
     *
     * <ul>
     *   <li>负责人是本人 ⇒ 可见；</li>
     *   <li>未指派（`owner_user_id IS NULL`）且本人有该客户（按 phone）的单 ⇒ 可见（存量兜底）；</li>
     *   <li>已指派给别人 ⇒ 不可见（哪怕本人出过单 —— 指派是明确的业务决定，不能被兜底覆盖）。</li>
     * </ul>
     */
    private boolean ownedByMe(CustomerProfile profile, String userId) {
        if (userId.equals(profile.getOwnerUserId())) {
            return true;
        }
        if (profile.getOwnerUserId() != null) {
            return false;
        }
        if (!org.springframework.util.StringUtils.hasText(profile.getPhone())) {
            return false;
        }
        Long count = orderMapper.selectCount(new LambdaQueryWrapper<com.migao.admin.entity.Order>()
                .eq(com.migao.admin.entity.Order::getTenantId, profile.getTenantId())
                .eq(com.migao.admin.entity.Order::getCreatedBy, userId)
                .eq(com.migao.admin.entity.Order::getCustomerPhone, profile.getPhone()));
        return count != null && count > 0;
    }
}
