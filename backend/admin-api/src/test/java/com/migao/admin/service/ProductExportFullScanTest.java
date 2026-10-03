// case_ids: PR-059
// 商品导出（issue #6198）：**全量导出不得被全局分页上限静默截断**。
//
// 病灶形态（实测）：`MybatisPlusConfig.paginationInnerInterceptor().setMaxLimit(500L)` 是**全局**分页护栏，
// 而 `ProductService.exportProducts` 旧实现把 `size` 设成 10000 后走 `getProducts` 分页入口
// ⇒ 分页拦截器把 10000 夹回 500 ⇒ 列表 `total=989` 而导出只有 500 行、**无任何提示**。
//
// 本文件按铁律 8 分两层：
//   ① 实例判据：989 行时**导出行数 == 同筛选条件下列表的 `total`**；表头 == `EXPORT_HEADERS` 逐字 7 列；边界 500 / 501。
//   ② 类级元守卫：**任何行数**下导出都不得少行（0/1/499/500/501/989/1001 逐一比），
//      且**护栏不许倒** —— 全局上限仍是 500（不许把 `setMaxLimit` 改成 -1 来「修」，
//      那会放开**所有**列表的分页保护），列表路径请求 size=10000 时依旧被夹到 500。
//
// 上限的**单一源** = `MybatisPlusConfig` 的 bean 本身（本文件现取 `getMaxLimit()`，不在测试里写死 500）——
// 否则「改配置」与「测配置」会各说各话；「必须 = 500」这一条由判据 5 单独钉住。
package com.migao.admin.service;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.migao.admin.config.MybatisPlusConfig;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.dto.ProductQueryRequest;
import com.migao.admin.dto.ProductResponse;
import com.migao.admin.entity.Category;
import com.migao.admin.entity.Product;
import com.migao.admin.entity.ProductColor;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.mapper.CategoryMapper;
import com.migao.admin.mapper.ProductAttributeMapper;
import com.migao.admin.mapper.ProductColorMapper;
import com.migao.admin.mapper.ProductMapper;
import com.migao.admin.mapper.ProductSkuMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.mock.web.MockHttpServletResponse;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("商品导出全量契约（issue #6198：不得被全局分页上限静默截断）")
class ProductExportFullScanTest {

    /** 全局分页上限的**单一源**：现取 `MybatisPlusConfig` 的 bean（不在测试里写死数字）。 */
    private static final long GLOBAL_MAX_LIMIT =
            new MybatisPlusConfig().paginationInnerInterceptor().getMaxLimit();

    /** 类级元守卫里的**登记表**（未登记即红）——本文件断言导出路径不依赖任何「一次取全量」的页大小。 */
    private static final List<String> PAGE_SIZES_ALLOWED_ABOVE_GLOBAL_LIMIT = List.of();

    @InjectMocks
    private ProductService productService;

    @Mock
    private ProductMapper productMapper;
    @Mock
    private CategoryMapper categoryMapper;
    @Mock
    private ProductColorMapper productColorMapper;
    @Mock
    private ProductSkuMapper productSkuMapper;
    @Mock
    private ProductAttributeMapper productAttributeMapper;
    @Mock
    private StockLedgerService stockLedgerService;

    @BeforeEach
    void setUp() {
        MybatisConfiguration configuration = new MybatisConfiguration();
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), Product.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), ProductColor.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), ProductSku.class);
        TableInfoHelper.initTableInfo(new MapperBuilderAssistant(configuration, ""), Category.class);
    }

    // ==================== 夹具（桩替身 = 真分页拦截器的行为复刻） ====================

    private List<Product> dataset(int n) {
        List<Product> rows = new ArrayList<>(n);
        for (int i = 0; i < n; i++) {
            Product p = new Product();
            p.setId(String.format("prod-%04d", i));
            p.setName("窗帘 " + i);
            p.setSkuCode("PJ-" + i);
            p.setStatus("on_sale");
            p.setDescription("描述 " + i);
            p.setBasePrice(new BigDecimal("199.0"));
            p.setStock(BigDecimal.TEN);
            rows.add(p);
        }
        return rows;
    }

    /**
     * 让桩替身**复刻真分页拦截器**（`PaginationInnerInterceptor.beforeQuery` 的夹取）：
     * 请求的 `size > maxLimit` ⇒ 夹到 `maxLimit`；`selectList`（不带 IPage）**不被拦**。
     *
     * <p>这正是生产上发生的事：旧导出请求 size=10000 ⇒ 只回 500 行，而 `total` 仍是全量。
     * 上限取自 {@link #GLOBAL_MAX_LIMIT}（现取配置），所以「改配置」不会被桩替身悄悄吸收。</p>
     */
    private void stubMapperWithGlobalLimitClamp(List<Product> rows) {
        when(productMapper.selectPage(any(Page.class), any())).thenAnswer(invocation -> {
            Page<Product> requested = invocation.getArgument(0);
            long size = requested.getSize();
            if (GLOBAL_MAX_LIMIT > 0 && size > GLOBAL_MAX_LIMIT) {
                requested.setSize(GLOBAL_MAX_LIMIT);
                size = GLOBAL_MAX_LIMIT;
            }
            long current = Math.max(requested.getCurrent(), 1L);
            long from = Math.min((current - 1) * size, rows.size());
            long to = Math.min(from + size, rows.size());
            Page<Product> page = new Page<>(current, size);
            page.setTotal(rows.size());
            page.setRecords(new ArrayList<>(rows.subList((int) from, (int) to)));
            return page;
        });
        when(productMapper.selectList(any())).thenReturn(rows);
    }

    /** 走真导出路径（含 POI 落盘）后，读回 xlsx 的**数据行数**（不含表头）。 */
    private int exportDataRows(int n) throws IOException {
        stubMapperWithGlobalLimitClamp(dataset(n));
        MockHttpServletResponse response = new MockHttpServletResponse();
        productService.exportProducts(new ProductQueryRequest(), 1L, response);
        try (Workbook workbook = new XSSFWorkbook(new ByteArrayInputStream(response.getContentAsByteArray()))) {
            return workbook.getSheetAt(0).getLastRowNum();   // 行 0 = 表头 ⇒ 数据行数 = lastRowNum
        }
    }

    /** 同筛选条件下列表的 `total`（导出必须与它逐值相等）。 */
    private long listTotal(int n) {
        stubMapperWithGlobalLimitClamp(dataset(n));
        return productService.getProducts(new ProductQueryRequest(), 1L).getTotal();
    }

    private static String[] headerCells(byte[] xlsx) throws IOException {
        try (Workbook workbook = new XSSFWorkbook(new ByteArrayInputStream(xlsx))) {
            Row header = workbook.getSheetAt(0).getRow(0);
            String[] cells = new String[header.getLastCellNum()];
            for (int i = 0; i < cells.length; i++) {
                cells[i] = header.getCell(i).getStringCellValue();
            }
            return cells;
        }
    }

    // ==================== ① 实例判据 ====================

    @Test
    @DisplayName("判据1：989 行 ⇒ 导出行数 == 同筛选条件下列表 total（静默截断在 500 不再发生）")
    void exportRowCountEqualsListTotal() throws IOException {
        long total = listTotal(989);
        assertThat(total).as("夹具自证：桩替身回报的 total 必须是全量 989（否则判据比的是错的靶子）").isEqualTo(989L);
        assertThat(exportDataRows(989))
                .as("导出行数必须 == 列表 total；旧实现被全局上限夹到 500 ⇒ 少 489 行且无任何提示")
                .isEqualTo((int) total);
    }

    @Test
    @DisplayName("判据2：导出表头 == EXPORT_HEADERS 逐字 7 列")
    void exportHeadersAreVerbatim() throws IOException {
        stubMapperWithGlobalLimitClamp(dataset(3));
        MockHttpServletResponse response = new MockHttpServletResponse();
        productService.exportProducts(new ProductQueryRequest(), 1L, response);

        assertThat(headerCells(response.getContentAsByteArray()))
                .as("表头必须与 ProductService.EXPORT_HEADERS 逐字同源")
                .containsExactly(ProductService.EXPORT_HEADERS);
        assertThat(headerCells(response.getContentAsByteArray()))
                .as("逐字 7 列（写死字面量：常量被改坏时不能被 containsExactly(常量) 自己骗过）")
                .containsExactly("商品名称", "货号", "分类", "价格", "库存", "状态", "描述");
    }

    @Test
    @DisplayName("判据3：边界 恰好 500 行 / 501 行 都不少行")
    void boundaryAtGlobalLimit() throws IOException {
        assertThat(exportDataRows(500)).as("恰好 500（= 全局上限）").isEqualTo(500);
        assertThat(exportDataRows(501)).as("501（= 上限 +1，旧实现正好在这里开始少行）").isEqualTo(501);
    }

    // ==================== ② 类级元守卫 ====================

    @Test
    @DisplayName("判据4（类级）：任意行数下导出都不得少行（0/1/499/500/501/989/1001）")
    void exportNeverSilentlyTruncatesForAnySize() throws IOException {
        for (int n : new int[]{0, 1, 499, 500, 501, 989, 1001}) {
            assertThat(exportDataRows(n))
                    .as("行数 n=%d 时导出行数必须等于 n —— 「静默截断」这一**类**形态在这里一律判红", n)
                    .isEqualTo(n);
        }
    }

    @Test
    @DisplayName("判据5（类级·护栏不许倒）：全局上限仍是 500，列表路径请求 size=10000 依旧被夹到 500")
    void globalPaginationGuardStillHolds() {
        assertThat(GLOBAL_MAX_LIMIT)
                .as("修法不得把 MybatisPlusConfig 的 setMaxLimit 放开成 -1 —— 那是放开**所有**列表的分页护栏（降护栏=红线）")
                .isEqualTo(500L);

        stubMapperWithGlobalLimitClamp(dataset(989));
        ProductQueryRequest query = new ProductQueryRequest();
        query.setPage(1L);
        query.setSize(10000L);
        PageResponse<ProductResponse> list = productService.getProducts(query, 1L);

        assertThat(list.getItems())
                .as("列表路径（分页入口）仍必须被全局上限夹住：请求 10000 只回 %d 行", GLOBAL_MAX_LIMIT)
                .hasSize((int) GLOBAL_MAX_LIMIT);
        assertThat(list.getTotal()).as("total 仍是全量，列表页自己知道有 989 件").isEqualTo(989L);
        assertThat(PAGE_SIZES_ALLOWED_ABOVE_GLOBAL_LIMIT)
                .as("登记表：允许「一次请求超过全局上限的页大小」的调用点 —— 导出路径**不在**其中（未登记即红）")
                .isEmpty();
    }

    @Test
    @DisplayName("判据6（判别力自证）：旧形态「一次分页取 10000」在同一桩替身下只回 500 行")
    void oldShapeIsReallyTruncatedByTheStub() {
        stubMapperWithGlobalLimitClamp(dataset(989));
        List<Product> oneShot = productMapper
                .selectPage(new Page<>(1L, 10000L), new LambdaQueryWrapper<Product>()).getRecords();

        assertThat(oneShot)
                .as("若这里不是 500，则判据 1/3/4 是**空断言**（桩替身没复刻夹取行为，红不起来也绿不了）")
                .hasSize(500);
    }
}
