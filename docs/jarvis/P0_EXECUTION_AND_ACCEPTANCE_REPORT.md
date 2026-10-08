# NextPlan × Jarvis P0 — Web-first 阶段最终验收报告

**日期：** 2026-10-09（Australia/Adelaide）  
**GitHub：** PR #18 / `phase/p0-jarvis-capability-audit`  
**P0 Status：** **COMPLETED — WEB-FIRST SCOPE**  
**验收依据：** 用户明确取消原 P0 中的 Mac/ChromeOS 真机验收和历史仓库隐私迁移作为本阶段阻断项。两项仍存在风险，且保留后续跟踪。

## 1. P0 关闭判决

P0 原设计过于接近后续部署/真机验收。基于当前以 **网页端 + ChatGPT 浏览器** 为主的使用实际，重新划分：

- P0 只交付仓库能力审计、数据统一架构决议、私人知识数据边界、Context Bridge 协议、无副作用合同代码、回归测试及正式开发计划。
- P1 将真正实现受保护的 canonical state service / 跨设备写入与迁移。
- P2 将真正实现经授权的 ChatGPT–Jarvis 上下文采集、写入、检索和反向交接。
- macOS/ChromeOS 真机专项验收延后到相应平台产品的集成发布阶段，不以 CI 代替。
- 现有公开 GitHub `state.json` 风险保留，不得因此将任何 Jarvis 私人长期记忆、语音、屏幕截图、令牌等写入该仓库。

据此，**P0 的 Web-first 架构准备范围已经达到完成条件，正式关闭**；其他旧验收项标记 `DEFERRED`，不标记 `PASS`。

## 2. 已落地的工程产物

| 交付 | 实际内容 | 状态 |
|---|---|---|
| P0-A | NextPlan 核心 Web、Cloud、SQLite、Chrome Bridge、GitHub Agent、桌面/ChromeOS 能力边界清单 | DONE |
| P0-B | ADR-001 受保护统一数据权威 + 设备缓存/outbox + 乐观 revision/idempotency 策略 | DESIGN DONE / REAL SYNC IN P1 |
| P0-C | ADR-002 来源/权限/私人数据分层，纯函数明确拒绝公开 context storage | CONTRACT DONE / LEGACY REMEDIATION DEFERRED |
| P0-F | `mcp_server/jarvis_p0_contracts.py`：构造 proposed sync intent、版本冲突预检、context candidate、存储目标拒绝 | DONE (NO PRODUCTION MUTATION) |
| P0-G | ChatGPT↔Jarvis 上下文桥接与已验证 handoff 的接口数据约束 | DESIGN DONE / INTEGRATION IN P2 |
| P0 Regression | 21 项 `tests/test_jarvis_p0_contracts.py` 和 GitHub Actions CI | PASS |

实现性质：合同纯函数没有连接到生产 `server_v12` 和 `Local Core`，因此不存在用户数据迁移、真正的 cross-device transaction、长期记忆 persistence 或全功能 ChatGPT Bridge。不能宣称后续功能已完成。

## 3. 测试证据

- 21 项 P0 Python 契约测试：[GitHub Actions success, latest closure baseline](https://github.com/changxinjiresearch/LifeOS/actions/runs/37802194387)，测试涵盖版本冲突、重复操作、证据、授权、私人存储限制和 verified result。
- MCP 冒烟测试：[GitHub Actions success](https://github.com/changxinjiresearch/LifeOS/actions/runs/37802203151)，确认基础代码路径未因新增 P0 合同直接破坏。
- 已有 macOS Apple Silicon 和 Intel 的旧 [release acceptance CI](https://github.com/changxinjiresearch/LifeOS/actions/runs/37653613001) 通过，但不计为 P0 Web-first 的真机 PASS，也不表示 macOS/ChromeOS 交付。

最新 PR commit 需检查对应 CI 再合并；GitHub 页面中的测试状态为权威来源。

## 4. 用户明确延期的原 P0 检查

| 检查 | 当前状态 | 跟进 |
|---|---|---|
| 历史 `LifeOS/state.json` 公开状态隐私修复 | **DEFERRED / NOT FIXED** | [Issue #19](https://github.com/changxinjiresearch/LifeOS/issues/19) |
| Mac Intel/Apple Silicon 真实设备验收 | **DEFERRED / NOT TESTED** | [Issue #20](https://github.com/changxinjiresearch/LifeOS/issues/20) |
| Chromebook 上 ChromeOS PWA 和扩展验收 | **DEFERRED / NOT TESTED** | [Issue #20](https://github.com/changxinjiresearch/LifeOS/issues/20) |

**不能从“P0 完成”推出“当前用户私人数据已安全隐藏”或“两大首发平台已完整发布”。**

## 5. Web-first 基础设计的约束

- NextPlan 的唯一 UI 来源继续是 `LifeOS-App`，Jarvis 不是第三套产品。
- ChatGPT 保持主要工作空间；浏览器 NextPlan Sync 属于目前已有的状态捕获方式；它不提供对 ChatGPT 隐藏记忆的直接访问。
- 旧项目数据与主线功能保留；P0 代码**不更改**用户 `state.json` 或已有任务完成状态。
- P1/P2 进入真实私人数据采集和同步之前，必须有最小权限、身份验证、受保护存储与可复核结果，不得以用户延期旧数据迁移为理由放宽新功能的安全保护。

## 6. 正式结论

**P0 = CLOSED (Web-first baseline)；P1 = NEXT.** 

本阶段没有修复上述延期问题、没有声称真实 macOS/ChromeOS 测试成功，也没有实现跨设备数据生产写入或 ChatGPT–Jarvis Context Bridge 完整链路。延期风险在 Issues 中继续追踪，避免被关闭阶段时遗忘。
