# NextPlan × Jarvis — P0 执行方案与验收门槛

**Status:** IN PROGRESS / docs-only draft  
**Primary platforms:** macOS (Apple Silicon + Intel), ChromeOS (PWA + Chrome Extension)  
**Product constraint:** Jarvis is a NextPlan capability layer, NOT a third standalone product.

## 0. P0 范围约束

- 不重写 NextPlan、不创建独立 Jarvis 产品 UI；
- `LifeOS-App` 仍是唯一 UI authority；
- 现有项目/任务/里程碑状态语义、事件 ID、幂等性、回执及权限规则不变；
- 此阶段不允许直接更改 `state.json`、迁移真实用户数据或触发删除；
- 不将私人记忆、凭据或原始语音写入公开仓库；
- 端到端验证所需真实设备证据缺失时必须报告未完成，不用“CI 通过”代替。

## 1. P0 Workstreams

### P0-A. 当前能力证据冻结（本 PR 已开始）
- 将 `P0_CURRENT_CAPABILITY_BOUNDARY_2026-10-09.md` 作为代码与 CI 基线；
- 每项能力区分 CODE / CI / DEVICE；
- 当后续 PR 引入新能力时，更新此矩阵；
- 生成一份可追踪能力清单，含代码入口、测试名和最新通过记录。

**Gate:** 无任何“尚未实现”的功能被误标为完成。

### P0-B. Canonical truth 与跨设备同步（Critical）
- 确定项目/任务等高层状态的唯一权威数据源；
- 设计 Mac 本地 SQLite 与 ChromeOS Web/PWA 之间的读取/写入/离线队列；
- 设计不可重复执行的 `operation_id`、应答状态（`applied`、`pending`、`rejected`、`failed` 等）、版本冲突策略；
- 区分 NextPlan 同步状态和 Jarvis 私有记忆；
- 提议目标：**一个受保护的 canonical NextPlan state service + 各设备本地缓存/outbox + 独立本地 Jarvis memory**；但在评估当前 GitHub event builder、Railway/成本、迁移和回滚前不直接改变运行架构。

**Gate:** Mac 修改一个测试任务后 ChromeOS 正确显示；断线重试无重复状态变更；冲突可检测且可解释。

### P0-C. 隐私与权限（Critical）
- 识别当前 GitHub 仓库可公开读取的 state 元数据范围（报告不复制个人数据）；
- 给出改私有仓库 / 安全存储服务 / 历史数据清理的操作方案及兼容影响；
- 明确数据类别：公开代码、项目元数据、个人记忆、原始语音、OAuth/API 凭据；
- 永不把 ChatGPT 网页内容当作可信指令来源；必须经结构化命令权限校验；
- 高风险操作需要明确批准并保留审计证据。

**Gate:** 外部未授权方不能通过公共资源读取个人长期记忆或新产生的敏感状态。

### P0-D. macOS 真实设备验收
- 校验 Apple Silicon / Intel 构建与下载安装包有效性；
- 测试无开发工具机器上的安装启动；
- 验证 Local Core `/healthz`、SQLite 完整性、持久化、备份与恢复；
- 测试 Chrome Local Bridge auto-bootstrap；
- 最少完成一条项目更新写入→receipt→读取最终状态闭环；
- 明确后续麦克风、屏幕录制、辅助功能权限的申请逻辑，不在 P0 偷偷激活。

**Gate:** 每个架构有可以复核的真实运行证据。当前仅有 CI 验收和产物。

### P0-E. ChromeOS 专项验收
- 通过 ChromeOS 浏览器安装和使用现有 PWA；
- 测试云端模式 extension 捕获、分类、确认、写入和回执；
- 校验离线/重连、PWA service worker 更新、权限提示；
- ChromeOS 首版不依赖 macOS/Windows Desktop Local Core；
- 网页/扩展的浏览器权限范围需明确，禁止对 OS-level control 作过度承诺。

**Gate:** ChromeOS 真实设备能够完成读取与状态写入，且与 macOS 权威数据一致。

### P0-F. Jarvis 模块接口契约与回归保护
将下列接口作为后续 P1/P2 提供的扩展点，而非提前宣称已经实现：

- `/jarvis/v1/interaction`：文本/语音指令任务接收（future）；
- `ModelAdapter`：本地优先、云模型可选；
- `MemoryStore`：私有情景/语义/偏好记忆；和 NextPlan canonical 项目状态分离；
- `PerceptionAdapter`：按平台/权限支持屏幕和网页感知；
- `SkillRegistry`：显式能力清单、风险级别和平台约束；
- `TaskRunner`：Observe → Plan → Authorize → Act → Verify → Reconcile → Explain；
- `JarvisUI`：只在 `LifeOS-App` 增加入口，不派生单独第二套 UI。

**Gate:** 设计与现有命令协议兼容；不绕开 NextPlan Sync、安全规则、回执确认；现有合同测试无回归。

## 2. macOS / ChromeOS 目标分层

| Layer | macOS | ChromeOS |
|---|---|---|
| Shared UI | 复用 LifeOS-App，经 Tauri Adapter | 复用 LifeOS-App，经 PWA |
| Conversation | 原生音频 + Web fallback（P1） | 浏览器音频（P1） |
| NextPlan State | 统一认证 API + Local SQLite cache（目标） | 统一认证 API + PWA cache（目标） |
| LLM | macOS local model optional（P1） | 远端/选配 Linux 环境（P1，需硬件验收） |
| Computer Skills | macOS permissions + structured local executor（P3） | 浏览器扩展范围内的工具（P3） |
| Security | OS 级授权 + 后端能力白名单 | Chrome permissions + 后端能力白名单 |

## 3. 首轮测试矩阵（待真实设备执行）

1. **Mac-arm64**：启动 → Local Core health → 读取 → 单项状态变更 → receipt → 刷新核验；
2. **Mac-x86_64**：同上；
3. **ChromeOS**：PWA 启动 → 读取状态 → 单项状态变更 → receipt；
4. **跨设备**：macOS 状态改变 → ChromeOS 确认一致；
5. **离线重试**：重试同一 operation_id 不重复变更；
6. **批量变更**：多个项目的状态更改全部明确反馈成功/失败；
7. **歧义**：实体同名、意图不明确时不自动写入；
8. **破坏性操作**：不经明确确认绝不执行；
9. **隐私**：任何新语音记录、敏感凭据或长期记忆不能出现在公开 GitHub；
10. **回归**：NextPlan 原有 Web UI / Local Core / CI 稳定，现有项目数据保持不变。

## 4. 执行次序与明确停止点

- P0-A 审计文档、P0-B 数据架构设计、P0-C 安全评估优先；
- P0-D / P0-E 需要两类真实设备的人工配合或可用设备测试环境；
- 未完成 Critical Gate 之前，不启动跨设备大范围个人数据同步；
- P0-F 可预先起草接口，但不能以此宣布 Jarvis Voice、Memory 或 OS Agent 已完成；
- P0 完成应有 PR、测试日志、真实设备验收、明确的剩余限制。

## 5. 当前交付状态

- [x] 阅读代码及状态协议，建立当前能力矩阵；
- [x] 审阅 GitHub Actions 最近的 macOS 构建/发布记录；
- [x] 辨认 cloud/local 状态双路径与 ChromeOS Local Bridge 限制；
- [x] 定义 Jarvis 增量接入的工作流和验收门槛；
- [ ] Canonical 数据方案决议；
- [ ] 公开状态数据风险修复；
- [ ] Mac 真机验收；
- [ ] ChromeOS 真机验收；
- [ ] Sync 端到端回归；
- [ ] Jarvis 接口契约代码与测试。

**本文件不更改任何用户项目状态。P0 尚未通过总体验收。**
