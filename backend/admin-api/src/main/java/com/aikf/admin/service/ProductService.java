package com.aikf.admin.service;

import com.aikf.admin.dto.*;
import com.aikf.admin.entity.Category;
import com.aikf.admin.entity.Product;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.mapper.CategoryMapper;
import com.aikf.admin.mapper.ProductMapper;
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
 * 商品服务类
 * 处理商品的增删改查、上下架等操作
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductService extends ServiceImpl<ProductMapper, Product> {

    private final ProductMapper productMapper;
    private final CategoryMapper categoryMapper;

    /**
     * 分页查询商品列表
     *
     * @param query 查询参数
     * @return 分页响应
     */
    public PageResponse<ProductResponse> getProducts(ProductQueryRequest query, Long tenantId) {
        // 构建查询条件
        LambdaQueryWrapper<Product> wrapper = new LambdaQueryWrapper<>();
        
        // 关键词搜索
        if (StringUtils.hasText(query.getKeyword())) {
            wrapper.like(Product::getName, query.getKeyword());
        }
        
        // 分类筛选
        if (StringUtils.hasText(query.getCategoryId())) {
            wrapper.eq(Product::getCategoryId, query.getCategoryId());
        }
        
        // 状态筛选
        if (StringUtils.hasText(query.getStatus())) {
            wrapper.eq(Product::getStatus, query.getStatus());
        }
        
        // 低库存筛选
        if (query.getStockBelow() != null) {
            wrapper.lt(Product::getStock, query.getStockBelow());
        }
        
        // 按创建时间倒序
        wrapper.orderByDesc(Product::getCreatedAt);
        
        // 执行分页查询
        Page<Product> page = new Page<>(query.getPage(), query.getSize());
        Page<Product> productPage = productMapper.selectPage(page, wrapper);
        
        // 获取分类名称映射
        Map<String, String> categoryNameMap = getCategoryNameMap(productPage.getRecords());
        
        // 转换为响应 DTO
        List<ProductResponse> responses = productPage.getRecords().stream()
                .map(product -> convertToResponse(product, categoryNameMap.get(product.getCategoryId())))
                .collect(Collectors.toList());
        
        return PageResponse.of(productPage.getTotal(), productPage.getCurrent(), productPage.getSize(), responses);
    }

    /**
     * 根据ID查询商品详情
     *
     * @param id 商品ID
     * @return 商品响应
     */
    public ProductResponse getProductById(String id, Long tenantId) {
        Product product = productMapper.selectById(id);
        if (product == null) {
            throw BusinessException.notFound("商品");
        }
        
        // 获取分类名称
        String categoryName = null;
        if (StringUtils.hasText(product.getCategoryId())) {
            Category category = categoryMapper.selectById(product.getCategoryId());
            if (category != null) {
                categoryName = category.getName();
            }
        }
        
        return convertToResponse(product, categoryName);
    }

    /**
     * 创建商品
     *
     * @param request 创建请求
     * @return 商品响应
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductResponse createProduct(ProductCreateRequest request, Long tenantId) {
        // 校验分类是否存在
        validateCategory(request.getCategoryId());
        
        // 创建商品实体
        Product product = new Product();
        BeanUtils.copyProperties(request, product);
        product.setTenantId(tenantId);
        
        // 处理图片列表（转换为 JSON）
        if (request.getImages() != null && !request.getImages().isEmpty()) {
            product.setImages(request.getImages());
        }
        
        // 保存商品
        productMapper.insert(product);
        
        log.info("创建商品成功: id={}, name={}", product.getId(), product.getName());
        
        return getProductById(product.getId(), tenantId);
    }

    /**
     * 更新商品
     *
     * @param id      商品ID
     * @param request 更新请求
     * @return 商品响应
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductResponse updateProduct(String id, ProductUpdateRequest request, Long tenantId) {
        // 查询商品是否存在
        Product product = productMapper.selectById(id);
        if (product == null) {
            throw BusinessException.notFound("商品");
        }
        
        // 校验分类是否存在
        validateCategory(request.getCategoryId());
        
        // 更新商品属性
        BeanUtils.copyProperties(request, product);
        product.setId(id);
        
        // 处理图片列表（转换为 JSON）
        if (request.getImages() != null) {
            product.setImages(request.getImages());
        }
        
        // 更新商品
        productMapper.updateById(product);
        
        log.info("更新商品成功: id={}, name={}", id, product.getName());
        
        return getProductById(id, tenantId);
    }

    /**
     * 删除商品（逻辑删除）
     *
     * @param id 商品ID
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteProduct(String id, Long tenantId) {
        Product product = productMapper.selectById(id);
        if (product == null) {
            throw BusinessException.notFound("商品");
        }
        
        productMapper.deleteById(id);
        log.info("删除商品成功: id={}", id);
    }

    /**
     * 更新商品上下架状态
     *
     * @param id     商品ID
     * @param status 状态：on_sale（上架）、off_sale（下架）
     */
    @Transactional(rollbackFor = Exception.class)
    public void updateProductStatus(String id, String status, Long tenantId) {
        // 校验状态值
        if (!"on_sale".equals(status) && !"off_sale".equals(status)) {
            throw BusinessException.validationError("状态值无效，只能是 on_sale 或 off_sale");
        }
        
        Product product = productMapper.selectById(id);
        if (product == null) {
            throw BusinessException.notFound("商品");
        }
        
        product.setStatus(status);
        productMapper.updateById(product);
        
        log.info("更新商品状态成功: id={}, status={}", id, status);
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
        
        Category category = categoryMapper.selectById(categoryId);
        if (category == null) {
            throw BusinessException.validationError("分类不存在");
        }
    }

    /**
     * 获取分类名称映射
     *
     * @param products 商品列表
     * @return 分类ID -> 分类名称 映射
     */
    private Map<String, String> getCategoryNameMap(List<Product> products) {
        List<String> categoryIds = products.stream()
                .map(Product::getCategoryId)
                .filter(StringUtils::hasText)
                .distinct()
                .collect(Collectors.toList());
        
        if (categoryIds.isEmpty()) {
            return new java.util.HashMap<>();
        }
        
        LambdaQueryWrapper<Category> wrapper = new LambdaQueryWrapper<>();
        wrapper.in(Category::getId, categoryIds);
        List<Category> categories = categoryMapper.selectList(wrapper);
        
        Map<String, String> map = new java.util.HashMap<>();
        for (Category c : categories) {
            map.put(c.getId(), c.getName());
        }
        return map;
    }

    /**
     * 转换为响应 DTO
     *
     * @param product      商品实体
     * @param categoryName 分类名称
     * @return 商品响应
     */
    @SuppressWarnings("unchecked")
    private ProductResponse convertToResponse(Product product, String categoryName) {
        ProductResponse response = new ProductResponse();
        BeanUtils.copyProperties(product, response);
        response.setCategoryName(categoryName);
        
        // 处理图片列表
        if (product.getImages() instanceof List) {
            response.setImages((List<String>) product.getImages());
        }
        
        return response;
    }
}
