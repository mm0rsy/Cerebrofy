# Windows Installation Guide

## Install via winget

```powershell
winget install cerebrofy
```

After installation, **open a new terminal** for `%PATH%` changes to take effect:

```powershell
cerebrofy --version
```

## Upgrade

```powershell
winget upgrade cerebrofy
```

## Known Limitations (v1)

### Cold-Start Delay (SC-008)

The first invocation of `cerebrofy validate` (e.g., when the pre-push hook runs) may take
**2–5 seconds** on Windows. This is caused by the self-extracting `.exe` unpacking its
bundled Python runtime to `%TEMP%` on cold start.

**Subsequent invocations are fast** — the extracted files are cached in `%TEMP%`.

This is a v1 known limitation and is documented as SC-008 in the Cerebrofy spec.

### New Terminal Required After Install

The NSIS installer adds `%PROGRAMFILES64%\Cerebrofy` to the system `PATH` via the Windows
registry. This change takes effect in **new terminal sessions only**. If `cerebrofy` is not
found after installation, open a new Command Prompt or PowerShell window.

## Manual Installation

If winget is not available, download the installer directly from the GitHub releases page
and run:

```powershell
.\cerebrofy-setup.exe /S
```

The `/S` flag performs a silent install. Open a new terminal afterwards.

## MCP Server (AI Tool Integration)

After installation, run `cerebrofy init` in your repository to register the MCP server
with your AI tool. No additional `pip install` is required — the MCP server is bundled.

```powershell
cd C:\path\to\your-repo
cerebrofy init
```

## Uninstall

```powershell
winget uninstall cerebrofy
```

Or use **Add or Remove Programs** in Windows Settings.
