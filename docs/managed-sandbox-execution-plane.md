# Managed Sandbox Execution Plane：HA 与供应链证明

## 证据状态（2026-08-03）

本文描述的是已提交的执行平面协议、策略校验、部署清单和 qualification 自动化，以及它们在托管环境中应满足的验收契约；不是一份已完成的部署或演练报告。仓库目前没有保留真实 KVM/Firecracker、Kata、HA Redis/Valkey、Cosign 或 TPM/TEE 在本地或 staging 实际运行的不可变证据。

因此，下文的 “staging/production” 均表示部署前置条件或验收要求，而非已观察到的环境事实。只有包含环境标识、commit SHA、`qualification.json: decision=qualified` 与签名 manifest 的证据包，才可以把该能力标记为 staging 已验证。当前状态以 [Capability Matrix](capability-matrix.md) 为准。

当前代码为 Broker 到独立执行平面的 mTLS、请求绑定 Ed25519 断言和策略重校验提供了控制路径。在目标托管拓扑中，执行平面可选择 Firecracker launcher 或 Kubernetes/Kata Job；本地 demo 的 Docker socket 便利配置不属于这一拓扑。

```text
Worker -> code-sandbox Broker -> internal L4/L7 load balancer
                                  ├─ execution-plane A ─┐
                                  ├─ execution-plane B ─┼─ HA Redis/Valkey
                                  └─ execution-plane C ─┘
                                          │
                               Firecracker node / Kata Job
```

## HA 与幂等语义

- staging/production 部署契约要求 `SANDBOX_EXECUTION_STATE_BACKEND=redis`。Redis/Valkey 必须由跨可用区 Sentinel、Cluster 或云托管主从提供，开启持久化、TLS、认证、自动故障切换和备份；单 Pod Redis 不能作为 HA 证据。
- `execution_id + request_hash` 是幂等键，`jti` 是防重放键。Lua 脚本原子完成 JTI 消费、请求冲突检查、lease 获取和 attempt fencing。键使用同一个 Redis Cluster hash tag，保证脚本在 Cluster 模式下仍为单槽原子操作。
- 相同请求完成后返回缓存结果并设置 `X-CodeMate-Idempotent-Replay: true`；相同 ID 绑定不同请求返回 409；运行中的请求返回 409 与 `Retry-After`。客户端只重试明确的 in-progress 响应和传输故障。
- 完成提交校验 owner fence。失去 lease 的旧节点不能覆盖新 attempt；共享状态不可用或结果无法提交时执行平面 fail closed，不返回未记账结果。
- Kubernetes 清单指定 3 replicas、PDB `minAvailable=2`、跨 zone/hostname 分散，以及 CPU 65% 时扩至最多 20 个控制器的 HPA。Kata Job 带 `codemate.io/attested-sandbox-node=true` selector；实际集群还必须为该标签对应的专用节点池配置 Cluster Autoscaler/Karpenter。
- RWX PVC 只承载短期工作区，不承担幂等一致性。生产 StorageClass 必须支持多节点 RWX；归档仍以 SHA-256 绑定请求。

## 供应链验证

每次执行都在启动 workload 前调用 Cosign：

1. 镜像必须使用 `image@sha256:<digest>`，并匹配服务端 allowlist。
2. `cosign verify` 校验签名者公钥，或严格匹配 keyless certificate identity 与 OIDC issuer。
3. `cosign verify-attestation --type slsaprovenance` 校验 SLSA provenance。代码解析 DSSE payload，按完整 repository URI（可带 `@revision`/`#fragment`）比对 source，不使用易误命中的字符串包含判断；可额外固定 builder ID。
4. Firecracker rootfs 同时校验本地 SHA-256 和 `cosign verify-blob --bundle`。摘要、bundle、rootfs 任一缺失或不匹配都会拒绝执行。

主分支工作流 `.github/workflows/sandbox-supply-chain.yml` 定义了以 BuildKit `mode=max` provenance 和 SBOM 构建 backend/execution-plane 镜像、再以 GitHub OIDC keyless Cosign 对不可变 digest 签名的步骤。工作流定义不等于一次成功的供应链构建；部署侧只有在保留成功 run receipt 后，才能把实际输出 digest 写入镜像 allowlist。

签名 microVM rootfs：

```bash
# keyless；也可设置 COSIGN_KEY 使用 KMS/HSM key URI
scripts/sign_sandbox_rootfs.sh /var/lib/codemate/images/rootfs.ext4
```

将生成的 `.bundle.json`、`.sha256` 和只读 rootfs 作为一个不可拆分 release 发布。生产密钥应使用 KMS/HSM，不能把私钥放入节点文件系统。

## TPM/TEE 节点证明

执行平面的生产部署契约要求信任“证明机构签名的规范化 verdict”，而不直接信任节点自报字段。verifier command 应在每次收到随机 256-bit nonce 和目标 `node_id` 后，从本机 TPM/TEE agent 或远程 attestation service 获取 quote、验证证书链/TCB/撤销状态，并在 stdout 返回 Ed25519 签名 envelope：

```json
{
  "payload": "base64(JSON claims)",
  "signature": "base64(Ed25519 signature)"
}
```

payload 必须包含 `node_id`、`nonce`、`issued_at`、`expires_at`、`verdict=verified`、`tee_type`、`measurement`、64 位十六进制 `quote_digest` 和 `verifier_id`。执行平面验证签名、nonce、时效、节点身份、TEE 类型及 measurement allowlist。示例命令约定：

```text
/usr/local/bin/codemate-node-attestation verify \
  --node {node_id} --nonce {nonce}
```

该二进制是部署方适配层：可对接 TPM2 Quote、AMD SEV-SNP、Intel TDX、AWS Nitro 或云厂商 attestation API。它必须随执行平面镜像一起审计和签名。静态/CSI 投影 verdict 仅允许本地开发；staging/production 配置校验强制 challenge-response。

Kubernetes 模式会读取 Kata Job Pod 的真实 `spec.nodeName`，并对该节点做证明后才接受结果；不会错误地用 execution-plane 控制器所在节点代替 workload 节点。节点证明控制器只有在证明持续有效时才能维护 `codemate.io/attested-sandbox-node=true` 标签，失效时应立即摘除标签并 cordon/drain。

## Kubernetes 部署

前置依赖：

- 支持 Kata 的 `RuntimeClass/kata` 与专用、可自动扩缩的 sandbox node pool；
- 跨 AZ HA Redis/Valkey，并创建 `sandbox-execution-state` Secret 的 `redis-url` key；
- cert-manager、名为 `codemate-workload-ca` 的 ClusterIssuer，以及 Stakater Reloader；
- `sandbox-workload-verifier`、`sandbox-supply-chain`（`cosign.pub`）和 `sandbox-attestation-authority`（`authority.pub`）Secrets；
- RWX StorageClass、Metrics Server，以及部署方提供的 `codemate-node-attestation` verifier；
- admission policy（Kyverno/Gatekeeper/Sigstore policy-controller）对 execution-plane 自身镜像执行 digest、Cosign 与 provenance 准入验证。

编辑清单中的 source、measurement 和两个 workload image digest 占位值后：

```bash
kubectl apply -k deploy/execution-plane/kubernetes
```

部署时应配置 cert-manager 签发 24 小时 mTLS 证书，并在剩余 8 小时时用新私钥续期。Uvicorn 不热重载 TLS context，因此 Reloader 应监听 Secret 变化并触发滚动发布；PDB 与 `maxUnavailable=1` 是轮换期间至少两个副本可用的验收条件。readiness probe 应使用轮换后的客户端证书真正访问 `/health`，同时检查 Redis 和节点证明，而不是只探测 TCP 端口。

Broker 客户端证书模板位于 `broker-certificate.example.yaml`。将 namespace 改为 Broker 所在 namespace，给 Broker Deployment 添加对应 Reloader annotation，并把 Secret 的 `tls.crt`、`tls.key`、`ca.crt` 挂载到 client 配置路径，即可用相同的 24h/8h 策略自动轮换；Secret 不应跨 namespace 复制。

CA 轮换必须采用双信任窗口：先让 client/server trust bundle 同时包含 old+new CA，再签发 leaf，确认全部连接迁移后移除 old CA。cert-manager 只负责 leaf 自动续期，不会替你安全地完成 root CA 换代。

## Firecracker 多节点（目标部署）

每个节点使用相同策略、Cosign trust root、rootfs release 和 HA Redis endpoint，但配置唯一的 node ID。节点置于跨 AZ Auto Scaling Group/MIG 后，由内部负载均衡器健康检查 8443；扩缩容 lifecycle hook 必须等 TPM/TEE 证明成功后注册 target，终止时先摘流再停止服务。

安装以下 systemd units：

- `codemate-sandbox-execution-plane.service`
- `codemate-sandbox-certificate-reload.path`
- `codemate-sandbox-certificate-reload.service`

SPIRE Agent、step-ca agent 或云私有 CA agent 将证书原子更新到 `/etc/codemate/pki` 后，path unit 自动重启 Uvicorn 以加载新 leaf/trust bundle。重启前负载均衡器应先把该节点标为 draining；至少保留两个其他健康节点。

```bash
systemctl enable --now codemate-sandbox-execution-plane.service
systemctl enable --now codemate-sandbox-certificate-reload.path
```

## 验收与故障演练

上线前至少留存以下证据：

- 并发向不同副本发送同一 ID/JTI，只发生一次执行且返回一致缓存结果；
- kill -9 owner、Redis primary failover、单 AZ 中断、HPA 扩缩与节点池 scale-from-zero；
- 篡改镜像 digest、Cosign 签名、SLSA source/builder、rootfs/bundle 均被 412 拒绝；
- 过期 quote、错误 nonce、错误 nodeName、measurement/TCB 不在 allowlist 均被拒绝；
- leaf 自动续期和双 CA 轮换期间持续压测，无未授权连接且满足 PDB 可用性。

本地单元测试覆盖原子 claim/fencing、幂等返回、SLSA 精确 source 匹配、nonce-bound 节点证明和安全 Job 清单。真实 KVM、Kata、Redis failover、证书与 TPM/TEE 演练必须在 staging 基础设施执行，不能用 mock 结果替代。

自动化执行入口和证据验签说明见 [Sandbox HA Staging Qualification](sandbox-ha-qualification.md)。
