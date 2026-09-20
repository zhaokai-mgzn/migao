# 验收 transcript — #4677 工艺项界面两层改造（PR #4710）

- 验收工作区：`/Users/guangzhen.zk/ai native/migao-wt/acceptance-craft-ui-4677`
- 被测对象：issue **#4677**（CLOSED）· PR **#4710**（MERGED，2026-09-20T02:45:42Z）· merge commit **`efa59d98a29034ca8f5d2455c6e03ea1dde3aef6`**
- 主仓库只读：`/Users/guangzhen.zk/ai native/migao`（`git rev-parse origin/main` = `efa59d98a29034ca8f5d2455c6e03ea1dde3aef6`）
- 被测源码**逐字节锚**（`git show efa59d98a:<path> | shasum -a 256`，**不可变引用**，不读 `origin/main` 移动靶）：

| 文件 | sha256 @efa59d98a |
|---|---|
| `frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx` | `017660477835219b0908d6e7a518369e4a7d388274ef4c422f8c123da2a003e9` |
| `frontend/admin-web/src/lib/api.ts` | `84b172c8832b5b6317fd104aeb28b2a797ba1cd5ac093f8dd1cdfcaaee5a206f` |
| `frontend/admin-web/src/types/index.ts` | `45fcf825bc0de74164fa8f8aaefa6437acef83885de3c061a99f03a3e0dbc9f8` |

交付文件**在 main 与工作区逐字节相同**（SAME × 4，含测试文件）—— 验收读取的源码 = 交付源码。

---

## R0 · 定对象与环境

```
$ git log --oneline -3
efa59d98a feat(web): #4677 工艺项两层改造（工序按车间分组 + 打包发货一列价）+ 布料单定价入口 + 从根上避免删除死路 (#4710)
b364a7eb5 fix(api+web): #4696 未定价 ≠ 0 —— 实例化侧区分三态 + 加工单/计件报表可见 + 定价入口 (#4703)
9a66a6239 fix(db): #4685 补种 V79 漏掉的布料种子（按租户 + 显式 ::numeric + 幂等 + 不覆盖商家已改） (#4706)

$ git show --stat efa59d98a --name-only   # 交付文件清单（6 个）
frontend/admin-web/src/app/(dashboard)/production/routings/page.tsx
frontend/admin-web/src/lib/api.ts
frontend/admin-web/src/types/index.ts
frontend/admin-web/tests/unit/components/OperationsProvenance.test.tsx
frontend/admin-web/tests/unit/components/OperationsScopeColumn.test.tsx
frontend/admin-web/tests/unit/pages/production-routings.test.tsx
```

### R0.1 设计依据（`docs/design/public-operations-and-craft-ui.md` @efa59d98a，828 行）

§4.1 目标形态逐字（`:292-320`）：

```
工艺项 · 计件单价（给工人）                            未定价 N 项   [搜索]
┌─ 【工序】 ─────────────────────────────────────────────────────────┐
│ ▾ 裁剪（裁床）                                                      │
│     精裁         ¥0.40 │ ¥0.40 │ ¥0.40    裁剪 · 米  必完  管理▸   │
├─ 【打包发货】★ 一列价 ─────────────────────────────────────────────┤
│     打包         未定价 /套               后道 · 套  必完  管理▸    │
└────────────────────────────────────────────────────────────────────┘
```

§4.2 分区判据（`:322-345`）：`scope === 'set'` ⇒ 打包发货；其余 ⇒ 工序。
§4.3 列收窄（`:335-345`）：`positionColumns = 矩阵里出现的部位 ∩ POSITION_DOMAIN`，**追加未知部位的行为取消**；但 **`布料` 不得从读面删掉**。
§4.5 方案 A 的界面聚合 3 条规则（`:372-390`）：全同 ⇒ 该价；有 `NULL` ⇒ `未定价`（≠ ¥0.00）；不相同 ⇒ `各部位不同价（N 处）`。
附录 B 16 条判据（`:787-810`）。

### R0.2 issue #4677 硬要求（评论逐字，`zhaokai-mgzn` 2026-09-20T01:52:16Z）

> ### 硬要求（本单验收判据，**必答**）
> **商家必须能在一个明确、可见的位置给布料单的 `裁剪` 与 `打包` 定价，且不依赖矩阵里存在「布料」列。**
>
> 二选一（由实现方判断并说明取舍）：
> - **① 用「工序库行价」**（`production_operations.unit_price`）—— 并在界面上**明确标注**"布料单按此价"（一处价、一处改，最省）；
> - **② 在「打包发货」区旁给一个「布料单」小区**（一列价：`裁剪` + `打包`）。

---

## R1 · 全量确定性测试（工作区 = 交付源码）

```
$ cd frontend/admin-web && npx vitest run
 Test Files  165 passed (165)
      Tests  2395 passed | 1 skipped (2396)
   Duration  32.89s
[exit code: 0]
```

```
$ cd frontend/admin-web && npx vitest run \
    tests/unit/pages/production-routings.test.tsx \
    tests/unit/components/OperationsProvenance.test.tsx \
    tests/unit/components/OperationsScopeColumn.test.tsx
 Test Files  3 passed (3)
      Tests  186 passed (186)
   Duration  8.74s
```

```
$ cd frontend/admin-web && npx tsc --noEmit
tsc exit=0          # 无输出 = 零类型错误
```

```
$ ./check-ui-regression.sh
✅ UI 无回退（worktree），关键文件与 main token 一致或为正常新增
[exit code: 0]
```

> ⚠️ 本条只证明「不崩 / 类型对 / 无回退」；**不证明**用户可见结果达成（见报告 §3、§6）。

### R1.1 全量档的新鲜度与空跑核对（协议 v1.3）

- **步骤级**：上面 3 条命令是**本会话在前台直接执行**的，退出码 0，**无 `skipped` 语义**（vitest/tsc/shell 脚本不存在被抑制的步骤）。
- **产物级**：vitest 的判定**内联在 stdout**（`Tests N passed`），非 artifact 文件 ⇒ 无「artifact 为 0 却 success」的形态。
- **新鲜度**：被测源码的 `sha256` 在跑测试前后**都等于** `0176604778…a003e9`（见 R3 每条注入的 `[注入自证]` 与还原自证）⇒ 产物对应**当前源码**。

### R1.2 CI 引用的归因边界（照实登记）

PR #4710 的 `statusCheckRollup` 全绿，但该 rollup 的 run `35484666211`（`PR Check`，`event=pull_request`）的 `head_sha` = **`9d8d65439b36068ffd1d4fd2fb30ac1c311e9052`**，**不是** merge commit `efa59d98a`。
`gh api "…/actions/runs?head_sha=efa59d98a…"` 只返回一条 `case-redraft :: completed/skipped`。
⇒ **本报告不引用该 CI 作为"交付源码已验"的证据**；全部机器判定取自 R1 的**本地直接执行**（源码逐字节等同交付件）。

---

## R2 · 端到端可达性（v1.11 三问）

### R2.1 谁发射 / 哪个入口可达

`page.tsx` @efa59d98a（`Promise.allSettled` 内，`:986`）：

```
      productionApi.getOperationPositions(),
      // ①- 两层分区读面（issue #4677；后端 #4676）：`operations` / `delivery` 两段 + 「打包发货」的一列价
      productionApi.getOperationLayers(),
```

`page.tsx:1012-1018`（消费）：

```
    // 两层分区（issue #4677）：`operations` / `delivery` 两段 + 「打包发货」的一列价
    // （`price_state` 逐字用服务端聚合 —— 前端不重算，见 §4.5 方案 A 的 3 条规则）
    setDeliveryAgg(layersRes.status === 'fulfilled' ? layersRes.value.data?.data?.delivery ?? [] : [])
```

`lib/api.ts:537-538`：

```
  getOperationLayers: () =>
    request.get<ApiResponse<OperationLayers>>('/api/admin/production/operation-layers'),
```

入口可达：`page.tsx:2668` 的 tab 定义里 `{ key: 'operations', label: '工艺项' }` 是**默认 tab**（`useState` 初值）；`craft-operations-panel` 在 `tab === 'operations'` 分支内 ⇒ **首屏即触发**，无需二次跳转。

### R2.2 有无测试钉住

`production-routings.test.tsx:4105-4116`：

```
  it('端点接入（验收协议 v1.11）：页面**真的调** `GET /operation-layers`（文件在 main ≠ 被触发）', async () => {
    await renderOperations()
    // 红证：改前 `operation-layers` **零前端调用点**（文件在 main、无人触发）⇒ 这条必红
    expect(mockGetOperationLayers).toHaveBeenCalled()
  })

  it('端点接入（验收协议 v1.11）：入口可达 —— 打开「工艺项」tab（默认 tab）即触发，无需二次跳转', async () => {
    render(<ProcessConfigPage />)
    // 默认就落在「工艺项」tab ⇒ 首屏渲染即触发（不是藏在某个二级入口后面）
    await waitFor(() => expect(screen.getByTestId('delivery-section')).toBeInTheDocument())
    expect(mockGetOperationLayers).toHaveBeenCalledTimes(1)
  })
```

**三问齐备 ⇒ 交付物可达（不再是 P0-1 的"零调用点"）。** 红证见 R3-INJ1。

---

## R3 · 红证矩阵（注入式负向夹具）

### R3.0 方法与卫生（issue #4260 / 协议 v1.12）

每条按 `migao-acceptance` 铁律 2 执行：**① 记基线内容指纹 → ② 注入 → ③ 自证注入生效（sha256 变化）→ ④ 清缓存 → ⑤ 跑目标测试 → ⑥ 还原 → ⑦ 自证还原 = 基线指纹**。

- **指纹用 `sha256` 内容指纹**，**禁用 mtime / size**（同秒 + 同字节长度替换会让 TS 转换缓存复用旧产物 ⇒ 假绿证）。
- 每轮注入前后 `rm -rf node_modules/.vite .next/cache`（`scripts/red_proof.py` 的 JS/TS 载体白名单同款）。
- **锚点 = 逐字节内联片段**（`python3` 精确替换，要求唯一命中 `count == 1`，否则 `INJECT_ANCHOR_FAIL` 直接失败，绝不静默）；**不读 `origin/main`**。
- **锚点文本出处**：全部锚点取自 **`@efa59d98a` 的交付源码**（= 上表 sha256 的文件），非移动靶。

harness 在 `/tmp/rp.sh`（验收期一次性工具，**不入库**）：

```bash
BASE=$(shasum -a 256 "$PAGE" | cut -d' ' -f1)
python3 - "$PAGE" "$INJ" <<'PY'   # 锚点必须 count==1
...
p.write_text(src.replace(old, new))
PY
NEW=$(shasum -a 256 "$PAGE" | cut -d' ' -f1); [ "$BASE" = "$NEW" ] && echo INJECT_NOOP && exit 3
rm -rf node_modules/.vite .next/cache
npx vitest run tests/unit/pages/production-routings.test.tsx -t "$PAT"
# 还原后：REST=$(shasum -a 256 "$PAGE"); [ "$BASE" != "$REST" ] && echo RESTORE_FAIL
```

### R3.1 结果总表

| # | 注入（把被测行为改坏） | 目标用例 | 期望 | 实测 |
|---|---|---|---|---|
| INJ1 | 把 `productionApi.getOperationLayers()` 换成 `Promise.resolve({operations:[],delivery:[]})`（= 模拟改前"零调用点"） | `端点接入（验收协议 v1.11）` ×2 | 红 | **RED_OK**（`Tests 2 failed \| 168 skipped`） |
| INJ2 | `matrixColumnsOf` 返回 `[...present]`（列不收窄 ⇒ `布料` 当第 4 列） | `B4` | 红 | **RED_OK**（`1 failed`） |
| INJ3 | `FABRIC_SHEET_OPERATIONS` 置空（隐藏【布料单】小区） | `硬要求：商家能…` | 红 | **RED_OK**（`1 failed`） |
| INJ4 | 删掉 `deliveryAgg.forEach((r) => byOp.set(r.operation, r))`（第二层行改为依赖矩阵格） | `B6-①` | 红 | **RED_OK**（`1 failed`） |
| INJ5 | 折叠条件恒真（`{true &&`） | `B2` | 红 | **RED_OK**（`1 failed`） |
| INJ6 | `routingsReady` 回退成 `routeList.length > 0 && emptyShells.length === 0`（= 数条数） | `§6-② 就绪度②` | 红 | **RED_OK**（`1 failed`） |
| INJ7 | 补套入口回退成 `{!operationsReady && (`（= 只在工序库为空时显示） | `§6-① 补套入口改成` | 红 | **RED_OK**（`1 failed`） |
| INJ8 | `unpriced` 分支渲染成 `{money(0)}`（= 未定价显示成 ¥0.00） | `B7-①` | 红 | **RED_OK**（`1 failed`） |
| INJ9 | `multiple_prices` 分支渲染成 `{money(row.price ?? 0)}`（= 静默取第一个） | `B7-②` | 红 | **RED_OK**（`1 failed`） |
| INJ10 | `no_applicable_position` 分支渲染成 `未定价`（谎报） | `B7-③` | 红 | **RED_OK**（`1 failed`） |
| INJ11 | 空态（`manageVariants` 为空）时隐藏「停用/删除」（= #4674 死路本体） | `B6-②` | 红 | **RED_OK**（`1 failed`） |
| INJ12 | `removeOpByName` 的 `if (opDeleteBlockerCells.length > 0)` 改 `if (false)`（= #4692 路径回退成一律普通删除） | `4692` | 红 | **RED_OK**（`Tests 4 failed \| 2 passed`） |
| INJ13 | 列只保留 `布料` 一列 | `B4` | 红 | **RED_OK**（`1 failed`） |
| INJ14 | 列返回 `[]`（一列都没有） | `B4` | 红 | **RED_OK**（`1 failed`） |
| **对照** | **锚点不改（old == new）** | `B6-②` | **不报红** | **INJECT_NOOP**（harness 明确报"注入未生效"⇒ 证明 harness **不会假报红**） |

逐条原始输出（关键行）：

```
═══ INJ1: 去掉 operation-layers 调用 ⇒ 期望红
   × … > 端点接入（验收协议 v1.11）：页面**真的调** `GET /operation-layers`（文件在 main ≠ 被触发） 63ms
   × … > 端点接入（验收协议 v1.11）：入口可达 —— 打开「工艺项」tab（默认 tab）即触发，无需二次跳转 16ms
      Tests  2 failed | 168 skipped (170)
RESULT INJ1-nolayers RED_OK (测试如预期变红)

═══ INJ2: 列不收窄（把 布料 当第 4 列渲染）⇒ 期望红
   × … > B4 `布料` **不出现在列头**（列收窄到部位词表）；但读面那一格**仍在**（孤儿判据 #4614 的载体） 85ms
      Tests  1 failed | 169 skipped (170)
RESULT INJ2-widecols RED_OK (测试如预期变红)

═══ INJ3: 隐藏【布料单】小区 ⇒ 期望红
   × … > 🔴 硬要求：商家能在**明确、可见**的位置给布料单的 `裁剪` + `打包` 定价，**且不依赖矩阵里存在「布料」列** 52ms
RESULT INJ3-nofabric RED_OK (测试如预期变红)

═══ INJ4: 第二层的行改为依赖矩阵格 ⇒ 期望红
   × … > B6-① 交付环节的行**不依赖矩阵格**：某道交付工序一格都没有 ⇒ 仍有行 + `管理▸`（**红证**：改前 #4674 死路） 57ms
RESULT INJ4-deliverydependscells RED_OK (测试如预期变红)

═══ INJ5: 分组不折叠（始终展开）⇒ 期望红
   × … > B2 「工序」区**按车间分组可折叠**（行业术语：裁剪（裁床）/ 车位（缝制）/ 后整（烫工及后整）/ 质检）；界面**不出现「槽位」** 103ms
RESULT INJ5-nofold RED_OK (测试如预期变红)

═══ INJ6: 就绪度② 回退成"数条数" ⇒ 期望红
   × … > §6-② 就绪度②从「**数条数**」改成「**两条基础路线是否齐**」并**点名** 59ms
RESULT INJ6-countonly RED_OK (测试如预期变红)

═══ INJ7: 补套入口回退成"只在工序库为空时显示" ⇒ 期望红
   × … > §6-① 补套入口改成「**缺失即显示**」（幂等）… 71ms
RESULT INJ7-seedonlyempty RED_OK (测试如预期变红)

═══ INJ8: 未定价渲染成 ¥0.00（回落工序库行价）⇒ 期望红
   × … > 反向护栏 B7-①：一列价**未定价 ≠ ¥0.00**（改前回落工序库行价会把「未定价」变成真 0 元 ⇒ 工人白干） 64ms
RESULT INJ8-zero RED_OK (测试如预期变红)

═══ INJ9: multiple_prices 静默取第一个价 ⇒ 期望红
   × … > 反向护栏 B7-②：各部位不同价 ⇒ **显式提示 + 计数**（**不静默取第一个**） 65ms
RESULT INJ9-multi RED_OK (测试如预期变红)

═══ INJ10: no_applicable_position 谎报成"未定价" ⇒ 期望红
   × … > 反向护栏 B7-③：一格「做」都没有 ⇒ 如实报出（`no_applicable_position`），不假装成 0 元或未定价 70ms
RESULT INJ10-noapp RED_OK (测试如预期变红)

═══ INJ11: 空态（manageVariants 为空）时停用/删除消失 = #4674 死路本体 ⇒ 期望红
  [注入自证] sha256 017660477835219b0908d6e7a518369e4a7d388274ef4c422f8c123da2a003e9 -> 5aee3ffd1bc52e5a6289696d3c4fa7959dfa3016d81835b45896cde93b4911d6
RESULT INJ11-indrawerloop RED_OK (测试如预期变红)

═══ INJ12: #4692 删除路径回退（一律普通删除）⇒ 期望红
   × … > #4692-E 护栏**不放宽**：仍挂在主线/规则 ⇒ 新路径（detach）**照样被拦**… 5006ms
      Tests  4 failed | 2 passed | 164 skipped (170)
RESULT INJ12-nodeatch RED_OK (测试如预期变红)

═══ INJ13: 只保留"布料"列 ⇒ 期望红
   × … > B4 … 177ms
RESULT INJ13-B4weakassert RED_OK (测试如预期变红)
═══ INJ14: 列返回 []（一列都没有）⇒ 期望红
   × … > B4 … 82ms
RESULT INJ14-onlyfabriccol RED_OK (测试如预期变红)

═══ 对照（锚点不变）⇒ 预期不报红
RESULT INJ11-indrawerloop INJECT_NOOP
```

每轮结束后 `shasum -a 256 page.tsx` 恒为 `017660477835219b0908d6e7a518369e4a7d388274ef4c422f8c123da2a003e9`，且 `git status --porcelain` 为空。

### R3.2 一处**空断言**（恒真）的实测定位 —— B4 里的夹具自证

`production-routings.test.tsx:3893-3910`（B4 用例尾部）：

```
    expect(within(workshop).queryByTestId('matrix-cell-裁剪-布料')).toBeNull()
    // ⚠️ **不得**把 `布料` 从读面响应里删掉：它是 `variant_operation_id` 的载体，
    // 也是 V88 的保命格 ⇒ 它只在**列**里退场，在**数据**里一字不动
    expect(LAYER_CELLS.some((c) => c.position === '布料' && c.operation === '裁剪')).toBe(true)
```

最后一条断言的**真值与被测行为无关**（它读的是**测试自己的夹具常量** `LAYER_CELLS`，不是渲染结果/页面数据）⇒ 按 `migao-acceptance`「空断言（恒绿）」形态，**无论页面怎么改都恒真**。

- **红证定位实测**：INJ13（列只留 `布料`）/ INJ14（列返回 `[]`）都让 B4 变红，说明 B4 **整体**有效；但红的是它**前面**的渲染断言（`getAllByRole('columnheader')` / `queryByTestId(...).toBeNull()`），**不是**最后那条。
- ⇒ 判定：**B4 有效，但其最后一条断言是空断言**（P2，见报告 §5-P2-3）；同时**没有**任何断言钉住"读面响应里 `布料` 那一格仍在"（真正的风险点），该缺口如实登记。

---

## R4 · 用户旅程逐点采集（剧本 → 判定）

| 步 | 用户动作 | 期望的用户可见结果（可判定谓词） | 采集方式 | 结果 |
|---|---|---|---|---|
| J1 | 进「工艺项」tab（默认） | 页面发 `GET /operation-layers`（恰好 1 次） | L1 `4105/4111` + R3-INJ1 | ✅ 触发 |
| J2 | 看第一屏 | 出现 `data-testid="delivery-section"`，标题逐字 `【打包发货】` | L1 `B3` + 读码 `:2912/2914` | ✅ |
| J3 | 看【工序】区 | 4 个可折叠组：`裁剪（裁床）`/`车位（缝制）`/`后整（烫工及后整）`/`质检`；`aria-expanded` 可切 | L1 `B2` + R3-INJ5 | ✅ |
| J4 | 看列头 | 恰为 `工序 / 布帘 / 纱帘 / 帘头 / 元数据 · 操作`（**不含** `布料`） | L1 `B4` + R3-INJ2 | ✅ |
| J5 | 给「打包」定价 | 一行一价：`¥1.50/套`（4 个部位格聚合，**不是 4 格**） | L1 `B3` + R3-INJ4 | ✅ |
| J6 | 看未定价的交付工序 | `外帘装袋` 显示 `未定价`，**不含** `¥`（≠ ¥0.00） | L1 `B7-①` + R3-INJ8 | ✅ |
| J7 | 看各部位不同价的交付工序 | `外帘发货` 显示 `各部位不同价（2 处）`，两个价一个都不显示 | L1 `B7-②` + R3-INJ9 | ✅ |
| J8 | 看一格都没设「做」的交付工序 | `外帘打卷` 显示 `未设置（没有部位设为「做」）` | L1 `B7-③` + R3-INJ10 | ✅ |
| J9 | 进【布料单】小区 | 出现 `fabric-sheet-row-裁剪` / `fabric-sheet-row-打包`，各一列价 | L1 `硬要求` + R3-INJ3 | ✅ |
| J10 | 给 `裁剪 × 布料` 定价 | 就地编辑 ⇒ `PUT /operation-positions/lc-8`，body **恰为** `{unit_price: 8.5}` | L1 `硬要求`（`expect(Object.keys(...)).toEqual(['unit_price'])`） | ✅ |
| J11 | 该格缺失时 | 两个**可点**动作：`接入部位…`（真开接入弹窗）/ `补套行业模板`（真到补套入口） | L1 `硬要求·空态给出路` | ✅ |
| J12 | 就绪度② | 缺布料路线 ⇒ `data-state="todo"` + `基础路线 1/2 条 · 缺 布料工序路线` | L1 `§6-②` + R3-INJ6 | ✅ |
| J13 | 补套入口 | 工序库非空 ∧ 缺布料路线 ⇒ 入口**可见**（标题 `缺基础路线 · 补套行业模板`） | L1 `§6-①` + R3-INJ7 | ✅ |
| J14 | 打开某交付工序的 `管理▸`（该工序一格都没有） | 抽屉空态：`停用` / `删除` / `关闭` **都在** | L1 `B6-②` + R3-INJ11 | ✅ |
| J15 | **点**空态的「删除」 | 真能删（按钮 **enabled**，不是只渲染出来） | 验收探针（R4.1） | ✅ |
| J16 | 删除一道挂在矩阵上的工序 | 走 `detachPositions: true`（#4692 不回退） | L1 `4692-A…E` + R3-INJ12 | ✅ |
| J17 | 新建路线勾「布料」 | 勾选项含 `布料`，能建出 `positions=['布料']` | L1 `3074` describe（7 条） | ✅ |
| J18 | 加工单「第 N 套」 | 布料单实例化 = `裁剪`+`打包` **2 道** | **未采集**（无浏览器/无活库） | ⚠️ 见报告 §6 |
| J19 | 真实环境看【布料单】 | 用户真的看到入口 | **未采集**（交付件**未部署**） | ❌ 见报告 §4 |

### R4.1 验收探针：抽屉空态「删除」按钮是否 **enabled**（补强 B6-②）

B6-② 只断言 `toBeInTheDocument()`（元素存在）。**存在 ≠ 可点** —— 抽屉 footer 的两个按钮带 `disabled={variantBusy || !manageOpEntry}`（`page.tsx:3873/3882`）。若 `manageOpEntry` 为 null，"出路"就只是**装饰**。故独立加一条探针：

```ts
    // 验收探针：空态删除入口**真的可点**吗（enabled）？还是只是渲染出来但 disabled？
    expect(screen.getByTestId('operations-manage-delete')).not.toBeDisabled()
    expect(screen.getByTestId('operations-manage-disable')).not.toBeDisabled()
```

```
$ npx vitest run tests/unit/pages/production-routings.test.tsx -t "B6-②"
 ✓ tests/unit/pages/production-routings.test.tsx (170 tests | 169 skipped) 142ms
      Tests  1 passed | 169 skipped (170)
```

⇒ **enabled 成立**（`manageOpEntry` 在该夹具下非 null）。探针跑完已 `git checkout --` 还原测试文件（`git status` 为空）。

> ⚠️ 归因强度：这是**存在性 + 值级**证据（该夹具下按钮 enabled）。它**不**等于"任何数据形态下都可删" —— 若工序库读面（`operations-catalog`）查不到该逻辑名，`manageOpEntry` 为 null ⇒ 按钮 disabled 且只报一句理由（`openDeleteOpByName` 的 `if (!manageOpEntry)` 分支，`page.tsx:2337-2342`）。该分支**有**就地理由（不是死路），但**无测试钉住**（见报告 §5-P2-2）。

---

### R4.2 验收探针：硬要求写的是**两格**，交付测试只覆盖了其中一格

issue 硬要求逐字「给布料单的 `裁剪` **与** `打包` 定价」。交付测试 `:4002-4033` 只对 `裁剪 × 布料`（`lc-8`）做**写**断言；`打包 × 布料`（`lc-12`）只有**读**断言（`:4020` `toHaveTextContent('¥1.50')`）。

```
$ grep -n "'lc-12'" frontend/admin-web/tests/unit/pages/production-routings.test.tsx
3755:  { id: 'lc-12', operation: '打包', position: '布料', unit_price: 1.5, … }   ← 仅夹具定义，无写面断言
```

独立探针（加在 describe 末尾，跑完 `cp /tmp/test.bak2 "$T"` 还原，`git status --porcelain` 仅 `?? acceptance/2026-09-20/`）：

```ts
  it('【验收探针】硬要求写的是两格：`打包 × 布料` 是否也能就地写（lc-12）', async () => {
    await renderOperations()
    const fabric = screen.getByTestId('fabric-sheet-section')
    expect(within(fabric).getAllByTestId('matrix-cell-打包-布料')).toHaveLength(1)
    await userEvent.click(within(fabric).getAllByTestId('matrix-price-edit-打包-布料')[0])
    const input = within(fabric).getAllByTestId('matrix-price-input-打包-布料')[0]
    await userEvent.clear(input)
    await userEvent.type(input, '2.25')
    await userEvent.click(within(fabric).getAllByTestId('matrix-price-save-打包-布料')[0])
    await waitFor(() => expect(mockUpdateOperationPosition).toHaveBeenCalledWith('lc-12', { unit_price: 2.25 }))
    expect(Object.keys(mockUpdateOperationPosition.mock.calls[0][1] as object)).toEqual(['unit_price'])
  })
```

```
 ✓ tests/unit/pages/production-routings.test.tsx (171 tests | 170 skipped) 237ms
      Tests  1 passed | 170 skipped (171)
[exit code: 0]
$ shasum -a 256 page.tsx
017660477835219b0908d6e7a518369e4a7d388274ef4c422f8c123da2a003e9
```

⇒ **`打包 × 布料` 写面实测可写**（`lc-12`，body 恰为 `{unit_price}`）⇒ 记为 **P12b 成立**；但交付测试**没钉住**它 ⇒ 单列 **P2-7**（断言缺口，非功能缺陷）。
> ⚠️ 归因强度 = **值级**（该夹具下真的发出 `lc-12` 写请求）。**不**等于"任何形态都可写"：`lc-12` 缺失时走 `fabric-sheet-missing-打包` 空态分支（代码在 `:3074-3090`），而测试只覆盖了 `裁剪` 的空态（`:4035`）。

---

## R5 · 后端读面（#4676，已合并）四态实现核对

`ProductionRoutingReadService.java:217-256` @efa59d98a：

```java
    private Map<String, Object> deliveryView(String operation, List<Map<String, Object>> cells) {
        Set<BigDecimal> prices = new LinkedHashSet<>();
        List<String> applicablePositions = new ArrayList<>();
        boolean unpriced = false;
        for (Map<String, Object> cell : cells) {
            if (!Boolean.TRUE.equals(cell.get("applicable"))) { continue; }
            applicablePositions.add(String.valueOf(cell.get("position")));
            Object price = cell.get("unit_price");
            if (price == null) { unpriced = true; } else { prices.add(new BigDecimal(String.valueOf(price))); }
        }
        String priceState; BigDecimal price = null;
        if (applicablePositions.isEmpty())      { priceState = "no_applicable_position"; }
        else if (unpriced)                      { priceState = "unpriced"; }
        else if (prices.size() == 1)            { priceState = "priced"; price = prices.iterator().next(); }
        else                                    { priceState = "multiple_prices"; }
        view.put("different_price_count", "multiple_prices".equals(priceState) ? prices.size() : 0);
```

- `unpriced` **优先于** `multiple_prices`（既有未定价又有异价 ⇒ 报 `unpriced`）—— 与 §4.5 规则 2/3 的读法一致（"有 NULL ⇒ 未定价"先命中），**照实登记**为口径细节。
- 后端确定性测试：`backend/admin-api/src/test/java/com/migao/admin/service/ProductionOperationLayersTest.java`（`deliveryPriceIsOneColumnWhenAllPositionsAgree` / `…IsUnpricedWhenAnyApplicableCellHasNoPrice` / `…IsNotSilentlyTheFirstWhenPositionsDiffer` / `…IgnoresNotApplicableCells` / `deliveryRowSurvivesWhenOnlyOnePositionHasACell` / `operationsSectionIsShapeIdenticalToOperationPositions`）。

**「否决方案①」理由的独立核验**（issue 硬要求要求独立判断）：

```
$ sed -n '11,16p' backend/admin-api/src/main/resources/db/migration/V49__create_production_operations_and_work_logs.sql
CREATE TABLE IF NOT EXISTS production_operations (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(64) NOT NULL,                       -- 工序名（按部位分设：韩褶-布 / 韩褶-纱）
    group_name VARCHAR(16) NOT NULL DEFAULT '其他',  -- 车间工位分组：裁剪/车位/后道/其他
    position VARCHAR(16),                            -- 部位：布帘/纱帘/帘头/外帘（空=通用）
    unit VARCHAR(16) NOT NULL DEFAULT '米',           -- 计件单位：米/折/幅/孔/套/个
    unit_price NUMERIC(10,2) NOT NULL DEFAULT 0,     -- 计件单价（元/单位）
```

⇒ `production_operations.unit_price` **确为 `NOT NULL DEFAULT 0`** ⇒ 用它当"布料单按此价"的落点，会把**未定价**显示成**真 ¥0.00**（工人白干）⇒ **否决方案① 的理由成立**（**值级**证据：DDL 逐字）。

---

## R6 · 交付件是否到达活环境（用户可见性的前置）

```
$ gh run list --limit 60 --json workflowName,headSha,… --jq '.[] | select(.headSha|startswith("efa59d98"))'
2026-09-20T02:48:55Z case-redraft :: completed/skipped
（即：针对交付 SHA 的 deploy-* run = 0 条）

$ for wf in deploy-frontend.yml deploy-admin-api.yml deploy-ai-agent-service.yml; do
    gh run list --workflow=$wf --limit 1 --json headSha,createdAt,conclusion; done
deploy-frontend.yml:          b364a7eb5 2026-09-20T02:42:44Z success
deploy-admin-api.yml:         b364a7eb5 2026-09-20T02:42:29Z success
deploy-ai-agent-service.yml:  b364a7eb5 2026-09-20T02:42:36Z success
```

⇒ 三条部署腿最后一次成功部署的都是 **`b364a7eb5`**（`efa59d98a` 的**父提交**，`git log` 逐字）⇒ **#4677 的界面改造（含 `getOperationLayers` 调用点）尚未部署到任何活环境**。

```
$ curl -s -m 8 -o /dev/null -w "SWAS operation-layers HTTP=%{http_code}\n" https://api.migaozn.com/api/admin/production/operation-layers
SWAS operation-layers HTTP=401        # 服务在（鉴权拦下），但**无法**从外部判定部署 SHA / 迁移版本
$ curl -s -m 8 -o /dev/null -w "SWAS admin web HTTP=%{http_code}\n" https://admin.migaozn.com/
SWAS admin web HTTP=000               # 前端域名不可达（exit code 6）
```

⇒ 活环境**被测 SHA 不可得**、**迁移（V88/V89/V90）应用状态不可得** ⇒ 按协议 v1.9「活环境判定的快照一致性」，**本次不对活环境下任何判定**；用户可见结果**未达成**（缺部署），如实登记（报告 §4 / §6）。

### R6.1 依赖单状态（用户可见性的另两个前置）

```
$ gh issue view 4685 --json state,title
CLOSED | [P1·真库缺陷] V79 按租户派生块类型推断报错（NULL 列被推成 text）⇒ 非 1 号租户的布料工序/矩阵/路线可能从未种上（很可能就是「建不出纯布料路线」的真根因）
$ gh pr view 4706 --json state,title
MERGED | fix(db): #4685 补种 V79 漏掉的布料种子（按租户 + 显式 ::numeric + 幂等 + 不覆盖商家已改）
$ gh issue view 4707 --json state,title
OPEN   | [P0·真库缺陷·第二层根因] 租户 20/21 的 production_operations **0 行**，但矩阵 84 格 + 窗帘主线 9 道 ⇒ **窗帘单本来就 fail-closed 422**（与 V79 缺陷正交，叠加成「建不出单」）
```

---

## R7 · 假绿/假红自查（逐条对照协议形态）

| 形态 | 本次自查 |
|---|---|
| **空跑（v1.3）** | 本报告**不引用任何 CI run 作为判定证据**（R1.2 已核：PR rollup 的 run head 是 `9d8d65439`，非交付 SHA）⇒ 无"步骤 skipped / artifact 0 却 success"可乘之机；机器判定全部来自本会话**前台直接执行**且退出码可查 |
| **陈旧产物（v1.4）** | 每轮注入都 `rm -rf node_modules/.vite .next/cache`；源码 `sha256` 跑前跑后逐字核（R3.0）；被测源码与 `@efa59d98a` 逐字节相同（R0 表） |
| **红证自身骗人（v1.12 / #4260）** | **内容指纹 sha256**（非 mtime/size）+ 注入自证（`INJECT_NOOP` 会非零退出）+ 还原自证（`RESTORE_FAIL` 会非零退出）+ 锚点唯一命中（`count==1` 否则 `INJECT_ANCHOR_FAIL`）；另设**空跑对照**（old==new ⇒ 实测 `INJECT_NOOP`，证明 harness 不会假报红） |
| **红证锚点读可变引用（v1.13 / #4313）** | 全部锚点 = **逐字节内联片段**，出处 **`@efa59d98a`**；**不读 `origin/main`** |
| **基线快照晚于被测事件（v1.5）** | R4.1 的探针断言是"当前状态"型（`not.toBeDisabled()`），无"等新增/等变化"比较 ⇒ 无基线取晚问题 |
| **重放未复现前置条件（v1.7）** | R4.1 探针**显式复现了前置条件**（该夹具下 `manageVariants.length === 0`，即 #4674 的空态）并给出观测值（按钮 enabled）；未复现前置条件的场景（J18 加工单实例化）**不写结论** |
| **测试自建产物路径（v1.8）** | 未使用任何"按名拼产物路径"的断言；`vitest`/`shasum` 的路径全部直接取自被测文件真实路径 |
| **注释漂移（v1.4）** | 关键注释（`page.tsx:136-193` 的 `POSITION_DOMAIN`/`matrixColumnsOf`/`FABRIC_SHEET_*`；`:1310-1369` 的 `deliveryRows`/`fabricSheetRows`）**逐条与实现同源核对**，未发现与代码不符的断言性注释 |
| **真值主张（自毁式）** | 本次**未**产出任何"断言仓库当下恰有该缺陷"的判据 |
| **过渡帧/滞后帧（v1.4）** | 无截图/快照类证据被引用 |
| **假红** | 每条"期望红"的注入都同时满足"注入生效（指纹变化）∧ 目标用例真的失败"；另有 INJ14/INJ13 两个方向性对照确认 B4 红在**渲染断言**而非恒真断言 |
