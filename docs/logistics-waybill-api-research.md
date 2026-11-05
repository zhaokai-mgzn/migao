# 物流取号（电子面单）调研与口径 —— 四季安 / 聚合平台 / 直连承运商

> **本文的来历（重要，防止下一个人当二手资料用）**：issue **#7897** 的正文写「详见 `docs/logistics-waybill-api-research.md`」，
> 但该文件**从未入库**（2026-11-05 现取：`git ls-tree -r --name-only origin/main | grep waybill` 为空、
> `git log --all -- docs/logistics-waybill-api-research.md` 无历史）。
> ⇒ 本文是**按 issue 正文逐条落盘**的补登，不是新调研。所有结论的**时效见文末「复验方法」**，
> 域名可达性这类事实**会腐**，引用前请先复验。

## 一、需求（用户 2026-10-27 逐字）

- 「如果我想对接现有的物流接口，直接在销售单上一键生成物流号，这个要如何对接」
- 「现在客户直接对接的四季安软件」
- 「我们现在要做取号下单，查物流是顺带做」
- 「四季安可能没有标准的取号接口，你调研下有哪些物流/快递公司开放了取号接口」

## 二、调研结论（2026-10-27）

1. **取号能力只存在于「标准快递」与「快运」**；**专线（四季安）没有公开取号接口** ——
   `sja56.com` DNS 不解析、无官网/开放平台，公开可行的只有**轨迹查询**（快递100 单号页 / 51Tracking `SJA56`），
   其单子由第三方 TMS 出（公开案例：八米科技）。
2. **有官方开放平台的快递**（域名实测可达）：顺丰丰桥 `qiao.sf-express.com`、中通 `open.zto.com`、
   圆通 `open.yto.net.cn`、韵达 `open.yundaex.com`、申通 `open.sto.cn`、京东物流 `open.jdl.com`、
   EMS `api.ems.com.cn`、极兔 `open.jtexpress.com.cn`、菜鸟 `open.cainiao.com`；
   德邦官网可达但开放平台入口未确认（散客模式可经快递100）。
3. **快运/零担有「下单」接口但无电子面单**：安能 `op.ane56.com`、壹米滴答 `open.yimidida.com`、
   中通快运 `iop.zto56.com`、顺心快运 `www.sxjdfreight.com`、百世 `open.800best.com`。
4. **聚合平台一次覆盖多家**：快递100（电子面单/HTML 面单/云打印/大件寄件）、快递鸟（电子面单指令 1007/云打印）。
   **微信物流助手**可能省掉逐家签约（需核实能否服务端调用、面单归属）。

## 三、已定口径（2026-10-27 裁定，后续实现按此）

1. **取号是主线**；轨迹查询是副产品 —— 取号落 `tracking_no` 后，客服侧 `logistics_track` 与
   C 端 `customer_logistics_track` **零改动**即可用，只需补一条 carrier → 查询编码映射。
2. **取号 ≠ 发货**：取号成功后订单仍「待发货」，必须人点「确认发货」；
   **现有 `ship` 端点一行不改**（避免「未交件却已发货」）。
3. **无 API 承运商降级**：四季安走「导出/剪贴板 + 单号回填」，并同步把「申请开放接口」挂商务待办。
4. **不做 RPA 驱动客户端**（登录态/验证码/界面改版/账号合规/审计断链；且 SaaS 浏览器够不到客户本地 exe）；
   **前端不直连承运商**（密钥不进浏览器）；**面单账号必须每租户自己的**（平台不代付，合规+对账双风险）。
5. **抽象 `WaybillProvider` + 承运商注册表（能力位 `canCreate`/`canCancel`/`canTrack`）**：
   未接入的承运商自动退回 manual（= 今天的手填能力），「支持多家」= 加配置而不是加流程。

## 四、分期（本单只记录，不实现）

| 期 | 内容 | 依赖 |
|---|---|---|
| P0 | `WaybillProvider` 抽象 + 承运商注册表 + manual 兜底 + 租户级配置（`/settings?domain=logistics`，真值源 `frontend/admin-web/src/lib/config-center-domains.ts`） | 无 |
| P1 | 接 **1 家聚合平台**（快递100 或快递鸟）覆盖标准快递 + 快运 | 账号/沙箱 |
| P1′ | 四季安：导出/剪贴板 + 单号回填 + 轨迹映射（**不依赖任何外部账号**） | 无 |
| P2 | 评估微信物流助手（若「一键寄件」发生在小程序内） | 官方边界确认 |
| P3 | 单量大时直连 1~2 家（顺丰/京东） | 月结账号 |
| P4 | 面单打印（云打印或本地控件）+ 取消/作废闭环 | 纸型与现有 241×140 三联纸不同，单开一条链 |

## 五、现状（代码真值，2026-10-27）

| 环节 | 位置 |
|---|---|
| 发货页手填单号 | `frontend/admin-web/src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx`（「快递单号」= `<input placeholder="请输入快递单号">`） |
| 原子发货端点 | `POST /api/admin/production/orders/{orderId}/ship`（`ProductionController#ship`；权限 `production:execute`；`X-Client-Request-Id` 幂等；单事务三步写序，issue #6181 / #6983） |
| 物流 / 发货单表 | `order_logistics`（公司+单号+状态）、`order_shipments`（发货事实） |
| 现有第三方物流对接 | **仅轨迹查询**：`backend/ai-agent-service/app/tools/logistics_track.py`、`customer_logistics_track.py` |

## 六、三个数据前置（P0 的真实阻塞项，不是 P1 的）

1. **收货地址是自由文本**：订单只有 `orders.customer_address` 单列 TEXT，无省/市/区/街道
   （`customer_profiles` 也只有 `default_receiver_address TEXT`）⇒ 取号前需地址解析或补全，
   失败 **fail-closed**（不拿脏地址下单，面单打歪比报错贵）。
2. **无重量 / 包裹件数**：取号时给默认值且页面可改，落本次运单，**不进商品主数据**。
3. **无寄件人档案**：`order_logistics.shipper_name` 只是「经手人姓名」，不是寄件人信息 ⇒
   租户级配置（默认发货地址）+ 页面临时覆盖。

## 七、待确认（须官方答复，**不得按二手资料拍板**）

1. 四季安（或其 TMS）是否有系统对接接口？开通条件？
2. 中通/圆通/韵达/申通/顺丰：**是否允许第三方 SaaS 代商家调用**（ISV 资质/授权书）？
3. 京东物流：无界电子面单对非京东店铺商家是否开放？
4. 菜鸟：无淘宝店铺的商家能否开通电子面单（ISV 路径成本）？
5. 极兔 / EMS：月结门槛（月单量下限）？
6. 德邦：开放平台真实入口 + 散客模式差异？
7. 快递100 / 快递鸟：**专线（四季安等）是否支持下单**（多数仅轨迹）、单笔费用、是否有沙箱？
8. 微信物流助手：能否**服务端**调用（非小程序内）、面单账号归属、是否支持外部订单？
9. 各平台**取消窗口期**与失败语义（跨日作废 / 已揽收作废）？
10. 各平台**回调/推送**是否支持（否则只能轮询）？

## 八、实现时必须落的验收判据（登记，实现时逐条兑现）

- **幂等**：同单重复点击 / 超时重试 ⇒ 只出一张运单
  （DB 唯一索引 `<order_id> WHERE status NOT IN ('cancelled','cancel_failed')` + `ClientRequestIdService`）；
- **并发**：两请求并发 ⇒ 一张运单（真库判据），与 #6965 同族口径；
- **失败分类**：未配置 / 地址不完整 / 超区 / 月结余额不足 / 上游超时 / 上游拒单，
  各给**可行动文案**（笼统「服务不可用」会让商家反复点 = 重复计费）；
- **密钥面**：承运商凭据只进服务端、按租户存；前端产物里**不得**出现任何承运商密钥（grep 判据）；
- **取号不改变订单状态**：取号成功后 `orders.status` 不变（这条最容易被"顺手"实现错）。

## 九、域名可达性实测（**2026-11-05 本机复验**，与 2026-10-27 结论一致）

```bash
for h in qiao.sf-express.com open.zto.com open.yto.net.cn open.yundaex.com open.sto.cn \
         open.jdl.com api.ems.com.cn open.jtexpress.com.cn open.cainiao.com \
         op.ane56.com open.yimidida.com iop.zto56.com open.800best.com sja56.com; do
  printf '%-28s ' "$h"; curl -s -o /dev/null -m 6 -w '%{http_code}\n' "https://$h/" 2>/dev/null || echo "DNS/连接失败"
done
```

| 承运商 | 域名 | HTTP | 判定 |
|---|---|---|---|
| 顺丰丰桥 | `qiao.sf-express.com` | 200 | ✅ 在 |
| 中通 | `open.zto.com` | 200 | ✅ 在 |
| 圆通 | `open.yto.net.cn` | 200 | ✅ 在 |
| 韵达 | `open.yundaex.com` | 200 | ✅ 在 |
| 申通 | `open.sto.cn` | 200 | ✅ 在 |
| 京东物流 | `open.jdl.com` | 200 | ✅ 在 |
| EMS | `api.ems.com.cn` | 200 | ✅ 在 |
| 极兔 | `open.jtexpress.com.cn` | 200 | ✅ 在 |
| 菜鸟 | `open.cainiao.com` | 200 | ✅ 在 |
| 安能（快运） | `op.ane56.com` | 404 | ✅ 在（根路径 404，非 DNS 失败） |
| 壹米滴答（快运） | `open.yimidida.com` | 200 | ✅ 在 |
| 中通快运 | `iop.zto56.com` | 200 | ✅ 在 |
| 百世（快运） | `open.800best.com` | 200 | ✅ 在 |
| **四季安（专线）** | `sja56.com` | **DNS/连接失败** | 🔴 **复验证实**：确实没有公开入口 |

⇒ **第二次独立复验（2026-11-05，相隔 9 天）与 2026-10-27 的结论逐条一致**，
其中「四季安没有公开取号接口」这一条**用两种方式各证一次**（DNS 不解析 + 无官网/开放平台）。
**判定口径**：`200/301/302/403/404` 都算「域名在」（404 只说明根路径没内容，不等于平台没了）；
**只有 DNS 不解析 / 连接失败**才是「真没了」。

## 十、其他复验（路径会随切片移动，引用前先跑）

```bash
# 本文引用的代码面是否还成立
git ls-tree -r --name-only origin/main | grep -E 'tools/(customer_)?logistics_track\.py|ship/ShipOrder\.tsx'
```



```bash
# ① 官方开放平台域名可达性（200/301/302/403 都算「在」；DNS 不解析才是真没了）
for h in qiao.sf-express.com open.zto.com open.yto.net.cn open.yundaex.com open.sto.cn \
         open.jdl.com api.ems.com.cn open.jtexpress.com.cn open.cainiao.com \
         op.ane56.com open.yimidida.com iop.zto56.com open.800best.com sja56.com; do
  printf '%-28s ' "$h"; curl -s -o /dev/null -m 6 -w '%{http_code}\n' "https://$h/" 2>/dev/null || echo "DNS/连接失败"
done

# ② 本文引用的代码面是否还成立（路径会随切片移动）
git ls-tree -r --name-only origin/main | grep -E 'tools/(customer_)?logistics_track\.py|ship/ShipOrder\.tsx'
```

**本文的时效边界**：结论来自 **2026-10-27**，其中「域名可达」与「是否支持某能力」两类**必须复验**后再引用；
「已定口径」（第三节）与「待确认」（第七节）是**决策记录**，不因时间失效，改它们要写明新的裁定出处。

**实测锚点**：第九节的表格是 **2026-11-05** 的本机实测（不是抄 10-27 的结论）；两次相隔 9 天、结论一致 ⇒
这组域名的稳定性可以当作「P1 选型前的可用输入」，但**签合同前**仍需按第九节的命令再过一遍（域名会易手、平台会下线）。
