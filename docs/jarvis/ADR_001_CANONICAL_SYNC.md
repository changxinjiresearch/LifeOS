# ADR-001 — NextPlan 项目状态的统一权威与双端同步

- **状态：** Accepted as P0 target architecture (design decision; migration NOT performed)
- **日期：** 2026-10-09
- **范围：** macOS Tauri/Local Core、ChromeOS PWA、NextPlan Cloud、ChatGPT Bridge
- **阻断项：** P1 数据迁移、隐私存储以及真实设备端到端验收

## 背景（以当前仓库代码为准）

现有 NextPlan 同时存在两条独立运行链：

1. **Cloud/GitHub chain:** `mcp_server.server_v12:app` 通过 GitHub 事件/状态构建与云端扩展处理同步。
2. **Local/Desktop chain:** `mcp_server.local_core_v4` 使用 SQLite、本地 Tauri shell 和 `chrome_extension_local`，在桌面电脑 loopback 端口上提供服务。

`LifeOS-App` 是唯一界面来源，但**相同 UI 不等于相同数据权威**。ChromeOS 不能直接假设存在 Tauri Desktop loopback 服务。

## 选项评估

| 选项 | 优点 | 问题 | 决定 |
|---|---|---|---|
| GitHub `state.json` 直接公开为权威 | 已存在、改动少 | 私有状态暴露、延迟、权限与移动端写入问题 | **不选** |
| 每台设备独立 SQLite | 本地/离线方便 | 状态分叉、冲突难解释 | **不选** |
| Mac 主机长期在线承担同步 | 可省远端托管 | Mac 关机时 Chromebook 无法读写，公网访问安全复杂 | **不选为首发默认** |
| 受身份验证保护的 NextPlan canonical event service + 各设备本地缓存与 outbox | 统一状态、离线、安全边界明确 | 要进行安全迁移并承担远端运行依赖 | **选用目标架构** |

## 决策

**一个受身份认证保护的 Canonical State Service 是项目/任务/日历等高层事实的唯一权威。** 应复用现有云端 Event Layer / Action Gateway 的业务语义，选择安全存储实现；新设备不得直接写 `state.json` 或把本地 SQLite 当作多端总权威。

- **Mac：** 本地 SQLite = 已同步投影和待发送 outbox，可在断网时保存用户明确操作。
- **ChromeOS：** PWA/浏览器受控缓存 + durable outbox；无任意本机系统权限。
- **服务端：** 为每个操作保留 `operation_id`、目标实体、`expected_revision`、操作来源和最终回执。
- **最终状态：** 只有权威服务确认应用后，客户端才能显示「已同步」。网络接受不等于状态提交。
- **并发：** 同一实体使用乐观版本号：版本不一致返回 `conflict`，停止盲写并请求解决。
- **重试：** 同一 `operation_id` 重试必须返回原结果或 `already_applied`，不能重复副作用。
- **离线：** 显示 `local_pending` / `offline` 和最近已确认的 revision；不能谎报完成。
- **删除：** 使用受控 tombstone 与明确确认；避免离线设备重建被删项目。
- **恢复：** 制定快照/事件备份、语义校验、可回滚迁移；先影子同步验证，再切换读写权威。

## 回执协议草案

命令草案见 `mcp_server/jarvis_p0_contracts.py`：

```json
{
  "protocol_version": "jarvis-p0-v1",
  "operation_id": "device-unique-op-id",
  "device_id": "mac-arm64",
  "target": {"entity_type": "project", "entity_id": "example-project"},
  "action": "update_project",
  "expected_revision": 12,
  "authority": "user_confirmed",
  "status": "proposed"
}
```

该 Python 模块的 `check_sync_intent` 只提供 **P0 无副作用预检查**。它不会检查业务动作的全部字段、真正执行操作、更新 revision 或保存回执。真正事务性幂等校验必须在 P1 的 authoritative writer 内实现，不可以将这段纯函数当作生产安全网关。

期望的 server states：`accepted_pending`, `applied`, `no_change`, `already_applied`, `conflict`, `needs_confirmation`, `rejected`, `failed`。最终 `applied` 必须带经核验的服务端 revision 和 operation_id。

## 安全与隐私

现有公共代码仓库不能充当 Jarvis 私人知识和音视频存储桶。

- 公开仓库只放可公开的源代码、规范、虚拟测试数据；
- 受保护的状态服务保存真实项目状态，需账号验证和最小权限；
- 个人知识/原始对话/长期记忆默认本地保密存储，跨设备同步时经用户授权，并必须使用受保护服务；
- OAuth/API 凭据应放置在安全凭据存储，不进入版本控制；
- 现有仓库 Git 历史可能已经包含状态信息：使其变私有不能让过去已经被复制的数据从外界消失，需额外决定清理与撤销策略；
- 对公开 `state.json` 的任何清理或可见性调整必须先评估 Web UI、现有依赖及历史影响。

## 决策生效范围与停机条件

此 ADR **不迁移** `state.json`，**不覆盖**用户 Local SQLite，**不在 P0 开启**双向生产写入。

在以下证据出现前，严格禁止宣称跨设备统一完成：

- 带数据备份和回滚的迁移计划；
- Mac ↔ ChromeOS 真实跨端读写测试；
- 网络断连、重复写、并发冲突和删除测试；
- 已保护的真实数据存储及密钥管理验证。

P0 交付 ADR 和预检查契约；P1 才实现可用的跨端同步闭环。
