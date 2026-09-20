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

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 加工项服务类
 * 处理加工项的增删改查（issue #4882：计价方式与价格计算随加工项目录单价一并退场）
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
