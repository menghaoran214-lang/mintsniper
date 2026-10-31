---
name: mintsniper
description: |
  Early discovery of BSC on-chain mint projects, including Binance Agent ID gated
  launches, before they are publicly announced. Runs three read-only discovery
  layers and merges them into one ranked report: GitHub development signals
  (new repositories shipping contracts), on-chain mint detection (ERC-721 and
  ERC-1155, scored by distinct wallets minting), and watched-wallet activity
  (contracts that user-supplied addresses minted). Use when asked to find new
  mint projects, scan for fresh agent-ID gated launches, look for projects
  nobody is talking about yet, monitor early wallets, or check what appeared
  on-chain recently. Triggers on: find new mint projects, scan for new launches,
  agent ID projects, BSC mint radar, early bird wallets, what is minting now,
  new agent-gated drops, 打新项目, 发现新项目, 智能体钱包项目, 链上新项目.
agent_created: true
metadata:
  author: mintsniper
  version: "1.0"
  license: MIT
---

# mintsniper

## Overview

Discovers BSC mint projects early by combining three independent read-only signals, then reports what was found together with what is **not** known about each candidate.

This skill never connects a wallet, never signs, never submits a transaction, and never executes a mint. It produces a report that a human then acts on.

## The three layers

| Layer | Script | Detects | Typical lead |
|---|---|---|---|
| GitHub | `scripts/github_scan.py` | Repositories that recently started shipping code for a project | Days |
| Chain | `scripts/chain_scan.py` | ERC-721 contracts many distinct wallets are minting now | Minutes |
| Chain | `scripts/erc1155_scan.py` | The same for ERC-1155, which uses different event signatures | Minutes |
| Wallet | `scripts/wallet_scan.py` | Contracts that user-supplied watched addresses minted | Minutes |

Layers are independent. A project found by two layers is usually more real than one found by a single layer, which is why the merge step adds a score bonus for multi-source hits.

## Workflow

Run the layers that apply, then merge.

### Step 1 — GitHub layer

```bash
python3 scripts/github_scan.py --days 5 --limit 20 --json > gh.json
```

Set the user's own GitHub token first. Anonymous search is limited to 10 requests per minute, so results will be partial without one:

```bash
export GITHUB_TOKEN=ghp_xxxxxxxx
# or: echo ghp_xxxxxxxx > <skill-dir>/state/github_token
```

### Step 2 — Chain layer

```bash
python3 scripts/chain_scan.py --backend native --minutes 8 --json > chain.json
python3 scripts/erc1155_scan.py --minutes 15 --json > e1155.json
```

Set a dedicated RPC for reliable coverage, or the public endpoints are used:

```bash
export MINTSNIPER_RPC="https://your-node.example"
```

### Step 3 — Wallet layer (optional)

Requires a local address list supplied by the user. This skill ships no address list and sends no address anywhere.

```bash
python3 scripts/wallet_scan.py --addresses ./watch.txt --minutes 60 --json > wallet.json
```

### Step 4 — Merge and report

```bash
python3 scripts/merge_report.py --github gh.json --chain chain.json --wallet wallet.json
```

Add `--out report.json` to persist the merged result, or `--json` for machine-readable output.

## Reading the result

Every chain scan carries a `coverage` object. Report it.

| `coverage.status` | Meaning | What to say |
|---|---|---|
| `complete` | Every requested block range was read | Normal result |
| `partial` | Some ranges failed | A gap, not an absence of projects. Name `failed_ranges`. |
| `error` | Nothing usable was read | The scan did not run; say so instead of reporting zero candidates |

The CLI exits non-zero when coverage is not complete, so check the exit code before summarising.

## Reporting rules

1. **State what was detected and what was not.** Every candidate carries `not_established`. Do not drop it.
2. **Never present a candidate as safe.** No public source can establish that. Say "mint activity detected", not "safe project".
3. **Never present a candidate as profitable.** Discovery is not a strategy; sell timing and liquidity decide outcomes.
4. **Cite the source layer, the scan timestamp and the coverage status.**
5. **Include the coverage note** from each layer, so the user knows what was out of scope.
6. **Close with the fixed disclaimer** below.

## Scope and limits

Read `references/sources.md` for per-layer detection logic, blind spots, and measured limits. Read `references/safety.md` before advising on any candidate.

Key limits to state when relevant:

- GitHub sees only projects that publish code.
- The chain layer sees only ERC-721 and ERC-1155 mints on BSC, and only what the RPC endpoint actually returned.
- The wallet layer cannot tell an active mint from an airdrop by the receiving event alone; it checks `tx.from` and marks each hit `direct` or `received`.
- A contract being minted by many wallets does not mean the mint was free.
- ERC-20 `Transfer` events share the ERC-721 signature but are not mints, and are rejected explicitly.

## Setup

See `references/setup.md` for installation, credentials, first-run self-check, and troubleshooting.

## Disclaimer

**This is a read-only discovery tool. It is not investment, financial, or trading advice, and it does not constitute a recommendation to buy, sell, or hold any asset.**

Detection does not establish safety or profitability. Contract behaviour can change after detection, including ownership controls, taxes, and liquidity withdrawal. Verify every contract source, check whether a mint is actually free, and confirm that buyers exist before acting. On-chain transactions are irreversible. Any trading decision, including a decision not to trade, remains the user's own responsibility.
