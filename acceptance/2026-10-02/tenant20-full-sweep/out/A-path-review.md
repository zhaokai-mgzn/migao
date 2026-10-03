# A 路独立复核报告（tenant20-full-sweep / out/ JSON 证据）

- 复核时间：2026-10-03（Asia/Shanghai）
- 复核人：A 路独立复核子代理（不信任任何结论文档文字，仅以 out/ 目录 JSON 原始数据为据；SUMMARY.md / R2-*.md 仅用于发现口径矛盾，不作为判定依据）
- 复核方法：python3 解析全部 24 个 .json（含子目录），0 个解析失败；对关键声明逐条用原始数据重算，而非复读 detail 文字。

## 一、逐文件计数表

| 文件 | 内容 | pass=N fail=M | 状态 |
|---|---|---|---|
| context.json | 参照数据（tenantId=20，员工 7 + 7 岗位码表，chain/h5Chain） | —（参照，非断言集） | ✅ |
| permission-surface-main.json | 参照快照：meta(commit b7fd8fa4…@origin/main, 2026-10-02T23:19+08) + 115 端点权限标注 | —（参照） | ✅ |
| route-guard-map-main.json | 参照快照：commit 402be478…，40 条前端路由 + 22 条 API 前缀→权限码 | —（参照） | ✅ |
| s2-seed.json | 阶段2 多岗位员工 + 工人档案 | pass=23 fail=0 | ✅ |
| s20-inventory.json | 阶段2 库存侧 | pass=18 fail=0 | ✅ |
| s21-craft-init.json | 阶段2 工艺侧 | pass=18 fail=0 | ✅ |
| s3-rbac.json | 阶段3 RBAC 第一轮 | pass=22 fail=0 | ✅ |
| s3-rbac-matrix.json | 160 探针 | mismatch=0 | ✅ |
| s3b-rbac2.json | 阶段3b 第二轮 | pass=29 fail=0 | ✅ |
| s3b-write-matrix.json | 56 写探针 | mismatch=0 | ✅ |
| s3b-order-create-escalation.json | 7 岗位越权下单探针（原始数据，无 status 字段） | 7/7 escalated=False、createdId=None、httpStatus=422 ⇒ 无越权 | ✅（原始数据，无判定字段） |
| s3c-rbac3.json | 阶段3c 第三轮 | pass=15 fail=0 **skip=1** | ❌（1 skip，见下） |
| s4-docs.json | 阶段4 功能单据逐项（两轮） | pass=40 fail=0 | ✅ |
| s5-h5.json | 阶段5 B 端 H5 工人端 | pass=15 fail=0 | ✅ |
| s6-chain.json | 阶段6 连贯链路 | pass=18 fail=0 | ✅ |
| s6-chain-flow.json | 链路终态快照（10 节点） | 与 context.chain / s6 逐项一致（见三-4） | ✅ |
| s7-rbac-matrix.json | 阶段7 矩阵元断言 M-00~M-03 | pass=5 fail=0 | ✅ |
| s7-matrix.json | 115 端点 × 8 身份 = 920 格 | violations=0（326 ALLOW + 570 DENY + 24 无法判定，独立重算一致） | ✅（含口径说明，见三-2） |
| s7-matrix-raw.json | 同 920 格的原始响应 | 与 s7-matrix.cells 完全同值，仅少 verdict 字段（verdict 为后处理） | ✅ |
| s8-routes.json | 8 身份 × 40 路由 = 320 行 | denied==expected 320/320，mismatch=0 | ✅ |
| s8-buttons-employees.json | 8 身份按钮门控 | 8/8 ok；canWrite/新增/编辑/重置仅管理员 True | ✅ |
| s8-routes-buttons.json | RT-01×8 + RT-02 + BTN-01 | pass=10 fail=0 | ✅ |
| s9-position-jobs.json | 阶段9 每岗位自带账号跑本岗位功能 | pass=10 fail=0 | ✅ |
| smoke-results.json | UI 冒烟结果 | **仅 1 条**：17-order-ship pass=true | ⚠️ 覆盖缺口（见三-5） |

自建断言合计：**pass=233 / fail=0 / skip=1**（s2+s3+s3b+s3c+s4+s5+s6+s7+s8+s9+s20+s21）。

## 二、关键声明的独立重算结果（均通过）

1. **RT-01 八身份路由守卫**：s8-routes.json 320 行逐行重算 denied==expected 全一致；拦截数与 s8-routes-buttons 声明逐一相符（admin 0 / 客服 20 / 运营 2 / 销售 22 / 财务 26 / 商品 20 / 知识 31 / 临时岗 32）。
2. **RT-02 仅 notifications 无守卫**：用 route-guard-map-main.json 的 22 条前缀对 40 条路由做前缀子序列匹配，重算「无前缀覆盖」的路由恰为 1 条 = notifications/page.tsx，与 RT-02 一致。旁证：s8-routes.json 中 8 身份全可打开的路由共 3 条（briefing/dashboard/notifications），前两条有 dashboard:view 守卫只是人人持有，notifications 确为唯一无守卫路由。
3. **BTN-01 按钮门控**：s8-buttons-employees 8/8 ok，仅管理员可写；context.json 7 个非管理岗的 expectedPerms 均不含 employee:create（含 employee:list 的仅运营），与按钮隐藏一致。
4. **s7 全量矩阵「零违规」**：按 verdict-vs-expected 重算 920 格：350 个 expected=allow 中 326 判 ALLOW、24 判 EARLY（无法判定）；570 个 expected=deny 全部判 DENY（403 PERMISSION_DENIED），**0 个 verdict 与 expected 相悖**。200 个非 2xx 的 allow 格全部带 note 且「同行非持有者全 403」反证控制 100% 成立（0 行反证失败）。EARLY 24 格 = files/upload、files/upload-batch、upload/image 三端点 × 8 身份：探针在权限层之前被 422/400 挡下（文件类型/请求体校验先行），行内无 403 对照 ⇒ 运行方如实标「无法判定」并逐格留痕（M-01 detail 亦明示 24 格），未冒充全绿。
5. **s7 与权限面参照一致**：permission-surface-main.json 115 端点与 s7 的 115 端点集合完全相同，method/path/perm 标注 0 差异。
6. **s7-matrix vs s7-matrix-raw**：920 格原始数据同值，raw 仅缺后处理加上的 verdict 字段，非数据冲突。
7. **s3b 越权下单**：7 岗位全部 httpStatus=422、createdId=None、escalated=False ⇒ 无越权成立（该文件为原始探针数据，无 status 字段，如实标注）。

## 三、发现的问题 / 口径缺口（如实记录，均非「假绿」）

1. **[skip] s3c RBAC3-04**「路由守卫缺口实测：/notifications」skip，detail=「无『缺 null』的样本身份」。skip 非通过；其目标已被 RT-02 现场复核覆盖（notifications 确为唯一无守卫路由，已如实标注为已知缺口）。
2. **s7 矩阵存在 24 格「无法判定」**（3 个文件/上传端点 × 8 身份）：这 3 端点的 RBAC 行为在本证据集中**未经证实**（探针在权限层前被挡），且 s3-rbac-matrix / s3b-write-matrix 亦无 files 相关探针（0 条）。「violations=0」的准确含义是「已判定的 896 格零违规」，6 行无 403 反证（files/upload、files/upload-batch、files/{fileId} DELETE、upload/image POST/DELETE、upload/images）已在 M-02 中逐条披露（109/115 行有反证）。另观察到 POST /api/admin/roles 在管理员行返回 500 INTERNAL_ERROR（同行非持有者 403 反证成立，权限面结论不受影响，但属可复核的服务端异常，建议后续归因）。
3. **SUMMARY.md 过期（文档矛盾，非证据缺陷）**：其阶段8 仍记 fail=1（RT-FATAL TypeError），与当前 s8-*.json（2026-10-03 02:32 重跑全绿）不符；阶段7 描述「111 端点 × 9 身份」与实际 JSON「115 端点 × 8 身份」不符；且未收录 s20/s21 阶段行。以 JSON 为准，SUMMARY.md 需重新生成。
4. **s6 链路单号口径**：s6-chain-flow 的「批次消耗」记录挂在加工单 JG-20261002-5094 / 订单 20261002950190004 下，与 CH-17（派工指定批次支线）detail 完全一致，属链路⑩的支线而非矛盾；主链订单 20261002267720003 / 加工单 JG-20261002-5093（completed, 工序 12/12, 报工 12 条 75.00 米 31.40 元）与 context.chain、CH-08/CH-12/CH-14 一致。另一观察：CH-16 的日志示例行来自 tenant=24（共享日志中他租户的行），仅示例选取问题，链路各步均有 DB/页面证据。
5. **UI 冒烟覆盖缺口（本目录内最重要的证据缺口）**：smoke-results.json 仅含 1 条旅程（17-order-ship，pass=true，2026-10-02T17:38Z = 01:38+08）；任务点名的 16/17/23/24/32 五条旅程中，**16/23/24/32 在本证据目录内没有任何机器判定 JSON**（screenshots/ 有对应旧截图，但截图≠L1 判定）。SUMMARY.md 亦自述「33 旅程 UI 冒烟未产出，12 条失败归因为脚本过期（见 REPORT.md）」。⇒ 「UI 冒烟层面全绿」**不能**由本目录证据支持。

## 四、结论（一句话）

**证据支持：「自建 L1 断言层面全绿」——233 pass / 0 fail / 1 skip（skip 已如实披露），且 RBAC 矩阵、路由守卫、按钮门控、连贯链路、H5、岗位功能经独立重算与声明一致；证据不支持：「全量（含 33 旅程 UI 冒烟）L1 全绿」——冒烟仅有 17-order-ship 一条 JSON 证据，16/23/24/32 无机器判定，另有 3 个文件/上传端点的 RBAC 行为属「无法判定」、SUMMARY.md 为过期文档。**

## 五、复核可复现方式

对 out/ 下每个 .json 用 python3 解析并重算：列表文件的 status 计数；矩阵文件的 expected-vs-verdict 对照 + 行内 403 反证；s8-routes 的 denied==expected 逐行比对；route-guard-map-main 前缀对 40 路由的覆盖匹配。全程未运行任何测试、未连接数据库、未改动 out/ 内除本文件外的任何文件。
