package com.migao.admin.service;

import com.migao.admin.dto.CategoryCreateRequest;
import com.migao.admin.dto.CategoryResponse;
import com.migao.admin.dto.CategoryUpdateRequest;
import com.migao.admin.entity.Category;
import com.migao.admin.entity.Product;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProductMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;

/**
 * 商品分类服务类
 *
 * issue #2905 — 分类排序重构：
 * - 分类为扁平结构（无父子概念），列表按 sortOrder 升序 + id 兜底展示
 * - 上下移动通过 moveCategory 交换相邻位置（重排 sortOrder）
 * - 创建/更新忽略 parentId；新分类未指定排序时追加到末尾
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CategoryService extends ServiceImpl<CategoryMapper, Category> {

    private final CategoryMapper categoryMapper;
    private final ProductMapper productMapper;

    /**
     * 获取分类列表（扁平结构，按 sortOrder 升序 + id 兜底）
     *
     * @return 分类列表
     */
    public List<CategoryResponse> getCategoryTree(Long tenantId) {
        // 查询所有分类：按排序号升序 + id 兜底，保证展示顺序稳定
        LambdaQueryWrapper<Category> wrapper = new LambdaQueryWrapper<>();
        wrapper.orderByAsc(Category::getSortOrder);
        wrapper.orderByAsc(Category::getId);
        List<Category> categories = categoryMapper.selectList(wrapper);

        return categories.stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());
    }

    /**
     * 创建分类
     * 忽略 parentId（父子概念移除）；未指定排序时追加到列表末尾
     *
     * @param request 创建请求
     * @return 分类响应
     */
    @Transactional(rollbackFor = Exception.class)
    public CategoryResponse createCategory(CategoryCreateRequest request, Long tenantId) {
        // 创建分类实体
        Category category = new Category();
        BeanUtils.copyProperties(request, category);
        category.setTenantId(tenantId);
        category.setParentId(null);
        category.setLevel(1);

        // 未指定排序 → 追加到末尾（max(sortOrder) + 1）
        if (category.getSortOrder() == null) {
            LambdaQueryWrapper<Category> lastWrapper = new LambdaQueryWrapper<>();
            lastWrapper.orderByDesc(Category::getSortOrder);
            lastWrapper.last("LIMIT 1");
            List<Category> lastCategories = categoryMapper.selectList(lastWrapper);
            int nextSort = (lastCategories == null || lastCategories.isEmpty()) ? 0 : (lastCategories.get(0).getSortOrder() + 1);
            category.setSortOrder(nextSort);
        }

        // 保存分类
        categoryMapper.insert(category);

        log.info("创建分类成功: id={}, name={}", category.getId(), category.getName());

        return convertToResponse(category);
    }

    /**
     * 更新分类（只更新名称等属性；忽略 parentId，不校验父分类）
     * 未随请求提供 sortOrder 时保留原排序值（防止 PUT 清空排序导致列表跳位）
     *
     * @param id      分类ID
     * @param request 更新请求
     * @return 分类响应
     */
    @Transactional(rollbackFor = Exception.class)
    public CategoryResponse updateCategory(String id, CategoryUpdateRequest request, Long tenantId) {
        // 查询分类是否存在
        Category category = categoryMapper.selectById(id);
        if (category == null) {
            throw BusinessException.notFound("分类");
        }

        Integer existingSort = category.getSortOrder();
        Integer existingLevel = category.getLevel();

        // 更新分类属性
        BeanUtils.copyProperties(request, category);
        category.setId(id);
        category.setParentId(null);
        // 未传排序/层级时保留原值（BeanUtils 会把 null 覆盖到实体）
        if (request.getSortOrder() == null) {
            category.setSortOrder(existingSort);
        }
        if (request.getLevel() == null) {
            category.setLevel(existingLevel);
        }

        // 更新分类
        categoryMapper.updateById(category);

        log.info("更新分类成功: id={}, name={}", id, category.getName());

        return convertToResponse(category);
    }

    /**
     * 删除分类
     * 不再因「存在子分类」拦截（父子概念移除）；保留关联商品校验
     *
     * @param id 分类ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteCategory(String id, Long tenantId) {
        Category category = categoryMapper.selectById(id);
        if (category == null) {
            throw BusinessException.notFound("分类");
        }

        // 检查是否有关联商品
        LambdaQueryWrapper<Product> productWrapper = new LambdaQueryWrapper<>();
        productWrapper.eq(Product::getCategoryId, id);
        Long productCount = productMapper.selectCount(productWrapper);
        if (productCount > 0) {
            throw BusinessException.validationError("该分类下有关联商品，无法删除");
        }

        categoryMapper.deleteById(id);
        log.info("删除分类成功: id={}", id);
    }

    /**
     * 上下移动分类（重排 sortOrder = 新顺序下标）
     * 已在首位/末位时幂等返回；direction 仅支持 up/down
     *
     * @param id        分类ID
     * @param direction up（上移）/ down（下移）
     * @param tenantId  租户ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void moveCategory(String id, String direction, Long tenantId) {
        if (!"up".equals(direction) && !"down".equals(direction)) {
            throw BusinessException.validationError("不支持的方向: " + direction + "，仅支持 up/down");
        }

        // 取有序列表（与列表页一致：sortOrder 升序 + id 兜底）；拷贝为可变 ArrayList 以便交换
        LambdaQueryWrapper<Category> wrapper = new LambdaQueryWrapper<>();
        wrapper.orderByAsc(Category::getSortOrder);
        wrapper.orderByAsc(Category::getId);
        List<Category> queried = categoryMapper.selectList(wrapper);
        if (queried == null || queried.isEmpty()) {
            return;
        }
        List<Category> ordered = new ArrayList<>(queried);

        // 定位目标分类
        int idx = -1;
        for (int i = 0; i < ordered.size(); i++) {
            if (ordered.get(i).getId().equals(id)) {
                idx = i;
                break;
            }
        }
        if (idx < 0) {
            throw BusinessException.notFound("分类");
        }

        // 计算目标位置：up → 与前一相邻位交换；down → 与后一相邻位交换
        int target = "up".equals(direction) ? idx - 1 : idx + 1;
        if (target < 0 || target >= ordered.size()) {
            // 已在边界：幂等返回
            return;
        }

        // 交换在内存列表中的位置
        Category tmp = ordered.get(idx);
        ordered.set(idx, ordered.get(target));
        ordered.set(target, tmp);

        // 按新顺序重排 sortOrder（0..n-1），仅持久化发生变化的行
        for (int i = 0; i < ordered.size(); i++) {
            Category c = ordered.get(i);
            if (c.getSortOrder() == null || c.getSortOrder() != i) {
                c.setSortOrder(i);
                categoryMapper.updateById(c);
            }
        }
        log.info("移动分类成功: id={}, direction={}", id, direction);
    }

    /**
     * 转换为响应 DTO（children 恒为空列表，扁平结构）
     *
     * @param category 分类实体
     * @return 分类响应
     */
    private CategoryResponse convertToResponse(Category category) {
        CategoryResponse response = new CategoryResponse();
        BeanUtils.copyProperties(category, response);
        response.setChildren(new ArrayList<>());
        return response;
    }
}