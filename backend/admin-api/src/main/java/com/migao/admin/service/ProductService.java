package com.migao.admin.service;

import com.migao.admin.dto.*;
import com.migao.admin.entity.Category;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductAttribute;
import com.migao.admin.entity.ProductColor;
import com.migao.admin.entity.ProductProcessingItem;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import com.migao.admin.mapper.ProductColorMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductProcessingItemMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.beans.BeanUtils;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.OutputStream;
import java.math.BigDecimal;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
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
    private final ProductColorMapper productColorMapper;
    private final ProductSkuMapper productSkuMapper;
    private final ProductProcessingItemMapper productProcessingItemMapper;
    private final ProcessingItemMapper processingItemMapper;
    private final ProductAttributeMapper productAttributeMapper;

    /**
     * 商品品牌存储在 product_attributes 表的 attr_key
     */
    private static final String ATTR_KEY_BRAND = "brand";

    /**
     * 合法的状态流转映射
     */
    private static final Map<String, List<String>> STATUS_TRANSITIONS = new HashMap<>();
    static {
        STATUS_TRANSITIONS.put("draft", List.of("under_review", "in_warehouse"));
        STATUS_TRANSITIONS.put("under_review", List.of("on_sale", "draft"));
        STATUS_TRANSITIONS.put("on_sale", List.of("in_warehouse"));
        STATUS_TRANSITIONS.put("in_warehouse", List.of("under_review"));
        // 兼容旧状态
        STATUS_TRANSITIONS.put("off_sale", List.of("on_sale", "under_review", "in_warehouse"));
    }

    /**
     * 分页查询商品列表
     */
    public PageResponse<ProductResponse> getProducts(ProductQueryRequest query, Long tenantId) {
        LambdaQueryWrapper<Product> wrapper = new LambdaQueryWrapper<>();

        // 关键词搜索（名称 + 货号）
        if (StringUtils.hasText(query.getKeyword())) {
            wrapper.and(w -> w.like(Product::getName, query.getKeyword())
                    .or().like(Product::getSkuCode, query.getKeyword()));
        }

        // 商品标题模糊搜索
        if (StringUtils.hasText(query.getName())) {
            wrapper.like(Product::getName, query.getName());
        }

        // 商品ID精确搜索
        if (StringUtils.hasText(query.getProductId())) {
            wrapper.eq(Product::getId, query.getProductId());
        }

        // SKU货号模糊搜索
        if (StringUtils.hasText(query.getSkuCode())) {
            wrapper.like(Product::getSkuCode, query.getSkuCode());
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

        // 时间范围筛选（createdFrom/createdTo 优先于 startDate/endDate）
        String fromDate = StringUtils.hasText(query.getCreatedFrom()) ? query.getCreatedFrom() : query.getStartDate();
        String toDate = StringUtils.hasText(query.getCreatedTo()) ? query.getCreatedTo() : query.getEndDate();
        if (StringUtils.hasText(fromDate)) {
            OffsetDateTime startDateTime = LocalDate.parse(fromDate, DateTimeFormatter.ISO_LOCAL_DATE)
                    .atStartOfDay().atOffset(ZoneOffset.UTC);
            wrapper.ge(Product::getCreatedAt, startDateTime);
        }
        if (StringUtils.hasText(toDate)) {
            OffsetDateTime endDateTime = LocalDate.parse(toDate, DateTimeFormatter.ISO_LOCAL_DATE)
                    .plusDays(1).atStartOfDay().atOffset(ZoneOffset.UTC);
            wrapper.lt(Product::getCreatedAt, endDateTime);
        }

        // 排序（支持 camelCase 和 snake_case）
        if (StringUtils.hasText(query.getSortBy())) {
            boolean isAsc = "asc".equalsIgnoreCase(query.getSortOrder());
            switch (query.getSortBy()) {
                case "stock" -> wrapper.orderBy(true, isAsc, Product::getStock);
                case "sales_count", "salesCount" -> wrapper.orderBy(true, isAsc, Product::getSalesCount);
                case "sales_amount", "salesAmount" -> wrapper.orderBy(true, isAsc, Product::getSalesAmount);
                case "created_at", "createdAt" -> wrapper.orderBy(true, isAsc, Product::getCreatedAt);
                default -> wrapper.orderByDesc(Product::getCreatedAt);
            }
        } else {
            wrapper.orderByDesc(Product::getCreatedAt);
        }

        // 执行分页查询
        Page<Product> page = new Page<>(query.getPage(), query.getSize());
        Page<Product> productPage = productMapper.selectPage(page, wrapper);

        // 获取分类名称映射
        Map<String, String> categoryNameMap = getCategoryNameMap(productPage.getRecords());

        // 转换为响应 DTO，附加 colorCount 和 totalStock
        List<ProductResponse> responses = productPage.getRecords().stream()
                .map(product -> {
                    ProductResponse response = convertToResponse(product, categoryNameMap.get(product.getCategoryId()));
                    // 附加颜色数和总库存
                    response.setColorCount(getColorCount(product.getId()));
                    response.setTotalStock(getTotalStock(product.getId()));
                    return response;
                })
                .collect(Collectors.toList());

        return PageResponse.of(productPage.getTotal(), productPage.getCurrent(), productPage.getSize(), responses);
    }

    /**
     * 根据ID查询商品详情
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

        ProductResponse response = convertToResponse(product, categoryName);
        response.setColorCount(getColorCount(id));
        response.setTotalStock(getTotalStock(id));

        // 查询关联颜色列表
        List<ProductColor> colorEntities = productColorMapper.selectList(
                new LambdaQueryWrapper<ProductColor>()
                        .eq(ProductColor::getProductId, id)
                        .orderByAsc(ProductColor::getSortOrder)
                        .orderByAsc(ProductColor::getId)
        );
        Map<Long, String> colorNameMap = new HashMap<>();
        if (colorEntities != null && !colorEntities.isEmpty()) {
            List<ProductColorResponse> colorResponses = colorEntities.stream().map(c -> {
                ProductColorResponse cr = new ProductColorResponse();
                cr.setId(c.getId());
                cr.setProductId(c.getProductId());
                cr.setColorName(c.getColorName());
                cr.setMainColorHex(c.getMainColorHex());
                cr.setColorImageUrl(c.getColorImageUrl());
                cr.setRemark(c.getRemark());
                cr.setSortOrder(c.getSortOrder());
                cr.setCreatedAt(c.getCreatedAt());
                cr.setUpdatedAt(c.getUpdatedAt());
                colorNameMap.put(c.getId(), c.getColorName());
                return cr;
            }).collect(Collectors.toList());
            response.setColors(colorResponses);
        }

        // 查询关联 SKU 列表
        List<ProductSku> skuEntities = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>()
                        .eq(ProductSku::getProductId, id)
                        .orderByAsc(ProductSku::getColorId)
                        .orderByAsc(ProductSku::getDoorWidth)
        );
        if (skuEntities != null && !skuEntities.isEmpty()) {
            List<ProductSkuResponse> skuResponses = skuEntities.stream().map(sku -> {
                ProductSkuResponse skuResp = new ProductSkuResponse();
                skuResp.setId(sku.getId());
                skuResp.setProductId(sku.getProductId());
                skuResp.setColorId(sku.getColorId());
                skuResp.setColorName(colorNameMap.get(sku.getColorId()));
                skuResp.setSellingMethod(sku.getSellingMethod());
                skuResp.setDoorWidth(sku.getDoorWidth());
                skuResp.setPrice(sku.getPrice());
                skuResp.setStock(sku.getStock());
                skuResp.setSkuCode(sku.getSkuCode());
                skuResp.setCreatedAt(sku.getCreatedAt());
                skuResp.setUpdatedAt(sku.getUpdatedAt());
                return skuResp;
            }).collect(Collectors.toList());
            response.setSkus(skuResponses);

            // 从 SKU 派生 sellingMethods 与 doorWidths（保持插入顺序去重）
            Set<String> sm = new LinkedHashSet<>();
            Set<String> dw = new LinkedHashSet<>();
            for (ProductSku sku : skuEntities) {
                if (StringUtils.hasText(sku.getSellingMethod())) sm.add(sku.getSellingMethod());
                if (StringUtils.hasText(sku.getDoorWidth())) dw.add(sku.getDoorWidth());
            }
            response.setSellingMethods(new ArrayList<>(sm));
            response.setDoorWidths(new ArrayList<>(dw));
        }

        // 回填商品属性：brand + specifications
        fillProductAttributes(response, id);

        // 回填加工项配置列表
        fillProcessingItemConfigs(response, id, tenantId);

        return response;
    }

    /**
     * 创建商品
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductResponse createProduct(ProductCreateRequest request, Long tenantId) {
        // 根据目标状态校验必填字段（draft 状态放宽）
        validateRequiredForStatus(request.getStatus(), request.getCategoryId(), request.getBasePrice());

        // 校验分类是否存在
        validateCategory(request.getCategoryId());

        // 创建商品实体
        Product product = new Product();
        BeanUtils.copyProperties(request, product);
        product.setTenantId(tenantId);

        // 处理图片列表
        if (request.getImages() != null && !request.getImages().isEmpty()) {
            product.setImages(request.getImages());
        }

        // 详情图列表（JSONB 存储于 products.detail_images）
        if (request.getDetailImages() != null) {
            product.setDetailImages(request.getDetailImages());
        }

        // 设置默认状态
        if (!StringUtils.hasText(product.getStatus())) {
            product.setStatus("draft");
        }

        // 设置编辑信息
        product.setEditedBy(getCurrentUsername());
        product.setEditedAt(OffsetDateTime.now());

        // 保存商品
        productMapper.insert(product);

        // 保存销售信息（颜色 + SKU）
        saveColorsAndSkus(product.getId(), tenantId,
                request.getColors(), request.getSkus());

        // 保存商品属性（brand + specifications，存入 product_attributes 表）
        saveProductAttributes(product.getId(), tenantId, request.getBrand(), request.getSpecifications());

        // 保存加工项配置到关联表
        if (request.getProcessingItemConfigs() != null) {
            saveProcessingItemConfigs(product.getId(), tenantId, request.getProcessingItemConfigs());
        }

        log.info("创建商品成功: id={}, name={}", product.getId(), product.getName());

        return getProductById(product.getId(), tenantId);
    }

    /**
     * 更新商品
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductResponse updateProduct(String id, ProductUpdateRequest request, Long tenantId) {
        Product product = productMapper.selectById(id);
        if (product == null) {
            throw BusinessException.notFound("商品");
        }

        // 根据目标状态校验必填字段（draft 状态放宽）
        validateRequiredForStatus(request.getStatus(), request.getCategoryId(), request.getBasePrice());

        // 校验分类是否存在
        validateCategory(request.getCategoryId());

        // 保存原始状态，防止 BeanUtils.copyProperties 绕过状态机
        String originalStatus = product.getStatus();

        // 更新商品属性
        BeanUtils.copyProperties(request, product);
        product.setId(id);
        // 恢复状态：状态变更必须通过 updateProductStatus 接口（含状态机校验）
        product.setStatus(originalStatus);

        // 处理图片列表
        if (request.getImages() != null) {
            product.setImages(request.getImages());
        }

        // 详情图列表（允许传空数组清空）
        if (request.getDetailImages() != null) {
            product.setDetailImages(request.getDetailImages());
        }

        // 更新编辑信息
        product.setEditedBy(getCurrentUsername());
        product.setEditedAt(OffsetDateTime.now());

        productMapper.updateById(product);

        // 更新销售信息（先删后插）：仅当请求中包含 colors/skus 字段时才更新，避免误清空
        if (request.getColors() != null || request.getSkus() != null) {
            // 删除旧颜色和旧 SKU
            productSkuMapper.delete(new LambdaQueryWrapper<ProductSku>()
                    .eq(ProductSku::getProductId, id));
            productColorMapper.delete(new LambdaQueryWrapper<ProductColor>()
                    .eq(ProductColor::getProductId, id));
            // 重新保存
            saveColorsAndSkus(id, tenantId, request.getColors(), request.getSkus());
        }

        // 更新商品属性：仅当请求中明确提交 brand 或 specifications 时才重写，避免误清空
        if (request.getBrand() != null || request.getSpecifications() != null) {
            saveProductAttributes(id, tenantId, request.getBrand(), request.getSpecifications());
        }

        // 更新加工项配置：先删后插，仅当请求中包含 processingItemConfigs 字段时才更新
        if (request.getProcessingItemConfigs() != null) {
            productProcessingItemMapper.delete(
                    new LambdaQueryWrapper<ProductProcessingItem>()
                            .eq(ProductProcessingItem::getProductId, id)
            );
            saveProcessingItemConfigs(id, tenantId, request.getProcessingItemConfigs());
        }

        log.info("更新商品成功: id={}, name={}", id, product.getName());

        return getProductById(id, tenantId);
    }

    /**
     * 保存商品的颜色与 SKU 数据
     *
     * 1. 先批量插入 colors，每条由数据库生成主键，构建 前端临时ID -> DB主键 映射
     * 2. 再批量插入 skus，使用映射替换 colorId
     * 3. 仅在 colors / skus 任一非空时执行；空集合或 null 则跳过
     */
    private void saveColorsAndSkus(String productId, Long tenantId,
                                    List<ProductColorInput> colorInputs,
                                    List<ProductSkuInput> skuInputs) {
        if ((colorInputs == null || colorInputs.isEmpty())
                && (skuInputs == null || skuInputs.isEmpty())) {
            return;
        }

        // 前端临时 colorId -> DB 真实 colorId
        Map<Long, Long> colorIdMap = new LinkedHashMap<>();

        if (colorInputs != null) {
            int idx = 0;
            for (ProductColorInput input : colorInputs) {
                if (input == null) continue;
                ProductColor entity = new ProductColor();
                entity.setTenantId(tenantId);
                entity.setProductId(productId);
                entity.setColorName(input.getColorName());
                entity.setMainColorHex(input.getMainColorHex());
                entity.setColorImageUrl(input.getColorImageUrl());
                entity.setRemark(input.getRemark());
                entity.setSortOrder(input.getSortOrder() != null ? input.getSortOrder() : idx);
                productColorMapper.insert(entity);
                if (input.getId() != null) {
                    colorIdMap.put(input.getId(), entity.getId());
                }
                idx++;
            }
        }

        if (skuInputs != null) {
            for (ProductSkuInput input : skuInputs) {
                if (input == null) continue;
                if (!StringUtils.hasText(input.getSellingMethod())
                        || !StringUtils.hasText(input.getDoorWidth())) {
                    continue;
                }
                Long mappedColorId = null;
                if (input.getColorId() != null) {
                    mappedColorId = colorIdMap.getOrDefault(input.getColorId(), input.getColorId());
                    // 若映射后非法（前端临时ID未在 colorIdMap 中且其本身为负数），则跳过
                    if (mappedColorId != null && mappedColorId <= 0) {
                        continue;
                    }
                }
                ProductSku entity = new ProductSku();
                entity.setTenantId(tenantId);
                entity.setProductId(productId);
                entity.setColorId(mappedColorId);
                entity.setSellingMethod(input.getSellingMethod());
                entity.setDoorWidth(input.getDoorWidth());
                entity.setPrice(input.getPrice() != null ? input.getPrice() : BigDecimal.ZERO);
                entity.setStock(input.getStock() != null ? input.getStock() : 0);
                entity.setSkuCode(input.getSkuCode());
                entity.setSalesCount(0);
                productSkuMapper.insert(entity);
            }
        }
    }

    /**
     * 保存/更新商品属性（brand + specifications）到 product_attributes 表
     * 先删后插，语义为全量覆盖。调用方负责判断是否需要调用。
     */
    private void saveProductAttributes(String productId, Long tenantId,
                                       String brand, Map<String, String> specifications) {
        // 删除已有属性（用于更新场景）
        productAttributeMapper.delete(new LambdaQueryWrapper<ProductAttribute>()
                .eq(ProductAttribute::getProductId, productId));

        List<ProductAttribute> attrs = new ArrayList<>();
        if (StringUtils.hasText(brand)) {
            ProductAttribute attr = new ProductAttribute();
            attr.setProductId(productId);
            attr.setTenantId(tenantId);
            attr.setAttrKey(ATTR_KEY_BRAND);
            attr.setAttrValue(brand);
            attrs.add(attr);
        }
        if (specifications != null) {
            specifications.forEach((key, value) -> {
                if (StringUtils.hasText(key) && StringUtils.hasText(value)) {
                    ProductAttribute attr = new ProductAttribute();
                    attr.setProductId(productId);
                    attr.setTenantId(tenantId);
                    attr.setAttrKey(key);
                    attr.setAttrValue(value);
                    attrs.add(attr);
                }
            });
        }
        if (!attrs.isEmpty()) {
            attrs.forEach(productAttributeMapper::insert);
        }
    }

    /**
     * 查询商品属性并填充到 ProductResponse。
     * brand 单独取出，其余属性放入 specifications map。
     */
    private void fillProductAttributes(ProductResponse response, String productId) {
        List<ProductAttribute> attrs = productAttributeMapper.selectList(
                new LambdaQueryWrapper<ProductAttribute>()
                        .eq(ProductAttribute::getProductId, productId)
        );
        if (attrs == null || attrs.isEmpty()) {
            return;
        }
        Map<String, String> specifications = new LinkedHashMap<>();
        for (ProductAttribute attr : attrs) {
            if (!StringUtils.hasText(attr.getAttrKey())) {
                continue;
            }
            if (ATTR_KEY_BRAND.equals(attr.getAttrKey())) {
                response.setBrand(attr.getAttrValue());
            } else {
                specifications.put(attr.getAttrKey(), attr.getAttrValue());
            }
        }
        if (!specifications.isEmpty()) {
            response.setSpecifications(specifications);
        }
    }

    /**
     * 保存商品的加工项配置到 product_processing_items 关联表
     * 调用方负责控制是否先删后插。
     */
    private void saveProcessingItemConfigs(String productId, Long tenantId,
                                           List<ProcessingItemConfigInput> configs) {
        if (configs == null || configs.isEmpty()) {
            return;
        }
        int idx = 0;
        for (ProcessingItemConfigInput input : configs) {
            if (input == null || !StringUtils.hasText(input.getProcessingItemId())) {
                continue;
            }
            ProductProcessingItem entity = new ProductProcessingItem();
            entity.setTenantId(tenantId);
            entity.setProductId(productId);
            entity.setProcessingItemId(input.getProcessingItemId());
            entity.setCustomPrice(input.getCustomPrice());
            entity.setSortOrder(idx++);
            productProcessingItemMapper.insert(entity);
        }
    }

    /**
     * 查询商品加工项配置并填充到 ProductResponse
     */
    private void fillProcessingItemConfigs(ProductResponse response, String productId, Long tenantId) {
        List<ProductProcessingItem> relations = productProcessingItemMapper.selectList(
                new LambdaQueryWrapper<ProductProcessingItem>()
                        .eq(ProductProcessingItem::getProductId, productId)
                        .eq(ProductProcessingItem::getTenantId, tenantId)
                        .orderByAsc(ProductProcessingItem::getSortOrder)
        );
        if (relations == null || relations.isEmpty()) {
            response.setProcessingItemConfigs(java.util.Collections.emptyList());
            return;
        }

        // 批量查询加工项名称
        List<String> processingItemIds = relations.stream()
                .map(ProductProcessingItem::getProcessingItemId)
                .filter(StringUtils::hasText)
                .distinct()
                .collect(Collectors.toList());
        Map<String, String> itemNameMap = new HashMap<>();
        if (!processingItemIds.isEmpty()) {
            List<ProcessingItem> items = processingItemMapper.selectList(
                    new LambdaQueryWrapper<ProcessingItem>()
                            .in(ProcessingItem::getId, processingItemIds)
            );
            if (items != null) {
                for (ProcessingItem item : items) {
                    itemNameMap.put(item.getId(), item.getName());
                }
            }
        }

        List<ProcessingItemConfigResponse> configs = new ArrayList<>();
        for (ProductProcessingItem rel : relations) {
            ProcessingItemConfigResponse cfg = new ProcessingItemConfigResponse();
            cfg.setProcessingItemId(rel.getProcessingItemId());
            cfg.setProcessingItemName(itemNameMap.get(rel.getProcessingItemId()));
            cfg.setCustomPrice(rel.getCustomPrice());
            configs.add(cfg);
        }
        response.setProcessingItemConfigs(configs);
    }

    /**
     * 删除商品（逻辑删除）
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
     * 更新商品状态（含状态流转校验）
     */
    @Transactional(rollbackFor = Exception.class)
    public void updateProductStatus(String id, String status, Long tenantId) {
        Product product = productMapper.selectById(id);
        if (product == null) {
            throw BusinessException.notFound("商品");
        }

        String currentStatus = product.getStatus();
        if (currentStatus == null) {
            currentStatus = "draft";
        }

        // 状态流转校验
        List<String> allowedTransitions = STATUS_TRANSITIONS.get(currentStatus);
        if (allowedTransitions == null || !allowedTransitions.contains(status)) {
            throw BusinessException.validationError(
                    String.format("状态流转无效: %s → %s，允许的目标状态: %s",
                            currentStatus, status,
                            allowedTransitions != null ? allowedTransitions : "无"));
        }

        product.setStatus(status);
        product.setEditedBy(getCurrentUsername());
        product.setEditedAt(OffsetDateTime.now());
        productMapper.updateById(product);

        log.info("更新商品状态成功: id={}, {} -> {}", id, currentStatus, status);
    }

    // ========== 批量操作 ==========

    /**
     * 批量上架
     * 只有 off_sale/in_warehouse 状态的商品可上架
     */
    @Transactional(rollbackFor = Exception.class)
    public BatchOperationResult batchOnShelf(List<String> productIds, Long tenantId) {
        BatchOperationResult result = BatchOperationResult.create();
        if (productIds == null || productIds.isEmpty()) {
            return result;
        }
        Set<String> allowedStatuses = Set.of("off_sale", "in_warehouse");

        for (String id : productIds) {
            Product product = productMapper.selectById(id);
            if (product == null) {
                result.addError(id, "商品不存在");
                continue;
            }
            String currentStatus = product.getStatus() != null ? product.getStatus() : "draft";
            if (!allowedStatuses.contains(currentStatus)) {
                result.addError(id, "当前状态[" + currentStatus + "]不允许上架");
                continue;
            }
            product.setStatus("on_sale");
            product.setEditedBy(getCurrentUsername());
            product.setEditedAt(OffsetDateTime.now());
            productMapper.updateById(product);
            result.addSuccess();
        }

        log.info("批量上架完成: success={}, failed={}", result.getSuccess(), result.getFailed());
        return result;
    }

    /**
     * 批量下架
     * 只有 on_sale 状态的商品可下架
     */
    @Transactional(rollbackFor = Exception.class)
    public BatchOperationResult batchOffShelf(List<String> productIds, Long tenantId) {
        BatchOperationResult result = BatchOperationResult.create();
        if (productIds == null || productIds.isEmpty()) {
            return result;
        }

        for (String id : productIds) {
            Product product = productMapper.selectById(id);
            if (product == null) {
                result.addError(id, "商品不存在");
                continue;
            }
            String currentStatus = product.getStatus() != null ? product.getStatus() : "draft";
            if (!"on_sale".equals(currentStatus)) {
                result.addError(id, "当前状态[" + currentStatus + "]不允许下架");
                continue;
            }
            product.setStatus("in_warehouse");
            product.setEditedBy(getCurrentUsername());
            product.setEditedAt(OffsetDateTime.now());
            productMapper.updateById(product);
            result.addSuccess();
        }

        log.info("批量下架完成: success={}, failed={}", result.getSuccess(), result.getFailed());
        return result;
    }

    /**
     * 批量删除
     * 只有 draft/off_sale 状态可删除；on_sale 不可删
     */
    @Transactional(rollbackFor = Exception.class)
    public BatchOperationResult batchDelete(List<String> productIds, Long tenantId) {
        BatchOperationResult result = BatchOperationResult.create();
        if (productIds == null || productIds.isEmpty()) {
            return result;
        }
        Set<String> allowedStatuses = Set.of("draft", "off_sale");

        for (String id : productIds) {
            Product product = productMapper.selectById(id);
            if (product == null) {
                result.addError(id, "商品不存在");
                continue;
            }
            String currentStatus = product.getStatus() != null ? product.getStatus() : "draft";
            if (!allowedStatuses.contains(currentStatus)) {
                result.addError(id, "当前状态[" + currentStatus + "]不允许删除");
                continue;
            }
            productMapper.deleteById(id);
            result.addSuccess();
        }

        log.info("批量删除完成: success={}, failed={}", result.getSuccess(), result.getFailed());
        return result;
    }

    // ========== 导入/导出 ==========

    /**
     * 导入商品
     * 解析 Excel 并批量创建商品
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductImportResult importProducts(MultipartFile file, Long tenantId) {
        ProductImportResult result = ProductImportResult.create();

        try (Workbook workbook = WorkbookFactory.create(file.getInputStream())) {
            Sheet sheet = workbook.getSheetAt(0);
            if (sheet == null) {
                throw BusinessException.validationError("Excel文件为空");
            }

            // 第一行为表头，从第二行开始读取数据
            int lastRow = sheet.getLastRowNum();
            result.setTotal(lastRow); // 数据行数

            for (int i = 1; i <= lastRow; i++) {
                Row row = sheet.getRow(i);
                if (row == null) {
                    continue;
                }
                try {
                    Product product = parseProductFromRow(row, tenantId);
                    productMapper.insert(product);
                    result.addSuccess();
                } catch (Exception e) {
                    result.addError(i + 1, e.getMessage());
                }
            }

        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            log.error("解析Excel文件失败", e);
            throw BusinessException.validationError("解析Excel文件失败: " + e.getMessage());
        }

        log.info("导入商品完成: total={}, success={}, failed={}",
                result.getTotal(), result.getSuccessCount(), result.getFailCount());
        return result;
    }

    /**
     * 导出商品
     */
    public void exportProducts(ProductQueryRequest query, Long tenantId, HttpServletResponse response) throws IOException {
        // 查询商品列表（不分页，全量导出）
        query.setPage(1L);
        query.setSize(10000L);
        PageResponse<ProductResponse> pageResult = getProducts(query, tenantId);
        List<ProductResponse> products = pageResult.getItems();

        // 设置响应头
        String filename = URLEncoder.encode("商品列表.xlsx", StandardCharsets.UTF_8);
        response.setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        response.setHeader("Content-Disposition", "attachment; filename=" + filename);

        try (Workbook workbook = new XSSFWorkbook(); OutputStream out = response.getOutputStream()) {
            Sheet sheet = workbook.createSheet("商品列表");

            // 表头
            String[] headers = {"商品名称", "货号", "分类", "价格", "库存", "状态", "描述"};
            Row headerRow = sheet.createRow(0);
            CellStyle headerStyle = workbook.createCellStyle();
            Font headerFont = workbook.createFont();
            headerFont.setBold(true);
            headerStyle.setFont(headerFont);

            for (int i = 0; i < headers.length; i++) {
                Cell cell = headerRow.createCell(i);
                cell.setCellValue(headers[i]);
                cell.setCellStyle(headerStyle);
            }

            // 数据行
            for (int i = 0; i < products.size(); i++) {
                ProductResponse p = products.get(i);
                Row row = sheet.createRow(i + 1);
                row.createCell(0).setCellValue(p.getName() != null ? p.getName() : "");
                row.createCell(1).setCellValue(p.getSkuCode() != null ? p.getSkuCode() : "");
                row.createCell(2).setCellValue(p.getCategoryName() != null ? p.getCategoryName() : "");
                row.createCell(3).setCellValue(p.getBasePrice() != null ? p.getBasePrice().doubleValue() : 0);
                row.createCell(4).setCellValue(p.getStock() != null ? p.getStock() : 0);
                row.createCell(5).setCellValue(getStatusLabel(p.getStatus()));
                row.createCell(6).setCellValue(p.getDescription() != null ? p.getDescription() : "");
            }

            // 自动列宽
            for (int i = 0; i < headers.length; i++) {
                sheet.autoSizeColumn(i);
            }

            workbook.write(out);
        }
    }

    /**
     * 生成导入模板
     */
    public void generateImportTemplate(HttpServletResponse response) throws IOException {
        String filename = URLEncoder.encode("商品导入模板.xlsx", StandardCharsets.UTF_8);
        response.setContentType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
        response.setHeader("Content-Disposition", "attachment; filename=" + filename);

        try (Workbook workbook = new XSSFWorkbook(); OutputStream out = response.getOutputStream()) {
            Sheet sheet = workbook.createSheet("商品导入");

            // 表头
            String[] headers = {"商品名称*", "货号", "分类ID", "价格*", "库存", "描述"};
            Row headerRow = sheet.createRow(0);
            CellStyle headerStyle = workbook.createCellStyle();
            Font headerFont = workbook.createFont();
            headerFont.setBold(true);
            headerStyle.setFont(headerFont);

            for (int i = 0; i < headers.length; i++) {
                Cell cell = headerRow.createCell(i);
                cell.setCellValue(headers[i]);
                cell.setCellStyle(headerStyle);
            }

            // 示例行
            Row exampleRow = sheet.createRow(1);
            exampleRow.createCell(0).setCellValue("示例商品名称");
            exampleRow.createCell(1).setCellValue("SKU001");
            exampleRow.createCell(2).setCellValue("");
            exampleRow.createCell(3).setCellValue(99.9);
            exampleRow.createCell(4).setCellValue(100);
            exampleRow.createCell(5).setCellValue("商品描述信息");

            for (int i = 0; i < headers.length; i++) {
                sheet.autoSizeColumn(i);
            }

            workbook.write(out);
        }
    }

    /**
     * 查询商品关联的加工项列表
     * 1. 查询 product_processing_items 表中该商品的所有关联记录
     * 2. 根据 processing_item_id 批量查询 processing_items 表获取完整信息
     * 3. 仅返回 status='active' 的加工项
     * 4. 合并自定义价格（custom_price 不为空则 finalPrice = customPrice，否则 finalPrice = unitPrice）
     * 5. 按 sort_order 升序排序
     */
    public List<ProductProcessingItemResponse> getProductProcessingItems(String productId, Long tenantId) {
        // 校验商品存在且属于当前租户
        Product product = productMapper.selectById(productId);
        if (product == null) {
            throw BusinessException.notFound("商品");
        }

        // 查询关联记录（按 sort_order 升序）
        List<ProductProcessingItem> relations = productProcessingItemMapper.selectList(
                new LambdaQueryWrapper<ProductProcessingItem>()
                        .eq(ProductProcessingItem::getProductId, productId)
                        .eq(ProductProcessingItem::getTenantId, tenantId)
                        .orderByAsc(ProductProcessingItem::getSortOrder)
        );
        if (relations == null || relations.isEmpty()) {
            return java.util.Collections.emptyList();
        }

        // 批量查询加工项详情（仅 active）
        List<String> processingItemIds = relations.stream()
                .map(ProductProcessingItem::getProcessingItemId)
                .filter(StringUtils::hasText)
                .distinct()
                .collect(Collectors.toList());
        if (processingItemIds.isEmpty()) {
            return java.util.Collections.emptyList();
        }

        List<ProcessingItem> processingItems = processingItemMapper.selectList(
                new LambdaQueryWrapper<ProcessingItem>()
                        .in(ProcessingItem::getId, processingItemIds)
                        .eq(ProcessingItem::getStatus, "active")
        );
        Map<String, ProcessingItem> itemMap = processingItems.stream()
                .collect(Collectors.toMap(ProcessingItem::getId, item -> item));

        // 按关联表顺序组装响应，过滤已被禁用/不存在的加工项
        List<ProductProcessingItemResponse> result = new java.util.ArrayList<>();
        for (ProductProcessingItem relation : relations) {
            ProcessingItem item = itemMap.get(relation.getProcessingItemId());
            if (item == null) {
                continue;
            }
            BigDecimal customPrice = relation.getCustomPrice();
            BigDecimal unitPrice = item.getUnitPrice();
            BigDecimal finalPrice = customPrice != null ? customPrice : unitPrice;

            result.add(ProductProcessingItemResponse.builder()
                    .id(item.getId())
                    .name(item.getName())
                    .pricingMethod(item.getPricingMethod())
                    .unitPrice(unitPrice)
                    .customPrice(customPrice)
                    .finalPrice(finalPrice)
                    .unit(item.getUnit())
                    .build());
        }
        return result;
    }

    // ========== 私有辅助方法 ==========

    /**
     * 从 Excel 行解析商品
     */
    private Product parseProductFromRow(Row row, Long tenantId) {
        String name = getCellStringValue(row, 0);
        if (!StringUtils.hasText(name)) {
            throw new IllegalArgumentException("商品名称不能为空");
        }

        String skuCode = getCellStringValue(row, 1);
        String categoryId = getCellStringValue(row, 2);

        BigDecimal price;
        try {
            double priceVal = getCellNumericValue(row, 3);
            if (priceVal <= 0) {
                throw new IllegalArgumentException("价格必须大于0");
            }
            price = BigDecimal.valueOf(priceVal);
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("价格格式错误");
        }

        int stock = 0;
        try {
            stock = (int) getCellNumericValue(row, 4);
        } catch (Exception ignored) {
            // 库存默认0
        }

        String description = getCellStringValue(row, 5);

        Product product = new Product();
        product.setName(name);
        product.setSkuCode(skuCode);
        product.setCategoryId(categoryId);
        product.setBasePrice(price);
        product.setStock(stock);
        product.setDescription(description);
        product.setTenantId(tenantId);
        product.setStatus("draft");
        product.setEditedBy(getCurrentUsername());
        product.setEditedAt(OffsetDateTime.now());

        return product;
    }

    /**
     * 获取单元格字符串值
     */
    private String getCellStringValue(Row row, int cellIndex) {
        Cell cell = row.getCell(cellIndex);
        if (cell == null) return null;
        return switch (cell.getCellType()) {
            case STRING -> cell.getStringCellValue().trim();
            case NUMERIC -> String.valueOf((long) cell.getNumericCellValue());
            case BOOLEAN -> String.valueOf(cell.getBooleanCellValue());
            default -> null;
        };
    }

    /**
     * 获取单元格数值
     */
    private double getCellNumericValue(Row row, int cellIndex) {
        Cell cell = row.getCell(cellIndex);
        if (cell == null) return 0;
        return switch (cell.getCellType()) {
            case NUMERIC -> cell.getNumericCellValue();
            case STRING -> Double.parseDouble(cell.getStringCellValue().trim());
            default -> 0;
        };
    }

    /**
     * 状态标签
     */
    private String getStatusLabel(String status) {
        if (status == null) return "";
        return switch (status) {
            case "on_sale" -> "出售中";
            case "off_sale" -> "已下架";
            case "in_warehouse" -> "仓库中";
            case "under_review" -> "审核中";
            case "draft" -> "草稿";
            default -> status;
        };
    }

    /**
     * 校验分类是否存在
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
     * 根据目标状态校验必填字段：draft 状态允许留空，其他状态需严格校验。
     */
    private void validateRequiredForStatus(String status, String categoryId, java.math.BigDecimal basePrice) {
        // 未传或为 draft 时不做必填校验
        if (!StringUtils.hasText(status) || "draft".equalsIgnoreCase(status)) {
            return;
        }
        if (!StringUtils.hasText(categoryId)) {
            throw BusinessException.validationError("分类ID不能为空");
        }
        if (basePrice == null) {
            throw BusinessException.validationError("基础价格不能为空");
        }
        if (basePrice.signum() <= 0) {
            throw BusinessException.validationError("基础价格必须大于 0");
        }
    }

    /**
     * 获取分类名称映射
     */
    private Map<String, String> getCategoryNameMap(List<Product> products) {
        List<String> categoryIds = products.stream()
                .map(Product::getCategoryId)
                .filter(StringUtils::hasText)
                .distinct()
                .collect(Collectors.toList());

        if (categoryIds.isEmpty()) {
            return new HashMap<>();
        }

        LambdaQueryWrapper<Category> wrapper = new LambdaQueryWrapper<>();
        wrapper.in(Category::getId, categoryIds);
        List<Category> categories = categoryMapper.selectList(wrapper);

        Map<String, String> map = new HashMap<>();
        for (Category c : categories) {
            map.put(c.getId(), c.getName());
        }
        return map;
    }

    /**
     * 获取商品颜色数量
     */
    private int getColorCount(String productId) {
        Long count = productColorMapper.selectCount(
                new LambdaQueryWrapper<ProductColor>()
                        .eq(ProductColor::getProductId, productId)
        );
        return count != null ? count.intValue() : 0;
    }

    /**
     * 获取SKU总库存
     */
    private int getTotalStock(String productId) {
        List<ProductSku> skus = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>()
                        .eq(ProductSku::getProductId, productId)
                        .select(ProductSku::getStock)
        );
        return skus.stream().mapToInt(s -> s.getStock() != null ? s.getStock() : 0).sum();
    }

    /**
     * 获取当前登录用户名
     */
    private String getCurrentUsername() {
        try {
            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            if (auth != null && auth.getName() != null) {
                return auth.getName();
            }
        } catch (Exception e) {
            // ignore
        }
        return "system";
    }

    /**
     * 转换为响应 DTO
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

        // 详情图列表（BeanUtils 拷贝同名同类型字段后仍显式设置以提高可读性）
        if (product.getDetailImages() != null) {
            response.setDetailImages(product.getDetailImages());
        }

        return response;
    }
}
