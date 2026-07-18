# Security Policy

BradOS includes a real security *subsystem* (BradSec: capability tokens, VFS gates, integrity checks, vault, audit log). It is still a **userland OS layer on Python** — not a hardened multi-tenant operating system or a substitute for OS/kernel isolation.

Please report security issues **privately** when practical so we can fix them before public write-ups.

## Supported versions

| Version | Supported |
|---------|-----------|
| Latest GitHub release (e.g. `v3.1.x`) | Yes |
| `main` branch | Yes (best-effort) |
| Older tags / forks | No — please upgrade or cherry-pick fixes |

## Reporting a vulnerability

**Preferred:** GitHub **private vulnerability reporting** for this repository  
(Security tab → “Report a vulnerability”), if enabled on the repo.

**Also fine:** open a **private** channel to the maintainer via the GitHub profile contact options for [Architect-Brad](https://github.com/Architect-Brad), or file a **public issue only if** the issue is already public or clearly non-exploitable (e.g. docs wording).

Please include:

- BradOS version or git tag / commit  
- OS environment (desktop Linux, Termux, etc.)  
- Clear reproduction steps  
- Impact (what an attacker gains: write outside sandbox, cap bypass, vault leak, etc.)  
- Whether you plan a public write-up (and rough timeline)

We will try to acknowledge reports in a reasonable time. There is **no formal SLA or bug bounty** — this is a community / portfolio project. Fixes ship as normal commits and patch releases when warranted.

## Scope (in)

Issues in these areas are especially welcome:

- **BradSec** capability tokens (HMAC, expiry, revoke, privilege escalation between PIDs)
- **VFS** path traversal / sandbox escape on LocalFS mounts
- **Capability enforcement** bypass (`FS_READ` / `FS_WRITE` / related gates)
- **Encrypted vault** confidentiality when locked (wrong password should not yield secrets)
- **bpkg** install-script trust (checksum bypass, remote package shadowing builtins)
- **Audit log** tampering assumptions if documented as append-only integrity (be precise about threat model)
- Default desktop/session paths that claim isolation but fail under normal use

## Out of scope (examples)

- Bugs that require **already-trusted local code** running as the same user (no privilege boundary)
- Host OS / kernel vulnerabilities unrelated to BradOS
- Denial of service by exhausting CPU/RAM in a local terminal app
- Missing features vs. SELinux/AppArmor/Qubes-style isolation
- Social engineering, physical access, or stolen user passwords outside BradOS
- Issues **only** in the legacy `--gui` path (unmaintained; prefer `--shell`)
- “I installed malware via yt-dlp / arbitrary URL in BradMusic download” without a BradOS trust-model bug
- Theoretical issues with no practical impact on the intended model (single-user local demo)

## Threat model (honest summary)

BradOS runs **as your user** on a host Python interpreter. Capabilities and VFS sandboxes constrain **in-app** behavior; they do not replace OS process isolation, SELinux, or a secure enclave.

- Tokens and VFS checks help demos, policy experiments, and accidental foot-guns.  
- A malicious Python dependency or host compromise is **out of BradOS’s control**.  
- Do not store production secrets in the vault without understanding the crypto backend (Fernet when `cryptography` is installed; weaker XOR fallback otherwise).

## Security-related features (for reporters)

| Feature | Notes |
|---------|--------|
| Capability tokens | HMAC-SHA256; `check_cap` / VFS `caller_pid` |
| Cap Demo | Guest write denied — regression target for enforcement bugs |
| Integrity baseline | SHA-256 file manifests; race-safe absolute paths |
| Vault | Prefer installing `cryptography` for Fernet |
| bpkg scripts | Untrusted remote scripts need matching `script_sha256` |

## Disclosure

- Prefer coordinated disclosure after a fix is available on `main` or a patch release.  
- Credit is welcome in release notes if you want to be named; say so in the report.  
- Please do not open a public PoC issue for high-impact bugs before a fix lands, unless the issue is already widely known.

## Questions

Non-security contribution questions belong in issues/PRs and [CONTRIBUTING.md](CONTRIBUTING.md).  
General product docs: [README.md](README.md).
