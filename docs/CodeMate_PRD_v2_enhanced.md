# CodeMate —— 代码库智能问答与自动修复 Agent

## PRD & 技术方案文档 v2.0（简历项目强化版）

---

## 0. 版本说明

本版本在 v1.0 的基础上进行重构，核心目标是让项目从“概念完整的 Agent 产品设想”升级为“可落地、可演示、能写进简历并经得起面试追问的工程项目”。

主要调整如下：

1. **收缩项目边界**：不再强调“索引任意 Git 仓库”，首期聚焦 TypeScript / Python 中小型仓库，避免目标过大导致难以落地。
2. **强化技术闭环**：围绕“代码索引 → 混合检索 → Agent 修复 → 沙箱测试 → 轨迹可视化 → 评测指标”构建完整闭环。
3. **补充工程细节**：完善 AST 分块、增量索引、混合检索、Agent 状态机、沙箱安全、Memory、Trace、Evaluation 等关键模块。
4. **修正 CoT 展示问题**：前端不展示模型隐藏思维链，而是展示可解释执行轨迹，如 Plan、Tool Call、Observation、Patch、Test Result。
5. **面向简历表达优化**：所有设计尽量能落到“我做了什么技术决策、解决了什么问题、如何衡量效果”。

---

## 1. 项目定位

### 1.1 项目名称

**CodeMate：代码库智能问答与自动修复 Agent**

### 1.2 一句话介绍

CodeMate 是一个面向 TypeScript / Python 项目的代码库智能助手，支持对 Git 仓库进行 AST 语义索引，通过自然语言问答理解代码结构，并基于 LangGraph 构建 Bug 自动修复 Agent，在 Docker 沙箱中验证生成的 patch，最终输出可审查的代码 diff。

### 1.3 项目目标

本项目不是要做一个商业级 Devin 或 Cursor，而是实现一个**小而完整的 Code Agent 闭环**：

```text
输入 Git 仓库
→ AST 语义索引
→ 代码问答与引用溯源
→ 输入报错日志 / 失败测试
→ Agent 检索相关代码
→ 生成 patch
→ Docker 沙箱运行测试
→ 失败反思重试
→ 输出最终 diff 与执行轨迹
```

### 1.4 简历定位

该项目适合用于展示以下能力：

- Agent 工程化能力：任务拆解、工具调用、状态机编排、反思重试、执行轨迹记录。
- RAG 深度能力：代码语义分块、混合检索、metadata 过滤、rerank、引用溯源。
- 前端产品能力：SSE 流式交互、Agent Timeline、Diff Viewer、代码引用跳转。
- 后端工程能力：异步任务队列、向量库、PostgreSQL 建模、Docker 沙箱、可观测性。
- 项目深挖能力：有完整指标体系，可以讲准确率、召回率、修复成功率、成本和耗时。

---

## 2. 项目边界与范围控制

### 2.1 首期支持范围

| 模块 | 首期范围 | 不做 / 后续再做 |
|---|---|---|
| 仓库类型 | 中小型 TypeScript / Python 项目 | 超大型 monorepo、多仓库联动 |
| 代码来源 | Git URL clone、本地 zip 上传 | 企业私有 Git 权限体系 |
| 语言解析 | TypeScript、JavaScript、Python | Java、Go、Rust 等多语言 |
| 问答能力 | 代码位置、模块职责、调用关系、报错解释 | 自动生成完整业务文档 |
| 修复能力 | 基于失败测试 / 报错日志的局部修复 | 大规模重构、自动合并 PR |
| 沙箱能力 | Docker 临时容器运行测试命令 | 云原生多租户沙箱平台 |
| 评测规模 | 20-50 个自建任务样例 | 工业级 benchmark |

### 2.2 为什么要收缩范围

如果项目声称支持“任意仓库、任意语言、任意 Bug 自动修复”，面试官会很容易追问到底层实现和效果数据，风险较高。首期聚焦 TypeScript / Python，可以把精力放在技术深度上：AST 分块、混合检索、Agent 状态机、沙箱验证和评测指标。

---

## 3. 目标用户与典型场景

| 用户 / 场景 | 痛点 | CodeMate 能力 |
|---|---|---|
| 新人接手代码库 | 不知道入口文件、模块职责、核心流程 | 自然语言代码问答，返回文件路径与行号引用 |
| 开发者排查 Bug | 报错栈长、定位慢、不确定改哪里 | Agent 根据报错日志检索代码、生成 patch、运行测试验证 |
| 前端 / 后端同学跨模块理解 | 不熟悉其他模块调用关系 | 结合 AST metadata 与检索结果解释依赖关系 |
| 面试展示项目 | 普通 AI 套壳项目缺少技术深度 | 展示完整 Agent 执行轨迹和自动修复 demo |

---

## 4. 核心功能需求

## 4.1 P0：必须完成的最小闭环

### 4.1.1 仓库接入与索引

#### 功能描述

用户输入 Git 仓库 URL 或上传本地 zip 后，系统自动创建索引任务，完成代码拉取、文件过滤、AST 解析、chunk 生成、embedding 计算和 Qdrant 写入。

#### 关键流程

```text
提交仓库
→ 创建 repository 记录
→ 异步 clone / 解压
→ 根据 .gitignore / 默认规则过滤文件
→ 识别语言类型
→ AST 解析
→ 生成语义 chunk
→ 写入 PostgreSQL metadata
→ 写入 Qdrant 向量索引
→ 更新索引状态
```

#### 文件过滤规则

默认忽略以下内容：

```text
node_modules/
dist/
build/
.next/
coverage/
.git/
.env
*.lock
*.png / *.jpg / *.mp4
大于 500KB 的单文件
```

#### 索引状态

| 状态 | 说明 |
|---|---|
| `pending` | 已创建仓库记录，等待索引 |
| `cloning` | 正在拉取或解压代码 |
| `parsing` | 正在解析文件与生成 chunk |
| `embedding` | 正在生成向量 |
| `indexed` | 索引完成，可以问答 |
| `failed` | 索引失败，记录错误原因 |

---

### 4.1.2 AST 语义分块

#### 为什么不用固定长度切分

代码不同于普通文档。固定长度切分可能把函数、类、组件拆断，导致 LLM 拿到的上下文不完整。CodeMate 使用 AST 解析代码，以函数、类、组件、导出方法为最小语义单元生成 chunk。

#### 分块粒度

| 语言 | 分块策略 |
|---|---|
| TypeScript / JavaScript | function、class、method、arrow function、React component、export symbol |
| Python | function、class、method、decorated function |
| Vue SFC（P1） | script setup、methods、computed、watch、template 关键结构 |

#### chunk metadata 设计

每个代码 chunk 除文本内容外，还需要保存以下 metadata：

```json
{
  "repo_id": "repo_001",
  "file_path": "src/auth/token.ts",
  "language": "typescript",
  "symbol_name": "refreshAccessToken",
  "symbol_type": "function",
  "start_line": 32,
  "end_line": 78,
  "imports": ["axios", "jwtDecode"],
  "exports": ["refreshAccessToken"],
  "content_hash": "sha256_xxx",
  "commit_hash": "abc123"
}
```

#### 长函数处理策略

如果单个函数超过模型上下文安全范围，不直接整块塞入，而是：

1. 保留函数签名、注释、参数、返回值。
2. 按内部语句块二次切分。
3. 检索时优先返回函数摘要，再根据需要读取完整文件。

---

### 4.1.3 增量索引

#### 目标

仓库更新后不全量重建索引，而是只处理变更文件，降低时间和 token 成本。

#### 实现策略

```text
获取当前 commit_hash
→ git diff --name-only old_commit new_commit
→ 找到 changed files
→ 删除旧 file_path 对应 chunks
→ 重新 AST 解析变更文件
→ 重新写入 PostgreSQL 和 Qdrant
→ 更新 repository.last_commit_hash
```

#### 面试可讲点

- 使用 `content_hash` 避免重复 embedding。
- 使用 `repo_id + file_path` 定位旧 chunk 并删除。
- 对删除文件同步清理 PostgreSQL 和 Qdrant。
- 对新增文件走完整 AST 解析流程。

---

### 4.1.4 混合检索 Retrieval

#### 为什么不能只用向量检索

代码场景下有大量精确查询，例如函数名、变量名、文件路径、报错栈、类名。单纯 embedding 对这类精确 token 不一定稳定，因此需要混合检索。

#### 检索链路

```text
用户问题 / 报错日志
→ Query Rewrite：提取关键词、函数名、文件路径、错误类型
→ BM25 / 关键词检索：匹配函数名、文件名、报错栈
→ 向量检索：匹配自然语言语义
→ metadata 过滤：repo_id、language、file_path
→ Rerank 重排：选择最相关 TopK
→ Context Expansion：补充 import、类型定义、相邻函数
→ 返回给 LLM / Agent
```

#### 检索策略

| 检索方式 | 适合场景 |
|---|---|
| BM25 / 关键词检索 | 函数名、变量名、文件路径、错误栈 |
| 向量检索 | “登录逻辑在哪里”“订单状态如何流转”这类自然语言问题 |
| metadata 过滤 | 指定语言、目录、文件类型、仓库 |
| rerank | TopK 结果过多时进行相关性重排 |
| context expansion | 找到函数后补充 import、类型定义、同文件上下文 |

---

### 4.1.5 代码库自然语言问答

#### 功能描述

用户可以针对某个已索引仓库提问，系统返回自然语言答案，并给出引用来源。

#### 示例问题

```text
登录逻辑在哪里实现的？
refresh token 失效后会发生什么？
订单创建接口的库存扣减逻辑在哪？
这个项目的路由是怎么组织的？
AuthProvider 被哪些组件依赖？
```

#### 回答要求

每个回答必须包含：

1. 直接结论。
2. 相关代码位置：文件路径 + 起止行号。
3. 关键代码逻辑解释。
4. 不确定时明确说明“未在当前索引中找到”。
5. 不编造不存在的文件和函数。

#### 引用格式

```text
相关代码：src/auth/token.ts:32-78
相关组件：src/components/AuthProvider.tsx:15-96
```

---

### 4.1.6 Bug 定位与自动修复 Agent

#### 输入类型

用户可以输入以下任意一种信息：

- 报错日志。
- 失败测试输出。
- issue 描述。
- 期望行为和实际行为。

#### Agent 核心流程

```text
InspectRepository
→ ReproduceFailure
→ PlanNextAction ↔ ExecuteLocalAction
→ GeneratePatch
→ ApplyPatch
→ TargetedTests
→ RegressionChecks
→ Reflect / FinalAnswer
```

#### LangGraph 状态机设计

| 节点 | 作用 | 输入 | 输出 |
|---|---|---|---|
| `InspectRepository` | 识别仓库与测试配置 | workspace + request | resolved commands |
| `ReproduceFailure` | Patch 前复现原始失败 | original workspace | baseline evidence |
| `PlanNextAction` | 根据 observation 选择一个严格类型动作 | issue + state + budgets | Pydantic action union |
| `ExecuteLocalAction` | 校验白名单、Schema、预算与重复调用后执行 | structured action | observation + evidence |
| `GeneratePatch` | 生成标准 diff | diagnosis + files | unified diff |
| `ApplyPatch` | 应用 patch | diff | apply result |
| `TargetedTests` | 运行目标测试 | patched workspace | targeted evidence |
| `RegressionChecks` | 运行回归检查 | patched workspace | regression evidence |
| `Reflect` | 失败结果写入 evidence 并回滚 workspace | failed diff + test output | new planner observation |
| `FinalAnswer` | 输出最终结果 | diff + trace | summary + patch |

#### 工具集设计

| Tool | 功能 | 备注 |
|---|---|---|
| `search_code(query, repo_id)` | 搜索相关代码 chunk | 混合检索 |
| `read_file(path, start_line?, end_line?)` | 读取文件内容 | 控制读取范围 |
| `list_files(pattern?)` | 查看仓库文件结构 | 避免盲目猜文件 |
| `find_symbol(symbol)` | 精确定位符号定义 | 基于索引 metadata |
| `find_references(symbol)` | 查找符号引用 | 有界候选与标识符边界过滤 |
| `apply_patch(diff)` | 应用统一 diff | 失败时返回错误 |
| `run_tests(command?)` | 执行测试命令 | Docker 沙箱中运行 |
| `git_diff()` | 查看当前修改 | 用于最终输出 |
| `reset_workspace()` | 回滚失败 patch | 防止污染下一轮 |

#### 反思重试策略

测试失败后，不让模型盲目继续生成，而是要求进入 `Reflect` 节点：

```text
分析失败原因
→ 判断是 patch 语法错误、定位错误、测试命令错误还是上下文不足
→ 决定下一步：重新检索 / 读取更多文件 / 重新生成 patch / 放弃并说明原因
```

默认最大 Patch 重试次数为 3；Planner 同时受工具调用、Planner 调用、Token、总时间、单次读取行数与连续无进展次数约束。重复搜索与重复 Patch 会被 fingerprint guardrail 拒绝。Graph 的普通节点使用数据库 checkpointer，每个 super-step 后均可恢复。

---

### 4.1.7 Docker 沙箱验证

#### 为什么需要沙箱

Agent 生成的代码不能直接在宿主机执行。代码仓库本身也可能包含不可信脚本，因此必须在隔离环境中执行测试。

#### 沙箱执行流程

```text
创建临时 workspace
→ 复制仓库代码
→ 应用 patch
→ 启动 Docker 容器
→ 安装依赖或使用预构建镜像
→ 执行测试命令
→ 收集 stdout / stderr / exit_code
→ 销毁容器
```

#### 安全限制

| 限制项 | 策略 |
|---|---|
| 网络 | 默认禁用外网访问 |
| 文件系统 | 只挂载临时 workspace，不挂载宿主机敏感目录 |
| 环境变量 | 禁止传入真实 `.env`、API Key、SSH Key |
| CPU / 内存 | 限制 CPU、memory，防止恶意脚本占满资源 |
| 执行时间 | 设置 timeout，超时直接终止容器 |
| 命令范围 | 仅允许配置好的测试命令，如 `npm test`、`pytest`、`pnpm test` |
| 容器生命周期 | 每次任务结束后销毁容器 |

#### 测试命令识别

优先级如下：

1. 用户手动指定测试命令。
2. 从 package.json 读取 `test` script。
3. Python 项目默认尝试 `pytest`。
4. 如果没有测试命令，则只进行 patch 格式校验和静态检查，并明确提示“未运行测试”。

---

### 4.1.8 Agent 执行轨迹可视化

#### 重要修正：不展示隐藏 CoT

前端不展示模型完整隐藏思维链，而是展示可解释执行轨迹。这样更符合真实产品设计，也能避免把模型内部推理直接暴露给用户。

#### Trace 事件类型

```ts
export type AgentTraceEvent =
  | { type: 'agent_plan'; action: PlanNextAction; budget: unknown; createdAt: string }
  | { type: 'agent_observation'; action: string; evidenceId?: string; createdAt: string }
  | { type: 'agent_guardrail'; action: string; reason: string; createdAt: string }
  | { type: 'checkpoint_resume'; nextNodes: string[]; createdAt: string }
  | { type: 'tool_call'; toolName: string; input: unknown; createdAt: string }
  | { type: 'tool_result'; toolName: string; output: unknown; durationMs: number; createdAt: string }
  | { type: 'patch'; diff: string; createdAt: string }
  | { type: 'test_result'; passed: boolean; exitCode: number; output: string; createdAt: string }
  | { type: 'reflection'; summary: string; nextAction: string; createdAt: string }
  | { type: 'final'; summary: string; createdAt: string };
```

#### 前端展示

页面使用 Timeline 组件展示：

```text
Step 1：解析报错日志
Step 2：检索相关代码 search_code
Step 3：读取 src/auth/token.ts
Step 4：生成 patch
Step 5：运行 npm test
Step 6：测试失败，进入反思
Step 7：重新生成 patch
Step 8：测试通过，输出最终 diff
```

#### 前端亮点

- SSE 实时接收 Agent 执行事件。
- 使用 Diff Viewer 展示 patch 修改前后。
- 点击引用文件路径跳转到代码片段。
- 展示每个工具调用耗时，体现可观测性。
- 修复结果支持“接受 / 拒绝 / 复制 diff / 下载 patch”。

---

## 4.2 P1：增强功能

| 功能 | 说明 | 价值 |
|---|---|---|
| Vue SFC 支持 | 解析 `.vue` 文件的 script / template | 更贴近前端项目 |
| PR Review | 输入 diff，检查潜在问题 | 可作为扩展场景 |
| Repo Summary | 索引完成后生成项目结构摘要 | 形成仓库级记忆 |
| 调用关系分析 | 基于 import/export 和符号引用生成简易依赖图 | 增强代码理解能力 |
| 用户反馈闭环 | 记录用户采纳 / 拒绝修复结果 | 用于优化 prompt 和策略 |

---

## 4.3 P2：加分项

| 功能 | 说明 |
|---|---|
| 多仓库联合检索 | 微服务场景下跨仓库查调用链 |
| 自动生成架构文档 | 根据目录结构和依赖关系生成模块说明 |
| gVisor / Firecracker 沙箱 | 替代普通 Docker，提升隔离级别 |
| CI 集成 | 自动读取失败 CI 日志并生成修复建议 |

---

## 5. Agent Memory 设计

### 5.1 为什么需要 Memory

Code Agent 如果每次任务都从零开始理解仓库，会浪费 token，也容易产生不一致的判断。Memory 的价值是把“仓库结构、历史失败原因、用户偏好”沉淀下来，提升后续任务效率和稳定性。

### 5.2 Memory 类型

| Memory 类型 | 存储内容 | 使用场景 |
|---|---|---|
| Repo Memory | 项目技术栈、目录结构、启动命令、测试命令、核心模块说明 | 后续问答和修复不必重复分析仓库 |
| Run Memory | 每次修复尝试、失败 patch、测试输出、反思摘要 | 避免重试时重复犯同样错误 |
| User Preference Memory | 用户偏好的修复风格，如最小改动、不重构、不改 API | 生成更符合项目习惯的 patch |

### 5.3 Repo Summary 示例

```json
{
  "repo_id": "repo_001",
  "framework": "Next.js 15.5.22",
  "language": "TypeScript",
  "package_manager": "pnpm",
  "test_command": "pnpm test",
  "entry_points": ["src/app/page.tsx", "src/app/api"],
  "core_modules": [
    { "name": "auth", "path": "src/lib/auth", "summary": "用户登录与 token 刷新" },
    { "name": "billing", "path": "src/lib/billing", "summary": "订阅支付与额度扣减" }
  ]
}
```

---

## 6. 系统架构设计

```text
┌──────────────────────────────────────────────────────────┐
│ Frontend：Next.js 15.5.22 + TypeScript + Tailwind + shadcn/ui │
│ - 仓库管理                                                │
│ - 代码问答 Chat                                           │
│ - Agent Trace Timeline                                    │
│ - Diff Viewer                                             │
│ - 代码引用跳转                                            │
└───────────────────────┬──────────────────────────────────┘
                        │ REST / SSE
┌───────────────────────▼──────────────────────────────────┐
│ Backend：FastAPI                                          │
│ - Repo Service                                            │
│ - Index Service                                           │
│ - Retrieval Service                                       │
│ - Agent Service                                           │
│ - Sandbox Service                                         │
│ - Trace Service                                           │
└──────┬───────────────┬────────────────┬──────────────────┘
       │               │                │
┌──────▼──────┐ ┌──────▼──────┐ ┌───────▼────────┐
│ LangGraph   │ │ Redis Queue │ │ Docker Sandbox │
│ Agent Flow  │ │ Index Tasks │ │ Test Runner    │
└──────┬──────┘ └──────┬──────┘ └────────────────┘
       │               │
┌──────▼──────┐ ┌──────▼──────────┐
│ Qdrant      │ │ PostgreSQL      │
│ Vector DB   │ │ Metadata / Logs │
└─────────────┘ └─────────────────┘
```

### 6.1 服务拆分

| 服务 | 职责 |
|---|---|
| Repo Service | 处理仓库创建、clone、状态查询、文件读取 |
| Index Service | 文件过滤、AST 解析、chunk 生成、embedding 写入 |
| Retrieval Service | query rewrite、混合检索、rerank、上下文扩展 |
| Agent Service | LangGraph 状态机、工具调用、反思重试 |
| Sandbox Service | Docker 容器创建、patch 应用、测试执行、结果收集 |
| Trace Service | 记录并通过 SSE 推送 Agent 事件 |

---

## 7. 数据库设计

### 7.1 PostgreSQL 核心表

#### repositories

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 仓库 ID |
| name | varchar | 仓库名称 |
| repo_url | text | Git 地址，可为空 |
| local_path | text | 服务器临时路径 |
| status | varchar | pending / cloning / parsing / indexed / failed |
| language_summary | jsonb | 语言统计 |
| last_commit_hash | varchar | 最近一次索引 commit |
| indexed_at | timestamp | 索引完成时间 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

#### code_files

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 文件 ID |
| repo_id | uuid | 所属仓库 |
| file_path | text | 文件路径 |
| language | varchar | 语言 |
| content_hash | varchar | 文件内容 hash |
| line_count | integer | 行数 |
| imports | jsonb | import 信息 |
| exports | jsonb | export 信息 |

#### code_chunks

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | chunk ID |
| repo_id | uuid | 所属仓库 |
| file_id | uuid | 所属文件 |
| file_path | text | 文件路径 |
| symbol_name | varchar | 函数 / 类 / 组件名 |
| symbol_type | varchar | function / class / component / method |
| start_line | integer | 起始行 |
| end_line | integer | 结束行 |
| content | text | chunk 原文 |
| summary | text | chunk 摘要，可选 |
| embedding_id | varchar | Qdrant point ID |
| content_hash | varchar | chunk hash |

#### conversations / messages

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 消息 ID |
| conversation_id | uuid | 会话 ID |
| repo_id | uuid | 仓库 ID |
| role | varchar | user / assistant / tool |
| content | text | 消息内容 |
| cited_chunks | jsonb | 引用的代码 chunk |
| created_at | timestamp | 创建时间 |

#### agent_runs

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | run ID |
| repo_id | uuid | 仓库 ID |
| task_type | varchar | fix / review / explain |
| user_input | text | 用户原始输入 |
| status | varchar | running / success / failed / cancelled |
| final_diff | text | 最终 diff |
| final_summary | text | 最终说明 |
| iterations | integer | 重试次数 |
| created_at | timestamp | 创建时间 |
| finished_at | timestamp | 完成时间 |

#### agent_steps

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | step ID |
| run_id | uuid | 所属 run |
| step_type | varchar | plan / tool_call / tool_result / reflection / final |
| tool_name | varchar | 工具名，可为空 |
| input_json | jsonb | 输入 |
| output_json | jsonb | 输出 |
| duration_ms | integer | 耗时 |
| created_at | timestamp | 创建时间 |

#### evaluations

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | 评测 ID |
| repo_id | uuid | 仓库 ID |
| task_type | varchar | qa / fix / retrieval |
| question | text | 测试问题 |
| expected_file | text | 期望命中文件 |
| expected_lines | jsonb | 期望命中行号 |
| result_json | jsonb | 实际结果 |
| passed | boolean | 是否通过 |

---

### 7.2 Qdrant Payload 设计

```json
{
  "repo_id": "repo_001",
  "chunk_id": "chunk_001",
  "file_path": "src/lib/auth.ts",
  "language": "typescript",
  "symbol_name": "login",
  "symbol_type": "function",
  "start_line": 10,
  "end_line": 45,
  "content_hash": "sha256_xxx"
}
```

---

## 8. API 设计

| Method | Path | 说明 |
|---|---|---|
| `POST` | `/repos` | 创建仓库索引任务 |
| `GET` | `/repos` | 获取仓库列表 |
| `GET` | `/repos/{repo_id}` | 获取仓库详情 |
| `GET` | `/repos/{repo_id}/status` | 查询索引状态 |
| `POST` | `/repos/{repo_id}/reindex` | 触发增量索引 |
| `GET` | `/repos/{repo_id}/files` | 获取文件树 |
| `GET` | `/repos/{repo_id}/files/content` | 读取文件内容 |
| `POST` | `/repos/{repo_id}/chat` | 代码问答，SSE 返回 |
| `POST` | `/repos/{repo_id}/fix` | 创建 Bug 修复 Agent 任务 |
| `GET` | `/runs/{run_id}` | 获取 Agent run 详情 |
| `GET` | `/runs/{run_id}/trace` | SSE 获取执行轨迹 |
| `POST` | `/runs/{run_id}/cancel` | 取消执行 |
| `POST` | `/runs/{run_id}/feedback` | 提交采纳 / 拒绝反馈 |

### 8.1 Chat SSE 返回示例

```text
event: token
data: {"content":"登录逻辑主要在"}

event: citation
data: {"file_path":"src/auth/login.ts","start_line":12,"end_line":56}

event: done
data: {"message_id":"msg_001"}
```

### 8.2 Trace SSE 返回示例

```text
event: tool_call
data: {"toolName":"search_code","input":{"query":"refresh token expired"}}

event: tool_result
data: {"toolName":"search_code","durationMs":342,"output":{"count":5}}

event: patch
data: {"diff":"--- a/src/auth.ts\n+++ b/src/auth.ts\n..."}

event: test_result
data: {"passed":true,"exitCode":0,"output":"12 tests passed"}
```

---

## 9. 前端产品设计

### 9.1 页面结构

| 页面 | 功能 |
|---|---|
| 仓库列表页 | 查看已索引仓库、索引状态、重新索引 |
| 仓库详情页 | 展示文件树、语言统计、Repo Summary |
| 代码问答页 | Chat UI，支持代码引用和文件跳转 |
| Bug 修复页 | 输入报错日志，启动 Agent 修复任务 |
| Agent 执行页 | Timeline + Diff Viewer + Test Result |

### 9.2 关键组件

| 组件 | 说明 |
|---|---|
| `RepoUploader` | Git URL / zip 上传 |
| `IndexProgress` | 索引进度展示 |
| `CodeChat` | 代码问答聊天框 |
| `CitationCard` | 文件路径 + 行号引用卡片 |
| `AgentTimeline` | Agent 执行轨迹时间线 |
| `ToolCallCard` | 展示工具调用输入输出 |
| `DiffViewer` | 展示 patch diff |
| `TestResultPanel` | 展示测试输出和通过状态 |

### 9.3 前端技术亮点

- 使用 SSE 同时支持 Chat 流式输出和 Agent Trace 实时推送。
- 使用状态机思维管理 Agent run 的前端状态：idle / running / success / failed / cancelled。
- 使用虚拟列表或折叠面板展示长 trace，避免页面卡顿。
- Diff Viewer 支持新增 / 删除 / 修改行高亮。
- 引用卡片点击后打开代码片段，增强可解释性。

---

## 10. 非功能需求

| 维度 | 要求 |
|---|---|
| 安全性 | 沙箱执行隔离，禁止外网，限制资源，过滤敏感文件 |
| 性能 | 中小仓库首次索引可接受在分钟级；问答首 token 尽量小于 2 秒 |
| 可观测性 | 每次 run 记录工具调用、耗时、输入输出摘要、错误信息 |
| 成本控制 | 混合检索 + rerank + context expansion，避免把大量代码直接塞入上下文 |
| 稳定性 | Agent 最大重试次数限制，失败时给出明确原因而不是无限循环 |
| 可解释性 | 回答必须给引用，修复必须展示 diff 和测试结果 |
| 可部署性 | 提供 Docker Compose，一键启动前端、后端、PostgreSQL、Redis、Qdrant |

---

## 11. 评测体系

### 11.1 为什么要做评测

没有评测指标的 Agent 项目很容易变成“看起来很智能”。为了让项目适合写简历，需要能回答以下问题：

```text
你的检索准不准？
AST 分块比固定长度分块好在哪里？
Agent 自动修复成功率是多少？
反思重试有没有提升成功率？
一次任务平均调用多少次工具？
平均成本和耗时是多少？
```

### 11.2 自建测试集

构建 20-50 个测试任务，分为三类：

| 类型 | 样例 | 判断方式 |
|---|---|---|
| 代码问答 | “登录逻辑在哪里？” | 回答是否引用正确文件和行号 |
| 检索任务 | 给定问题，目标函数已知 | TopK 是否包含目标 chunk |
| Bug 修复 | 给定失败测试和错误代码 | Agent patch 后测试是否通过 |

### 11.3 核心指标

| 指标 | 含义 |
|---|---|
| Recall@5 | 前 5 个检索结果是否包含目标代码块 |
| Citation Precision / Line Overlap | 检索引用中相关 citation 比例与期望行区间覆盖率 |
| Final Verified Fix Rate | 修前复现失败、Patch 应用、修后目标测试与回归测试实际执行并通过的比例 |
| Verified Fix@1 | 第一轮即满足完整 verification evidence 的比例 |
| Reflection Improvement | 最终 Verified Fix Rate 相对 Verified Fix@1 的变化 |
| Avg Tool Calls | 平均工具调用次数 |
| Avg Latency | 平均任务耗时 |
| Avg Token Cost | 平均 token 消耗 |

### 11.4 对比实验

建议至少做两个对比：

1. **vector-only vs hybrid vs hybrid + rerank/context**：对比动态 Recall@K、MRR、nDCG 和引用准确率。
2. **无反思修复 vs 反思重试修复**：对比 Verified Fix@1 与最终 Verified Fix Rate。
3. **固定 workflow vs adaptive planner**：对比最终 Verified Fix Rate、工具路径、成本与 p95 延迟。

### 11.5 简历中如何使用评测结果

未完成真实评测前，不写虚假的百分比。完成后从带 model、prompt hash、commit SHA 和 dataset
snapshot 的 artifact 自动生成简历表述，不在文档中保留待替换百分比：

```text
在固定版本 benchmark 上执行三组消融；具体 Recall@K、Verified Fix@1 和最终 Verified Fix Rate 以 benchmarks/results 下对应 artifact 的实测值为准。
```

---

## 12. 技术栈选型

| 层级 | 技术 | 选型理由 |
|---|---|---|
| 前端 | Next.js 15.5.22 + TypeScript + TailwindCSS + shadcn/ui | 适合构建流式 Chat、Timeline、Diff Viewer，与你现有技术栈匹配 |
| 后端 | FastAPI | async 支持好，适合 SSE、Agent 编排、Python AI 生态 |
| Agent 编排 | LangGraph | 用状态机表达多节点 Agent，比简单 Chain 更适合修复循环 |
| 向量库 | Qdrant | 支持向量检索和 payload metadata 过滤 |
| 结构化存储 | PostgreSQL | 保存仓库、chunk、消息、trace、评测结果 |
| 队列 / 缓存 | Redis + RQ / Celery | 索引任务异步化，避免请求超时 |
| AST 解析 | tree-sitter / TypeScript Compiler API / Python ast | 保证代码 chunk 语义完整 |
| 沙箱 | Docker | 隔离执行测试命令，验证 patch |
| LLM | OpenAI / DeepSeek / Claude API 可替换 | 通过 provider 抽象降低模型绑定 |
| 部署 | Docker Compose | 面试 demo 和本地部署简单稳定 |

---

## 13. 开发计划

### Phase 1：项目脚手架与仓库索引（第 1 周）

交付目标：

- 前后端项目初始化。
- PostgreSQL / Redis / Qdrant / Docker Compose 配置完成。
- 支持 Git URL clone。
- 支持 TS / Python 文件过滤和 AST 分块。
- chunk metadata 写入 PostgreSQL，embedding 写入 Qdrant。

验收标准：

```text
输入一个 demo 仓库 URL 后，可以在页面看到索引状态从 pending 到 indexed。
数据库中能看到 code_files 和 code_chunks。
Qdrant 中能查询到对应向量点。
```

---

### Phase 2：代码问答 RAG 闭环（第 2 周）

交付目标：

- 实现混合检索基础版本。
- 支持 Chat SSE 流式回答。
- 回答包含文件路径和行号引用。
- 前端支持引用卡片点击查看代码片段。

验收标准：

```text
用户提问“登录逻辑在哪里”，系统能返回相关文件路径、行号和解释。
不确定的问题能明确提示未找到，而不是编造。
```

---

### Phase 3：Bug 修复 Agent 闭环（第 3-4 周）

交付目标：

- 使用 LangGraph 实现受控 `PlanNextAction ↔ ExecuteLocalAction` 循环以及严格的修前复现、修后双阶段验证。
- 实现 search_code、read_file、list_files、find_symbol、find_references、run_tests 等模型可选动作；Patch 应用与最终验证保持确定性。
- 使用数据库 LangGraph checkpointer 和 RQ 退避重试支持 Worker 故障恢复。
- Docker 沙箱中执行测试。
- 支持最多 3 轮失败反思重试。

验收标准：

```text
准备一个带失败测试的 demo 仓库。
输入失败日志后，Agent 能生成 patch。
patch 应用后测试通过，并输出最终 diff。
```

---

### Phase 4：Agent Trace 与 Diff Viewer（第 4-5 周）

交付目标：

- Agent 执行事件写入 agent_steps。
- 前端通过 SSE 实时展示 Timeline。
- 展示 Tool Call、Patch、Test Result、Reflection。
- Diff Viewer 支持查看最终 patch。

验收标准：

```text
用户可以看到 Agent 每一步做了什么、调用了什么工具、测试是否通过。
用户可以复制最终 diff 或查看修改前后代码。
```

---

### Phase 5：评测、打磨与简历材料（第 5 周）

交付目标：

- 构建 20-50 个评测任务。
- 统计 Recall@5、Fix Success Rate、Avg Tool Calls 等指标。
- 准备 1 个稳定 demo 仓库。
- 编写 README、架构图、演示 GIF、简历表述。

验收标准：

```text
项目可以一键启动。
README 能说明架构和核心流程。
面试时可以现场演示“报错日志 → 自动修复 → 测试通过”。
```

---

## 14. 风险与应对

| 风险 | 表现 | 应对方案 |
|---|---|---|
| 范围过大 | 多语言、多仓库、PR Review 都想做，最终烂尾 | 首期只做 TS / Python + 单仓库 + P0 闭环 |
| 检索不准 | 问答引用错文件、Agent 定位错代码 | 混合检索、rerank、context expansion、评测集优化 |
| patch 无法应用 | LLM 输出 diff 格式不稳定 | 统一 diff schema 校验，失败自动要求重新生成 |
| 测试执行失败 | 环境依赖复杂，容器跑不起来 | 准备固定 demo 仓库，优先支持简单测试命令 |
| Agent 无限循环 | 一直失败重试 | 设置最大迭代次数和失败终止条件 |
| 安全风险 | 执行恶意代码 | Docker 隔离、禁网、限资源、过滤敏感文件 |
| 简历被追问穿 | 写了未实现能力 | 简历只写实际完成的 P0，不写 P1/P2 作为已完成 |

---

## 15. 推荐 Demo 仓库设计

为了保证面试展示稳定，建议专门准备一个小型 demo 仓库，而不是随便找大型开源项目。

### 15.1 TypeScript Demo

功能：简单 Todo / Auth / Order 模块。

内置 Bug 示例：

| Bug | 失败表现 | 预期修复 |
|---|---|---|
| token 过期判断反了 | refresh token 测试失败 | 修改条件判断 |
| 数组边界未处理 | 空数组时报错 | 添加 guard clause |
| 金额计算浮点误差 | 单元测试不通过 | 使用 cents 整数计算 |
| async 函数漏 await | 返回 Promise 未解析 | 添加 await |

### 15.2 Python Demo

功能：简单工具函数库或 Flask API。

内置 Bug 示例：

| Bug | 失败表现 | 预期修复 |
|---|---|---|
| 参数为空未处理 | pytest 报 TypeError | 添加参数校验 |
| 日期格式解析错误 | 测试断言失败 | 修复 format |
| 字典 key 缺失 | KeyError | 使用 get 或默认值 |

### 15.3 Demo 展示脚本

```text
1. 打开仓库详情页，展示已完成索引。
2. 提问：“refresh token 的逻辑在哪里？”
3. 系统返回 src/auth/token.ts:xx-xx，并解释逻辑。
4. 切到 Bug 修复页，粘贴失败测试日志。
5. Agent 开始执行，Timeline 实时出现 search_code、read_file、generate_patch、run_tests。
6. 第一次测试失败，进入 Reflect。
7. 第二次 patch 成功，测试通过。
8. 展示最终 diff，并解释为什么这样修。
```

---

## 16. 简历表述建议

### 16.1 无数据版本

```text
CodeMate 代码库智能问答与自动修复 Agent
技术栈：Next.js 15.5.22、FastAPI、LangGraph、Qdrant、PostgreSQL、Redis、Docker、OpenAI API

- 设计并实现面向 TypeScript/Python 仓库的代码索引管道，基于 AST 将函数、类、组件切分为语义 chunk，并记录文件路径、起止行号、符号名称、imports/exports 等 metadata，用于精准代码问答与溯源引用。
- 实现关键词检索 + 向量检索 + metadata 过滤 + rerank 的混合检索策略，解决代码场景下函数名、报错栈、文件路径等精确匹配召回不稳定的问题。
- 基于 LangGraph 构建受控 Bug 修复 Agent Loop，由模型根据 observation 动态选择严格类型的代码工具，执行器强制 Schema、白名单、调用/Token/时间预算、重复调用与无进展停机策略，并以数据库 checkpoint 支持节点级故障恢复。
- 通过 Docker 沙箱隔离执行 Agent 生成的 patch，配置网络禁用、资源限制、超时终止和临时工作目录，避免直接采信 LLM 输出。
- 基于 SSE 实现 Agent 执行轨迹实时可视化，前端展示 Plan、Tool Call、Observation、Patch Diff、Test Result 等事件，提升修复过程透明度。
```

### 16.2 有数据版本

```text
- 只引用 `benchmarks/results` 中已完成 artifact 的动态 Recall@K、MRR、nDCG、Citation Precision、Verified Fix@1、最终 Verified Fix Rate、成本和 p95 延迟。
- 简历数字必须同时保留模型/provider、prompt hash、代码 commit、dataset snapshot 和 artifact 链接；`not_run` 的 Fix 消融不能写成项目成绩。
```

注意：没有真实测试前，不要写百分比。

---

## 17. 面试深挖问题准备

### 17.1 RAG 相关

1. 为什么代码库不能直接用固定长度切分？
2. AST 分块怎么处理长函数？
3. 为什么要做混合检索？
4. embedding 检索和关键词检索各自适合什么场景？
5. 如何保证回答引用的文件和行号准确？

### 17.2 Agent 相关

1. 你的 Agent 和普通 Chatbot 有什么区别？
2. LangGraph 状态机怎么设计？
3. 测试失败后 Agent 如何反思？
4. 如何避免 Agent 无限循环？
5. 为什么不能直接让 LLM 一次性生成修复？

### 17.3 沙箱相关

1. 为什么需要 Docker 沙箱？
2. 如何限制容器访问宿主机？
3. 如何处理测试命令超时？
4. 如果项目没有测试命令怎么办？

### 17.4 前端相关

1. Agent 执行轨迹为什么用 SSE？
2. Trace Timeline 如何设计数据结构？
3. Diff Viewer 怎么展示 patch？
4. 如何处理长时间运行任务的前端状态？

---

## 18. 最终建议

CodeMate 的核心不是“做很多功能”，而是先跑通一个有说服力的闭环：

```text
代码理解准确
→ Bug 定位合理
→ patch 能应用
→ 测试能验证
→ 失败能反思
→ 过程可观察
→ 结果可评测
```

完成 P0 后，这个项目已经足够写进简历，并且比普通 AI 写作、AI 聊天、知识库问答项目更有 Agent 深度。P1/P2 可以作为后续迭代，不建议在未完成前写成已实现能力。
