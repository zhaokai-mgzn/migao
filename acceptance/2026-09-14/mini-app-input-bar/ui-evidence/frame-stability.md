# 帧稳定性取证（输入条区域两帧 + 全屏差异定位）

| 阶段 | 状态 | 输入条区域 md5(帧1) | 区域两帧一致(a) | 全屏差异 bbox | 差异是否触到输入条(b) | 与上一状态区域同 md5 | 跨状态唯一(c) |
|---|---|---|---|---|---|---|---|
| before | empty | `64e94564dff7…` | ✅ | None | ✅ 否 | 不同✅ | ✅ |
| before | hintDismissed | - | - | - | - | - | - |
| before | draft | `c05a1bc26195…` | ✅ | None | ✅ 否 | 不同✅ | ✅ |
| before | image | `5138a87212f7…` | ✅ | [0, 170, 546, 187] | ✅ 否 | 不同✅ | ✅ |
| before | multiline | `a8df78b1856a…` | ✅ | [0, 170, 546, 187] | ✅ 否 | 不同✅ | ✅ |
| after | empty | `a0e6b3fafc93…` | ✅ | None | ✅ 否 | 不同✅ | ✅ |
| after | hintDismissed | `bff03a3aabae…` | ✅ | [0, 170, 546, 187] | ✅ 否 | 不同✅ | ✅ |
| after | draft | `1c1e836e77e2…` | ✅ | None | ✅ 否 | 不同✅ | ✅ |
| after | image | `99d8377dab36…` | ✅ | None | ✅ 否 | 不同✅ | ✅ |
| after | multiline | `60d257c214ee…` | ✅ | [0, 170, 546, 187] | ✅ 否 | 不同✅ | ✅ |