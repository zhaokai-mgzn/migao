package com.migao.admin.service;

// case_ids=[PR-061]

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.migao.admin.dto.InboundOrderCreateRequest;
import com.migao.admin.dto.InboundOrderResponse;
import com.migao.admin.dto.OpeningImportReport;
import com.migao.admin.entity.InboundOrder;
import com.migao.admin.entity.ProductSku;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductSkuMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.apache.poi.ss.usermodel.WorkbookFactory;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.mock.web.MockMultipartFile;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 期初建账的 Excel 批量导入（V118 / issue #5153）—— 报告与「全或无」的契约。
 *
 * <p>守四条会被下一个验收者重开的判据：</p>
 * <ol>
 *   <li><b>批量必带幂等键</b>：空白 {@code importRunId} ⇒ 当场拒绝，**不建单**
 *       （没有幂等键就不许上批量导入，否则重跑 = 库存加两次）；</li>
 *   <li><b>全或无</b>：只要有 1 行不通过 ⇒ 一行都不写（{@code create} 一次都没被调），
 *       报告逐行说明原因 —— 部分成功会让「改好后用同一次导入标识重跑」变成重复建账；</li>
 *   <li><b>导入走服务层且不自己归一</b>：数值判据只来自
 *       {@link InboundOrderService#requireItemNumbers}（本类不做任何 {@code setScale}/进位），
 *       {@code 2.755} 因此在报告里被标红而不是被静默取整；</li>
 *   <li><b>重跑幂等</b>：{@code create} 命中既有「已过账」的单 ⇒ 报告 {@code created=false}
 *       且**不再调** {@code post}（重复过账 = 重复加库存）。</li>
 * </ol>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
@DisplayName("期初建账 Excel 批量导入（V118 / issue #5153）")
class OpeningRegisterImportServiceTest {

    @Mock private InboundOrderService inboundOrderService;
    @Mock private ProductSkuMapper productSkuMapper;

    @InjectMocks private OpeningRegisterImportService service;

    private static final Long TENANT = 1L;
    private static final String RUN_ID = "opening-register-20260924-01";

    @BeforeEach
    void setUp() {
        MybatisConfiguration conf = new MybatisConfiguration();
        MapperBuilderAssistant asst = new MapperBuilderAssistant(conf, "");
        TableInfoHelper.initTableInfo(asst, ProductSku.class);
    }

    // ============================================================ 工具

    /** 造一份 .xlsx：第 1 行表头（与 HEADERS 同源）+ 逐行数据 */
    private static MockMultipartFile xlsx(String[][] dataRows) {
        try (Workbook workbook = new XSSFWorkbook()) {
            Sheet sheet = workbook.createSheet("期初建账");
            Row header = sheet.createRow(0);
            for (int i = 0; i < OpeningRegisterImportService.HEADERS.size(); i++) {
                header.createCell(i).setCellValue(OpeningRegisterImportService.HEADERS.get(i));
            }
            for (int r = 0; r < dataRows.length; r++) {
                Row row = sheet.createRow(r + 1);
                for (int c = 0; c < dataRows[r].length; c++) {
                    row.createCell(c).setCellValue(dataRows[r][c]);
                }
            }
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            workbook.write(out);
            return new MockMultipartFile("file", "opening-register.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    out.toByteArray());
        } catch (Exception e) {
            throw new IllegalStateException("测试造 xlsx 失败", e);
        }
    }

    /** 货号 → SKU 的查库替身（真库按 `(tenant_id, sku_code)` 唯一命中；找不到就空） */
    private void stubSkus(Map<String, ProductSku> byCode) {
        when(productSkuMapper.selectList(any(LambdaQueryWrapper.class))).thenAnswer(inv -> {
            LambdaQueryWrapper<ProductSku> wrapper = inv.getArgument(0);
            // MyBatis-Plus 惰性物化入参：不先取一次 SQL 段，paramNameValuePairs 还是空的
            if (wrapper.getParamNameValuePairs().isEmpty()) {
                wrapper.getSqlSegment();
            }
            String code = wrapper.getParamNameValuePairs().values().stream()
                    .filter(String.class::isInstance).map(String.class::cast)
                    .findFirst().orElse(null);
            ProductSku sku = byCode.get(code);
            return sku == null ? List.of() : List.of(sku);
        });
    }

    private static ProductSku sku(long id, String code) {
        ProductSku s = new ProductSku();
        s.setId(id);
        s.setTenantId(TENANT);
        s.setProductId("prod-" + id);
        s.setSkuCode(code);
        return s;
    }

    private static InboundOrderResponse order(String status) {
        InboundOrderResponse resp = new InboundOrderResponse();
        resp.setId("inbound-uuid-1");
        resp.setInboundNo("RK-20260924-0301");
        resp.setStatus(status);
        resp.setSource(InboundOrder.SOURCE_OPENING);
        resp.setImportRunId(RUN_ID);
        return resp;
    }

    // ============================================================ 判据

    @Test
    @DisplayName("模板：第 1 表只有表头（**不放示例行** —— 原样上传会建出一批假账）+ 第 2 表填写说明")
    void templateHasHeadersAndNoExampleRow() throws Exception {
        byte[] bytes = service.template();
        try (Workbook workbook = WorkbookFactory.create(new ByteArrayInputStream(bytes))) {
            Sheet sheet = workbook.getSheetAt(0);
            assertThat(sheet.getLastRowNum()).isZero();
            Row header = sheet.getRow(0);
            for (int i = 0; i < OpeningRegisterImportService.HEADERS.size(); i++) {
                assertThat(header.getCell(i).getStringCellValue())
                        .isEqualTo(OpeningRegisterImportService.HEADERS.get(i));
            }
            assertThat(workbook.getSheet("填写说明")).isNotNull();
        }
    }

    @Test
    @DisplayName("幂等键缺失（空白）⇒ 当场拒绝，**不**建单（没有幂等键就不许上批量导入）")
    void rejectsBlankImportRunId() {
        MockMultipartFile file = xlsx(new String[][]{{"HUOHAO-01", "0.5"}});

        assertThatThrownBy(() -> service.importOpening(file, "  ", TENANT, "op"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("导入标识");
        verify(inboundOrderService, never()).create(any(), any(), anyString());
    }

    @Test
    @DisplayName("0.5 米 + 旧系统批次号 + 缸号 ⇒ 建一张 source=opening 的单并过账（GAP-12）")
    void importsHalfMeterTailIntoAnOpeningOrder() {
        stubSkus(Map.of("HUOHAO-01", sku(11L, "HUOHAO-01")));
        when(inboundOrderService.create(any(), eq(TENANT), anyString())).thenReturn(order(InboundOrder.STATUS_DRAFT));
        when(inboundOrderService.post(anyString(), eq(TENANT), anyString())).thenReturn(order(InboundOrder.STATUS_POSTED));

        OpeningImportReport report = service.importOpening(
                xlsx(new String[][]{{"HUOHAO-01", "0.5", "缸A-8891", "OLD-2024-0001", "12.50", "尾料"}}),
                RUN_ID, TENANT, "op");

        ArgumentCaptor<InboundOrderCreateRequest> reqCap = ArgumentCaptor.forClass(InboundOrderCreateRequest.class);
        verify(inboundOrderService).create(reqCap.capture(), eq(TENANT), anyString());
        InboundOrderCreateRequest req = reqCap.getValue();
        // 复用 V117 既有件：来源 + 运行级幂等键（本单**不新造**幂等键）
        assertThat(req.getSource()).isEqualTo(InboundOrder.SOURCE_OPENING);
        assertThat(req.getImportRunId()).isEqualTo(RUN_ID);
        assertThat(req.getItems()).hasSize(1);
        InboundOrderCreateRequest.Item item = req.getItems().get(0);
        assertThat(item.getQuantity()).isEqualByComparingTo("0.5");
        assertThat(item.getLegacyBatchNo()).isEqualTo("OLD-2024-0001");
        assertThat(item.getDyeLot()).isEqualTo("缸A-8891");
        assertThat(item.getSkuId()).isEqualTo(11L);
        // 模板里有「备注」列 ⇒ 必须原样落到明细行（不许静默丢掉：那会让用户以为填了没用）
        assertThat(item.getRemark()).isEqualTo("尾料");

        verify(inboundOrderService).post("inbound-uuid-1", TENANT, "op");
        assertThat(report.isCreated()).isTrue();
        assertThat(report.getStatus()).isEqualTo(InboundOrder.STATUS_POSTED);
        assertThat(report.getInboundNo()).isEqualTo("RK-20260924-0301");
        assertThat(report.getTotal()).isEqualTo(1);
        assertThat(report.getFailCount()).isZero();
        assertThat(report.getRows().get(0).isOk()).isTrue();
        assertThat(report.getRows().get(0).getRowNo()).isEqualTo(2);
    }

    @Test
    @DisplayName("全或无：2.755（超 1 位小数）⇒ 报告标红该行、**一行都不写**（不建单、不静默取整）")
    void threeDecimalRowFailsTheWholeImport() {
        stubSkus(Map.of("HUOHAO-01", sku(11L, "HUOHAO-01"), "HUOHAO-02", sku(12L, "HUOHAO-02")));

        OpeningImportReport report = service.importOpening(
                xlsx(new String[][]{
                        {"HUOHAO-01", "0.5", "", "OLD-1", "", ""},
                        {"HUOHAO-02", "2.755", "", "", "", ""},
                }), RUN_ID, TENANT, "op");

        assertThat(report.getTotal()).isEqualTo(2);
        assertThat(report.getOkCount()).isEqualTo(1);
        assertThat(report.getFailCount()).isEqualTo(1);
        assertThat(report.isCreated()).isFalse();
        assertThat(report.getInboundNo()).isNull();
        OpeningImportReport.Row bad = report.getRows().get(1);
        assertThat(bad.getRowNo()).isEqualTo(3);
        assertThat(bad.isOk()).isFalse();
        assertThat(bad.getMessage()).contains("1 位小数").contains("2.755");
        // 关键：一行都不写 —— 部分成功会让「改好后重跑」变成重复建账
        verify(inboundOrderService, never()).create(any(), any(), anyString());
        verify(inboundOrderService, never()).post(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("货号不存在 / 数量非数字 ⇒ 逐行可行动报告（第几行、哪个值），且不建单")
    void reportsRowLevelErrors() {
        stubSkus(Map.of("HUOHAO-01", sku(11L, "HUOHAO-01")));

        OpeningImportReport report = service.importOpening(
                xlsx(new String[][]{
                        {"NO-SUCH-SKU", "3", "", "", "", ""},
                        {"HUOHAO-01", "abc", "", "", "", ""},
                        {"", "3", "", "", "", ""},
                        // 自由文本列超长（缸号列宽 VARCHAR(64)）⇒ 必须是**逐行报告**里的原因，
                        // 不能放任它到 INSERT 变成 22001 / 「服务器内部错误」
                        {"HUOHAO-01", "3", "缸".repeat(65), "", "", ""},
                }), RUN_ID, TENANT, "op");

        assertThat(report.getFailCount()).isEqualTo(4);
        assertThat(report.getRows().get(0).getMessage()).contains("NO-SUCH-SKU").contains("不存在");
        assertThat(report.getRows().get(1).getMessage()).contains("剩余米数").contains("abc");
        assertThat(report.getRows().get(2).getMessage()).contains("货号不能为空");
        assertThat(report.getRows().get(3).getMessage()).contains("缸号最多 64 个字符");
        assertThat(report.getMessage()).contains("未建账");
        verify(inboundOrderService, never()).create(any(), any(), anyString());
    }

    @Test
    @DisplayName("重跑幂等：create 命中既有「已过账」的单 ⇒ created=false 且**不再调 post**")
    void replayDoesNotPostAgain() {
        stubSkus(Map.of("HUOHAO-01", sku(11L, "HUOHAO-01")));
        // 同一 run_id 重跑：服务层返回既有那张（已过账）= 库存早已加过
        when(inboundOrderService.create(any(), eq(TENANT), anyString()))
                .thenReturn(order(InboundOrder.STATUS_POSTED));

        OpeningImportReport report = service.importOpening(
                xlsx(new String[][]{{"HUOHAO-01", "0.5", "", "OLD-2024-0001", "", ""}}),
                RUN_ID, TENANT, "op");

        assertThat(report.isCreated()).isFalse();
        assertThat(report.getMessage()).contains("幂等命中");
        verify(inboundOrderService, never()).post(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("表头不是「货号」开头 ⇒ 拒绝（防上传了别的表：列错位会把数字填到错误的语义上）")
    void rejectsWrongHeader() {
        // 复现「上传了商品导入表」：表头第一格不是货号
        MockMultipartFile file = new MultipartWithHeader(xlsx(new String[][]{{"x", "y"}}), "价格表*");
        assertThatThrownBy(() -> service.importOpening(file, RUN_ID, TENANT, "op"))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("表头第一列");
        verify(inboundOrderService, never()).create(any(), any(), anyString());
    }

    /** 把 xlsx 的表头第一格换成别的值（用于「上传了别的表」的判据） */
    private static final class MultipartWithHeader extends MockMultipartFile {
        MultipartWithHeader(MockMultipartFile source, String header) {
            super("file", "wrong.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    rewrite(source, header));
        }

        private static byte[] rewrite(MockMultipartFile source, String header) {
            try (Workbook workbook = WorkbookFactory.create(new ByteArrayInputStream(source.getBytes()))) {
                workbook.getSheetAt(0).getRow(0).getCell(0).setCellValue(header);
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                workbook.write(out);
                return out.toByteArray();
            } catch (Exception e) {
                throw new IllegalStateException("改写表头失败", e);
            }
        }
    }

    @Test
    @DisplayName("没有数据行（只有表头）⇒ 报告 total=0 且不建单（不落一张零行的期初单）")
    void emptyFileCreatesNothing() {
        OpeningImportReport report = service.importOpening(xlsx(new String[0][]), RUN_ID, TENANT, "op");

        assertThat(report.getTotal()).isZero();
        assertThat(report.getMessage()).contains("没有数据行");
        verify(inboundOrderService, never()).create(any(), any(), anyString());
    }

    /** 数值口径只来自服务层的一处判据（本类不做归一）——用 0.5 与 0.1 边界钉住 */
    @Test
    @DisplayName("0.1 米（粒度下限）⇒ 通过；0 ⇒ 报告标红（下限仍是「大于 0」）")
    void lowerBoundaryIsAboveZero() {
        stubSkus(Map.of("HUOHAO-01", sku(11L, "HUOHAO-01")));
        when(inboundOrderService.create(any(), eq(TENANT), anyString())).thenReturn(order(InboundOrder.STATUS_DRAFT));
        when(inboundOrderService.post(anyString(), eq(TENANT), anyString())).thenReturn(order(InboundOrder.STATUS_POSTED));

        OpeningImportReport ok = service.importOpening(
                xlsx(new String[][]{{"HUOHAO-01", "0.1", "", "", "", ""}}), RUN_ID, TENANT, "op");
        assertThat(ok.getFailCount()).isZero();
        assertThat(ok.getRows().get(0).getQuantity()).isEqualByComparingTo("0.1");

        OpeningImportReport zero = service.importOpening(
                xlsx(new String[][]{{"HUOHAO-01", "0", "", "", "", ""}}), "another-run", TENANT, "op");
        assertThat(zero.getFailCount()).isEqualTo(1);
        assertThat(zero.getRows().get(0).getMessage()).contains("必须大于 0 米");
    }
}
