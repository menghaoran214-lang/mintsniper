<div align="center">

# mintsniper

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)](references/setup.md)
[![BSC](https://img.shields.io/badge/BNB%20Chain-1B7FA8)](https://bscscan.com)
[![mainnet](https://img.shields.io/badge/network-mainnet-F0B90B)](https://bscscan.com)
[![721](https://img.shields.io/badge/ERC--721-534AB7)](#detection)
[![1155](https://img.shields.io/badge/ERC--1155-534AB7)](#detection)
[![40](https://img.shields.io/badge/tests-40%20passed-brightgreen)](tests/test_chain.py)
[![readonly](https://img.shields.io/badge/read--only-A32D2D)](#safety)
[![nosign](https://img.shields.io/badge/no%20signing-A32D2D)](#safety)
[![notrade](https://img.shields.io/badge/no%20auto%20trade-A32D2D)](#safety)
[![MIT](https://img.shields.io/badge/license-MIT-3B6D11)](#license)

### 在 BSC 打新项目被公开宣传之前发现它，包括 Binance Agent ID 门控的发射。

**简体中文** · [English](./README.en.md)

[安装](#install) · [配置](#configure) · [使用](#usage) · [原理](#detection) · [安全](#safety)

</div>

---

Mintsniper 把三路独立的**只读**信号合并成一份排序报告：

| 层 | 检测什么 | 典型提前量 | 数据源 |
|---|---|---|---|
| GitHub | 刚开始为项目写代码的新仓库 | 数天 | GitHub REST 搜索 |
| 链上 | 正在被大量不同钱包 mint 的合约 | 分钟级 | BSC RPC 直连（ERC-721 + ERC-1155） |
| 钱包 | 你的观察地址刚刚 mint 过的合约 | 分钟级 | BSC RPC 直连 |

它是**结构上只读的**：不连钱包、不经手私钥、不签名、不提交交易，更不会自动 mint、买入或卖出。它产出报告，决策永远由人来做。

> 检测不等于安全，检测也不等于盈利。一个被一千个钱包 mint 过的合约，仍然可能是貔貅、税收陷阱或永远卖不掉的项目。

## 目录

- [安装](#install)
- [配置](#configure)
- [使用](#usage)
- [报告怎么读](#report)
- [检测原理](#detection)
- [目录结构](#architecture)
- [安全边界](#safety)
- [免责声明](#disclaimer)
- [许可证](#license)

<a id="install"></a>

## 安装

需要 **Python 3.10+**，以及一条能通到 BSC RPC 节点的网络。无任何第三方 Python 依赖。

### 用 skills CLI 安装（推荐）

```bash
npx skills add https://github.com/menghaoran214-lang/mintsniper
```

### 手动安装

```bash
git clone https://github.com/menghaoran214-lang/mintsniper.git
bash mintsniper/scripts/install.sh ~/.claude/skills
```

`install.sh` 会把技能复制进它找到的第一个技能目录：`~/.claude/skills`、`~/.config/opencode/skills`、`~/.workbuddy/skills`、`~/.codex/skills`，或你作为第一个参数传入的目录。

### 不安装直接试

```bash
cd mintsniper/scripts
python3 chain_scan.py --backend native --minutes 8
```

<a id="configure"></a>

## 配置

### RPC 节点（强烈建议）

公共 BSC 端点把 `eth_getLogs` 限制在**每次 25 个块**，会拒绝它们不完整支持的过滤器，并且偶发地对合法查询返回空数组。专用节点的覆盖质量有实质差别。

```bash
export MINTSNIPER_RPC="https://your-bsc-node.example"
```

不配置也能跑：工具会把 `coverage.status` 报为 `partial` 或 `complete`，并列出读取失败的块区间。**读不到的区间永远不会被伪装成"没发现项目"。**

### GitHub Token（建议）

匿名 GitHub 搜索限额是 **10 次/分钟、60 次/小时**。多人同时扫会很快耗尽，所以每个用户应配自己的 token：

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

无任何权限的空 token 即可搜索公开仓库。

### 观察钱包（可选）

本地文本文件，一行一个地址，`#` 开头是注释。**名单只存在你本机**，不会发送给任何 RPC 端点。

```
# 我的早期钱包
0x1234abcd...5678
0x9abcde01...2345
```

<a id="usage"></a>

## 使用

### 单层扫描

```bash
python3 scripts/github_scan.py --days 5 --limit 20
python3 scripts/chain_scan.py --backend native --minutes 8
python3 scripts/erc1155_scan.py --minutes 15
python3 scripts/wallet_scan.py --addresses ./watch.txt --minutes 60
```

### 三层合并报告

```bash
python3 scripts/github_scan.py --json > gh.json
python3 scripts/chain_scan.py --backend native --json > chain.json
python3 scripts/wallet_scan.py --addresses ./watch.txt --json > wallet.json
python3 scripts/merge_report.py --github gh.json --chain chain.json --wallet wallet.json
```

### 复用已有的 mintradar

如果你已经在跑 [mintradar](https://github.com/hornofchina1-svg/mintradar)，直接指向它，而不是让任何代码去下载执行：

```bash
python3 scripts/chain_scan.py --backend mintradar --mintradar-path /path/to/mintradar
```

该后端以只读方式打开 `radar.db`：**不 clone、不执行外部代码**。它的快照时间与链 ID 未经验证，其标签只当作另一个观点，不当作安全证书。

### 作为 Agent 技能

直接让 Agent"找找新 mint 项目"、"扫一下有没有新的 Agent ID 门控发射"、"看看 BSC 现在在 mint 什么"。

<a id="report"></a>

## 报告怎么读

每条候选都写明检测到了什么、以及什么**未被确立**：

```
199    chain     199 mints / 199 receivers
                  https://bscscan.com/address/0x1a78...
                  ! not established: whether the mint was free,
                    whether the contract is safe, whether it sold
```

- **detected** —— 来自具名来源的事实观察，带时间戳和覆盖状态
- **not established** —— 公开数据无法告诉你的事

### 覆盖状态是结果的一部分

每次链上扫描都返回 `coverage` 对象：

```json
{ "status": "complete", "failed_ranges": [], "duplicates": 0, "rejected_logs": 0 }
```

任一区间失败时 `status` 变为 `partial` 或 `error`，`failed_ranges` 列出未读块区间，CLI 退出码非零。**partial 扫描要当作缺口处理，而不是"没有项目"。**

<a id="detection"></a>

## 检测原理

### 链上层 —— ERC-721 与 ERC-1155

读取 `from` 为零地址的 mint 日志，然后按**不同钱包数**给合约打分。要求不同钱包而非原始事件数，是为了把面向公众的发射与项目方自刷分开。

两个标准的事件 topic 布局不同，弄错会静默产出垃圾数据：

| 标准 | Topics | `from` 位置 |
|---|---|---|
| ERC-721 `Transfer` | `[sig, from, to, tokenId]` | 1 |
| ERC-1155 `TransferSingle` / `TransferBatch` | `[sig, operator, from, to]` | 2 |

ERC-20 的 `Transfer` 与 ERC-721 共用 topic0 签名，但只有 3 个 topic 且 data 非空，因此被显式拒绝而不是计成 mint。事件签名在运行时从公开的 EIP-721 / EIP-1155 定义推导，不靠手抄。

时间窗口用**真实区块时间戳**（二分查找）确定，不假设出块速度；扫描前校验链 ID 必须是 BSC（56）。

### 钱包层 —— 主动 mint 与收到转账

观察地址**收到** NFT 不等于它 mint 了——空投打的是同一个字段。每个命中都会补查 `eth_getTransactionByHash` 并标记：

- `direct` —— `tx.from` 就是观察地址，即它主动发起
- `received` —— 其余情况（空投、路由、未知），如实报告但不计为主动 mint

### GitHub 层

窄查询组加 topic 过滤，对 `agent id`、`free mint`、`fair mint`、`agent-gated`、`launchpad`、声明官网等强信号打分。被多个独立查询组同时命中的仓库得分更高。刻意避免宽泛关键词：一次宽泛查询 14 天命中 311,869 个仓库，信号全被淹没。

<a id="architecture"></a>

## 目录结构

```
mintsniper/
├── SKILL.md                 agent 入口
├── scripts/
│   ├── common.py            RPC 客户端、事件解析、时间窗口
│   ├── github_scan.py       第 1 层
│   ├── chain_scan.py        第 2 层，ERC-721
│   ├── erc1155_scan.py      第 2 层，ERC-1155
│   ├── wallet_scan.py       第 3 层
│   ├── merge_report.py      合并 + 安全标注
│   ├── install.sh           复制进技能目录
│   └── publish.sh           推送 fork 到 GitHub
├── references/
│   ├── sources.md           各层逻辑、盲区、实测限制
│   ├── safety.md            如何判断一条候选
│   └── setup.md             凭据、排障
└── tests/
    └── test_chain.py        离线测试，无需网络
```

跑测试：

```bash
python3 -m unittest discover -s tests
```

<a id="safety"></a>

## 安全边界

- 不连钱包、不经手私钥、不签名
- 不构造、不提交任何交易
- 不自动 mint、买入或卖出
- 不捆绑地址名单；观察地址只留本机
- RPC 方法限定在只读白名单内
- 错误信息对端点 URL 脱敏

最终决策永远由人做出。

<a id="disclaimer"></a>

## 免责声明

**mintsniper 是只读发现工具。它不构成投资、金融或交易建议，不构成对任何资产的买卖持有建议。**

检测不能确立安全或盈利。检测之后合约行为仍可能变化，包括所有权控制、交易税与撤池。行动前请自行核实合约源码、确认 mint 是否真的免费、确认存在真实买家。链上交易不可逆。包括"不交易"在内的一切决定，责任都在你自己。

<a id="license"></a>

## 许可证

MIT

---

## 附录：脚本参数速查

每个脚本都是独立可执行的，`--json` 输出结构化结果，`--help` 有完整说明。

### github_scan.py

| 参数 | 默认 | 说明 |
|---|---|---|
| `--days N` | 5 | 回看多少天的仓库创建时间 |
| `--limit N` | 20 | 最多输出多少候选 |
| `--json` | 关 | 输出 JSON，供合并层消费 |

### chain_scan.py

| 参数 | 默认 | 说明 |
|---|---|---|
| `--backend` | `native` | `native` 或 `mintradar` |
| `--minutes N` | 15 | 回看窗口，按真实区块时间计算 |
| `--mint-threshold N` | 12 | 至少多少次 mint 才算候选 |
| `--wallet-threshold N` | 6 | 至少多少个不同钱包才算候选 |
| `--mintradar-path PATH` | 无 | 仅 `mintradar` 后端需要，指向本地已有副本 |
| `--json` | 关 | 输出 JSON |

### erc1155_scan.py

| 参数 | 默认 | 说明 |
|---|---|---|
| `--minutes N` | 15 | 回看窗口 |
| `--min-mints N` | 5 | 至少多少次 mint |
| `--min-wallets N` | 3 | 至少多少个不同钱包 |
| `--json` | 关 | 输出 JSON |

### wallet_scan.py

| 参数 | 默认 | 说明 |
|---|---|---|
| `--addresses FILE` | 必填 | 观察地址文件，一行一个 |
| `--minutes N` | 15 | 回看窗口 |
| `--json` | 关 | 输出 JSON |

### merge_report.py

| 参数 | 默认 | 说明 |
|---|---|---|
| `--github FILE` | 无 | github_scan 的 JSON |
| `--chain FILE` | 无 | chain_scan 的 JSON |
| `--wallet FILE` | 无 | wallet_scan 的 JSON |

### 环境变量

| 变量 | 作用 |
|---|---|
| `MINTSNIPER_RPC` | 自定义 BSC RPC 端点，逗号分隔可配多个 |
| `GITHUB_TOKEN` | GitHub 令牌，避开匿名限流 |
| `MINTSNIPER_STATE` | 状态目录，默认是技能目录下的 `state/` |

### 退出码

| 码 | 含义 |
|---|---|
| 0 | 扫描完成且覆盖完整 |
| 1 | 参数错误或覆盖不完整（`coverage.status` 非 `complete`） |

**退出码非 0 表示"这次扫描有盲区"，不是"什么都没找到"。** 在自动化里请据此处理，别把盲区当成空结果。
