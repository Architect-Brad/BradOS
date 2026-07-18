# Running BradOS on Termux (Android)

BradOS is a pure-Python, terminal-based (Textual/Rich) application, so it
runs on Termux's Linux userland with no code changes to the core kernel,
VFS, shell, or GUI apps. Two optional features rely on things Termux
doesn't have (Docker, systemd) — see **Limitations** below.

## Quick start

```bash
pkg install git
git clone https://github.com/Architect-Brad/BradOS.git
cd BradOS
bash scripts/termux-setup.sh
python brados.py
```

`scripts/termux-setup.sh` installs Python and, where your Termux mirror
has them, prebuilt `python-cryptography`/`python-psutil` packages (much
faster than compiling). If those aren't available as prebuilt packages,
it installs the build toolchain (`clang`, `rust`, `openssl`) so `pip`
can build them instead — this can take several minutes on a phone.

## Manual install

If you'd rather do it by hand:

```bash
pkg install -y python python-cryptography python-psutil
pip install -e . --no-deps
pip install -r requirements-termux.txt
```

## Running it

```bash
python brados.py           # interactive menu: classic / kernel / desktop shell
python brados.py --shell   # desktop shell directly
python brados.py --daemon  # security daemon only, no UI
```

For the best experience, run Termux full-screen and consider a Bluetooth
keyboard — BradOS's desktop shell uses mouse-click support in Textual,
which works with Termux's touch-to-tap, but a keyboard makes the shell
(brash) much more comfortable.

## Limitations on Termux

**Docker-backed mail server is unavailable.** BradOS's mail app can run a
full IMAP/SMTP stack via `docker-mailserver`, but Termux can't run Docker
(no container namespaces without root). The mail app already checks for
Docker at runtime and reports it as unavailable rather than crashing —
this is the same behavior you'd see running BradOS on any machine
without Docker installed, not something specific to Termux.

**No systemd.** `brados-sec.service` / `scripts/install-service.sh` are
for auto-starting the security daemon on boot via `systemctl --user`,
which doesn't exist on Termux. This does **not** affect normal use — the
security daemon and mesh networking already start automatically,
in-process, the moment you launch BradOS. It only matters if you want
the daemon running even when BradOS itself isn't open. For that, install
the **Termux:Boot** app from F-Droid and drop a script in
`~/.termux/boot/` that runs:

```bash
cd ~/BradOS && python brados.py --daemon
```

**Background execution.** Android suspends background apps aggressively
to save battery. If you want the mesh networking or security daemon to
keep running while Termux isn't in the foreground, run
`termux-wake-lock` (from the `termux-api` package) first, and keep
Termux from being battery-optimized in Android's settings.

**First install is slow.** Compiling `cryptography` from source on a
phone can take several minutes if prebuilt packages aren't available for
your device's architecture/Termux mirror. This is one-time cost.

## What needed no changes at all

The kernel scheduler, VFS, brash shell, bpkg, the Textual GUI, and the
test suite are all plain Python + terminal I/O — they were already
portable and needed zero Termux-specific code changes.
