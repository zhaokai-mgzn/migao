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
        STATUS_TRANSITIONS.put("draft", List.of("under_review", "on_sale"));
        STATUS_TRANSITIONS.put("under_review", List.of("on_sale", "draft"));
        STATUS_TRANSITIONS.put("on_sale", List.of("off_sale"));
        STATUS_TRANSITIONS.put("off_sale", List.of("on_sale", "under_review"));
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

        // 低库存筛选（#1291→#1396: 使用 SKU 级 EXISTS 子查询，口径统一 — 仅 on_sale 商品）
        if (query.getStockBelow() != null) {
            // 未显式指定 status 时，自动过滤 on_sale（排除已下架/已关闭商品）
            if (!StringUtils.hasText(query.getStatus())) {
                wrapper.eq(Product::getStatus, "on_sale");
            }
            wrapper.apply("EXISTS (SELECT 1 FROM product_skus ps WHERE ps.product_id = products.id AND ps.stock >= 0 AND ps.stock <= {0})", query.getStockBelow());
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
                case "stock" -> {
                    // #1201: products.stock 常为 0（默认值），与前端展示值（SKU 汇总 sum）不同源。
                    // ORDER BY products.stock 无实际排序效果 → 改用 SKU 汇总子查询排序。
                    String direction = isAsc ? "ASC" : "DESC";
                    wrapper.last(" ORDER BY (SELECT COALESCE(SUM(ps.stock), 0) FROM product_skus ps WHERE ps.product_id = products.id) " + direction);
                }
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
                    // 附加颜色数和总库存（总库存以 SKU 汇总为准，覆盖 product.stock 可能为 0 的情况）
                    response.setColorCount(getColorCount(product.getId()));
                    int totalStock = getTotalStock(product.getId());
                    response.setTotalStock(totalStock);
                    response.setStock(totalStock);
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
        int totalStock = getTotalStock(id);
        response.setTotalStock(totalStock);
        response.setStock(totalStock);

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
                // 新数据直接取 SKU 的 colorName，旧数据从 product_colors 回退
                skuResp.setColorName(
                    StringUtils.hasText(sku.getColorName())
                        ? sku.getColorName()
                        : colorNameMap.get(sku.getColorId())
                );
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

        // 保存销售信息（颜色 + SKU），支持笛卡尔积自动生成
        saveColorsAndSkus(product.getId(), product.getSkuCode(), tenantId,
                request.getColors(),
                request.getSellingMethods(), request.getDoorWidths(),
                product.getBasePrice(), product.getStock(),
                request.getSkus());

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

        // 更新销售信息（先删后插），支持笛卡尔积自动生成
        if (request.getColors() != null || request.getSkus() != null
                || request.getSellingMethods() != null || request.getDoorWidths() != null) {
            // 删除旧颜色和旧 SKU
            productSkuMapper.delete(new LambdaQueryWrapper<ProductSku>()
                    .eq(ProductSku::getProductId, id));
            productColorMapper.delete(new LambdaQueryWrapper<ProductColor>()
                    .eq(ProductColor::getProductId, id));
            // 重新保存（price/stock 优先取请求值，否则用商品当前值）
            BigDecimal skuPrice = request.getBasePrice() != null ? request.getBasePrice() : product.getBasePrice();
            Integer skuStock = request.getStock() != null ? request.getStock() : product.getStock();
            saveColorsAndSkus(id, product.getSkuCode(), tenantId,
                    request.getColors(),
                    request.getSellingMethods(), request.getDoorWidths(),
                    skuPrice, skuStock,
                    request.getSkus());
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
    private void saveColorsAndSkus(String productId, String productSkuCode, Long tenantId,
                                    List<ProductColorInput> colorInputs,
                                    List<String> sellingMethods,
                                    List<String> doorWidths,
                                    BigDecimal basePrice,
                                    Integer stock,
                                    List<ProductSkuInput> skuInputs) {
        // 提取颜色名列表（优先用 colorName，即色号如 "2699-01"）
        List<String> colorNames = new ArrayList<>();
        if (colorInputs != null) {
            for (ProductColorInput input : colorInputs) {
                if (input == null) continue;
                colorNames.add(StringUtils.hasText(input.getColorName()) ? input.getColorName() : "");
            }
        }

        // 保存颜色到 product_colors（兼容前端旧逻辑）
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

        // 构建颜色 → 序号映射（用于 SKU 编码生成）
        Map<String, Integer> colorSeqMap = new LinkedHashMap<>();
        int seq = 1;
        for (String cn : colorNames) {
            if (StringUtils.hasText(cn)) {
                colorSeqMap.putIfAbsent(cn, seq++);
            }
        }

        // 笛卡尔积自动生成 SKU：colors × sellingMethods × doorWidths
        if ((skuInputs == null || skuInputs.isEmpty())
                && !colorNames.isEmpty()
                && sellingMethods != null && !sellingMethods.isEmpty()
                && doorWidths != null && !doorWidths.isEmpty()) {
            skuInputs = new ArrayList<>();
            for (String colorName : colorNames) {
                for (String sm : sellingMethods) {
                    for (String dw : doorWidths) {
                        ProductSkuInput sku = new ProductSkuInput();
                        sku.setColorName(colorName);
                        sku.setSellingMethod(sm);
                        sku.setDoorWidth(dw);
                        sku.setPrice(basePrice);
                        sku.setStock(stock != null && stock > 0 ? stock : 100);
                        // 自动生成 SKU 编码
                        Integer colorSeq = colorSeqMap.get(colorName);
                        sku.setSkuCode(generateSkuCode(productId, productSkuCode,
                                colorSeq != null ? colorSeq : 0, sm, dw));
                        skuInputs.add(sku);
                    }
                }
            }
        }

        if (skuInputs != null) {
            for (ProductSkuInput input : skuInputs) {
                if (input == null) continue;
                if (!StringUtils.hasText(input.getSellingMethod())
                        || !StringUtils.hasText(input.getDoorWidth())) {
                    continue;
                }
                // 解析 colorId（兼容前端旧逻辑，新数据走 colorName）
                Long mappedColorId = null;
                if (input.getColorId() != null) {
                    mappedColorId = colorIdMap.getOrDefault(input.getColorId(), input.getColorId());
                    if (mappedColorId != null && mappedColorId <= 0) {
                        mappedColorId = null;
                    }
                }
                ProductSku entity = new ProductSku();
                entity.setTenantId(tenantId);
                entity.setProductId(productId);
                entity.setColorId(mappedColorId);
                entity.setColorName(input.getColorName());
                entity.setSellingMethod(input.getSellingMethod());
                entity.setDoorWidth(input.getDoorWidth());
                entity.setPrice(input.getPrice() != null ? input.getPrice() : BigDecimal.ZERO);
                entity.setStock(input.getStock() != null ? input.getStock() : 0);
                // 优先使用传入的 skuCode，未传入则自动生成
                String skuCode = StringUtils.hasText(input.getSkuCode())
                        ? input.getSkuCode()
                        : generateSkuCode(productId, productSkuCode,
                                colorSeqMap.getOrDefault(input.getColorName(), 0),
                                input.getSellingMethod(), input.getDoorWidth());
                entity.setSkuCode(skuCode);
                entity.setSalesCount(0);
                productSkuMapper.insert(entity);
            }
        }
    }

    /**
     * 生成 SKU 编码
     * 格式: {货号}-{颜色序号2位}-{售卖方式缩写}-{门幅缩写}
     * 示例: 50181A94-01-SJ-28（有货号优先用货号），984D744B-01-SJ-28（无货号兜底用ID前缀）
     */
    private String generateSkuCode(String productId, String productSkuCode, int colorSeq,
                                   String sellingMethod, String doorWidth) {
        String prefix;
        if (StringUtils.hasText(productSkuCode)) {
            prefix = productSkuCode.toUpperCase();
        } else {
            prefix = productId.length() >= 8 ? productId.substring(0, 8).toUpperCase() : productId.toUpperCase();
        }
        return String.format("%s-%02d-%s-%s", prefix, colorSeq, toMethodAbbr(sellingMethod), toWidthShort(doorWidth));
    }

    /** 售卖方式 → 缩写: bulk_cut→SJ(散剪), full_roll→ZJ(整卷) */
    private String toMethodAbbr(String sellingMethod) {
        if (sellingMethod == null) return "XX";
        return switch (sellingMethod) {
            case "bulk_cut" -> "SJ";
            case "full_roll" -> "ZJ";
            default -> sellingMethod.length() > 3 ? sellingMethod.substring(0, 3).toUpperCase() : sellingMethod.toUpperCase();
        };
    }

    /** 门幅 → 数字缩写: "2.8米"→"28", "3.2米"→"32" */
    private String toWidthShort(String doorWidth) {
        if (doorWidth == null) return "XX";
        // 提取数字部分（含小数点），拼接成简短代码
        String digits = doorWidth.replaceAll("[^0-9.]", "");
        // 去掉小数点: "2.8"→"28", "3.2"→"32", "3.4"→"34"
        return digits.replace(".", "");
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
        Set<String> allowedStatuses = Set.of("off_sale");

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
            product.setStatus("off_sale");
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
        // 校验商品存在且属于当前租户（租户隔离）
        Product product = productMapper.selectOne(
                new LambdaQueryWrapper<Product>()
                        .eq(Product::getId, productId)
                        .eq(Product::getTenantId, tenantId));
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
        } catch (NumberFormatException | IndexOutOfBoundsException e) {
            log.warn("库存解析失败，默认0: {}", e.getMessage());
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

    /**
     * 按颜色+规格维度查询低库存 SKU（用于库存告警）
     *
     * @param threshold 库存阈值，SKU 库存低于此值视为低库存
     * @param limit     最大返回条数
     * @return 低库存 SKU 列表
     */
    public List<LowStockByColorResponse> getLowStockByColor(int threshold, int limit) {
        return productMapper.findLowStockByColor(threshold, limit);
    }

    // ======================== Agent BFF 方法 ========================

    /**
     * Agent 专用创建商品。
     * 自动填充默认值、解析分类/加工项 ID（支持名称/UUID/序号）。
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductResponse createProductForAgent(com.migao.admin.dto.agent.AgentProductCreateRequest request,
                                                  Long tenantId) {
        ProductCreateRequest createReq = new ProductCreateRequest();

        // name: 手动校验
        if (!StringUtils.hasText(request.getName())) {
            throw BusinessException.validationError("商品名称不能为空");
        }
        createReq.setName(request.getName());

        // categoryId: 解析（名称/UUID/前缀 → UUID）
        if (StringUtils.hasText(request.getCategoryId())) {
            String resolved = resolveCategoryId(request.getCategoryId(), tenantId);
            if (resolved == null) {
                throw new BusinessException("CATEGORY_NOT_FOUND",
                        "无法找到匹配的分类：" + request.getCategoryId(),
                        422);
            }
            createReq.setCategoryId(resolved);
        }

        // 价格/库存/描述/品牌 直接透传
        createReq.setBasePrice(request.getBasePrice());
        createReq.setStock(request.getStock() != null ? request.getStock() : 0);
        createReq.setDescription(request.getDescription());
        createReq.setBrand(request.getBrand());

        // 货号: 空则自动生成
        if (StringUtils.hasText(request.getSkuCode())) {
            createReq.setSkuCode(request.getSkuCode());
        }
        // 不设 skuCode — createProduct 会在 saveColorsAndSkus 中自动生成

        // unit / pricingType: 智能默认
        createReq.setUnit(StringUtils.hasText(request.getUnit()) ? request.getUnit() : "米");
        createReq.setPricingType(StringUtils.hasText(request.getPricingType())
                ? request.getPricingType() : "per_meter");

        // status: 默认 draft
        createReq.setStatus(StringUtils.hasText(request.getStatus()) ? request.getStatus() : "draft");
        // 图片
        if (request.getImages() != null) createReq.setImages(request.getImages());
        if (request.getDetailImages() != null) createReq.setDetailImages(request.getDetailImages());

        // 颜色: 字符串 → ProductColorInput
        if (request.getColors() != null && !request.getColors().isEmpty()) {
            List<ProductColorInput> colorInputs = request.getColors().stream()
                    .map(c -> {
                        ProductColorInput ci = new ProductColorInput();
                        ci.setColorName(c);
                        return ci;
                    })
                    .collect(Collectors.toList());
            createReq.setColors(colorInputs);
        }

        // 售卖方式: "散剪"/"整卷" → bulk_cut/full_roll
        if (request.getSellingMethods() != null) {
            createReq.setSellingMethods(request.getSellingMethods().stream()
                    .map(this::translateSellingMethod)
                    .collect(Collectors.toList()));
        }

        // 门幅 直接透传
        if (request.getDoorWidths() != null) createReq.setDoorWidths(request.getDoorWidths());

        // 规格
        if (request.getSpecifications() != null) createReq.setSpecifications(request.getSpecifications());

        // 加工项: 解析 ID → ProcessingItemConfigInput
        if (request.getProcessingItemIds() != null && !request.getProcessingItemIds().isEmpty()) {
            List<String> resolved = resolveProcessingItemIds(request.getProcessingItemIds(), tenantId);
            if (!resolved.isEmpty()) {
                createReq.setProcessingItemConfigs(resolved.stream()
                        .map(id -> {
                            ProcessingItemConfigInput cfg = new ProcessingItemConfigInput();
                            cfg.setProcessingItemId(id);
                            return cfg;
                        })
                        .collect(Collectors.toList()));
            }
        } else if (request.getProcessingItemConfigs() != null) {
            // 带自定义价格的加工项配置
            List<ProcessingItemConfigInput> configs = new ArrayList<>();
            for (var cfg : request.getProcessingItemConfigs()) {
                if (!StringUtils.hasText(cfg.getProcessingItemId())) continue;
                String resolved = resolveProcessingItemId(cfg.getProcessingItemId(), tenantId);
                if (resolved != null) {
                    ProcessingItemConfigInput input = new ProcessingItemConfigInput();
                    input.setProcessingItemId(resolved);
                    input.setCustomPrice(cfg.getCustomPrice());
                    configs.add(input);
                }
            }
            if (!configs.isEmpty()) createReq.setProcessingItemConfigs(configs);
        }

        return createProduct(createReq, tenantId);
    }

    /**
     * Agent 专用部分更新商品。
     * null 字段 = 不修改。数组字段 (colors/sellingMethods/doorWidths) 传了才触发 SKU 重建。
     */
    @Transactional(rollbackFor = Exception.class)
    public ProductResponse updateProductForAgent(String id,
                                                   com.migao.admin.dto.agent.AgentProductUpdateRequest request,
                                                   Long tenantId) {
        Product product = productMapper.selectOne(
                new LambdaQueryWrapper<Product>()
                        .eq(Product::getId, id)
                        .eq(Product::getTenantId, tenantId));
        if (product == null) {
            throw BusinessException.notFound("商品");
        }

        ProductUpdateRequest updateReq = new ProductUpdateRequest();
        boolean hasUpdate = false;

        // name: null = 不修改，传了就更新
        if (request.getName() != null) {
            updateReq.setName(request.getName());
            hasUpdate = true;
        } else {
            updateReq.setName(product.getName()); // 保持原名（满足 @NotBlank）
        }

        // categoryId: 解析后更新
        if (request.getCategoryId() != null) {
            String resolved = resolveCategoryId(request.getCategoryId(), tenantId);
            if (resolved == null) {
                throw new BusinessException("CATEGORY_NOT_FOUND",
                        "无法找到匹配的分类：" + request.getCategoryId(), 422);
            }
            updateReq.setCategoryId(resolved);
            hasUpdate = true;
        }

        if (request.getBasePrice() != null) { updateReq.setBasePrice(request.getBasePrice()); hasUpdate = true; }
        if (request.getSkuCode() != null) { updateReq.setSkuCode(request.getSkuCode()); hasUpdate = true; }
        if (request.getDescription() != null) { updateReq.setDescription(request.getDescription()); hasUpdate = true; }
        if (request.getBrand() != null) { updateReq.setBrand(request.getBrand()); hasUpdate = true; }
        if (request.getUnit() != null) { updateReq.setUnit(request.getUnit()); hasUpdate = true; }
        if (request.getPricingType() != null) { updateReq.setPricingType(request.getPricingType()); hasUpdate = true; }
        if (request.getStock() != null) { updateReq.setStock(request.getStock()); hasUpdate = true; }
        if (request.getImages() != null) { updateReq.setImages(request.getImages()); hasUpdate = true; }
        if (request.getDetailImages() != null) { updateReq.setDetailImages(request.getDetailImages()); hasUpdate = true; }
        if (request.getSpecifications() != null) { updateReq.setSpecifications(request.getSpecifications()); hasUpdate = true; }
        if (request.getStockDeductionMode() != null) { /* 不支持通过 update 修改，忽略 */ }

        // 颜色/售卖方式/门幅: 传了才处理（会触发 SKU 重建）
        if (request.getColors() != null) {
            updateReq.setColors(request.getColors().stream().map(c -> {
                ProductColorInput ci = new ProductColorInput();
                ci.setColorName(c);
                return ci;
            }).collect(Collectors.toList()));
            hasUpdate = true;
        }
        if (request.getSellingMethods() != null) {
            updateReq.setSellingMethods(request.getSellingMethods().stream()
                    .map(this::translateSellingMethod).collect(Collectors.toList()));
            hasUpdate = true;
        }
        if (request.getDoorWidths() != null) { updateReq.setDoorWidths(request.getDoorWidths()); hasUpdate = true; }

        // 不传 processingItemConfigs，保留现有关联
        updateReq.setProcessingItemConfigs(null);

        if (!hasUpdate) {
            return getProductById(id, tenantId);
        }

        return updateProduct(id, updateReq, tenantId);
    }

    /**
     * Agent 专用加工项增删。
     * add: 仅插入不存在的；remove: 仅删除存在的（幂等）。
     */
    @Transactional(rollbackFor = Exception.class)
    public java.util.List<ProductProcessingItemResponse> updateProductProcessingItems(
            String productId, com.migao.admin.dto.agent.AgentProcessingItemActionRequest request, Long tenantId) {

        Product product = productMapper.selectOne(
                new LambdaQueryWrapper<Product>()
                        .eq(Product::getId, productId)
                        .eq(Product::getTenantId, tenantId));
        if (product == null) {
            throw BusinessException.notFound("商品");
        }

        String action = request.getAction();
        if (!"add".equals(action) && !"remove".equals(action)) {
            throw BusinessException.validationError("action 必须为 add 或 remove");
        }

        List<String> resolvedIds = resolveProcessingItemIds(request.getItemIds(), tenantId);
        List<String> warnings = new ArrayList<>();

        if ("add".equals(action)) {
            // 查询已有加工项，去重
            List<ProductProcessingItem> existing = productProcessingItemMapper.selectList(
                    new LambdaQueryWrapper<ProductProcessingItem>()
                            .eq(ProductProcessingItem::getProductId, productId)
                            .eq(ProductProcessingItem::getTenantId, tenantId));
            java.util.Set<String> existingIds = existing.stream()
                    .map(ProductProcessingItem::getProcessingItemId)
                    .collect(Collectors.toSet());

            int sortOrder = existing.size();
            for (String resolvedId : resolvedIds) {
                if (existingIds.contains(resolvedId)) {
                    // 通过加工项名称生成更友好的警告
                    ProcessingItem item = processingItemMapper.selectById(resolvedId);
                    String name = item != null ? item.getName() : resolvedId;
                    warnings.add("加工项'" + name + "'已存在，已跳过");
                    continue;
                }
                ProductProcessingItem entity = new ProductProcessingItem();
                entity.setTenantId(tenantId);
                entity.setProductId(productId);
                entity.setProcessingItemId(resolvedId);
                entity.setSortOrder(sortOrder++);
                productProcessingItemMapper.insert(entity);
            }
        } else {
            // remove
            for (String resolvedId : resolvedIds) {
                int deleted = productProcessingItemMapper.delete(
                        new LambdaQueryWrapper<ProductProcessingItem>()
                                .eq(ProductProcessingItem::getProductId, productId)
                                .eq(ProductProcessingItem::getProcessingItemId, resolvedId)
                                .eq(ProductProcessingItem::getTenantId, tenantId));
                if (deleted == 0) {
                    warnings.add("加工项'" + resolvedId + "'不存在或已删除，已跳过");
                }
            }
        }

        log.info("Agent 加工项 {} 完成: productId={}, action={}, count={}, warnings={}",
                action, productId, resolvedIds.size(), warnings.size());

        return getProductProcessingItems(productId, tenantId);
    }

    // ======================== ID 解析辅助方法 ========================

    /**
     * 解析商品 ID：支持 UUID / 商品名称 / UUID 前缀 / 序号（1-based）。
     * 匹配优先级：UUID 完整匹配 → UUID 前缀 → 名称精确匹配 → 序号 → 名称模糊匹配。
     *
     * @return 真实 UUID，未找到返回 null
     */
    String resolveProductId(String raw, Long tenantId) {
        if (!StringUtils.hasText(raw)) return null;
        String s = raw.trim();

        java.util.List<Product> all = productMapper.selectList(
                new LambdaQueryWrapper<Product>()
                        .eq(Product::getTenantId, tenantId)
                        .orderByAsc(Product::getCreatedAt));

        // 1. 精确 UUID
        for (Product p : all) {
            if (s.equals(p.getId())) return p.getId();
        }

        // 2. UUID 前缀（LLM 可能截断 UUID）
        if (s.length() >= 8) {
            for (Product p : all) {
                if (p.getId() != null && p.getId().startsWith(s.substring(0, Math.min(16, s.length())))) {
                    return p.getId();
                }
            }
        }

        // 3. 精确名称
        for (Product p : all) {
            if (s.equals(p.getName())) return p.getId();
        }

        // 4. 序号（1-based，按创建时间排序）
        if (s.matches("\\d+")) {
            int idx = Integer.parseInt(s) - 1;
            if (idx >= 0 && idx < all.size())
                return all.get(idx).getId();
        }

        // 5. 名称模糊匹配（包含关键字）
        for (Product p : all) {
            if (p.getName() != null && p.getName().contains(s)) return p.getId();
        }

        return null;
    }

    /**
     * 解析分类 ID：支持 UUID / 名称 / UUID 前缀。
     *
     * @return 真实 UUID，未找到返回 null
     */
    String resolveCategoryId(String raw, Long tenantId) {
        if (!StringUtils.hasText(raw)) return null;

        java.util.List<Category> cats = categoryMapper.selectList(
                new LambdaQueryWrapper<Category>().eq(Category::getTenantId, tenantId));

        // 1. 精确 UUID 匹配
        for (Category c : cats) {
            if (raw.equals(c.getId())) return c.getId();
        }

        // 2. 名称匹配
        for (Category c : cats) {
            if (raw.equals(c.getName())) return c.getId();
        }

        // 3. UUID 前缀匹配（LLM 可能截断 UUID）
        if (raw.length() >= 8) {
            for (Category c : cats) {
                if (c.getId() != null
                        && c.getId().startsWith(raw.substring(0, Math.min(16, raw.length())))) {
                    return c.getId();
                }
            }
        }

        return null;
    }

    /**
     * 解析单个加工项 ID：支持 UUID / 名称 / 序号 / UUID 前缀。
     */
    String resolveProcessingItemId(String raw, Long tenantId) {
        List<String> resolved = resolveProcessingItemIds(java.util.Collections.singletonList(raw), tenantId);
        return resolved.isEmpty() ? null : resolved.get(0);
    }

    /**
     * 批量解析加工项 ID：支持 UUID / 名称 / 序号（1-based）/ UUID 前缀。
     */
    List<String> resolveProcessingItemIds(List<String> rawIds, Long tenantId) {
        if (rawIds == null || rawIds.isEmpty()) return java.util.Collections.emptyList();

        java.util.List<ProcessingItem> allItems = processingItemMapper.selectList(
                new LambdaQueryWrapper<ProcessingItem>()
                        .eq(ProcessingItem::getTenantId, tenantId)
                        .eq(ProcessingItem::getStatus, "active")
                        .orderByAsc(ProcessingItem::getCreatedAt));

        List<String> resolved = new ArrayList<>();
        for (String raw : rawIds) {
            if (!StringUtils.hasText(raw)) continue;
            String s = raw.trim();

            // 兼容 "pi_xxx|加工项名" 格式
            if (s.contains("|")) s = s.substring(0, s.indexOf("|")).trim();

            String found = null;

            // 1. 纯数字 → 按列表位置匹配（1-based 序号）
            if (s.matches("\\d+")) {
                int idx = Integer.parseInt(s) - 1;
                if (idx >= 0 && idx < allItems.size()) {
                    found = allItems.get(idx).getId();
                }
            }

            // 2. 精确 UUID / 名称 / 前缀 匹配
            if (found == null) {
                for (ProcessingItem item : allItems) {
                    if (s.equals(item.getId()) || s.equals(item.getName())) {
                        found = item.getId();
                        break;
                    }
                }
            }

            // 3. UUID 前缀匹配
            if (found == null && s.length() >= 8) {
                String prefix = s.substring(0, Math.min(16, s.length()));
                for (ProcessingItem item : allItems) {
                    if (item.getId() != null && item.getId().startsWith(prefix)) {
                        found = item.getId();
                        break;
                    }
                }
            }

            if (found != null) {
                resolved.add(found);
            } else {
                log.warn("[Agent] 无法解析加工项ID: {}", raw);
            }
        }

        return resolved;
    }

    /**
     * 售卖方式中文 → 英文
     */
    private String translateSellingMethod(String raw) {
        if (raw == null) return null;
        return switch (raw.trim()) {
            case "散剪" -> "bulk_cut";
            case "整卷" -> "full_roll";
            case "按片" -> "per_piece";
            case "定高" -> "fixed_height";
            case "买通" -> "buy_through";
            default -> raw; // 已经是英文则直接透传
        };
    }

    /**
     * 统计待补库存 SKU 数（排除已删除 + 已下架商品下的 SKU）
     * #1396: 口径统一 — 三个入口（Dashboard 卡片、low-stock-by-color API、商品列表 stockBelow）
     *         使用相同的过滤条件：p.deleted=0 AND p.status='on_sale'
     *
     * @param tenantId  租户 ID
     * @param threshold 库存阈值（SKU stock ≤ threshold 视为低库存）
     * @return 低库存 SKU 总数
     */
    public long getLowStockSkuCount(Long tenantId, int threshold) {
        return productMapper.countLowStockSkus(tenantId, threshold);
    }
}
