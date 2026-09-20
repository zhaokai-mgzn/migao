package com.migao.admin.service;

// case_ids: PP-006, OR-014
// 加工项解耦（issue #4371）：`applicable_product_categories` 与 `applicableProductCategoryId`
// 过滤随「按商品分类过滤加工项」一并删除 ⇒「按适用商品分类筛选」「带适用商品分类的建/改」
// 三条用例随之删除（原声明的 PP-005 即该筛选用例，用例库中已同步移除）；
// 解耦本身的回归防线见 ProductProcessingDecouplingTest。
// PP-006/OR-014（issue #3005，回滚 #2986）：行业加工费按米计价且辅料含在加工费中，
// 加工项计价方式仅 per_meter/per_set/fixed/per_area——per_piece 与「每米数量」密度被移除，
// calculatePrice 不再有 fabricMeters 密度推导，数量由请求方直接给出。
// #4882（用户裁定，2026-09-21）：加工项目录**彻底删除**「计价方式」与「单价」两列 ⇒
// 本文件里 `calculatePrice_*` 一族（含数量上下限校验 / 按面积尺寸 / createPriceDetail）
// 与「per_piece / invalid_method 被拒绝」用例**整族退场**（不是删掉不管：对应的
// `ProcessingItemService.validatePricingMethod` / `calculatePrice` / `calculateArea` /
// `createPriceDetail` 与端点 `POST /api/admin/processing-items/calculate` 一并删除，
// 行为面移交 `processing_fee_combinations` 组合价目；加工项目录不再承担计价）。
// 补偿断言：`unit` 语义改为「加工数量单位」、默认由「元」改为「米」⇒ 新增
// `createProcessingItem_UnitDefaultsToMeter`（改回「元」即红）。
// PP-006 / OR-014 声明的「计价方式枚举」行为面随目录删列整体退场（用例库侧由 #4882 用例包处置）。

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
                .unit("米")
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

    // ======================== 创建加工项测试 ========================

    @Test
    @DisplayName("创建加工项成功")
    void createProcessingItem_Success() {
        // given
        ProcessingItemCreateRequest request = new ProcessingItemCreateRequest();
        request.setName("新加工项");
        request.setCategoryId("pcat-001");

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
    @DisplayName("创建加工项失败 - 分类不存在")
    void createProcessingItem_CategoryNotFound() {
        // given
        ProcessingItemCreateRequest request = new ProcessingItemCreateRequest();
        request.setName("新加工项");
        request.setCategoryId("nonexistent");

        when(processingCategoryMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> processingItemService.createProcessingItem(request, 1L))
                .isInstanceOf(BusinessException.class)
                .hasMessage("加工分类不存在");
    }

    // ======================== 更新加工项测试 ========================

    @Test
    @DisplayName("更新加工项成功")
    void updateProcessingItem_Success() {
        // given
        ProcessingItemUpdateRequest request = new ProcessingItemUpdateRequest();
        request.setName("更新后的加工项");
        request.setCategoryId("pcat-001");

        when(processingItemMapper.selectById("pi-001")).thenReturn(testItem);
        when(processingCategoryMapper.selectById("pcat-001")).thenReturn(testCategory);
        when(processingItemMapper.updateById(any(ProcessingItem.class))).thenReturn(1);

        // getProcessingItemById 内部调用
        ProcessingItem updatedItem = ProcessingItem.builder()
                .id("pi-001")
                .name("更新后的加工项")
                .categoryId("pcat-001")
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
    @DisplayName("更新加工项失败 - 加工项不存在")
    void updateProcessingItem_NotFound() {
        // given
        ProcessingItemUpdateRequest request = new ProcessingItemUpdateRequest();
        request.setName("更新");
        request.setCategoryId("pcat-001");

        when(processingItemMapper.selectById("nonexistent")).thenReturn(null);

        // when & then
        assertThatThrownBy(() -> processingItemService.updateProcessingItem("nonexistent", request, 1L))
                .isInstanceOf(BusinessException.class)
                .satisfies(ex -> {
                    BusinessException bex = (BusinessException) ex;
                    assertThat(bex.getCode()).isEqualTo("NOT_FOUND");
                });
    }

    @Test
    @DisplayName("#4882 建加工项：不传 unit ⇒ 默认「米」（加工数量单位，不再是计价单位「元」）")
    void createProcessingItem_UnitDefaultsToMeter() {
        // 红证：把 ProcessingItemCreateRequest.unit 的默认值改回 "元" ⇒ 本断言必红。
        ProcessingItemCreateRequest request = new ProcessingItemCreateRequest();
        request.setName("新加工项");
        request.setCategoryId("pcat-001");
        assertThat(request.getUnit()).as("#4882：unit 语义 = 加工数量单位，默认米").isEqualTo("米");

        when(processingCategoryMapper.selectById("pcat-001")).thenReturn(testCategory);
        when(processingItemMapper.insert(any(ProcessingItem.class))).thenAnswer(invocation -> {
            ProcessingItem item = invocation.getArgument(0);
            item.setId("pi-new");
            return 1;
        });
        // getProcessingItemById 内部按 id 回查：实体 unit 必须与请求一致（不是恒定桩）
        when(processingItemMapper.selectById("pi-new")).thenReturn(
                ProcessingItem.builder().id("pi-new").name("新加工项").categoryId("pcat-001")
                        .unit("米").status("active").build());

        ProcessingItemResponse result = processingItemService.createProcessingItem(request, 1L);

        assertThat(result.getUnit()).as("落库/回显的加工数量单位 = 米").isEqualTo("米");
    }
}
