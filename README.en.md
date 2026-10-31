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

### Find BSC mint projects before they are publicly announced, including Binance Agent ID gated launches.

**English** · [简体中文](./README.md)

[Install](#install) · [Configure](#configure) · [Usage](#usage) · [Report](#report) · [How](#detection) · [Safety](#safety)

</div>

---

Mintsniper merges three independent **read-only** signals into one ranked report:

| Layer | Detects | Typical lead | Source |
|---|---|---|---|
| GitHub | Repositories that recently started shipping code for a project | Days | GitHub REST search |
| Chain | Contracts many distinct wallets are minting right now | Minutes | Direct BSC RPC (ERC-721 + ERC-1155) |
| Wallet | Contracts your own watched addresses minted | Minutes | Direct BSC RPC |

It is **read-only by construction**: no wallet connection, no key handling, no signing, no transaction submission, and no automatic minting, buying or selling. It produces a report a human acts on.

> Detection is not safety, and detection is not profitability. A contract can be minted by a thousand wallets and still be a honeypot, a tax trap, or a project that never sells.

## Contents

- [Install](#install)
- [Configure](#configure)
- [Usage](#usage)
- [Reading the report](#report)
- [How detection works](#detection)
- [Architecture](#architecture)
- [Safety boundaries](#safety)
- [Disclaimer](#disclaimer)
- [License](#license)

<a id="install"></a>

## Install

Requires **Python 3.10+** and a network path to a BSC RPC endpoint. No third-party Python packages.

### With the `skills` CLI (recommended)

```bash
npx skills add https://github.com/menghaoran214-lang/mintsniper
```

### Manual install

```bash
git clone https://github.com/menghaoran214-lang/mintsniper.git
bash mintsniper/scripts/install.sh ~/.claude/skills
```

`install.sh` copies the skill into the first skills directory it finds among `~/.claude/skills`, `~/.config/opencode/skills`, `~/.workbuddy/skills`, `~/.codex/skills`, or into the directory passed as the first argument.

### Try it without installing

```bash
cd mintsniper/scripts
python3 chain_scan.py --backend native --minutes 8
```

<a id="configure"></a>

## Configure

### RPC node (strongly recommended)

Public BSC endpoints restrict `eth_getLogs` to **25 blocks per request**, reject filters they do not fully support, and intermittently return an empty array for a valid query. A dedicated node gives materially better coverage.

```bash
export MINTSNIPER_RPC="https://your-bsc-node.example"
```

Without it the tool still runs, reports `coverage.status` as `partial` or `complete`, and names the failed block ranges. A scan that could not read a range is never presented as "nothing found".

### GitHub token (recommended)

Anonymous GitHub search allows **10 requests/minute** and **60 core requests/hour**. Several people scanning at once will exhaust that, so every user should supply their own token.

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

A token with no scopes is enough for public repository search.

### Watched wallets (optional)

A local text file, one address per line, `#` for comments. The list never leaves your machine and is never sent to any RPC endpoint.

```
# my early wallets
0x1234abcd...5678
0x9abcde01...2345
```

<a id="usage"></a>

## Usage

### Single layer

```bash
python3 scripts/github_scan.py --days 5 --limit 20
python3 scripts/chain_scan.py --backend native --minutes 8
python3 scripts/erc1155_scan.py --minutes 15
python3 scripts/wallet_scan.py --addresses ./watch.txt --minutes 60
```

### Everything, merged

```bash
python3 scripts/github_scan.py --json > gh.json
python3 scripts/chain_scan.py --backend native --json > chain.json
python3 scripts/wallet_scan.py --addresses ./watch.txt --json > wallet.json
python3 scripts/merge_report.py --github gh.json --chain chain.json --wallet wallet.json
```

### Using an existing mintradar checkout

If you already run [mintradar](https://github.com/hornofchina1-svg/mintradar), point at it instead of letting anything download code:

```bash
python3 scripts/chain_scan.py --backend mintradar --mintradar-path /path/to/mintradar
```

That backend reads `radar.db` in read-only mode. It does **not** clone, does **not** execute external code, and its snapshot time and chain id are unverified, so treat its labels as another opinion rather than a safety certificate.

### As an agent skill

Ask your agent to find new mint projects, scan for fresh agent-ID gated launches, or check what is minting on BSC now.

<a id="report"></a>

## Reading the report

Each candidate states what was detected and what was **not** established:

```
199    chain     199 mints / 199 receivers
                  https://bscscan.com/address/0x1a78...
                  ! not established: whether the mint was free,
                    whether the contract is safe, whether it sold
```

- **detected** — a factual observation from a named source, with a timestamp and coverage status
- **not established** — what public data cannot tell you

### Coverage is part of the result

Every chain scan returns a `coverage` object:

```json
{ "status": "complete", "failed_ranges": [], "duplicates": 0, "rejected_logs": 0 }
```

When any range fails, `status` becomes `partial` or `error`, `failed_ranges` lists the blocks that were not read, and the CLI exits non-zero. Treat a partial scan as a gap, not as an absence of projects.

<a id="detection"></a>

## How detection works

### Chain layer — ERC-721 and ERC-1155

Reads mint logs where the `from` field is the zero address, then scores contracts by how many **distinct wallets** minted them. Requiring distinct wallets, not just a raw event count, separates a broad public launch from one operator farming their own collection.

The two standards have different topic layouts, and getting this wrong silently produces garbage:

| Standard | Topics | `from` index |
|---|---|---|
| ERC-721 `Transfer` | `[sig, from, to, tokenId]` | 1 |
| ERC-1155 `TransferSingle` / `TransferBatch` | `[sig, operator, from, to]` | 2 |

An ERC-20 `Transfer` shares the ERC-721 topic signature but carries only 3 topics and a non-empty data field, so it is rejected explicitly rather than counted as a mint. Event signatures are derived from the published EIP-721 / EIP-1155 definitions at runtime, not copied by hand.

Time windows use **actual block timestamps** found by binary search, not an assumed block time, and the chain id is verified to be BSC (56) before any scan.

### Wallet layer — direct mints vs receipts

A watched address receiving an NFT is not proof it minted it; airdrops hit the same field. For each hit, the tool fetches `eth_getTransactionByHash` and marks the result:

- `direct` — `tx.from` equals the watched address, so it initiated the mint
- `received` — anything else (airdrop, router, unknown), reported but not counted as a mint

### GitHub layer

Narrow query groups plus topic filters, scored on strong signals such as `agent id`, `free mint`, `fair mint`, `agent-gated`, `launchpad`, and a declared homepage. A repository matched by several independent groups scores higher. Broad keyword queries are avoided deliberately: one matched 311,869 repositories over 14 days and buried the signal.

<a id="architecture"></a>

## Architecture

```
mintsniper/
├── SKILL.md                 agent entry point
├── scripts/
│   ├── common.py            RPC client, event parsing, window resolution
│   ├── github_scan.py       layer 1
│   ├── chain_scan.py        layer 2, ERC-721
│   ├── erc1155_scan.py      layer 2, ERC-1155
│   ├── wallet_scan.py       layer 3
│   ├── merge_report.py      merge + safety labelling
│   ├── install.sh           copy into a skills directory
│   └── publish.sh           push a fork to GitHub
├── references/
│   ├── sources.md           per-layer logic, blind spots, measured limits
│   ├── safety.md            how to judge a candidate
│   └── setup.md             credentials, troubleshooting
└── tests/
    └── test_chain.py        offline tests, no network
```

Run the tests:

```bash
python3 -m unittest discover -s tests
```

<a id="safety"></a>

## Safety boundaries

- No wallet connection, no key handling, no signing
- No transaction construction or submission
- No automatic minting, buying or selling
- No bundled address list; watched addresses stay local
- RPC methods restricted to an allowlist of read-only calls
- Error messages redact endpoint URLs

The final decision is always a human one.

<a id="disclaimer"></a>

## Disclaimer

**mintsniper is a read-only discovery tool. It is not investment, financial, or trading advice, and it does not constitute a recommendation to buy, sell, or hold any asset.**

Detection does not establish safety or profitability. Contract behaviour can change after detection, including ownership controls, taxes, and liquidity withdrawal. Verify every contract source, check whether a mint is actually free, and confirm that buyers exist before acting. On-chain transactions are irreversible. Any trading decision, including a decision not to trade, remains your own responsibility.

<a id="license"></a>

## License

MIT

---

## Appendix: script parameters

Every script runs standalone. `--json` emits structured output, `--help` has the full description.

### github_scan.py

| Flag | Default | Meaning |
|---|---|---|
| `--days N` | 5 | How many days of repository creation to look back |
| `--limit N` | 20 | Maximum candidates to print |
| `--json` | off | Emit JSON for the merge layer |

### chain_scan.py

| Flag | Default | Meaning |
|---|---|---|
| `--backend` | `native` | `native` or `mintradar` |
| `--minutes N` | 15 | Lookback window, measured from real block time |
| `--mint-threshold N` | 12 | Minimum mints to qualify as a candidate |
| `--wallet-threshold N` | 6 | Minimum distinct wallets to qualify |
| `--mintradar-path PATH` | none | Required for the `mintradar` backend, points at a local checkout |
| `--json` | off | Emit JSON |

### erc1155_scan.py

| Flag | Default | Meaning |
|---|---|---|
| `--minutes N` | 15 | Lookback window |
| `--min-mints N` | 5 | Minimum mints |
| `--min-wallets N` | 3 | Minimum distinct wallets |
| `--json` | off | Emit JSON |

### wallet_scan.py

| Flag | Default | Meaning |
|---|---|---|
| `--addresses FILE` | required | Watched address file, one per line |
| `--minutes N` | 15 | Lookback window |
| `--json` | off | Emit JSON |

### merge_report.py

| Flag | Default | Meaning |
|---|---|---|
| `--github FILE` | none | github_scan JSON |
| `--chain FILE` | none | chain_scan JSON |
| `--wallet FILE` | none | wallet_scan JSON |

### Environment variables

| Variable | Effect |
|---|---|
| `MINTSNIPER_RPC` | Custom BSC RPC endpoints, comma separated |
| `GITHUB_TOKEN` | GitHub token, avoids anonymous rate limits |
| `MINTSNIPER_STATE` | State directory, defaults to `state/` inside the skill |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Scan finished with complete coverage |
| 1 | Bad arguments or incomplete coverage (`coverage.status` is not `complete`) |

**A non-zero exit code means "this scan had blind spots", not "nothing was found".** Handle it that way in automation instead of treating a blind spot as an empty result.
