# macOS / ChromeOS 真实设备验收手册（用户延期，未来执行）

**当前决议：** 用户采用 Web-first 范围关闭 P0；本文全部真机步骤标记 `DEFERRED / NOT TESTED`，并转由 [Issue #20](https://github.com/changxinjiresearch/LifeOS/issues/20) 跟踪。**此延期不表示 macOS/ChromeOS 功能已验收。**

**日期：** 2026-10-09  
**版本：** P0-v1  
**作用：** 提供可复现的证据收集步骤，不把 CI 构建成功误当作用户真实设备测试通过。  
**前提：** 用户同意进行测试；不使用真实敏感资料，且测试修改只作用于虚拟测试项目或经用户批准的非敏感记录。

## 0. 测试环境记录

每个设备保存：测试时间（本地时间及 IANA 时区）、系统与版本、架构、浏览器版本、NextPlan 包/commit SHA、扩展版本、云端/本地运行模式、通过/失败情况、回执与脱敏日志位置。

不要在 GitHub 公开 PR 上上传令牌、数据库原文件、私人聊天记录或无脱敏截图。

## 1. macOS Apple Silicon（arm64）

1. 从 [发布打包工作流](https://github.com/changxinjiresearch/LifeOS/actions/runs/37653613030) 的 `NextPlan-macOS-apple-silicon-v0.1.3` artifact 获取对应安装包（下载权限/过期时间以 GitHub 为准）。
2. 核查安装包来源和架构，按 macOS 正常安全流程安装，不绕过陌生来源的安全警告。
3. 启动 NextPlan，确认 UI 与 Web 共用相同设计，窗口可正常缩放。
4. 检查桌面所启动的 Local Core 是否处于健康状态，以及 SQLite 持久化/恢复流程（不要公开本地 bearer token）。
5. 在浏览器中安装可信来源的 NextPlan Local Bridge；检测扩展能与桌面进行会话绑定。
6. 使用虚拟测试项目（或备份后的独立测试数据库），提交一次无破坏性任务状态变更，记录原状态、操作 ID、执行回执和读取后的最终状态。
7. 重启应用，确认测试状态仍在；断开网络，验证本地模式的允许范围。
8. 恢复网络后核实数据同步是否真的存在；**不要预设本地 SQLite 已经能跨设备自动同步**。
9. 记录日志以及任何安装/签名/权限报错。

**Gate:** 无开发工具链也能安装启动；Local Core 健康；基础读取/写入/回执/重启通过；问题有脱敏证据。

## 2. macOS Intel（x86_64）

按上述同一矩阵测试，但使用 [Intel release artifact](https://github.com/changxinjiresearch/LifeOS/actions/runs/37653613030) 的 `NextPlan-macOS-intel-v0.1.3`。

**Gate:** 不能用 Apple Silicon + Rosetta 或 GitHub Runner 结果直接替代 Intel 真机测试；若无 Intel 真机，明确标记 `NOT TESTED ON DEVICE`。

## 3. ChromeOS（Chrome 浏览器 / PWA）

1. 记录 ChromeOS 版本、设备型号、Chrome 浏览器版本与网络条件。
2. 使用受信任的 NextPlan Web 发布入口（依据当前部署配置），测试 PWA 安装、打开、导航、缓存行为。
3. 测试只读项目列表、任务、NextPlan Today、数据刷新与错误状态。
4. **区分两套扩展：** `chrome_extension/` 是云端 ChatGPT Bridge；`chrome_extension_local/` 依赖本机 `127.0.0.1:47123/47124` 桌面 Local Core，不能默认在普通 ChromeOS 上工作。
5. 若使用云端 Bridge，先在安全测试环境验证授权状态、一个明确变更指令、一个模糊命令、以及失败后待确认队列。
6. 记录 PWA 离线/恢复现状；在真正的 P1 同步后重测跨端一致性。未实现前结果应如实标记 `NOT SUPPORTED YET`。
7. 验证 Extension 停止/浏览器重启之后，系统不会对同一用户变更重复执行副作用。
8. 任何浏览器权限弹窗要清楚说明用途；不得假定拥有 OS 全局键鼠或文件权限。

**Gate:** 在 ChromeOS 设备上真实打开、读取、交互，并提供准确限制和结果；不能用普通 Windows/Linux Chrome 测试替代。

## 4. 双平台与隐私/同步专项测试

| Case | 场景 | 通过标准 |
|---|---|---|
| SYNC-01 | Mac 上更改虚拟项目，ChromeOS 读取 | P1 实装后读取同一 authoritative state |
| SYNC-02 | 重复发送同一 `operation_id` | 只应用一次，后续回 `already_applied` |
| SYNC-03 | 两端同时修改同一版本 | 明确冲突，不能静默覆盖 |
| SYNC-04 | 网路中断后恢复 | 不丢、不错、可见 pending |
| SYNC-05 | 同名/指代模糊项目 | 请求确认，不盲写 |
| SYNC-06 | 错误反馈或工具超时 | 不谎称已完成 |
| PRIV-01 | 保存 Jarvis context 到公开 GitHub | 必须拒绝 |
| PRIV-02 | 未授权的 ChatGPT 消息捕获 | 不创建上下文候选 |
| PRIV-03 | 凭据出现在输入中 | 阻断、无公开日志泄漏 |
| PRIV-04 | 设备/用户撤销授权 | 后续访问应被拒绝（P1–P3 实装后） |
| CTX-01 | 用户确认的知识决策 | 可追溯来源、时间、归属项目（P2 实装后） |
| CTX-02 | 未核验 Jarvis 操作回执 | 不得成为 completed handoff |

P0 仅有纯函数契约/CI 测试覆盖 `SYNC-02/03` 和 `PRIV-01/02/03` 的**预检查逻辑**；其余必须留在后续实现/真机矩阵中。

## 5. 证据模板（每台设备独立）

```text
Date/time:
Tester:
OS / version / architecture:
Browser / version:
NextPlan / Git commit:
Bridge extension / version:
Operation mode: cloud | local
Test case:
Expected result:
Actual result:
Receipt status / operation ID (redacted):
Result: PASS | FAIL | NOT TESTED | BLOCKED
Diagnostic (no secrets):
```

## 6. P0 实际限制

即使现有 GitHub Actions 中已经有 macOS arm64/x86_64 的成功构建和安装产物，当前会话仍无法直接对用户 Mac 或 Chromebook 点击安装、录制现场检查、确认扩展状态。因此在获得设备端证据之前，这两项永远保持待验，而不是推定 PASS。
