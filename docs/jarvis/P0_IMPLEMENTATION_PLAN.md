# NextPlan × Jarvis — P0 Web-first 实施范围与验收标准

**Status:** CLOSED / ACCEPTED FOR WEB-FIRST FOUNDATION  
**Scope decision:** 用户于 2026-10-09（Australia/Adelaide）确认，目前以 Web/ChatGPT 浏览器工作流为主，允许 P0 跳过旧仓库隐私迁移和物理 Mac/ChromeOS 测试。  
**产品主体：** NextPlan（`LifeOS-App` 唯一 UI authority）；Jarvis 是后续添加的智能能力，不是单独产品。  
**Important:** 这是一项**限缩范围后的 P0 验收**，不是旧风险已解决，更不是 Jarvis P1/P2 已上线。

## 1. P0 本轮实际目标

P0 是现有 NextPlan 的**工程基线、架构选择和安全契约**阶段。本次验收包含：

1. **P0-A 能力审计**：基于真实仓库代码/CI区分 CODE、CI、DEVICE；明确现有 Sync、Local Core、cloud state、OS skills 能力边界。
2. **P0-B 统一权威方案**：ADR-001 选择目标架构（受保护的 canonical service + Mac/ChromeOS 本地缓存），并用纯函数明确 operation ID、乐观版本号、重复与冲突语义；**真实跨端同步由 P1 开发**。
3. **P0-C 私人知识边界**：ADR-002 区分项目事实、上下文候选、私有记忆、日志和原始聊天；新上下文契约拒绝公开目标；**现有公开状态的安全迁移明确延期**。
4. **P0-F 接口初稿**：提供 `mcp_server/jarvis_p0_contracts.py` 的同步及上下文候选纯函数，约束其不执行任何状态变更。
5. **P0-G ChatGPT–Jarvis Bridge 设计**：明确授权来源、用户事实与助手猜测区分、verified execution receipt、私有保存限制；**生产知识提取和双向交接由 P2 开发**。
6. **基线 CI**：`tests/test_jarvis_p0_contracts.py` 21 个测试，独立 GitHub Actions + 原有 MCP smoke tests 无回归；仅覆盖当前契约逻辑。

## 2. 根据用户决定从 P0 Exit Gates 移出的事项

| 原 Gate | 当前决议 | 追踪 |
|---|---|---|
| P0-C 旧 `LifeOS/state.json` 公开状态安全整改 | **DEFERRED — 未解决**。目前仅修订新 Jarvis 上下文安全契约；不向公开仓库追加私人记忆/原始聊天/令牌 | [Issue #19](https://github.com/changxinjiresearch/LifeOS/issues/19) |
| P0-D macOS arm64 和 Intel 真机验收 | **DEFERRED — NOT TESTED ON DEVICE**。历史 CI 构建成功不能冒充真实安装 | [Issue #20](https://github.com/changxinjiresearch/LifeOS/issues/20) |
| P0-E ChromeOS PWA/Bridge 真机验收 | **DEFERRED — NOT TESTED ON DEVICE**。网页优先不代表 ChromeOS 已通过验证 | [Issue #20](https://github.com/changxinjiresearch/LifeOS/issues/20) |

用户接受延期，是**产品阶段范围决策**，不是技术整改与安全验证的结果。生产接入私人长期知识或真实跨端用户数据之前必须重新打开相关安全/设备门槛。

## 3. 当前 Web-first 运行范围

- 以已有的 NextPlan Web UI 和 ChatGPT 浏览器使用方式为首要产品入口；
- 保留目前 Cloud/extension 同步架构，绝不假设已具备 ChatGPT 隐藏记忆或全历史直接读取能力；
- 本次 PR 不修改主站 UI、不修改 `state.json`、不修改现有项目/里程碑、不启用新的自动同步监听；
- Mac/ChromeOS 原生能力仅记录目标平台与后续验收步骤，不作为 P0 必须启动的功能。

## 4. P0 验收证据

- [能力边界审计](P0_CURRENT_CAPABILITY_BOUNDARY_2026-10-09.md)
- [P0 完整路线](MASTER_DEVELOPMENT_ROADMAP_V1.md)
- [ADR-001 — canonical sync](ADR_001_CANONICAL_SYNC.md)
- [ADR-002 — context and privacy](ADR_002_CONTEXT_BRIDGE_AND_PRIVACY.md)
- [设备专项 runbook](P0_DEVICE_ACCEPTANCE_RUNBOOK.md)（仅备以后使用）
- [P0 final acceptance report](P0_EXECUTION_AND_ACCEPTANCE_REPORT.md)
- [21 tests passed](https://github.com/changxinjiresearch/LifeOS/actions/runs/37802194387)，后续提交也应检查最新 PR CI。

## 5. P0 结论

**P0 = COMPLETED / CLOSED（Web-first scoped foundation）**。审计、架构决议、安全候选对象/协议、21 项契约测试和 CI 形成可追溯基线。

**不包含**跨设备可用同步、私有存储上线、ChatGPT 对话知识自动提取、Jarvis Agent/Voice，也不包含真实 macOS / ChromeOS 设备验收。上述能力按 P1/P2 及后续阶段实现；旧公开状态风险继续作为待处理问题追踪。

## 6. 下一阶段

**P1** 进入时优先实现 Web-first 统一状态服务与受保护的数据迁移方案；不得把个人长期知识直接写入现有公开 GitHub。**P2** 再做 ChatGPT→Knowledge→Jarvis 的经授权双向桥接，要求对来源和最终执行结果可验证。
