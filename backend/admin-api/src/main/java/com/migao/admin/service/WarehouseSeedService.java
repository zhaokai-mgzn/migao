package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.Warehouse;
import com.migao.admin.mapper.WarehouseMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 开租「默认主仓」播种（issue #7592）—— 开箱就有仓可选，不是让商家先去造一个。
 *
 * <h2>为什么需要它（缺陷形态，#7592）</h2>
 * `warehouses` 表在现网是 **0 行**：段 1 有意「不自动建仓」（{@link WarehouseService} 的
 * {@code defaultWarehouse} 注释逐字「缺省由调用方明说」），而调用方只可能是
 * {@code POST /api/admin/warehouses} —— 商家面上**没有任何建仓入口**（菜单无节点、admin-web 的
 * {@code warehouseApi} 只有只读 {@code list()}）。
 * <p>后果落在盘点单上：{@code /stocktakes} →「出盘点任务」的仓库下拉**只有占位项** ⇒
 * 一张盘点单也出不了（P1-1 多仓/盘点这一段整段不可用）。</p>
 *
 * <h2>为什么是「播种」而不是「查询时兜底一个虚拟仓」</h2>
 * 盘点单的 {@code warehouse_id} 是**真外键**（{@code stocktakes.warehouse_id REFERENCES warehouses(id)}）、
 * 调拨两端也是 ⇒ 必须真有一行；口径与 #6295（默认商品分类）/ #7148（默认加工项目录）同族：
 * <b>开租必需初始数据清单</b>（{@link OnboardingInitialData#REQUIRED}）里登记、入驻后置条件校验、
 * 类级元守卫 {@code tests/unit_ci_workflows/test_onboarding_required_seed_guard.py} 对账。
 *
 * <h2>边界（照实登记）</h2>
 * <ul>
 *   <li>只种**一个**默认主仓（{@code store} 类型）：多仓建档页/调拨页仍未做（issue #7592 明列，
 *       用户 2026-10-24 裁定「零 UI 最小解」），第二个仓目前只能走 {@code POST /api/admin/warehouses}；</li>
 *   <li>**不回填历史批次的仓库文本**：文本不是 code 也不是仓名、且非空的批次不计入主仓盘点
 *       （那属于「多仓建档页」的归属）；空文本按「未指定仓 = 默认仓」计入（见
 *       {@code StocktakeService.open}）；</li>
 *   <li>幂等：已有**任何**仓的租户一律不种（不碰 {@code uk_warehouses_single_default} 与
 *       商家自己建的默认仓）。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WarehouseSeedService {

    private final WarehouseMapper warehouseMapper;

    /**
     * 该租户现存仓数（入驻**后置条件**探针：0 ⇒ 开箱「出盘点任务」的仓库下拉为空）。
     *
     * <p>现取读库（不读缓存、不按「播种调用在不在」推断）—— 播种调用可能被后来的重构搬走 /
     * 条件化 / 吞掉异常，只有读库能把「漏种」变成可归因的红。</p>
     */
    public long countWarehouses(Long tenantId) {
        return warehouseMapper.selectCount(new LambdaQueryWrapper<Warehouse>()
                .eq(Warehouse::getTenantId, tenantId));
    }

    /**
     * 播种默认主仓（幂等）。
     *
     * @return 真的种下（1）还是本就有仓 / 并发撞唯一索引（0）
     */
    @Transactional
    public int seedDefaultWarehouse(Long tenantId) {
        if (countWarehouses(tenantId) > 0) {
            return 0;
        }
        Warehouse warehouse = new Warehouse();
        warehouse.setTenantId(tenantId);
        // 默认值的单一来源 = OnboardingInitialData（迁移 V189 里同值，两处由用例 WH-002 对账）
        warehouse.setCode(OnboardingInitialData.DEFAULT_WAREHOUSE_CODE);
        warehouse.setName(OnboardingInitialData.DEFAULT_WAREHOUSE_NAME);
        // V194（issue #7750）：默认仓装的是**布料** ⇒ 类型 = 原料仓（与 V196 对存量默认仓的回填同口径；
        // 成品仓由打包动作按需自动建，不在这里种 —— 没有成品时可少一个空仓）。
        warehouse.setWarehouseType(Warehouse.TYPE_MATERIAL);
        warehouse.setIsDefault(true);
        warehouse.setStatus("active");
        try {
            warehouseMapper.insert(warehouse);
        } catch (DuplicateKeyException duplicate) {
            // 并发入驻 / 重试：另一条已经把默认仓种下了 ⇒ 幂等返回 0，不是失败
            log.info("[warehouse] 默认主仓已存在（并发或重试），跳过 | tenant={}", tenantId);
            return 0;
        }
        log.info("[warehouse] 开租播种默认主仓 | tenant={} code={}",
                tenantId, warehouse.getCode());
        return 1;
    }
}
