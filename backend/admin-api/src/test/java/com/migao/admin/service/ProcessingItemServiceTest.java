package com.migao.admin.service;

// case_ids: PP-005, PP-006, OR-014
// PP-005：加工项按「适用商品分类」筛选（issue #2964）。
// PP-006/OR-014（issue #3005，回滚 #2986）：行业加工费按米计价且辅料含在加工费中，
// 加工项计价方式仅 per_meter/per_set/fixed/per_area——per_piece 与「每米数量」密度被移除，
// calculatePrice 不再有 fabricMeters 密度推导，数量由请求方直接给出。

import com.migao.admin.dto.*;
import com.migao.admin.entity.ProcessingCategory;
import com.migao.admin.entity.ProcessingItem;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProcessingCategoryMapper;
import com.migao.admin.mapper.ProcessingItemMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * ProcessingItemService 单元测试
 */
@ExtendWith(MockitoExtension.class)
class ProcessingItemServiceTest {

    @InjectMocks
    private ProcessingItemService processingItemService;

    @Mock
    private ProcessingItemMapper processingItemMapper;

    @Mock
    private ProcessingCategoryMapper processingCategoryMapper;

    private ProcessingItem testItem;
    private ProcessingCategory testCategory;

    @BeforeEach
    void setUp() {
        // 初始化 MyBatis-Plus 实体 lambda 缓存，使 LambdaQueryWrapper 的
        // ProcessingItem::getXxx 等方法引用可解析（纯 Mockito 环境无 Spring 容器兜底）
        com.baomidou.mybatisplus.core.MybatisConfiguration conf =
                new com.baomidou.mybatisplus.core.MybatisConfiguration();
        org.apache.ibatis.builder.MapperBuilderAssistant assistant =
                new org.apache.ibatis.builder.MapperBuilderAssistant(conf, "");
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant, ProcessingItem.class);
        com.baomidou.mybatisplus.core.metadata.TableInfoHelper.initTableInfo(assistant, ProcessingCategory.class);

        testCategory = ProcessingCategory.builder()
                .id("pcat-001")
                .tenantId(1L)
                .name("窗帘加工")
                .sortOrder(1)
                .status("active")
                .build();

        testItem = ProcessingItem.builder()
                .id("pi-001")
                .tenantId(1L)
                .name("打孔加工")
                .categoryId("pcat-001")
                .pricingMethod("per_meter")
                .unitPrice(new BigDecimal("15.00"))
                .unit("元/米")
                .minQuantity(1)
                .maxQuantity(100)
                .processingDays(3)
                .status("active")
                .build();
    }

    // ======================== 分页查询测试 ========================

    @Test
    @DisplayName("分页查询加工项 - 默认分页")
    void getProcessingItems_DefaultPagination() {
        // given
        ProcessingItemQueryRequest query = new ProcessingItemQueryRequest();

        Page<ProcessingItem> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testItem));
        mockPage.setTotal(1);

        when(processingItemMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);
        when(processingCategoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(testCategory));

        // when
        PageResponse<ProcessingItemResponse> result = processingItemService.getProcessingItems(query, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getTotal()).isEqualTo(1);
        assertThat(result.getItems()).hasSize(1);
        assertThat(result.getItems().get(0).getName()).isEqualTo("打孔加工");
        assertThat(result.getItems().get(0).getCategoryName()).isEqualTo("窗帘加工");
    }

    @Test
    @DisplayName("分页查询加工项 - 带筛选条件")
    void getProcessingItems_WithFilters() {
        // given
        ProcessingItemQueryRequest query = new ProcessingItemQueryRequest();
        query.setKeyword("打孔");
        query.setCategoryId("pcat-001");
        query.setStatus("active");

        Page<ProcessingItem> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testItem));
        mockPage.setTotal(1);

        when(processingItemMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);
        when(processingCategoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(testCategory));

        // when
        PageResponse<ProcessingItemResponse> result = processingItemService.getProcessingItems(query, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getItems()).hasSize(1);
    }

    @Test
    @DisplayName("分页查询加工项 - 空结果")
    void getProcessingItems_EmptyResult() {
        // given
        ProcessingItemQueryRequest query = new ProcessingItemQueryRequest();

        Page<ProcessingItem> emptyPage = new Page<>(1, 20);
        emptyPage.setRecords(List.of());
        emptyPage.setTotal(0);

        when(processingItemMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(emptyPage);

        // when
        PageResponse<ProcessingItemResponse> result = processingItemService.getProcessingItems(query, 1L);

        // then
        assertThat(result.getTotal()).isEqualTo(0);
        assertThat(result.getItems()).isEmpty();
    }

    @Test
    @DisplayName("分页查询加工项 - 按适用商品分类筛选（空列表=适用所有，JSONB 包含目标分类）")
    void getProcessingItems_FilterByApplicableProductCategory() {
        // given
        ProcessingItemQueryRequest query = new ProcessingItemQueryRequest();
        query.setApplicableProductCategoryId("cat-curtain");

        Page<ProcessingItem> mockPage = new Page<>(1, 20);
        mockPage.setRecords(List.of(testItem));
        mockPage.setTotal(1);

        when(processingItemMapper.selectPage(any(Page.class), any(LambdaQueryWrapper.class)))
                .thenReturn(mockPage);
        when(processingCategoryMapper.selectList(any(LambdaQueryWrapper.class)))
                .thenReturn(List.of(testCategory));

        // when
        PageResponse<ProcessingItemResponse> result = processingItemService.getProcessingItems(query, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getItems()).hasSize(1);

        // 筛选 SQL 必须同时包含：空列表（=适用所有）+ JSONB 包含目标分类（目标分类 ID 走参数化占位，值在 paramNameValuePairs）
        ArgumentCaptor<LambdaQueryWrapper<ProcessingItem>> wrapperCaptor =
                ArgumentCaptor.forClass(LambdaQueryWrapper.class);
        verify(processingItemMapper).selectPage(any(Page.class), wrapperCaptor.capture());
        String sql = wrapperCaptor.getValue().getCustomSqlSegment();
        assertThat(sql).contains("applicable_product_categories");
        assertThat(sql).contains("'[]'");
        assertThat(wrapperCaptor.getValue().getParamNameValuePairs().values())
                .anyMatch(v -> v.toString().contains("cat-curtain"));
    }

    // ======================== 创建加工项测试 ========================

    @Test
    @DisplayName("创建加工项成功")
    void createProcessingItem_Success() {
        // given
        ProcessingItemCreateRequest request = new ProcessingItemCreateRequest();
        request.setName("新加工项");
        request.setCategoryId("pcat-001");
        request.setPricingMethod("per_meter");
        request.setUnitPrice(new BigDecimal("20.00"));

        when(processingCategoryMapper.selectById("pcat-001")).thenReturn(testCategory);
        when(processingItemMapper.insert(any(ProcessingItem.class))).thenAnswer(invocation -> {
            ProcessingItem item = invocation.getArgument(0);
            item.setId("pi-new");
            return 1;
        });
        // getProcessingItemById 内部调用
        ProcessingItem savedItem = ProcessingItem.builder()
                .id("pi-new")
                .name("新加工项")
                .categoryId("pcat-001")
                .pricingMethod("per_meter")
                .unitPrice(new BigDecimal("20.00"))
                .status("active")
                .build();
        when(processingItemMapper.selectById("pi-new")).thenReturn(savedItem);
        when(processingCategoryMapper.selectById("pcat-001")).thenReturn(testCategory);

        // when
        ProcessingItemResponse result = processingItemService.createProcessingItem(request, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getName()).isEqualTo("新加工项");
        verify(processingItemMapper).insert(any(ProcessingItem.class));
    }

    @Test
    @DisplayName("创建加工项成功 - 带适用商品分类")
    void createProcessingItem_WithApplicableProductCategories() {
        // given
        ProcessingItemCreateRequest request = new ProcessingItemCreateRequest();
        request.setName("打孔加工");
        request.setCategoryId("pcat-001");
        request.setPricingMethod("per_meter");
        request.setUnitPrice(new BigDecimal("15.00"));
        request.setApplicableProductCategories(List.of("cat-001", "cat-002"));

        when(processingCategoryMapper.selectById("pcat-001")).thenReturn(testCategory);
        when(processingItemMapper.insert(any(ProcessingItem.class))).thenAnswer(invocation -> {
            ProcessingItem item = invocation.getArgument(0);
            item.setId("pi-new");
            return 1;
        });

        ProcessingItem savedItem = ProcessingItem.builder()
                .id("pi-new")
                .name("打孔加工")
                .categoryId("pcat-001")
                .pricingMethod("per_meter")
                .unitPrice(new BigDecimal("15.00"))
                .applicableProductCategories(List.of("cat-001", "cat-002"))
                .status("active")
                .build();
        when(processingItemMapper.selectById("pi-new")).thenReturn(savedItem);

        // when
        ProcessingItemResponse result = processingItemService.createProcessingItem(request, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getApplicableProductCategories()).containsExactly("cat-001", "cat-002");
        verify(processingItemMapper).insert((ProcessingItem) argThat((ProcessingItem item) ->
                item.getApplicableProductCategories() != null
                        && item.getApplicableProductCategories().containsAll(List.of("cat-001", "cat-002"))));
    }

    @Test
    @DisplayName("创建加工项失败 - 分类不存在")
    void createProcessingItem_CategoryNotFound() {
        // given
        ProcessingItemCreateRequest request = new ProcessingItemCreateRequest();
        request.setName("新加工项");
        request.setCategoryId("nonexistent");
        request.setPricingMethod("per_meter");
        request.setUnitPrice(new BigDecimal("20.00"));

        when(processingCategoryMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> processingItemService.createProcessingItem(request, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessage("加工分类不存在");
    }

    @Test
    @DisplayName("创建加工项失败 - 无效计价方式")
    void createProcessingItem_InvalidPricingMethod() {
        // given
        ProcessingItemCreateRequest request = new ProcessingItemCreateRequest();
        request.setName("新加工项");
        request.setCategoryId("pcat-001");
        request.setPricingMethod("invalid_method");
        request.setUnitPrice(new BigDecimal("20.00"));

        when(processingCategoryMapper.selectById("pcat-001")).thenReturn(testCategory);

        // when & then
        assertThatThrownBy(() -> processingItemService.createProcessingItem(request, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("无效的计价方式");
    }

    // ======================== 更新加工项测试 ========================

    @Test
    @DisplayName("更新加工项成功")
    void updateProcessingItem_Success() {
        // given
        ProcessingItemUpdateRequest request = new ProcessingItemUpdateRequest();
        request.setName("更新后的加工项");
        request.setCategoryId("pcat-001");
        request.setPricingMethod("per_meter");
        request.setUnitPrice(new BigDecimal("25.00"));

        when(processingItemMapper.selectById("pi-001")).thenReturn(testItem);
        when(processingCategoryMapper.selectById("pcat-001")).thenReturn(testCategory);
        when(processingItemMapper.updateById(any(ProcessingItem.class))).thenReturn(1);

        // getProcessingItemById 内部调用
        ProcessingItem updatedItem = ProcessingItem.builder()
                .id("pi-001")
                .name("更新后的加工项")
                .categoryId("pcat-001")
                .pricingMethod("per_meter")
                .unitPrice(new BigDecimal("25.00"))
                .status("active")
                .build();
        when(processingItemMapper.selectById("pi-001")).thenReturn(testItem).thenReturn(updatedItem);

        // when
        ProcessingItemResponse result = processingItemService.updateProcessingItem("pi-001", request, 1L);

        // then
        assertThat(result).isNotNull();
        verify(processingItemMapper).updateById(any(ProcessingItem.class));
    }

    @Test
    @DisplayName("更新加工项成功 - 带适用商品分类")
    void updateProcessingItem_WithApplicableProductCategories() {
        // given
        ProcessingItemUpdateRequest request = new ProcessingItemUpdateRequest();
        request.setName("更新后的加工项");
        request.setCategoryId("pcat-001");
        request.setPricingMethod("per_meter");
        request.setUnitPrice(new BigDecimal("25.00"));
        request.setApplicableProductCategories(List.of("cat-003", "cat-004"));

        when(processingItemMapper.selectById("pi-001")).thenReturn(testItem);
        when(processingCategoryMapper.selectById("pcat-001")).thenReturn(testCategory);
        when(processingItemMapper.updateById(any(ProcessingItem.class))).thenReturn(1);

        ProcessingItem updatedItem = ProcessingItem.builder()
                .id("pi-001")
                .name("更新后的加工项")
                .categoryId("pcat-001")
                .pricingMethod("per_meter")
                .unitPrice(new BigDecimal("25.00"))
                .applicableProductCategories(List.of("cat-003", "cat-004"))
                .status("active")
                .build();
        when(processingItemMapper.selectById("pi-001")).thenReturn(testItem).thenReturn(updatedItem);

        // when
        ProcessingItemResponse result = processingItemService.updateProcessingItem("pi-001", request, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getApplicableProductCategories()).containsExactly("cat-003", "cat-004");
    }

    @Test
    @DisplayName("更新加工项失败 - 加工项不存在")
    void updateProcessingItem_NotFound() {
        // given
        ProcessingItemUpdateRequest request = new ProcessingItemUpdateRequest();
        request.setName("更新");
        request.setCategoryId("pcat-001");
        request.setPricingMethod("per_meter");

        when(processingItemMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> processingItemService.updateProcessingItem("nonexistent", request, 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    // ======================== 价格计算测试 ========================

    @Test
    @DisplayName("价格计算 - 按米计价")
    void calculatePrice_PerMeter() {
        // given
        PriceCalculateRequest request = new PriceCalculateRequest();
        request.setProcessingItemId("pi-001");
        request.setQuantity(new BigDecimal("5"));

        when(processingItemMapper.selectById("pi-001")).thenReturn(testItem);

        // when
        PriceCalculateResponse result = processingItemService.calculatePrice(request, 1L);

        // then
        assertThat(result).isNotNull();
        assertThat(result.getPricingMethod()).isEqualTo("per_meter");
        assertThat(result.getTotalPrice()).isEqualByComparingTo(new BigDecimal("75.00"));
        assertThat(result.getDetails()).hasSize(1);
        assertThat(result.getDetails().get(0).getDescription()).contains("按米计价");
    }

    @Test
    @DisplayName("价格计算 - 按套计价")
    void calculatePrice_PerSet() {
        // given
        ProcessingItem perPieceItem = ProcessingItem.builder()
                .id("pi-002")
                .name("挂钩")
                .pricingMethod("per_set")
                .unitPrice(new BigDecimal("3.00"))
                .minQuantity(1)
                .maxQuantity(500)
                .processingDays(1)
                .build();

        PriceCalculateRequest request = new PriceCalculateRequest();
        request.setProcessingItemId("pi-002");
        request.setQuantity(new BigDecimal("10"));

        when(processingItemMapper.selectById("pi-002")).thenReturn(perPieceItem);

        // when
        PriceCalculateResponse result = processingItemService.calculatePrice(request, 1L);

        // then
        assertThat(result.getTotalPrice()).isEqualByComparingTo(new BigDecimal("30.00"));
        assertThat(result.getDetails().get(0).getDescription()).contains("按套计价");
    }

    @Test
    @DisplayName("价格计算 - 固定价格")
    void calculatePrice_Fixed() {
        // given
        ProcessingItem fixedItem = ProcessingItem.builder()
                .id("pi-003")
                .name("安装服务")
                .pricingMethod("fixed")
                .unitPrice(new BigDecimal("200.00"))
                .minQuantity(1)
                .maxQuantity(1)
                .processingDays(1)
                .build();

        PriceCalculateRequest request = new PriceCalculateRequest();
        request.setProcessingItemId("pi-003");
        request.setQuantity(new BigDecimal("1"));

        when(processingItemMapper.selectById("pi-003")).thenReturn(fixedItem);

        // when
        PriceCalculateResponse result = processingItemService.calculatePrice(request, 1L);

        // then
        assertThat(result.getTotalPrice()).isEqualByComparingTo(new BigDecimal("200.00"));
        assertThat(result.getDetails().get(0).getDescription()).contains("固定价格");
    }

    @Test
    @DisplayName("价格计算 - 按面积计价")
    void calculatePrice_PerArea() {
        // given
        ProcessingItem areaItem = ProcessingItem.builder()
                .id("pi-004")
                .name("面料裁剪")
                .pricingMethod("per_area")
                .unitPrice(new BigDecimal("50.00"))
                .minQuantity(1)
                .maxQuantity(100)
                .processingDays(2)
                .build();

        PriceCalculateRequest request = new PriceCalculateRequest();
        request.setProcessingItemId("pi-004");
        request.setQuantity(new BigDecimal("2"));
        request.setDimensions(Map.of("width", new BigDecimal("1.5"), "height", new BigDecimal("2.0")));

        when(processingItemMapper.selectById("pi-004")).thenReturn(areaItem);

        // when
        PriceCalculateResponse result = processingItemService.calculatePrice(request, 1L);

        // then
        // 面积 = 1.5 * 2.0 = 3.0, 总价 = 50 * 3.0 * 2 = 300.00
        assertThat(result.getTotalPrice()).isEqualByComparingTo(new BigDecimal("300.00"));
        assertThat(result.getDetails().get(0).getDescription()).contains("按面积计价");
    }

    @Test
    @DisplayName("价格计算 - 数量低于最小值")
    void calculatePrice_BelowMinQuantity() {
        // given
        ProcessingItem item = ProcessingItem.builder()
                .id("pi-005")
                .name("加工项")
                .pricingMethod("per_meter")
                .unitPrice(new BigDecimal("10.00"))
                .minQuantity(5)
                .maxQuantity(100)
                .build();

        PriceCalculateRequest request = new PriceCalculateRequest();
        request.setProcessingItemId("pi-005");
        request.setQuantity(new BigDecimal("2"));

        when(processingItemMapper.selectById("pi-005")).thenReturn(item);

        // when & then
        assertThatThrownBy(() -> processingItemService.calculatePrice(request, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("数量不能小于最小数量");
    }

    @Test
    @DisplayName("价格计算 - 数量超过最大值")
    void calculatePrice_AboveMaxQuantity() {
        // given
        PriceCalculateRequest request = new PriceCalculateRequest();
        request.setProcessingItemId("pi-001");
        request.setQuantity(new BigDecimal("200"));

        when(processingItemMapper.selectById("pi-001")).thenReturn(testItem);

        // when & then
        assertThatThrownBy(() -> processingItemService.calculatePrice(request, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("数量不能大于最大数量");
    }

    @Test
    @DisplayName("价格计算 - 加工项不存在")
    void calculatePrice_ItemNotFound() {
        // given
        PriceCalculateRequest request = new PriceCalculateRequest();
        request.setProcessingItemId("nonexistent");
        request.setQuantity(new BigDecimal("1"));

        when(processingItemMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> processingItemService.calculatePrice(request, 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("价格计算 - 按面积计价缺少尺寸参数")
    void calculatePrice_PerArea_MissingDimensions() {
        // given
        ProcessingItem areaItem = ProcessingItem.builder()
                .id("pi-006")
                .name("面料裁剪")
                .pricingMethod("per_area")
                .unitPrice(new BigDecimal("50.00"))
                .minQuantity(1)
                .maxQuantity(100)
                .build();

        PriceCalculateRequest request = new PriceCalculateRequest();
        request.setProcessingItemId("pi-006");
        request.setQuantity(new BigDecimal("1"));
        // 不设置 dimensions

        when(processingItemMapper.selectById("pi-006")).thenReturn(areaItem);

        // when & then
        assertThatThrownBy(() -> processingItemService.calculatePrice(request, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("width");
    }

    // ======================== 计价方式回滚（PP-006 / OR-014，issue #3005） ========================
    // 行业加工费按米计价、辅料含在加工费里 → per_piece 与「每米数量」密度已移除：
    // per_piece 创建/更新被拒绝；calculatePrice 无密度推导（准用请求数量）。

    @Test
    @DisplayName("创建加工项 - per_piece 计价方式被拒绝")
    void createProcessingItem_RejectPerPiece() {
        // given
        ProcessingItemCreateRequest request = new ProcessingItemCreateRequest();
        request.setName("打孔（罗马圈）");
        request.setCategoryId("pcat-001");
        request.setPricingMethod("per_piece");
        request.setUnitPrice(new BigDecimal("1.50"));

        when(processingCategoryMapper.selectById("pcat-001")).thenReturn(testCategory);

        // when/then：per_piece 不再合法
        assertThatThrownBy(() -> processingItemService.createProcessingItem(request, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("无效的计价方式");
        verify(processingItemMapper, never()).insert(any(ProcessingItem.class));
    }

    @Test
    @DisplayName("更新加工项 - per_piece 计价方式被拒绝")
    void updateProcessingItem_RejectPerPiece() {
        // given
        ProcessingItemUpdateRequest request = new ProcessingItemUpdateRequest();
        request.setName("打孔（罗马圈）");
        request.setCategoryId("pcat-001");
        request.setPricingMethod("per_piece");
        request.setUnitPrice(new BigDecimal("1.50"));

        when(processingItemMapper.selectById("pi-001")).thenReturn(testItem);
        when(processingCategoryMapper.selectById("pcat-001")).thenReturn(testCategory);

        // when/then
        assertThatThrownBy(() -> processingItemService.updateProcessingItem("pi-001", request, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("无效的计价方式");
        verify(processingItemMapper, never()).updateById(any(ProcessingItem.class));
    }

    @Test
    @DisplayName("价格计算 - per_meter 无密度推导，数量沿用请求值（面料米数）")
    void calculatePrice_PerMeter_NoDensityDerivation() {
        // given：打孔加工 8 元/米，面料 6.6 米 → 数量即面料米数 6.6
        ProcessingItem perMeterItem = ProcessingItem.builder()
                .id("pi-punch")
                .name("打孔（罗马圈）")
                .pricingMethod("per_meter")
                .unitPrice(new BigDecimal("8.00"))
                .minQuantity(1)
                .maxQuantity(999)
                .processingDays(1)
                .build();

        PriceCalculateRequest request = new PriceCalculateRequest();
        request.setProcessingItemId("pi-punch");
        request.setQuantity(new BigDecimal("6.6"));

        when(processingItemMapper.selectById("pi-punch")).thenReturn(perMeterItem);

        // when
        PriceCalculateResponse result = processingItemService.calculatePrice(request, 1L);

        // then：数量 = 面料米数，费用 = 8 × 6.6 = 52.8，无任何密度推导
        assertThat(result.getQuantity()).isEqualByComparingTo(new BigDecimal("6.6"));
        assertThat(result.getTotalPrice()).isEqualByComparingTo(new BigDecimal("52.80"));
        assertThat(result.getDetails().get(0).getDescription()).contains("按米计价");
    }

    @Test
    @DisplayName("价格计算 - fixed 计价：一件一口价，数量=1")
    void calculatePrice_Fixed_SinglePrice() {
        // given：固定价加工项
        ProcessingItem fixedItem = ProcessingItem.builder()
                .id("pi-fixed")
                .name("帘头加工")
                .pricingMethod("fixed")
                .unitPrice(new BigDecimal("300.00"))
                .minQuantity(1)
                .maxQuantity(1)
                .processingDays(1)
                .build();

        PriceCalculateRequest request = new PriceCalculateRequest();
        request.setProcessingItemId("pi-fixed");
        request.setQuantity(new BigDecimal("1"));

        when(processingItemMapper.selectById("pi-fixed")).thenReturn(fixedItem);

        // when
        PriceCalculateResponse result = processingItemService.calculatePrice(request, 1L);

        // then：一口价，不随数量变化
        assertThat(result.getTotalPrice()).isEqualByComparingTo(new BigDecimal("300.00"));
        assertThat(result.getDetails().get(0).getDescription()).contains("固定价格");
    }
}
