package com.aikf.admin.service;

import com.aikf.admin.dto.PageResponse;
import com.aikf.admin.entity.*;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.mapper.*;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
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
    private final CustomerTagMapper customerTagMapper;
    private final CustomerSegmentMapper customerSegmentMapper;
    private final CustomerSegmentMemberMapper customerSegmentMemberMapper;
    private final OrderMapper orderMapper;
    private final SessionMapper sessionMapper;

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
        LambdaQueryWrapper<CustomerProfile> wrapper = new LambdaQueryWrapper<>();

        // 来源渠道筛选
        if (StringUtils.hasText(sourceChannel)) {
            wrapper.eq(CustomerProfile::getSourceChannel, sourceChannel);
        }

        // VIP等级筛选
        if (StringUtils.hasText(vipLevel)) {
            wrapper.eq(CustomerProfile::getVipLevel, vipLevel);
        }

        // 关键词搜索
        if (StringUtils.hasText(keyword)) {
            wrapper.and(w -> w.like(CustomerProfile::getWechatNickname, keyword)
                    .or()
                    .like(CustomerProfile::getPhone, keyword));
        }

        wrapper.orderByDesc(CustomerProfile::getCreatedAt);

        Page<CustomerProfile> customerPage = new Page<>(page, size);
        Page<CustomerProfile> resultPage = customerProfileMapper.selectPage(customerPage, wrapper);

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
        CustomerProfile profile = customerProfileMapper.selectById(customerId);
        if (profile == null) {
            throw BusinessException.notFound("客户");
        }

        Map<String, Object> detail = new HashMap<>();
        detail.put("profile", profile);

        // 查询客户标签
        List<CustomerTag> tags = getCustomerTags(profile.getTenantId());
        detail.put("tags", tags);

        // 查询订单历史（最近10条）
        LambdaQueryWrapper<Order> orderWrapper = new LambdaQueryWrapper<>();
        orderWrapper.eq(Order::getCustomerPhone, profile.getPhone())
                .orderByDesc(Order::getCreatedAt)
                .last("LIMIT 10");
        List<Order> orders = orderMapper.selectList(orderWrapper);
        detail.put("orders", orders);

        // 查询会话历史（最近10条）
        LambdaQueryWrapper<Session> sessionWrapper = new LambdaQueryWrapper<>();
        sessionWrapper.eq(Session::getCustomerId, customerId)
                .orderByDesc(Session::getCreatedAt)
                .last("LIMIT 10");
        List<Session> sessions = sessionMapper.selectList(sessionWrapper);
        detail.put("sessions", sessions);

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
        // 检查手机号唯一性（如果有手机号）
        if (StringUtils.hasText(profile.getPhone())) {
            LambdaQueryWrapper<CustomerProfile> wrapper = new LambdaQueryWrapper<>();
            wrapper.eq(CustomerProfile::getPhone, profile.getPhone())
                    .eq(CustomerProfile::getTenantId, profile.getTenantId());
            CustomerProfile existing = customerProfileMapper.selectOne(wrapper);
            if (existing != null) {
                throw BusinessException.validationError("该手机号已存在客户档案");
            }
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

        customerProfileMapper.insert(profile);
        log.info("创建客户档案成功: id={}, phone={}", profile.getId(), profile.getPhone());
        return profile;
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
        // 先检查是否已存在
        if (StringUtils.hasText(wechatOpenid)) {
            LambdaQueryWrapper<CustomerProfile> wrapper = new LambdaQueryWrapper<>();
            wrapper.eq(CustomerProfile::getWechatOpenid, wechatOpenid)
                    .eq(CustomerProfile::getTenantId, tenantId);
            CustomerProfile existing = customerProfileMapper.selectOne(wrapper);
            if (existing != null) {
                // 更新最后活跃时间
                existing.setLastActiveAt(OffsetDateTime.now());
                customerProfileMapper.updateById(existing);
                return existing;
            }
        }

        CustomerProfile profile = CustomerProfile.builder()
                .tenantId(tenantId)
                .wechatOpenid(wechatOpenid)
                .wechatNickname(wechatNickname)
                .sourceChannel(sourceChannel != null ? sourceChannel : "wechat_mini")
                .vipLevel("normal")
                .customerStatus("active")
                .lifecycleStage("new")
                .totalOrders(0)
                .totalConsumption(BigDecimal.ZERO)
                .registeredAt(OffsetDateTime.now())
                .lastActiveAt(OffsetDateTime.now())
                .build();

        customerProfileMapper.insert(profile);
        log.info("从会话自动创建客户档案: id={}, wechatOpenid={}", profile.getId(), wechatOpenid);
        return profile;
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

        customerProfileMapper.updateById(existing);
        log.info("更新客户档案成功: id={}", customerId);
        return existing;
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
        customerTagMapper.deleteById(tagId);
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

        return PageResponse.of(resultPage.getTotal(), resultPage.getCurrent(),
                resultPage.getSize(), resultPage.getRecords());
    }
}
