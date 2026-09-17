# Sandbox and local execution

English | [简体中文](./sandbox.md)

## Current capabilities

Status: `Implemented`.

Version 1.5.2 provides Wasm/WASIX and nsjail skill sandboxes. Both fail closed when their real backend is unavailable. Current `2.0.0a1` additionally implements the unified `SandboxProvider`, `SandboxRegistry`, a Docker/OCI backend, an explicitly authorized local backend, and a sandbox command tool. The legacy Wasm/nsjail classes are not yet adapted to the new contract.

## Provider status

Status: the first local slice is `Implemented`.

| Provider | Use | Platform |
|---|---|---|
| Docker/OCI | `Implemented`: coding agents, commands, full workspaces | Platforms supported by Docker CLI/Daemon |
| nsjail adapter | `Planned`: join the existing skill backend to the new contract | Linux |
| Wasm adapter | `Planned`: join the existing skill backend to the new contract | Supported Wasmer platforms |
| `UnsafeLocalSandboxProvider` | `Implemented`: explicitly authorized local development | All supported platforms |
| Remote sandbox | Remote isolation-service protocol | `Reserved` |

## SandboxProvider

`SandboxProvider.open(SandboxSpec)` returns a lifecycle-owned `SandboxHandle`. The handle executes shell-free argv through `execute(SandboxCommand)` and converges its container or local runtime through `close()`. Providers use the `sandbox.provider` capability in the shared versioned, scoped registry.

`SandboxSpec` includes workspace, image, access mode, network, CPU/memory/PID limits, environment, and container workdir. `SandboxCommand` independently specifies argv, timeout, and output bounds. Docker environment values pass through a permission-restricted temporary env file that is deleted after creation; values never enter CLI arguments, logs, checkpoints, or composition codes.

## Docker/OCI defaults

- Containers are unprivileged by default.
- Only explicit workspaces are mounted.
- CPU, memory, process count, and time are limited by default.
- Network is disabled by default; `bridge` is currently optional, while granular allowlists remain `Planned`.
- Images require a digest or non-`latest` tag by default; mutable tags require explicit provider opt-in.
- The root filesystem is read-only, all Linux capabilities are dropped, `no-new-privileges` is set, and only `/tmp` uses a bounded tmpfs.
- The default container user is `65534:65534`; applications may explicitly change it for image compatibility.
- Containers and temporary volumes are removed after a run.
- Timeout, cancellation, or uncertain execution closes the handle and removes the container rather than reusing it.

The default keepalive uses `sh`/`sleep` from the image and can be replaced through `SandboxSpec.keepalive_command`. The framework does not automatically pull or trust images; image source and scanning remain the responsibility of the local developer or an upper profile.

## UnsafeLocalSandbox

`UnsafeLocalSandboxProvider` is a dangerous development mode, not a security sandbox.

Enabling it requires:

- Python explicitly creates a process-local object through `UnsafeLocalAuthorization.grant(source, acknowledge_host_access=True)`.
- A warning that host files, processes, and network are accessible.
- Authorization cannot be deserialized from configuration or composition codes.
- Imported projects, plugin defaults, and model calls cannot enable it.
- Authorization records source and time; CLI/TUI audit surfaces remain `Planned`.

Failure to create a safe backend never selects `UnsafeLocalSandboxProvider`. Local mode cannot enforce network isolation or a read-only workspace, so callers must explicitly select `SandboxNetwork.BRIDGE` and read-write access; safety-oriented values are rejected instead of silently ignored. Container-user and CPU/memory/PID fields are likewise not security guarantees in dangerous mode. It provides only shell-free argv, working directory, environment selection, timeout, cancellation, and output bounds.

## Coding agent

The coding profile remains `Planned`. The underlying handle can already run consecutive commands in one container and workspace, with read-only or read-write Docker mounts. The upper coding profile still needs writeback validation, patch preview, and session lifecycle.

## Tool integration

`sandbox_command_tool()` opens a provider handle for one tool call, executes, and always closes it. It requires `sandbox.execute` by default and uses a `WRITE` effect, producing per-call approval. Applications hold a handle directly when a container must persist across multiple steps.

`command_tool()` is a separate host-command development adapter, not a sandbox. It requires `process.execute` and per-call approval by default and should not be exposed to untrusted agents automatically.

## Not implemented yet

- Docker domain/IP network allowlists, image-pull policy, and image scanning.
- Adapters from nsjail/Wasm into the new `SandboxProvider`.
- Coding-agent workspace writeback review, durable sandbox sessions, and TUI authorization surfaces.
- A first-party remote sandbox.
