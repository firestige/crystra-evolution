# Crystra Evolution

[English](README.md) | 中文

evolution-system 是 Crystra 的无状态 Metric Result 服务。它把
`EvaluationSelection` 解析到 Evidence，绑定 owner 已批准的 Evaluation Catalog 2.0 评审候选，并返回
`ResolvedEvaluationContext` receipt 与权威 Metric Results。compare 请求分别携带左右
selection；两侧结果和所有兼容 delta 均由 Evolution 计算。

Evolution 只通过带版本的 Evidence Query API 读取 Facts 与 recorded Traces。它不拥有
Evidence、不持久化数据库、不回写 Metric Result，也不推断未记录因果。BI 是展示客户
端，不计算 published metrics。

Iteration 5 明确不包含 Workflow 编辑、改进应用、AI 归因和 meta-recursive loop；它们是
后续产品范围，不是本服务基线的职责。

## 开发者预览

当前候选提供封闭、无副作用的 compute 边界、精确的 12-coordinate registry、12/12
candidate metric pure formula、typed Evidence/Workflow resolver，以及端到端
SINGLE/FULL_COMPARE/PARTIAL_COMPARE 编排。每个成功 side 都返回恰好 12 项 Metric
Results 与绑定 resolved read set 的 receipt；单项 coverage 空洞不会使其他结果失败。
JSON wire 将 authoritative integer value/count 序列化为 canonical decimal string，因此 browser
client 能保留超过 `2^53-1` 的 Python integer 精度。`coverage` 字段始终存在：Evolution
能建立候选总体时包含五个字段，无法建立 denominator 时显式为 `null`。已知候选总体为空
仍使用五字段 `NO_POPULATION` 对象并令 `raw_ratio: null`；不适用的 `alert` 也显式为 `null`。

当前 public Fact projection 仍不暴露 Usage Event native Span identity，因此 call-scoped
Usage input 会产生显式 missing coverage；绝不按 Delivery identity、timestamp、arrival
order 或文本猜关联。Role-template rework 改为描述性的 Delivery/template exposure：accepted
Manifest 与 recorded C30 选择精确 template，同 Delivery 的有效 `FINDING_FIX` relationship
表示发生过 rework；它不把因果归于 template、reviewer 或 writer。

Resolution safety limit 全部可配置。默认每 side 500 个 unique Delivery、每次 traversal 20
页、每 side 100,000 条 Fact+Trace record、side deadline 120 秒。超过边界会显式令该 side
失败，绝不静默截断。2.0 Catalog 仍是 review candidate，**正式发布前仍可能发生破坏兼容性的变更。**

历史 Workflow enrichment 只解析 Evidence 已记录的确定 Package 与 Snapshot 坐标，并按配置顺序读取 public GitHub source；参考坐标为 `firestige/crystra-workflow-package`。通过校验的进程内 cache 以完整 Package/Workflow/Snapshot/Role 内容坐标为 key；它不是 Evidence authority，也不会用 stale、compatible、latest、branch 或本地 checkout 内容替代。Enrichment 失败只形成诊断，不能改写 Metric Result。

## 开发

支持 Python 3.13 与 3.14。依赖锁定和构建由 [uv](https://docs.astral.sh/uv/) 管理；
本地命令默认使用 Python 3.14。

```sh
make sync    # 安装精确锁定的环境
make format  # 格式化 Python 源码与测试
make lint    # 格式、Ruff 与严格 mypy
make unit    # 运行无需外部服务的确定性测试
make build   # 构建 wheel 与源码包
make check   # 运行非容器验收门
```

## 本地 runtime image

Image 同时绑定 Evolution source 与 pinned Workflow DSL 2.0 candidate checker，因此必须从
superproject root 构建：

```sh
docker build -f evolution-system/Dockerfile -t crystra-evolution:local .
```

Process 要求 `CRYSTRA_EVOLUTION_CONFIG` 指向 mounted closed JSON file。以
`deployment/evolution.example.json` 为起点，按期望尝试顺序配置一到八个 public GitHub
source；需要时只能降低其中的 safety limits。该文件没有 database/provider credential 字段。
Container port `8000` 只在私网使用；`GET /healthz` 仅证明 local process liveness。

## 获取源码

本仓库通常作为 [crystra-evolution](https://github.com/firestige/crystra-evolution)
的 submodule 使用：

```sh
git clone --recurse-submodules https://github.com/firestige/crystra-evolution.git
```

单独克隆：

```sh
git clone https://github.com/firestige/crystra-evolution.git
```

## 文档

- [Evolution System 设计](https://github.com/firestige/crystra-evolution/blob/main/docs/systems/evolution/evolution-system.zh-CN.md)
- [Metric Catalog 2.0 评审候选](https://github.com/firestige/crystra-evolution/blob/main/docs/contracts/evaluation/metric-catalog-2-candidate.zh-CN.md)
- [Evidence Query Contract](https://github.com/firestige/crystra-evolution/blob/main/docs/contracts/evidence-query/evidence-query.zh-CN.md)

## License

[Apache-2.0](LICENSE)
