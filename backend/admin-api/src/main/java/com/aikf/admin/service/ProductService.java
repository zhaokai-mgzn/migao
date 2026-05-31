package com.aikf.admin.service;

import com.aikf.admin.dto.*;
import com.aikf.admin.entity.Category;
import com.aikf.admin.entity.ProcessingItem;
import com.aikf.admin.entity.Product;
import com.aikf.admin.entity.ProductColor;
import com.aikf.admin.entity.ProductProcessingItem;
import com.aikf.admin.entity.ProductSku;
import com.aikf.admin.exception.BusinessException;
import com.aikf.admin.mapper.CategoryMapper;
import com.aikf.admin.mapper.ProcessingItemMapper;
import com.aikf.admin.mapper.ProductColorMapper;
import com.aikf.admin.mapper.ProductMapper;
import com.aikf.admin.mapper.ProductProcessingItemMapper;
import com.aikf.admin.mapper.ProductSkuMapper;
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
import java.util.HashMap;
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

        // 查询关联 SKU 列表
        List<ProductSku> skuEntities = productSkuMapper.selectList(
                new LambdaQueryWrapper<ProductSku>()
                        .eq(ProductSku::getProductId, id)
                        .orderByAsc(ProductSku::getColorId)
                        .orderByAsc(ProductSku::getDoorWidth)
        );
        if (skuEntities != null && !skuEntities.isEmpty()) {
            // 批量获取颜色名称
            List<Long> colorIds = skuEntities.stream()
                    .map(ProductSku::getColorId)
                    .filter(cid -> cid != null)
                    .distinct()
                    .collect(Collectors.toList());
            Map<Long, String> colorNameMap = new HashMap<>();
            if (!colorIds.isEmpty()) {
                List<ProductColor> colors = productColorMapper.selectList(
                        new LambdaQueryWrapper<ProductColor>()
                                .in(ProductColor::getId, colorIds)
                );
                colors.forEach(c -> colorNameMap.put(c.getId(), c.getColorName()));
            }

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
        }

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

        // 设置默认状态
        if (!StringUtils.hasText(product.getStatus())) {
            product.setStatus("draft");
        }

        // 设置编辑信息
        product.setEditedBy(getCurrentUsername());
        product.setEditedAt(OffsetDateTime.now());

        // 保存商品
        productMapper.insert(product);
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

        // 更新商品属性
        BeanUtils.copyProperties(request, product);
        product.setId(id);

        // 处理图片列表
        if (request.getImages() != null) {
            product.setImages(request.getImages());
        }

        // 更新编辑信息
        product.setEditedBy(getCurrentUsername());
        product.setEditedAt(OffsetDateTime.now());

        productMapper.updateById(product);
        log.info("更新商品成功: id={}, name={}", id, product.getName());

        return getProductById(id, tenantId);
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

        return response;
    }
}
