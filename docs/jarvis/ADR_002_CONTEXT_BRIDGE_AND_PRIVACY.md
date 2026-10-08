# ADR-002 — ChatGPT ↔ Jarvis Context Bridge, knowledge provenance and privacy

- **状态：** Accepted as P0 interface architecture (design; no production capture/store deployed)
- **日期：** 2026-10-09
- **产品原则：** ChatGPT remains the main work interface; NextPlan is canonical project truth; Jarvis is a second authorized intelligence/execution entrypoint.

## 背景和边界

NextPlan Sync 通过 Chrome extension 观察用户浏览器内已经显示的 ChatGPT 消息，生成结构化状态候选，再交给 NextPlan 后端分类和写入。它**没有**程序化读取 ChatGPT 内部隐藏上下文或完整账号 Memory 的能力。基于 DOM 的捕获可能在页面变化、权限丢失、Service Worker 停止或浏览器关闭时失败。

因此不能承诺自动得到用户所有历史 ChatGPT 信息。上下文共享必须基于明确可访问、用户授权的数据入口。

## 数据分层

| 层 | 保存什么 | Authority | 默认位置 |
|---|---|---|---|
| NextPlan Canonical State | 项目、任务、日期、状态和回执 | 验证后的 authoritative event service | 受保护的 NextPlan 后端 |
| Context Knowledge | 已确认的研究决策、观察、来源指针和项目交接摘要 | 用户确认或经过核验的工具结果 | 本地私人存储；可选受保护同步 |
| Jarvis Memory | 情景、语义、操作与偏好记忆 | 具有来源、有效期和可更正机制 | 本地私人存储 |
| Conversation Archive（可选） | 授权选择的原文片段或导出 | 明确的 opt-in 导入/保留策略 | 私人加密存储 |
| Execution Log | 操作请求、权限、执行回执与后验验证 | 受控执行网关和 provider 证据 | 专用、受保护审计存储 |

禁止将模糊讨论、助手提出的猜测或未经执行的计划自动记作项目完成事实。

## Bridge 的三条通路

**1. ChatGPT → NextPlan/Jarvis：**

- 保留现有 ChatGPT 扩展的项目状态同步行为，新增**单独**的 context candidate 通道；
- 内容分类：`decision`、`observation`、`hypothesis`、`preference`、`handoff`；
- 默认仅提取相关摘要及来源引用；不得批量上传整段对话；
- 用户确认后的摘要可入知识库；模型独立总结的内容只作为待确认候选；
- 对话原文导入须单独明确授权，不等于隐藏 Memory 导出。

**2. NextPlan → Jarvis：**

- 读取 canonical state 及授权上下文；
- 限定项目 scope，来源检索不得跨越用户权限；
- 检索回答包含事实来源、时间、置信状态；拒绝伪造缺失历史。

**3. Jarvis → ChatGPT：**

- Jarvis 任务执行完毕后保存经过核验的 receipt / summary；
- ChatGPT 通过有权限的 MCP/插件读取，若环境不支持则通过可复制的 Context Bundle 由用户显式带回；
- 不依赖 ChatGPT 自带记忆可被外部机器直接读取；
- `accepted`、`started`、`dispatched` 不是 `verified`。

## P0 ContextCandidate 最小结构

见 `mcp_server/jarvis_p0_contracts.py`：

```json
{
  "protocol_version": "jarvis-p0-v1",
  "record_type": "jarvis_context_candidate",
  "context_type": "decision",
  "project_id": "example-project",
  "summary": "用户明确确认实验 B 优先",
  "source": {"kind": "chatgpt_user_turn", "ref": "chatgpt://conversation/abc#turn-8"},
  "confirmed": true,
  "privacy": "private",
  "storage_status": "not_persisted",
  "fingerprint": "<SHA-256>"
}
```

这是 **候选数据对象**，不是自动存储的记忆。P0 仅定义和校验对象；P2 引入实际授权 UI、抽取和桥接流水线；P3 引入检索索引和长期保留策略。

## 私人数据和威胁防护

- 默认 opt-in 细粒度记录；显式关闭记录则不应建立私人上下文；
- 机密和令牌不能出现在候选上下文中；P0 使用已知凭据模式的防护，**并不代替生产 DLP、内容审计或加密**；
- 公开源代码仓库不允许存储 `jarvis_context_candidate`、raw conversations、voice/vision captures、private memory；
- 用户必须可以看到、编辑、更正、拒绝、导出和删除已经保存的知识；
- 明确保留期限、访问控制、密钥管理和设备撤销；不应把网页内容伪装成工具或系统指令；
- 将来源和身份绑定到已认证的接口，**客户端自报 confirmed=true 不是可信证明**；
- 未来生产写入必须由服务端验证授权凭据、来源、操作权限和去重；
- 持续纠正旧事实，不能让矛盾记忆静默覆盖 canonical project state。

## P0 成功与后续依赖

本阶段交付一个**明确且安全的设计契约**、纯函数候选构造器及单测。

只有 P2 接入经过认证的收集/确认 API、来源回溯、真实多端同步和用户删除接口，并通过端到端测试后，才能宣称 ChatGPT–Jarvis Context Bridge 已经投入使用。

## 失败与降级

- ChatGPT 自定义连接器不可用 → 浏览器扩展与明确 Context Bundle 导出/导入仍可用；
- 无历史记录/未授权 → 不猜测，说明知识缺失；
- 中断或重复读取 → 以 stable fingerprint 去重，未核验不写；
- 设备断网 → 候选留在授权本地缓存，恢复后再验证；
- 业务状态和个人知识冲突 → NextPlan canonical 状态优先，知识层记录冲突和来源。
