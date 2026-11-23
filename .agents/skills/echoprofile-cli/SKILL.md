---
name: echoprofile-cli
description: Reference for the EchoProfile CLI and its STDIO/HTTP MCP server entrypoints, browser-session commands, configuration, and safety boundaries.
---

# EchoProfile CLI Reference

## At a glance

- echoprofile is a command-line client for the EchoProfile browser-session service.
- Start echoprofile serve before most commands; seed-from-maestro is the exception.
- login opens the persistent headed browser profile; clone creates an isolated ephemeral browser context from its storage-state snapshot.
- --device selects the target service for one command; device use persists the default selection.
- extension-token prints a sensitive pairing token. Do not expose it in logs or chat.
- seed-from-maestro --force can overwrite EchoProfile's profile and bypass the source SingletonLock check.
- The central echoprofile-browser-automation skill retains browser workflows; this skill documents command mechanics.

## Activation contract

Before acting under this skill, read this entire SKILL.md from the first line to the last. The summary above is orientation only; it does not replace the complete instructions below. If the target device, server, or profile state is unclear, inspect it before invoking a command that changes browser state.

## Entry points

| Executable | Purpose |
|---|---|
| echoprofile | CLI client for the local or selected EchoProfile server. |
| echoprofile-extension-mcp | STDIO MCP server for extension-backed browser control. |
| echoprofile-mcp | Compatibility alias for echoprofile-extension-mcp. |
| echoprofile-extension-mcp-http | Stateless Streamable HTTP MCP transport exposing the same extension tools. |

The normal EchoProfile API server listens on 127.0.0.1:8756 by default. The HTTP MCP transport defaults to 127.0.0.1:8757. The MCP server entrypoints are service/MCP-host commands, not interactive CLI commands.

## Global options and device selection

Global option: --device DEVICE may appear before the subcommand. Targets include auto, arch, laptop, vps, or an explicit base URL. It overrides the saved device selection for that command.

- echoprofile device status shows health for known devices and the selected target.
- echoprofile device use auto|arch|laptop|vps persists the default device.
- ECHOPROFILE_DEVICE can override the saved selection through the environment.
- Use --device when only one operation should target a different device; use device use only when the persistent default should change.

## Command catalog

| Command | Purpose |
|---|---|
| echoprofile setup-browser [--browser chromium|msedge] | Install the browser build paired with the pinned Playwright version. |
| echoprofile login [OPTIONS] | Open the persistent headed browser profile. |
| echoprofile extension-token | Print the local browser-extension pairing token. |
| echoprofile logout | Close the persistent profile. |
| echoprofile persistent-status | Print open or closed. |
| echoprofile seed-from-maestro [--force] | Copy Maestro's profile into EchoProfile's own profile directory. |
| echoprofile serve | Start the EchoProfile API server. |
| echoprofile clone [URL] | Create an ephemeral clone; URL defaults to configured default_url. |
| echoprofile list | List active clones. |
| echoprofile close <clone_id> | Close one clone. |

### login options

- --chatgpt-extension loads the configured ChatGPT unpacked extension.
- --extension DIR may be repeated to load custom unpacked extensions.
- --restrict-extensions disables extensions except those explicitly selected for this launch.
- --no-switchboard skips Switchboard; configured Multica Web Runtime remains enabled.

### Persistent profile and clone behavior

- login opens the persistent profile through the running server. Log in manually in that headed browser window.
- The persistent profile stores durable login state on disk.
- clone creates a new BrowserContext seeded from a snapshot of the persistent profile. Each clone is isolated after creation; it does not keep syncing later profile changes.
- clone can take a bare hostname; the client adds https://. If no URL is supplied, the configured default is used (default about:blank).
- list shows clone ID, creation time, and URL. close requires the clone ID.
- logout closes the persistent window; it does not close clones.

### Profile-copy and token safety

- seed-from-maestro is a one-time filesystem copy, not a browser launch. It refuses when Maestro appears open (SingletonLock exists) or when the destination profile already exists.
- --force bypasses both checks and deletes an existing EchoProfile destination before copying. Use only when the source is known safe to copy and overwriting the destination is explicitly intended.
- extension-token prints the local pairing token. Treat it as a secret; do not paste it into issue reports, logs, or agent context.
- The server creates the token at ~/.config/echoprofile/extension-token with owner-only permissions if not already configured.

## Server configuration

Core environment variables:

| Variable | Default / purpose |
|---|---|
| ECHOPROFILE_HOST | 127.0.0.1 |
| ECHOPROFILE_PORT | 8756 |
| ECHOPROFILE_DEFAULT_URL | about:blank |
| ECHOPROFILE_PROFILE_DIR | ~/.local/share/echoprofile/edge-profile |
| ECHOPROFILE_DOWNLOAD_DIR | ~/Downloads |
| ECHOPROFILE_CHANNEL | bundled Chromium; msedge selects native Edge |
| ECHOPROFILE_SWITCHBOARD_DIR | ~/Projects/switchboard/dist |
| ECHOPROFILE_CHATGPT_EXTENSION_DIR | unset; required for --chatgpt-extension |
| ECHOPROFILE_NO_RELOAD | set to 1 to disable reload |
| ECHOPROFILE_EXTENSION_TOKEN | explicit pairing token override |

The API server is required for login, logout, persistent-status, clone, list, and close. serve starts it; it normally binds to loopback.

### MCP HTTP transport

- echoprofile-extension-mcp-http binds to ECHOPROFILE_MCP_HTTP_HOST (default 127.0.0.1) and ECHOPROFILE_MCP_HTTP_PORT (default 8757).
- ECHOPROFILE_MCP_HTTP_ALLOWED_CLIENTS defaults to 172.20.0.0/16, 127.0.0.1/32, and ::1/128.
- ECHOPROFILE_MCP_HTTP_ALLOWED_ORIGINS defaults to an empty list. Requests with an Origin header are rejected unless that exact origin is allowed.
- The HTTP endpoint is /mcp. The transport accepts application/json and the implemented MCP protocol version; it is not a public unauthenticated API.
- Keep the transport behind the intended trusted local/container network. Do not expose it through a public reverse proxy.

## Related workflow skill

Use echoprofile-browser-automation in the central skills repository for browser-control selection and task workflows. This skill covers the CLI and server entrypoints.
