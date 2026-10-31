# Setup, credentials, and troubleshooting

## Requirements

- Python 3.10 or newer
- Network access to `api.github.com` and a BSC RPC endpoint

No third-party Python packages. Everything uses the standard library. No `git` required.

## Install

```bash
npx skills add https://github.com/menghaoran214-lang/mintsniper
```

Or:

```bash
git clone https://github.com/menghaoran214-lang/mintsniper.git
bash mintsniper/scripts/install.sh ~/.claude/skills
```

## Credentials

Both are optional. Without them the tool still runs, with reduced coverage.

### GITHUB_TOKEN

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

Or store it once inside the skill directory:

```bash
mkdir -p <skill-dir>/state
echo ghp_your_token_here > <skill-dir>/state/github_token
```

`GITHUB_TOKEN`, `GH_TOKEN` and `MINTSNIPER_GITHUB_TOKEN` are read, in that order.

A token with no scopes is enough for public repository search. Anonymous access is limited to 10 search requests per minute and 60 core requests per hour, which several simultaneous users will exhaust between them.

### MINTSNIPER_RPC

```bash
export MINTSNIPER_RPC="https://your-bsc-node.example"
```

Comma-separate multiple endpoints. Without it the tool uses the public endpoints defined in `scripts/common.py`, which cap `eth_getLogs` at 25 blocks per request and often rate-limit. See `references/sources.md` for the measured endpoint table.

### State directory

```bash
export MINTSNIPER_STATE=/path/to/state
```

Defaults to `<skill-dir>/state`.

## First run

```bash
cd <skill-dir>/scripts

# offline tests, no network, no credentials
python3 -m unittest discover -s tests

# chain layer
python3 chain_scan.py --backend native --minutes 8

# ERC-1155 gap
python3 erc1155_scan.py --minutes 15

# GitHub layer
python3 github_scan.py --days 5

# optional wallet layer
python3 wallet_scan.py --addresses ./watch.txt --minutes 60
```

Check the exit code of the chain scans. A non-zero exit means coverage was not complete, which is a gap rather than an empty result.

## Continuous operation

A chain scan takes roughly 15–30 seconds for an 8-minute window. On a dedicated node a one-minute loop is realistic; on public endpoints it is not.

The wallet layer is slower by construction, because it has to read mint logs before it can match your addresses locally. Measured on public endpoints: 8 minutes of history took about 110 seconds and returned `coverage.status: partial`. Use a dedicated node for the wallet layer, and keep the window short.

```cron
* * * * * flock -n /tmp/mintsniper.lock /bin/sh -c 'cd /path/to/mintsniper/scripts && MINTSNIPER_STATE=/path/to/state python3 chain_scan.py --backend native --minutes 8 --json > /path/to/state/chain.json'
```

## Troubleshooting

### "all RPC endpoints failed"

The endpoint rejected the query. Check the range limit (25 blocks on public endpoints) and whether the endpoint supports address-less log queries at all. Error text names the endpoint index, not the URL, so credentials are not leaked into logs.

### Empty results but no error

Check `coverage.status` first.

- `complete` with zero candidates means nothing crossed the threshold in that window. Widen `--minutes` or lower `--mint-threshold`.
- `partial` means some ranges were not read. That is a gap, so do not report it as "nothing found".

If `status` is `complete` and you still expect results on ERC-1155, the endpoint may be silently dropping that topic filter. Point `MINTSNIPER_RPC` at a dedicated node.

### "chain id mismatch" or a refusal to scan

The RPC endpoint is not on BSC (chain id 56). The tool refuses rather than producing numbers from the wrong chain.

### "no GITHUB_TOKEN found"

Not an error, but the GitHub layer is rate-limited and may return partial results. The report states whether a token was used.

### mintradar backend fails

It requires `--mintradar-path` pointing at an existing local checkout. Nothing is downloaded automatically. Use `--backend native` if you do not already run mintradar.

### Windows path issues

Use absolute paths with forward slashes. `MINTSNIPER_STATE` should look like `C:/Users/you/mintsniper-state`. Git Bash and PowerShell resolve `/tmp` differently, so prefer an explicit path when redirecting output.

## Files it writes

| Path | Content |
|---|---|
| `state/` | Only what you ask for: JSON reports and an optional token file |

Nothing is written outside the state directory, and no watched address is ever transmitted.

## Uninstall

```bash
rm -rf <skills-dir>/mintsniper
```
