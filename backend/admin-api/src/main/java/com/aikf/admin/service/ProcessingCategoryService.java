package com.aikf.admin.service;

import com.aikf.admin.dto.ProcessingCategoryCreateRequest;
import com.aikf.admin.dto.ProcessingCategoryResponse;
import com.aikf.admin.dto.ProcessingCategoryUpdateRequest;
import com.aikf.admin.entity.ProcessingCategory;
import com.aikf.admin.entity.ProcessingItem;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.mapper.ProcessingCategoryMapper;
import com.aikf.admin.mapper.ProcessingItemMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 加工分类服务类
 * 处理加工分类的增删改查
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProcessingCategoryService extends ServiceImpl<ProcessingCategoryMapper, ProcessingCategory> {

    private final ProcessingCategoryMapper processingCategoryMapper;
    private final ProcessingItemMapper processingItemMapper;

    /**
     * 获取加工分类列表
     *
     * @return 分类列表
     */
    public List<ProcessingCategoryResponse> getProcessingCategories(Long tenantId) {
        LambdaQueryWrapper<ProcessingCategory> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(ProcessingCategory::getTenantId, tenantId)
                .orderByAsc(ProcessingCategory::getSortOrder);
        List<ProcessingCategory> categories = processingCategoryMapper.selectList(wrapper);

        // 批量查询每个分类下的加工项数量
        Map<String, Long> itemCountMap = getItemCountMap(categories);

        return categories.stream()
                .map(c -> convertToResponse(c, itemCountMap.getOrDefault(c.getId(), 0L)))
                .collect(Collectors.toList());
    }

    /**
     * 根据ID查询加工分类
     *
     * @param id 分类ID
     * @return 分类响应
     */
    public ProcessingCategoryResponse getProcessingCategoryById(String id, Long tenantId) {
        ProcessingCategory category = processingCategoryMapper.selectById(id);
        if (category == null) {
            throw BusinessException.notFound("加工分类");
        }
        // 查询关联加工项数量
        LambdaQueryWrapper<ProcessingItem> countWrapper = new LambdaQueryWrapper<>();
        countWrapper.eq(ProcessingItem::getCategoryId, id);
        Long itemCount = processingItemMapper.selectCount(countWrapper);
        return convertToResponse(category, itemCount);
    }

    /**
     * 创建加工分类
     *
     * @param request 创建请求
     * @return 分类响应
     */
    @Transactional(rollbackFor = Exception.class)
    public ProcessingCategoryResponse createProcessingCategory(ProcessingCategoryCreateRequest request, Long tenantId) {
        // 创建分类实体
        ProcessingCategory category = new ProcessingCategory();
        BeanUtils.copyProperties(request, category);
        category.setTenantId(tenantId);

        // 保存分类
        processingCategoryMapper.insert(category);

        log.info("创建加工分类成功: id={}, name={}", category.getId(), category.getName());

        return convertToResponse(category, 0L);
    }

    /**
     * 更新加工分类
     *
     * @param id      分类ID
     * @param request 更新请求
     * @return 分类响应
     */
    @Transactional(rollbackFor = Exception.class)
    public ProcessingCategoryResponse updateProcessingCategory(String id, ProcessingCategoryUpdateRequest request, Long tenantId) {
        // 查询分类是否存在
        ProcessingCategory category = processingCategoryMapper.selectById(id);
        if (category == null) {
            throw BusinessException.notFound("加工分类");
        }

        // 更新分类属性
        BeanUtils.copyProperties(request, category);
        category.setId(id);

        // 更新分类
        processingCategoryMapper.updateById(category);

        log.info("更新加工分类成功: id={}, name={}", id, category.getName());

        return convertToResponse(category, 0L);
    }

    /**
     * 删除加工分类
     *
     * @param id 分类ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteProcessingCategory(String id, Long tenantId) {
        ProcessingCategory category = processingCategoryMapper.selectById(id);
        if (category == null) {
            throw BusinessException.notFound("加工分类");
        }

        // 检查是否有关联加工项
        LambdaQueryWrapper<ProcessingItem> itemWrapper = new LambdaQueryWrapper<>();
        itemWrapper.eq(ProcessingItem::getCategoryId, id);
        Long itemCount = processingItemMapper.selectCount(itemWrapper);
        if (itemCount > 0) {
            throw BusinessException.validationError("该分类下有关联加工项，无法删除");
        }

        processingCategoryMapper.deleteById(id);
        log.info("删除加工分类成功: id={}", id);
    }

    /**
     * 转换为响应 DTO
     *
     * @param category 分类实体
     * @return 分类响应
     */
    private ProcessingCategoryResponse convertToResponse(ProcessingCategory category, Long itemCount) {
        ProcessingCategoryResponse response = new ProcessingCategoryResponse();
        BeanUtils.copyProperties(category, response);
        response.setItemCount(itemCount);
        return response;
    }

    /**
     * 批量获取分类下的加工项数量
     */
    private Map<String, Long> getItemCountMap(List<ProcessingCategory> categories) {
        List<String> categoryIds = categories.stream()
                .map(ProcessingCategory::getId)
                .collect(Collectors.toList());
        if (categoryIds.isEmpty()) {
            return Map.of();
        }
        LambdaQueryWrapper<ProcessingItem> wrapper = new LambdaQueryWrapper<>();
        wrapper.in(ProcessingItem::getCategoryId, categoryIds);
        List<ProcessingItem> items = processingItemMapper.selectList(wrapper);
        return items.stream()
                .collect(Collectors.groupingBy(ProcessingItem::getCategoryId, Collectors.counting()));
    }
}
