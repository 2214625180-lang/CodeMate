# 技术难点与取舍

CodeMate 的核心不是单次调用模型，而是把代码库理解、Agent 修复、沙箱验证、持续评测和权限审计做成一个可闭环的工程系统。面试讲解可以围绕四条主线展开：RAG 保证答案可定位，沙箱保证修复可验证，安全提供明确边界，评测保证效果可度量。各能力的证据级别以 [Capability Matrix](capability-matrix.md) 为准；代码和清单不等同于 staging 实测。

## 1. RAG: 代码检索要可定位、可引用、可复现

难点：

- 代码不是普通文档。函数、类、方法、React/Vue 组件、导入导出关系比固定长度文本切块更重要。
- 问答结果必须能回到真实文件和行号，否则模型容易生成看似合理但无法验证的路径或引用。
- 单纯向量检索容易漏掉精确符号名，单纯关键词检索又无法覆盖语义表达。

实现：

- 对 TS/JS/Python/Vue 做语义分块，chunk payload 保存 repo、path、language、symbol、start/end line 等引用信息。
- 使用 PostgreSQL 存元数据，Qdrant 存向量；检索时结合关键词召回、向量召回、repo 过滤、确定性 rerank。
- 对高置信命中做 same-file context expansion，把相邻/父级 chunk 一起带入上下文，同时保留原始 citation。
- 支持多仓库问答，citation 带 repo_id/repo_name，避免跨仓库场景下引用混淆。

取舍：

- AST/SFC 分块比固定窗口复杂，但能换来更稳定的符号定位和行号引用；代价是语言覆盖需要逐步扩展。
- 先用确定性 rerank 而不是学习型 reranker，牺牲一部分排序上限，换来本地可复现、CI 可测试、无额外模型依赖。
- 上下文扩展提升回答完整性，但会增加 token；因此限制窗口和额外 chunk 数量，避免把无关代码塞进提示词。

## 2. 沙箱: Agent 生成的补丁必须隔离验证

难点：

- Agent 会修改和执行用户仓库代码，测试命令本身也可能不可信。
- 不同项目的依赖、测试命令、运行时间差异很大，既要能跑通常见项目的测试，又不能开放无限制执行。
- 本地演示需要启动简单，生产或多租户场景又需要更强隔离。

实现：

- 每次修复创建临时 workspace，复制必要文件，排除 `.env*`、`node_modules`、build/coverage 等高风险或大目录。
- 补丁通过 `git apply` 应用，测试命令必须命中 `SANDBOX_ALLOWED_COMMANDS`。
- Docker 执行默认关闭网络，设置 CPU、内存和 timeout。**仅本地 demo Compose overlay** 将 Docker socket 挂给 worker，以启动禁网测试容器；这是开发便利，不是托管部署拓扑。
- `SANDBOX_RUNTIME=gvisor` 与 `SANDBOX_RUNTIME=firecracker` 的配置、客户端控制路径和部署工件已存在；真实 gVisor/Firecracker/Kata runtime 尚无本仓库保留的本地或 staging 运行证据，不能表述为已验证运行时。

取舍：

- Docker 兼容性和开发效率最好，但隔离强度不如 microVM；因此本地默认 Docker。更强隔离是托管执行平面的部署目标，只有通过真实环境 qualification 后才能升级为 staging 验证能力。
- 命令白名单会降低灵活性，但能把风险从“任意命令执行”收敛到“明确允许的验证命令”。
- `--network none` 会让部分需要联网下载依赖的测试失败，因此更适合预装依赖或 CI 缓存完善的场景。

## 3. 安全: 前端 RBAC 不够，后端也必须二次校验

难点：

- 如果 RBAC 只在 Next.js proxy 做，后端仍然只认 admin token，一旦 proxy 配置错误或 token 泄漏，浏览器请求可能绕过角色限制。
- 直接信任 `role/user` header 会有伪造风险，必须证明这些 header 来自可信 proxy。
- CI/script 仍然需要无浏览器身份的服务调用，但不能让 CI token 拥有全部 admin 权限。

实现：

- 后端解析 `EvaluationPrincipal`，统一处理 admin/viewer、GitHub OAuth 用户、service-admin/service-ci/service-read token。
- Evaluation 路由做全路由 RBAC：读接口 viewer 可访问，运行接口 admin 或 CI token 可访问，数据集变更只允许 admin。
- Proxy 转发 `X-CodeMate-Evaluation-Role/User/Provider` 时，同时带 timestamp、nonce、signature。
- 后端用 HMAC 校验 method、path/query、timestamp、nonce、role、user、provider，校验通过后才信任 principal。
- nonce 通过 memory 或 Redis `SET NX EX` 消费一次，防 replay；支持 current/previous secret，方便无停机 key rotation。
- `CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY` 可要求浏览器 Evaluation 请求必须带 signed identity；生产环境要求显式配置。
- 前后端安全事件写入 JSONL audit log，后端日志包含解析出的 principal、role、provider、auth method、token kind。

取舍：

- HMAC 比短期 JWT 更简单，适合 proxy-to-backend 的内部信任边界；JWT 更标准但需要 issuer、claim、key id 和轮换策略。
- memory nonce store 适合单进程本地开发；多实例必须用 Redis，否则不同实例之间无法发现 replay。
- 继续保留 token-only service path 兼容 CI/script，但拆成 admin、ci、read token，避免一个 CI token 拥有全部权限。

## 4. 评测: 让 Agent 效果从演示变成可回归指标

难点：

- RAG 和修复效果不能只靠主观 demo，需要可重复数据集、快照、指标和历史趋势。
- 检索评测关注 Recall/latency，修复评测关注是否真正通过测试，两类指标粒度不同。
- CI gate 不能过于敏感，否则会频繁阻塞；也不能过松，否则无法发现质量退化。

实现：

- Evaluation Center 管理 datasets、cases、snapshots、runs、artifacts、history、compare reports。
- Retrieval evaluation 统计 Recall@5 和延迟；Fix evaluation 统计 Fix Success Rate、tool calls、延迟。
- CI gate 工作流可在 GitHub Actions 中调用，使用 scoped CI token 触发 run，并可作为合并门禁；单有 workflow 定义不等于存在成功 CI 运行，发布时必须链接 receipt 或 artifact。
- 评测、审计、安全页面都走同一套 RBAC，避免评测数据或历史结果被未授权用户修改。

取舍：

- snapshot 会增加存储和数据管理成本，但能保证同一次评测基于固定 case 定义，结果可复现。
- 固定阈值 gate 简单透明，适合秋招项目和 CI；复杂项目可以继续扩展分维度阈值、趋势阈值和 flaky case 处理。
- 先覆盖 retrieval/fix 两条主链路，比泛化到所有 Agent 行为更可控，也更容易解释指标和失败原因。

## 面试收束

可以这样总结：CodeMate 把 AI 代码助手从“能回答/能修复”推进到“可定位、可验证、可评测、可审计”。RAG 提供 grounded context，Agent 生成补丁，沙箱验证结果，评测系统持续回归，RBAC 与签名身份提供明确的部署安全边界；真实 CI/staging 与托管运行时结论必须由对应 evidence artifact 支撑。
