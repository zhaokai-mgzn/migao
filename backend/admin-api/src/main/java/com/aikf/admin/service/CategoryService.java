package com.aikf.admin.service;

import com.aikf.admin.dto.CategoryCreateRequest;
import com.aikf.admin.dto.CategoryResponse;
import com.aikf.admin.dto.CategoryUpdateRequest;
import com.aikf.admin.entity.Category;
import com.aikf.admin.entity.Product;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.mapper.CategoryMapper;
import com.aikf.admin.mapper.ProductMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 商品分类服务类
 * 处理分类的树形结构管理
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CategoryService extends ServiceImpl<CategoryMapper, Category> {

    private final CategoryMapper categoryMapper;
    private final ProductMapper productMapper;

    /**
     * 获取分类树
     *
     * @return 分类树列表
     */
    public List<CategoryResponse> getCategoryTree(Long tenantId) {
        // 查询所有分类
        LambdaQueryWrapper<Category> wrapper = new LambdaQueryWrapper<>();
        wrapper.orderByAsc(Category::getSortOrder);
        List<Category> categories = categoryMapper.selectList(wrapper);

        // 构建树形结构
        return buildCategoryTree(categories);
    }

    /**
     * 创建分类
     *
     * @param request 创建请求
     * @return 分类响应
     */
    @Transactional(rollbackFor = Exception.class)
    public CategoryResponse createCategory(CategoryCreateRequest request, Long tenantId) {
        // 校验父分类
        if (StringUtils.hasText(request.getParentId())) {
            Category parent = categoryMapper.selectById(request.getParentId());
            if (parent == null) {
                throw BusinessException.validationError("父分类不存在");
            }
            // 设置层级
            request.setLevel(parent.getLevel() + 1);
        }

        // 创建分类实体
        Category category = new Category();
        BeanUtils.copyProperties(request, category);
        category.setTenantId(tenantId);

        // 保存分类
        categoryMapper.insert(category);

        log.info("创建分类成功: id={}, name={}", category.getId(), category.getName());

        return convertToResponse(category);
    }

    /**
     * 更新分类
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

        // 校验父分类
        if (StringUtils.hasText(request.getParentId())) {
            // 不能将自己设为父分类
            if (id.equals(request.getParentId())) {
                throw BusinessException.validationError("不能将自己设为父分类");
            }

            Category parent = categoryMapper.selectById(request.getParentId());
            if (parent == null) {
                throw BusinessException.validationError("父分类不存在");
            }
            // 更新层级
            request.setLevel(parent.getLevel() + 1);
        }

        // 更新分类属性
        BeanUtils.copyProperties(request, category);
        category.setId(id);

        // 更新分类
        categoryMapper.updateById(category);

        log.info("更新分类成功: id={}, name={}", id, category.getName());

        return convertToResponse(category);
    }

    /**
     * 删除分类
     *
     * @param id 分类ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteCategory(String id, Long tenantId) {
        Category category = categoryMapper.selectById(id);
        if (category == null) {
            throw BusinessException.notFound("分类");
        }

        // 检查是否有子分类
        LambdaQueryWrapper<Category> childWrapper = new LambdaQueryWrapper<>();
        childWrapper.eq(Category::getParentId, id);
        Long childCount = categoryMapper.selectCount(childWrapper);
        if (childCount > 0) {
            throw BusinessException.validationError("该分类下有子分类，无法删除");
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
     * 构建分类树
     *
     * @param categories 分类列表
     * @return 树形结构列表
     */
    private List<CategoryResponse> buildCategoryTree(List<Category> categories) {
        // 转换为响应对象
        List<CategoryResponse> responseList = categories.stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());

        // 按父分类ID分组
        Map<String, List<CategoryResponse>> parentIdMap = responseList.stream()
                .filter(c -> StringUtils.hasText(c.getParentId()))
                .collect(Collectors.groupingBy(CategoryResponse::getParentId));

        // 设置子分类
        for (CategoryResponse category : responseList) {
            List<CategoryResponse> children = parentIdMap.get(category.getId());
            if (children != null) {
                category.setChildren(children);
            }
        }

        // 返回顶级分类（parentId 为空）
        return responseList.stream()
                .filter(c -> !StringUtils.hasText(c.getParentId()))
                .collect(Collectors.toList());
    }

    /**
     * 转换为响应 DTO
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
