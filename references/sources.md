# Sources, detection logic, and blind spots

Each layer answers a different question. None of them can answer whether a project is safe or profitable.

## Layer 1 — GitHub development signal

**Question answered:** is someone actively building this?

**Detection.** The GitHub repository search API, `created:>DATE` plus narrow keyword and topic queries, sorted by creation date descending. A 5-day window is the practical default.

**Scoring.** Strong signals (3–6 points each): `agent id`, `agentic wallet`, `free mint`, `fair mint`, `agent-gated`, `agent-only`, `proof of agent`, `whitelist`, `bnb chain`, `launchpad`. A declared `homepage` adds 3, because the project is usually live by then. Stars are capped at 8 so new projects are not buried by older popular ones. A repository matched by more than one query group gains 4.

**Why the queries are narrow.** A broad query such as `(agent OR mint OR airdrop OR launchpad) (bnb OR bsc)` matched **311,869** repositories in a 14-day window, nearly all irrelevant. Topic-scoped queries are far more precise: `topic:fair-launch` returned 4 and `topic:bnb-chain` returned 29 over the same window.

**Blind spots.**

- Projects that publish no code are invisible.
- Repository creation time is not launch time.
- `homepage` may point anywhere, including an unrelated site.
- A description can be marketing copy rather than a technical description.

## Layer 2 — On-chain mint activity

**Question answered:** is anyone minting this right now?

**Detection.** Read mint logs where `from` is the zero address, then score contracts by distinct-wallet count and breadth (distinct wallets divided by mint events). Breadth at or above 0.5 means roughly one mint per wallet, which reads as a genuine public drop. Low breadth means one operator cycling few wallets.

**Topic layouts differ by standard, and this is the main correctness trap:**

| Standard | Topics | `from` index | Extra check |
|---|---|---|---|
| ERC-721 `Transfer` | `[sig, from, to, tokenId]` | 1 | exactly 4 topics, empty data |
| ERC-1155 `TransferSingle` | `[sig, operator, from, to]` | 2 | 4 topics, data holds id and value |
| ERC-1155 `TransferBatch` | `[sig, operator, from, to]` | 2 | 4 topics, data holds two arrays |

An ERC-20 `Transfer` shares the ERC-721 topic signature, so a filter on the signature alone counts token transfers as mints. Rejecting events with only 3 topics, or with a non-empty data field, removes them.

Event signatures are derived from the published EIP-721 / EIP-1155 definitions at runtime rather than copied by hand, because a wrong constant fails silently: the query returns nothing and looks like "no mints".

**Time windows.** The start block is found by binary search on actual block timestamps, not by assuming a fixed block time. Assuming 3 seconds per block on a chain that has changed cadence silently shifts the window. The chain id is verified to be BSC (56) before scanning.

**Blind spots.**

- Non-standard mint contracts that emit no standard event are missed.
- A contract being minted by many wallets says nothing about whether the mint was free.
- A contract that mints rarely but in a large batch can sit below the threshold.
- Gas-sponsored or meta-transaction mints may appear with a non-zero `from` and be excluded.

### RPC constraints, measured 2026-11-01

| Endpoint | `eth_getLogs` without address | Range limit |
|---|---|---|
| `jp-bscscutum.blockrazor.xyz` | works | 25 blocks |
| `bsc.blockrazor.xyz` | works | 25 blocks |
| `bsc-dataseed.bnbchain.org` | rejected, "limit exceeded" | — |
| `bsc-dataseed1.defibit.io` | rejected, "limit exceeded" | — |
| `bsc.publicnode.com` | rejected, "specify an address" | — |

Further measurements:

- Only **one** topic group per request. Supplying several topic0 alternatives returns an empty array instead of the union, so each standard is queried separately.
- The zero-address filter must be a 32-byte topic (64 hex characters). The 40-character address form makes the endpoint answer `hex has invalid length 20; expected 32`.
- `blockNumber` is a hex quantity and must be parsed with base 16.
- Some endpoints intermittently return an empty array for a valid query. A dedicated node via `MINTSNIPER_RPC` is strongly recommended.

### Coverage contract

Every scan returns `coverage`:

```json
{
  "status": "complete | partial | error",
  "failed_ranges": [{"topic": "...", "from_block": 0, "to_block": 0}],
  "successful_ranges": [],
  "rejected_logs": 0,
  "duplicates": 0
}
```

A failed range is reported, never silently treated as empty. The CLI exits non-zero when coverage is not complete. This distinction is the difference between "no projects" and "I could not read that part of the chain".

### Optional mintradar backend

`--backend mintradar --mintradar-path <dir>` reads an existing [mintradar](https://github.com/hornofchina1-svg/mintradar) database in read-only mode.

It does not clone repositories and does not execute external code. Its snapshot time and chain id are unverified, so its green/yellow/red labels are another opinion, not a safety certificate.

## Layer 3 — Watched wallet activity

**Question answered:** did the addresses I follow mint something?

**Detection.** The same mint-log scan, filtered to the receiver being one of the supplied addresses. Address matching happens locally; the address list is never included in an RPC request.

**Direct vs received.** Receiving an NFT is not proof of minting it, because airdrops write the same field. For each hit the tool fetches `eth_getTransactionByHash` and classifies:

- `direct` — `tx.from` equals the watched address
- `received` — anything else, including airdrops, routers and unknown senders

Only `direct` hits count as mints.

**Address file format.** One address per line, `#` for comments. Invalid addresses are reported, not silently skipped. Addresses are lowercased and de-duplicated.

**Blind spots.**

- List quality is entirely the user's responsibility. Early participants in one project are not consistently early wallets.
- Only supplied addresses are visible.
- The transaction lookup has a per-scan cap; hits beyond it are kept as `received` rather than being upgraded on a guess.

## Merge behaviour

Candidates are keyed by contract address, falling back to URL then title. A candidate seen by more than one layer gains 12 points and is tagged `multi-source`.

The merge attaches `not_established` to every candidate, listing what that source cannot tell you. That list keeps a detection report from being read as a recommendation.

## Timing

| Layer | Window | Measured runtime |
|---|---|---|
| GitHub | days | ~100 s for 7 query groups |
| Chain (ERC-721) | 8–30 min of history | 14–30 s |
| Chain (ERC-1155) | 15 min of history | 15 s |
| Wallet | 60 min of history | ~115 s |

The real advantage is not runtime but lead time: the chain layer surfaces a project within minutes of its first burst of mints, and the GitHub layer surfaces a project days before it launches.
