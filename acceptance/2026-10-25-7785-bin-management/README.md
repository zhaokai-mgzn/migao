# 仓位管理 UI 多模态验收（issue #7785）

- **被测**：`feat/7785-warehouse-bin-management`（本目录同 commit；代码 = 出库单页第三页签 + `WarehouseLocationPanel`）。
- **入口**：`http://localhost:3001`（§15.7 本机唯一入口）；admin-api = 本 worktree 的 `:8080`。
- **登录**：管理员手机验证码（`13900001025` / 测试环境 bypass `123456`）。
- **采样**：2026-10-25 22:58 +08（Asia/Shanghai），视口 1440×980。采证 SHA `75a13b656`；此后仅把状态列从徽标改成「点 + 文字」（表格有行时才可见）并把删除确认里的「快照」改成商家说法，空态与新建弹窗未变。
- **命令**：

```bash
# 空态 + 页签
MIGAO_REPO_ROOT="/Users/guangzhen.zk/ai native/migao" \
node "$HOME/.dsh/.agent-presets/migao/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs" \
  --site http://localhost:3001 --path /outbound-orders --phone 13900001025 --code 123456 \
  --click 仓位管理 --shot warehouse-location-panel --out /tmp/ui-acceptance-7785-final

# 新建弹窗（只打开，不提交）
MIGAO_REPO_ROOT="/Users/guangzhen.zk/ai native/migao" \
node "$HOME/.dsh/.agent-presets/migao/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs" \
  --site http://localhost:3001 --path /outbound-orders --phone 13900001025 --code 123456 \
  --click 仓位管理 --click 新建仓位 --shot warehouse-bin-code-input --out /tmp/ui-acceptance-7785-final-modal
```

## 读图判定（逐条写「看到了什么」）

1. **页签就位**：出库单页现有三个页签「出库单 / 成品库存 / 仓位管理」，第三个为选中态（浅主色底 + 主色边框），与既有药丸态一致；没有多出菜单项。
2. **空态入口单一**：面板标题「成品仓仓位」+ 一行规则说明；空态「还没有仓位」+ 一个「新建仓位」CTA。
   —— 第一轮截图（`/tmp/ui-acceptance-7785`，22:56）曾出现**两个同名按钮相距约 100px**（工具栏一个 + 空态一个）；
   本 commit 已收成空态单个入口（回归判据 = `WarehouseLocationPanel.test.tsx`「没有仓位 ⇒ 空态 + 新建入口」）。
3. **文案换行**：规则说明一行放下、无半截换行；空态说明缩到一句（「打包时会自动建 A-01…；也可以先按货架建号。」）。
4. **新建弹窗**：标题「新建仓位」；`FormPanel` 浅底「仓位信息」+ 2 列字段（仓位号 / 区域编码 / 区域名称 / 备注）；
   字段下方提示不挤压、不断行；底部「取消 / 创建」。
5. **无 5xx**：`summary.json` 的 `http5xx: []`；页签页 `testid: 29`、弹窗页 `testid: 35`；`loginOk: true`。
6. **未覆盖（照实登记）**：本轮**未提交**真实仓位（避免污染共享 dev 库 / 遵守 SDQS 清理口径），
   因此「列表有行 / 占用中禁用删除 / 编辑弹窗仓位号禁用」的**视觉**态未取证 —— 这些由
   `frontend/admin-web/tests/unit/components/WarehouseLocationPanel.test.tsx` 的 11 条单测覆盖。
   重启条件 = 有独立测试租户时补写一条后删并自证 `GET` 不再返回（DQ-5）。

## 证据

- `01-full.png` —— 出库单页 / 仓位管理 / 空态（1440×980）。
- `warehouse-location-panel.png` —— 面板逐元素截图。
- `modal-01-full.png` —— 「新建仓位」弹窗。
- `page-text.txt` / `testids.txt` / `summary.json` / `modal-summary.json` —— 逐字文本与采证读数。
