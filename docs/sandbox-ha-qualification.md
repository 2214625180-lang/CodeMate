# Sandbox HA Staging Qualification 与证据包

> **证据状态（2026-08-03）：** 本文定义并自动化 qualification gate，不是一次已完成的 qualification report。当前仓库未保留真实 staging 执行平面产生的 `qualified` 签名 evidence bundle。实际状态见 [Capability Matrix](capability-matrix.md)。

该 gate 在真实 staging execution plane 上运行时，会发起 mTLS + request-bound Ed25519 请求，并执行可恢复的破坏性演练。dry-run、mock、单机 Compose 和跳过场景只能生成 rehearsal evidence，不能得到 `qualified` 决策。

## 覆盖范围

- 至少 3 个 Ready execution-plane replicas，分布在至少 2 个节点和 2 个 zone；HPA、PDB、Certificate 必须 Ready。
- 同一 `execution_id/request_hash` 并发打到多个实例，只允许一次实际执行，之后返回带 `X-CodeMate-Idempotent-Replay` 的缓存结果。
- 基线并发负载，以及负载中的 execution-plane Pod 删除、Redis primary failover、HPA scale-out；Redis 切换后再次运行跨实例幂等 gate。
- cert-manager leaf 强制续期、Secret resourceVersion 变化、Reloader Pod rollout，以及轮换期间的持续负载。
- 在真实 execution-plane Pod 内运行错误 SLSA source、unsigned digest image、错误 node identity；Firecracker backend 额外运行 tampered rootfs control。
- 前后 inventory、health、Pod logs、Deployment/HPA/PDB/Certificate describe、Kubernetes events。
- 所有 artifact 写入 `manifest.sha256`，并可用 Cosign keyless/KMS key签名为 `manifest.bundle.json`。

## Runner 权限与隔离

workflow 使用 `[self-hosted, codemate-staging, sandbox-admin]` runner。其 kubeconfig 必须只授权 staging namespace 中以下操作：读取 workload/HPA/PDB/Certificate/events/logs、删除 execution-plane Pod、修改 HPA、在 execution-plane Pod 中执行只读 negative controls。它不需要读取 Secret 内容，也不得复用 production context。

最小权限示例位于 `deploy/execution-plane/kubernetes/qualification-rbac.example.yaml`。其中唯一的 cluster-scoped 权限是读取目标 Node 的 zone label，用于证明副本确实跨 AZ；不授予修改 Node、Secret、Job 或其他 namespace 的权限。

运行器必须能够访问 execution plane 的内部 HTTPS 地址。qualification client certificate 和 workload signing key 是独立的短期 staging 身份，不得复用 Broker production key。workflow 将 GitHub Secrets 写入权限为 `0600` 的 `$RUNNER_TEMP` 文件，并在结束时删除。

## GitHub Environment 配置

Variables：

- `SANDBOX_QUALIFICATION_KUBE_CONTEXT`
- `SANDBOX_QUALIFICATION_NAMESPACE=codemate-sandbox`
- `SANDBOX_QUALIFICATION_URL=https://...:8443`
- `SANDBOX_NODE_IMAGE=<signed test image>@sha256:<digest>`；镜像必须包含 Node/npm，测试不安装依赖且不访问网络。
- `SANDBOX_QUALIFICATION_UNSIGNED_IMAGE=<existing unsigned fixture>@sha256:<digest>`
- workload identity issuer、subject、audience 三个变量。

Secrets：

- qualification CA、client certificate、client key、workload Ed25519 private key PEM。
- `SANDBOX_REDIS_FAILOVER_COMMAND_JSON`：云厂商/Redis Operator 对应的非 shell argv。例如 `["/usr/local/bin/trigger-staging-redis-failover","--cluster","codemate-staging"]`。命令必须在 failover 完成后退出 0。
- `SANDBOX_CERTIFICATE_RENEW_COMMAND_JSON`：例如 `["cmctl","renew","-n","codemate-sandbox","sandbox-execution-plane-mtls"]`。

Redis hook 和 certificate hook 只接受 JSON argv，永不经 shell 执行。证据记录命令 SHA-256、退出码及截断输出，不记录命令正文。

## 执行

在 GitHub Actions 手工触发 `Sandbox HA Staging Qualification`，输入 `QUALIFY-SANDBOX`。本地受控 rehearsal 示例：

```bash
python scripts/run_sandbox_ha_qualification.py \
  --execute \
  --rehearsal \
  --context codemate-staging \
  --requests 30 \
  --output-dir artifacts/sandbox-ha-qualification/rehearsal
```

`--skip-faults`、`--skip-certificate-rotation` 或 `--skip-negative-controls` 都会生成 `incomplete` gate，最终决策固定为 `hold`。只有全部 gate 为 `passed`、非 rehearsal 且 evidence manifest 成功签名时才可用于发布批准。

## 验证证据

```bash
cd artifacts/sandbox-ha-qualification/run
sha256sum -c manifest.sha256
cosign verify-blob \
  --bundle manifest.bundle.json \
  --certificate-identity-regexp 'https://github.com/.+/.+/.github/workflows/sandbox-staging-qualification.yml@.+' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  manifest.sha256
```

发布审批需要同时检查 `qualification.json` 的 `decision=qualified`、`qualification.md`、负向控制日志，以及是否有未解释的 Kubernetes warning events。
