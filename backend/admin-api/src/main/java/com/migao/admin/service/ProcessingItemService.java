package com.migao.admin.service;

import com.migao.admin.dto.*;
import com.migao.admin.entity.ProcessingCategory;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProcessingCategoryMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 加工项服务类
 * 处理加工项的增删改查和价格计算
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessingItemService extends ServiceImpl<ProcessingItemMapper, ProcessingItem> {

    private final ProcessingItemMapper processingItemMapper;
    private final ProcessingCategoryMapper processingCategoryMapper;

    /**
     * 分页查询加工项列表
     *
     * @param query 查询参数
     * @return 分页响应
     */
    public PageResponse<ProcessingItemResponse> getProcessingItems(ProcessingItemQueryRequest query, Long tenantId) {
        // 构建查询条件
        LambdaQueryWrapper<ProcessingItem> wrapper = new LambdaQueryWrapper<>();
        
        // 关键词搜索
        if (StringUtils.hasText(query.getKeyword())) {
            wrapper.like(ProcessingItem::getName, query.getKeyword());
        }
        
        // 分类筛选
        if (StringUtils.hasText(query.getCategoryId())) {
            wrapper.eq(ProcessingItem::getCategoryId, query.getCategoryId());
        }
        
        // 状态筛选
        if (StringUtils.hasText(query.getStatus())) {
            wrapper.eq(ProcessingItem::getStatus, query.getStatus());
        }
        
        // 按创建时间倒序
        wrapper.orderByDesc(ProcessingItem::getCreatedAt);
        
        // 执行分页查询
        Page<ProcessingItem> page = new Page<>(query.getPage(), query.getSize());
        Page<ProcessingItem> itemPage = processingItemMapper.selectPage(page, wrapper);
        
        // 获取分类名称映射
        Map<String, String> categoryNameMap = getCategoryNameMap(itemPage.getRecords());
        
        // 转换为响应 DTO
        List<ProcessingItemResponse> responses = itemPage.getRecords().stream()
                .map(item -> convertToResponse(item, categoryNameMap.get(item.getCategoryId())))
                .collect(Collectors.toList());
        
        return PageResponse.of(itemPage.getTotal(), itemPage.getCurrent(), itemPage.getSize(), responses);
    }

    /**
     * 根据ID查询加工项详情
     *
     * @param id 加工项ID
     * @return 加工项响应
     */
    public ProcessingItemResponse getProcessingItemById(String id, Long tenantId) {
        ProcessingItem item = processingItemMapper.selectById(id);
        if (item == null) {
            throw BusinessException.notFound("加工项");
        }
        
        // 获取分类名称
        String categoryName = null;
        if (StringUtils.hasText(item.getCategoryId())) {
            ProcessingCategory category = processingCategoryMapper.selectById(item.getCategoryId());
            if (category != null) {
                categoryName = category.getName();
            }
        }
        
        return convertToResponse(item, categoryName);
    }

    /**
     * 创建加工项
     *
     * @param request 创建请求
     * @return 加工项响应
     */
    @Transactional(rollbackFor = Exception.class)
    public ProcessingItemResponse createProcessingItem(ProcessingItemCreateRequest request, Long tenantId) {
        // 校验分类是否存在
        validateCategory(request.getCategoryId());
        
        // 校验计价方式
        validatePricingMethod(request.getPricingMethod());
        
        // 创建加工项实体
        ProcessingItem item = new ProcessingItem();
        BeanUtils.copyProperties(request, item);
        item.setTenantId(tenantId);
        
        // 处理选项（转换为 JSON）
        if (request.getOptions() != null && !request.getOptions().isEmpty()) {
            item.setOptions(request.getOptions());
        }
        
        // 保存加工项
        processingItemMapper.insert(item);
        
        log.info("创建加工项成功: id={}, name={}", item.getId(), item.getName());
        
        return getProcessingItemById(item.getId(), tenantId);
    }

    /**
     * 更新加工项
     *
     * @param id      加工项ID
     * @param request 更新请求
     * @return 加工项响应
     */
    @Transactional(rollbackFor = Exception.class)
    public ProcessingItemResponse updateProcessingItem(String id, ProcessingItemUpdateRequest request, Long tenantId) {
        // 查询加工项是否存在
        ProcessingItem item = processingItemMapper.selectById(id);
        if (item == null) {
            throw BusinessException.notFound("加工项");
        }
        
        // 校验分类是否存在
        validateCategory(request.getCategoryId());
        
        // 校验计价方式
        validatePricingMethod(request.getPricingMethod());
        
        // 更新加工项属性
        BeanUtils.copyProperties(request, item);
        item.setId(id);
        
        // 处理选项（转换为 JSON）
        if (request.getOptions() != null) {
            item.setOptions(request.getOptions());
        }
        
        // 更新加工项
        processingItemMapper.updateById(item);
        
        log.info("更新加工项成功: id={}, name={}", id, item.getName());
        
        return getProcessingItemById(id, tenantId);
    }

    /**
     * 删除加工项
     *
     * @param id 加工项ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteProcessingItem(String id, Long tenantId) {
        ProcessingItem item = processingItemMapper.selectById(id);
        if (item == null) {
            throw BusinessException.notFound("加工项");
        }
        
        processingItemMapper.deleteById(id);
        log.info("删除加工项成功: id={}", id);
    }

    /**
     * 计算价格
     *
     * @param request 价格计算请求
     * @return 价格计算结果
     */
    public PriceCalculateResponse calculatePrice(PriceCalculateRequest request, Long tenantId) {
        // 查询加工项
        ProcessingItem item = processingItemMapper.selectById(request.getProcessingItemId());
        if (item == null) {
            throw BusinessException.notFound("加工项");
        }
        
        // 校验数量范围
        BigDecimal quantity = request.getQuantity();
        if (item.getMinQuantity() != null && quantity.compareTo(BigDecimal.valueOf(item.getMinQuantity())) < 0) {
            throw BusinessException.validationError("数量不能小于最小数量 " + item.getMinQuantity());
        }
        if (item.getMaxQuantity() != null && quantity.compareTo(BigDecimal.valueOf(item.getMaxQuantity())) > 0) {
            throw BusinessException.validationError("数量不能大于最大数量 " + item.getMaxQuantity());
        }
        
        // 根据计价方式计算价格
        BigDecimal totalPrice;
        List<PriceCalculateResponse.PriceDetail> details = new ArrayList<>();
        
        switch (item.getPricingMethod()) {
            case "per_meter":
                // 按米计价：单价 × 数量（米数）
                totalPrice = item.getUnitPrice().multiply(quantity);
                details.add(createPriceDetail("基础加工费", item.getUnitPrice(), quantity, totalPrice, "按米计价"));
                break;
                
            case "per_piece":
                // 按件计价：单价 × 件数
                totalPrice = item.getUnitPrice().multiply(quantity);
                details.add(createPriceDetail("基础加工费", item.getUnitPrice(), quantity, totalPrice, "按件计价"));
                break;
                
            case "fixed":
                // 固定价
                totalPrice = item.getUnitPrice();
                details.add(createPriceDetail("固定加工费", item.getUnitPrice(), BigDecimal.ONE, totalPrice, "固定价格"));
                break;
                
            case "per_area":
                // 按面积计价：单价 × 面积（宽 × 高）
                BigDecimal area = calculateArea(request.getDimensions());
                totalPrice = item.getUnitPrice().multiply(area).multiply(quantity);
                details.add(createPriceDetail("基础加工费", item.getUnitPrice(), area.multiply(quantity), totalPrice, 
                        "按面积计价，面积=" + area + "平方米"));
                break;
                
            default:
                // 默认按件计价
                totalPrice = item.getUnitPrice().multiply(quantity);
                details.add(createPriceDetail("基础加工费", item.getUnitPrice(), quantity, totalPrice, "默认计价"));
        }
        
        // 构建响应
        PriceCalculateResponse response = new PriceCalculateResponse();
        response.setProcessingItemId(item.getId());
        response.setProcessingItemName(item.getName());
        response.setPricingMethod(item.getPricingMethod());
        response.setUnitPrice(item.getUnitPrice());
        response.setQuantity(quantity);
        response.setTotalPrice(totalPrice.setScale(2, RoundingMode.HALF_UP));
        response.setProcessingDays(item.getProcessingDays());
        response.setDetails(details);
        
        return response;
    }

    /**
     * 校验分类是否存在
     *
     * @param categoryId 分类ID
     */
    private void validateCategory(String categoryId) {
        if (!StringUtils.hasText(categoryId)) {
            return;
        }
        
        ProcessingCategory category = processingCategoryMapper.selectById(categoryId);
        if (category == null) {
            throw BusinessException.validationError("加工分类不存在");
        }
    }

    /**
     * 校验计价方式
     *
     * @param pricingMethod 计价方式
     */
    private void validatePricingMethod(String pricingMethod) {
        List<String> validMethods = List.of("per_meter", "per_piece", "fixed", "per_area");
        if (!validMethods.contains(pricingMethod)) {
            throw BusinessException.validationError("无效的计价方式，可选值：per_meter（按米计价）、per_piece（按件计价）、fixed（固定价格）、per_area（按面积计价）");
        }
    }

    /**
     * 计算面积
     *
     * @param dimensions 尺寸（宽 x 高）
     * @return 面积
     */
    private BigDecimal calculateArea(Map<String, BigDecimal> dimensions) {
        if (dimensions == null || !dimensions.containsKey("width") || !dimensions.containsKey("height")) {
            throw BusinessException.validationError("按面积计价需要提供 width 和 height 尺寸");
        }
        
        BigDecimal width = dimensions.get("width");
        BigDecimal height = dimensions.get("height");
        
        if (width == null || height == null || width.compareTo(BigDecimal.ZERO) <= 0 || height.compareTo(BigDecimal.ZERO) <= 0) {
            throw BusinessException.validationError("尺寸必须大于 0");
        }
        
        // 面积 = 宽 × 高（单位：平方米，假设输入是米）
        return width.multiply(height);
    }

    /**
     * 创建价格明细项
     */
    private PriceCalculateResponse.PriceDetail createPriceDetail(
            String name, BigDecimal unitPrice, BigDecimal quantity, BigDecimal subtotal, String description) {
        PriceCalculateResponse.PriceDetail detail = new PriceCalculateResponse.PriceDetail();
        detail.setName(name);
        detail.setUnitPrice(unitPrice);
        detail.setQuantity(quantity);
        detail.setSubtotal(subtotal.setScale(2, RoundingMode.HALF_UP));
        detail.setDescription(description);
        return detail;
    }

    /**
     * 获取分类名称映射
     *
     * @param items 加工项列表
     * @return 分类ID -> 分类名称 映射
     */
    private Map<String, String> getCategoryNameMap(List<ProcessingItem> items) {
        List<String> categoryIds = items.stream()
                .map(ProcessingItem::getCategoryId)
                .filter(StringUtils::hasText)
                .distinct()
                .collect(Collectors.toList());
        
        if (categoryIds.isEmpty()) {
            return Map.of();
        }
        
        LambdaQueryWrapper<ProcessingCategory> wrapper = new LambdaQueryWrapper<>();
        wrapper.in(ProcessingCategory::getId, categoryIds);
        List<ProcessingCategory> categories = processingCategoryMapper.selectList(wrapper);
        
        return categories.stream()
                .collect(Collectors.toMap(ProcessingCategory::getId, ProcessingCategory::getName));
    }

    /**
     * 转换为响应 DTO
     *
     * @param item         加工项实体
     * @param categoryName 分类名称
     * @return 加工项响应
     */
    @SuppressWarnings("unchecked")
    private ProcessingItemResponse convertToResponse(ProcessingItem item, String categoryName) {
        ProcessingItemResponse response = new ProcessingItemResponse();
        BeanUtils.copyProperties(item, response);
        response.setCategoryName(categoryName);
        
        // 处理选项
        if (item.getOptions() instanceof List) {
            response.setOptions((List<Map<String, Object>>) item.getOptions());
        }
        
        return response;
    }
}
