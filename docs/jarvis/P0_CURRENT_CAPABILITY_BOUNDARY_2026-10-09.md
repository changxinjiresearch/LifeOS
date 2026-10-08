# NextPlan × Jarvis — P0 当前能力边界审计

**审计日期：** 2026-10-09（Australia/Adelaide）  
**审计范围：** `changxinjiresearch/LifeOS`、`changxinjiresearch/LifeOS-App` 默认分支及 GitHub Actions 历史  
**审计性质：** 静态代码与 CI 证据审计；**未在用户设备上做安装和真实端到端验证**  
**状态：** 能力审计基线已完成；P0 按用户确认的 Web-first 限缩范围关闭；本文不表示 Jarvis 已实现。

## 1. 判定标准

- **CODE**：功能存在可定位的生产代码或协议。
- **CI**：找到明确的 GitHub Actions 成功记录；只证明相关工作流定义的检查通过。
- **DEVICE**：已在真实 macOS / ChromeOS 设备执行端到端验收。**本次无 DEVICE 证据。**
- **PLANNED**：设计或文档存在，但缺乏相应能力的完整可用实现。
- **NOT PRESENT**：本次仓库审计未找到实现该能力所需的完整模块。

不要根据项目看板 `completed` 标签推断 Jarvis 或跨平台能力已交付。

## 2. 当前产品与运行拓扑

- Web UI authority：`LifeOS-App/index.html`、`sw.js`、`manifest.webmanifest`。
- Cloud runtime：`LifeOS/Dockerfile` 启动 `mcp_server.server_v12:app`；有云端事件/状态后端与 Chrome extension `chrome_extension/`。
- Local runtime：`mcp_server/local_core_v4.py` / SQLite；`desktop_local/` 是 Tauri 2 Shell，通过 `desktop-adapter.js` 复用 Web UI。
- Local browser bridge：`chrome_extension_local/`，通过 127.0.0.1:47123 / :47124 与 Desktop/Local Core 连接。
- Cloud 与 Local 是两个不同的状态运行模式。**本次没有确认它们能在 macOS 与 ChromeOS 之间自动双向一致同步。**

## 3. 功能边界清单

| 能力 | 本轮证据 | 精确边界 |
|---|---|---|
| 项目、任务、里程碑及状态 | CODE + 部分 CI | 事件模型、动作协议、状态构建及本地动作实现；必须单独验收用户设备写入 |
| Deadline / Calendar / Note / Resource | CODE + 部分 CI | NextPlan 自有实体；不是通用外部日历/邮件管理 |
| Today / Decision Engine | CODE + CI | 基于任务、状态、优先级、时间的规则决策；非自主 LLM |
| AI Planning | CODE + CI | `phase_d_engine.plan_state` 生成可解释建议；不主动完成任意目标 |
| Automation feed | CODE + CI | 规则评价与 GitHub Actions 定期刷新；非实时全屏主动感知 |
| ChatGPT turn capture / Sync | CODE + 部分 CI | 扩展识别网页对话，分类并请求后端，可能受 DOM、权限、登录、服务及设备状态影响；必须以执行回执为准 |
| Cloud Agent gateway | CODE + CI | 权限、预览、动作执行、回执、核验与协调记录；不等同完整通用 Agent |
| 外部 SaaS 连接器 | CODE | 当前 `ConnectorRegistry` 实装 GitHub Connector；并非 Gmail/Calendar/系统全部可用 |
| Local OS execution | CODE + CI | 仅 `artifact.open`、`folder.open`、`file.copy`、`application.open` 四项白名单能力 |
| macOS shell | CODE + CI | Tauri Shell，Apple Silicon / Intel 构建产物和发布验收；暂无真实用户设备验收 |
| ChromeOS PWA | CODE | 有 Web App + service worker + manifest；尚未进行 ChromeOS 特定验收 |
| ChromeOS local Core | NOT PRESENT | 不能将 macOS Desktop loopback bridge 直接视为 ChromeOS 原生服务 |
| 实时语音 Jarvis | NOT PRESENT | 未发现完整 wake word / STT / TTS / barge-in pipeline |
| 长期语义记忆 | NOT PRESENT | 项目事件历史不是个人长时记忆系统 |
| 多模态屏幕视觉感知 | NOT PRESENT | 尚无授权视觉推理端到端管线 |
| 通用跨软件自主 Agent | NOT PRESENT | 尚未见从自然语言到跨应用计划、逐步行动、故障恢复、最后验证的完整可验收执行链 |
| 电影式 HUD | NOT PRESENT | 需要在唯一 Web UI Authority 中设计和实现 |

## 4. 关键源码证据

- [Desktop UI source-of-truth contract](https://github.com/changxinjiresearch/LifeOS/blob/main/desktop_local/README.md)
- [Local Core runtime](https://github.com/changxinjiresearch/LifeOS/blob/main/mcp_server/local_core_v4.py)
- [Local execution allowlist](https://github.com/changxinjiresearch/LifeOS/blob/main/mcp_server/local_execution_v1.py)
- [Agent Stage III contract](https://github.com/changxinjiresearch/LifeOS/blob/main/NEXTPLAN_AGENT_STAGE3_V1.md)
- [External connector implementation](https://github.com/changxinjiresearch/LifeOS/blob/main/mcp_server/connectors_v1.py)
- [Local browser bridge](https://github.com/changxinjiresearch/LifeOS/blob/main/chrome_extension_local/background.js)
- [Cloud browser bridge](https://github.com/changxinjiresearch/LifeOS/blob/main/chrome_extension/manifest.json)
- [Local/cloud architecture distinction](https://github.com/changxinjiresearch/LifeOS/blob/main/docs/local/NEXTPLAN_LOCAL_ARCHITECTURE.md)
- [Web application PWA manifest](https://github.com/changxinjiresearch/LifeOS-App/blob/main/manifest.webmanifest)

## 5. CI 证据（不等于真实设备已可用）

2026-10-07：
- [macOS dual-architecture release acceptance — success](https://github.com/changxinjiresearch/LifeOS/actions/runs/37653613001)，Apple Silicon arm64 / Intel x86_64 两项成功，并存在对应 artifacts；
- [NextPlan Release Packaging v1 — success](https://github.com/changxinjiresearch/LifeOS/actions/runs/37653613030)，有 macOS Intel、Apple Silicon 和 Windows 安装产物；
- [Local Stage 9-10 release acceptance — success](https://github.com/changxinjiresearch/LifeOS/actions/runs/37653613006)；
- [Local Stage 1-3 acceptance — success](https://github.com/changxinjiresearch/LifeOS/actions/runs/37651716612)。

2026-10-08：
- [Agent external trigger poll — success](https://github.com/changxinjiresearch/LifeOS/actions/runs/37783896161)；
- [Daily automation — success](https://github.com/changxinjiresearch/LifeOS/actions/runs/37711844765)。

**限制：** 工作流成功不等于 ChromeOS 部署、终端用户扩展同步或跨设备数据一致性已验证。

## 6. P0 风险与优先级

### Critical — 公开数据边界
审计时 `LifeOS` 仓库可公开读取，且根目录 `state.json` 包含实际项目和活动状态。不要向该仓库添加语音记录、全文对话、个人长期记忆、凭据、私人文件或其他敏感内容。对已有数据需要决定是否改私有以及必要时清理历史；仅删除当前文件并不足以清除 Git 历史。

### Critical — Canonical state / 跨设备同步
云端 GitHub 和本地 SQLite 均有状态路径。在任何 Mac ↔ ChromeOS 同步发布之前，需要明确唯一 canonical authority、冲突策略、迁移策略和接收回执，且以真实端到端测试证明。

### High — Sync correctness
ChatGPT 内容脚本依赖网页 DOM；失败、延迟或被忽略时不能宣称已同步。需要针对普通单项、批量状态更新、模糊目标、重复请求和断线恢复定义验收测试，并展示 operation_id、receipt/status 与目标最终状态。

### High — ChromeOS 运行边界
Local Bridge 默认依赖 Desktop 本机回环服务。ChromeOS 第一版优先 Web/PWA + Chrome Extension + 可选远端后端；不应承诺任意桌面程序控制、常驻唤醒或完整本机模型推理。

### High — Agent 能力过度宣传
现有 Action Gateway、记录/回执、Proactive Policy 是良好基础，但不能将 GitHub 的定向受控动作框架称为通用 Jarvis。必须重新引入可测试的 AI 模型适配、任务规划和工具调度，再证明端到端行为。

## 7. P0 关闭范围（2026-10-09 修订）

用户明确确认 NextPlan 当前主要以 Web 端运行，将 P0 的 exit gate 调整为**现有能力审计、统一数据架构决议、Context Bridge 安全契约、CI 契约测试、后续阶段验收计划**。

- 当前 P0 **COMPLETED (WEB-FIRST BASELINE)**；结论见 [最终验收报告](P0_EXECUTION_AND_ACCEPTANCE_REPORT.md)。
- 实际 macOS / ChromeOS 设备验收延期而非 PASS：[Issue #20](https://github.com/changxinjiresearch/LifeOS/issues/20)。
- 历史公开仓库状态安全整改延期而非修复：[Issue #19](https://github.com/changxinjiresearch/LifeOS/issues/19)。
- 实际跨设备 canonical sync 属于 P1；ChatGPT–Jarvis Context Bridge 端到端数据流属于 P2。
- 保留本报告的 CODE/CI/DEVICE 判断，不因用户调整 P0 的验收范围而改变其真实性。

**本文未更改** `state.json` 或任何用户项目/任务状态。
