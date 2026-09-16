# Sandbox and local execution

English | [简体中文](./sandbox.md)

## Current capabilities

Status: `Implemented`.

Version 1.5.2 provides Wasm/WASIX and nsjail skill sandboxes. Both fail closed when their real backend is unavailable. Wasm fits restricted skill scripts, while nsjail provides Linux process isolation. They do not yet implement one next-generation `SandboxProvider`.

## First-release target

Status: `Planned`.

| Provider | Use | Platform |
|---|---|---|
| Docker/OCI | Coding agents, commands, full workspaces | Linux, macOS, Windows Docker Desktop/WSL2 |
| nsjail adapter | Lightweight Linux process isolation | Linux |
| Wasm adapter | Small portable skills | Supported Wasmer platforms |
| `UnsafeLocalSandbox` | Explicitly authorized local development | All supported platforms |
| Remote sandbox | Remote isolation-service protocol | `Reserved` |

## SandboxProvider

A provider receives an image, workspace mounts, environment references, network policy, resource limits, timeout, and command, then returns a lifecycle-owned handle. The handle provides file, process, and close operations; every child process converges when the handle closes.

Workspace mounts use least privilege by default. Secrets enter through temporary references and never appear in logs, checkpoints, or composition codes.

## Docker/OCI defaults

- Containers are unprivileged by default.
- Only explicit workspaces are mounted.
- CPU, memory, process count, and time are limited by default.
- Network is disabled or allowlisted explicitly by the profile.
- Images use fixed tags or digests; mutable tags require explicit permission.
- Containers and temporary volumes are removed after a run.
- Exported patches or file changes validate destination paths before writeback.

## UnsafeLocalSandbox

`UnsafeLocalSandbox` is a dangerous development mode, not a security sandbox.

Enabling it requires:

- Explicit selection through Python, CLI, or TUI.
- A warning that host files, processes, and network are accessible.
- Authorization bound to current local configuration and excluded from composition codes.
- Imported projects, plugin defaults, and model calls cannot enable it.
- Audit events record the authorization source and scope but no secrets.

Failure to create a safe backend never automatically selects `UnsafeLocalSandbox`.

## Coding agent

The coding profile performs file reads, commands, tests, and builds in one sandbox handle so files and processes share a consistent workspace. Explicit mounts expose read-only host files; workspace policy bounds every writeback path.

## Tool integration

A tool declares side effects and required capabilities. Before invocation, the execution pipeline resolves sandbox, permission, resource budget, and approval. Tools cannot bypass `SandboxProvider` to create host subprocesses; an explicit local tool is marked as a dangerous capability.
