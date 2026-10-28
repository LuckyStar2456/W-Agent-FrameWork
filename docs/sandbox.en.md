# Sandbox and local execution

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

English | [简体中文](./sandbox.md)

## Current capabilities

Status: `Implemented`.

Version 1.5.2 provides Wasm/WASIX and nsjail skill sandboxes. Both fail closed when their real backend is unavailable. The current version also provides `SandboxProvider`, `SandboxRegistry`, Docker/OCI and nsjail command backends, an explicitly authorized local backend, and a sandbox command tool. `ProviderSkillSandbox` bridges legacy `execute(skill, script_name, args)` calls into a new provider. Wasm does not yet implement the generic command and hard resource-limit contract.

## Provider status

Status: the first local slice is `Implemented`.

| Provider | Use | Platform |
|---|---|---|
| Docker/OCI | `Implemented`: coding agents, commands, full workspaces | Platforms supported by Docker CLI/Daemon |
| nsjail provider + skill adapter | `Implemented`: command protocol and legacy skill bridge; real isolation awaits platform acceptance | Linux, curated rootfs + cgroup v2 |
| Wasm adapter | `Planned`: join the existing skill backend to the new contract | Supported Wasmer platforms |
| `UnsafeLocalSandboxProvider` | `Implemented`: explicitly authorized local development | All supported platforms |
| Remote sandbox | Remote isolation-service protocol | `Reserved` |

## SandboxProvider

`SandboxProvider.open(SandboxSpec)` returns a lifecycle-owned `SandboxHandle`. The handle executes shell-free argv through `execute(SandboxCommand)` and converges its container or local runtime through `close()`. Providers use the `sandbox.provider` capability in the shared versioned, scoped registry.

`SandboxSpec` includes workspace, image, access mode, network, CPU/memory/PID limits, environment, and container workdir. `SandboxCommand` independently specifies argv, timeout, and output bounds. Docker environment values pass through a permission-restricted temporary env file that is deleted after creation; values never enter CLI arguments, logs, checkpoints, or composition codes.

CPU and timeout require finite positive numbers. Memory, PID and output limits require positive integers; booleans, NaN and infinity are rejected. Network/access strings normalize to enums; unknown values, including the unimplemented `allowlist`, are rejected immediately.

## nsjail and the legacy skill bridge

`NsJailSandboxProvider(rootfs, cgroup_path=...)` requires a host-provisioned curated rootfs, delegated cgroup v2 directory and nsjail. Each command gets a fresh jail with the explicit shared workspace, not a persistent container. CPU, memory and process bounds map to cgroup quota/memory/pids, with wall-clock and output bounds. Only `network=none` is supported: a network namespace is retained and seccomp denies socket syscalls. Async runtimes that require socketpair may also be rejected. Namespace/cgroup/command failures never trigger a weaker retry.

`available()` only checks directories and the CLI, not kernel isolation, permissions or cgroup delegation. The host must provision numeric UID/GID mappings and workspace permissions. Explicit environment values appear in nsjail CLI arguments and may be visible to host processes; do not put secrets there. Argument construction follows the [official nsjail implementation](https://github.com/google/nsjail/blob/master/cmdline.cc).

The 64 MiB `/tmp` tmpfs uses a private per-command protobuf configuration. Filesystem `options` contain only `size`/`mode`; `rw`, `nosuid`, `nodev`, `noexec` and `mandatory` are separate fields, not generic flags embedded in CLI `--mount` filesystem data. This follows the [official MountPt schema](https://github.com/google/nsjail/blob/master/config.proto#L26-L58) and [mount flag implementation](https://github.com/google/nsjail/blob/master/mnt_legacy.cc#L85-L115). No user text enters the configuration: dynamic paths, environment and commands remain separate argv entries. The configuration is loaded before CLI limits because its parser uses `CopyFrom`. A newly created private directory prevents overwriting user configurations; success, failure and cancellation all remove it. Configuration/mount failure never triggers a weaker fallback.

CPU quota conversion follows the [official cgroup v2 implementation](https://github.com/google/nsjail/blob/master/cgroup2.cc#L236-L250), with an additional bound preventing overflow in its uint32 multiplication by 1000. The memory field limits RAM; swap is not additionally bounded. The cgroup directory needs authorized controllers and write access; nsjail may attempt to enable controllers itself, and an existing ordinary directory proves neither availability nor enforcement.

```python
from pathlib import Path
from w_agent import NsJailSandboxProvider, ProviderSkillSandbox, SandboxSpec

provider = NsJailSandboxProvider(
    Path("/opt/w-agent/rootfs"),
    cgroup_path=Path("/sys/fs/cgroup/w-agent"),
)
sandbox = ProviderSkillSandbox(
    provider,
    SandboxSpec(Path.cwd(), cpu_limit=0.5, memory_bytes=256 * 1024 * 1024),
    python_executable="/usr/bin/python3",
)
# skill is a reviewed Skill; the host must authorize execution separately.
result = await sandbox.execute(skill, "main", {"input": "hello"})
```

Each call creates a temporary read-only payload containing only the selected script, JSON arguments and runner. It always closes the handle and removes the payload without mounting the original project. Both `execute(args)` and global `result` conventions work; async function support depends on backend policy. The template's workspace is replaced, and sibling imports/writeback are unsupported. Docker can use the same adapter with a Python image. The old Wasm API remains directly usable, but SDK CPU/memory/PID enforcement has not been verified, so it is not advertised as a generic provider honoring `SandboxSpec`.

## Docker/OCI defaults

- Containers are unprivileged by default.
- Only explicit workspaces are mounted.
- CPU, memory, process count, and time are limited by default.
- Network is disabled by default; `bridge` is currently optional, while granular allowlists remain `Planned`.
- Images require a digest or non-`latest` tag by default; mutable tags require explicit provider opt-in. The provider passes `--pull never` by default; `missing` or `always` is a host opt-in.
- The root filesystem is read-only, all Linux capabilities are dropped, `no-new-privileges` is set, and only `/tmp` uses a bounded tmpfs.
- The default container user is `65534:65534`; applications may explicitly change it for image compatibility.
- Containers and temporary volumes are removed after a run.
- Timeout, cancellation, or uncertain execution closes the handle and removes the container rather than reusing it.

Creation timeout/failure also attempts cleanup by the unique container name. After removal failure the handle rejects execution, but `close()` can retry cleanup. A disconnected daemon prevents confirming remote removal.

The default keepalive uses `sh`/`sleep` from the image and can be replaced through `SandboxSpec.keepalive_command`. The framework does not automatically pull or trust images; image source and scanning remain the responsibility of the local developer or an upper profile.

## UnsafeLocalSandbox

`UnsafeLocalSandboxProvider` is a dangerous development mode, not a security sandbox.

Enabling it requires:

- Python explicitly creates a process-local object through `UnsafeLocalAuthorization.grant(source, acknowledge_host_access=True)`.
- A warning that host files, processes, and network are accessible.
- Authorization cannot be deserialized from configuration or composition codes.
- Imported projects, plugin defaults, and model calls cannot enable it.
- Authorization records source and time. Current CLI/TUI locked-package installation uses a local confirmation distinct from Docker confirmation; a general authorization audit log remains `Planned`.

Failure to create a safe backend never selects `UnsafeLocalSandboxProvider`. Local mode cannot enforce network isolation or a read-only workspace, so callers must explicitly select `SandboxNetwork.BRIDGE` and read-write access; safety-oriented values are rejected instead of silently ignored. Container-user and CPU/memory/PID fields are likewise not security guarantees in dangerous mode. It provides only shell-free argv, working directory, environment selection, timeout, cancellation, and output bounds.

## Coding agent

The coding-agent template is `Implemented`, but it declares only system instructions, recommended tools, and default budgets and grants no execution authority. The underlying handle can already run consecutive commands in one container and workspace, with read-only or read-write Docker mounts. Richer writeback validation, patch preview, and durable sandbox sessions remain later capabilities.

## Locked plugin package installation

The `2.0.0a4` release's `SandboxPipPackageInstaller` reuses the same `SandboxProvider` protocol. Installation explicitly selects `SandboxNetwork.BRIDGE` and a read-write workspace and uses `PluginInstallAuthorization`, bound to the exact request digest, to acknowledge network and package-code execution. CLI/TUI default to Docker. The installer creates a fresh empty staging directory per request; Docker mounts only that directory for writing, not the surrounding local state with Sessions and Checkpoints. After closing the sandbox, it hashes the staged site, copies it to the final target, verifies the copied tree again, and removes staging and newly created target directories on failure. Unix maps the current UID/GID for the writable bind mount; Windows Docker Desktop uses the image user while retaining the read-only root, dropped capabilities, and no-new-privileges. Unisolated local mode additionally requires separate host-access confirmation: staging cannot prevent it from reading other host files, and it is never selected after Docker failure.

The default installer uses shell-free argv with `--isolated --require-hashes --only-binary=:all: --no-deps`. The complete dependency closure, versions, and artifact SHA-256 values come from a host lock catalog. `--isolated` ignores pip environment variables and user configuration, but does not itself isolate global/site configuration inside the image or network proxies. The installer resolves no unlocked dependency, accepts no sdist, does not automatically pull or trust a Docker image, and does not project sandbox credentials into the install result. Success produces a directory addressed by the request digest with a separate content-tree digest and credential-free provenance; plugin loading still requires independent confirmation.

## Tool integration

`sandbox_command_tool()` opens a provider handle for one tool call, executes, and always closes it. It requires `sandbox.execute` by default and uses a `WRITE` effect, producing per-call approval. Applications hold a handle directly when a container must persist across multiple steps.

`command_tool()` is a separate host-command development adapter, not a sandbox. It requires `process.execute` and per-call approval by default and should not be exposed to untrusted agents automatically.

## Not implemented yet

- Docker domain/IP network allowlists and image scanning. `bridge` grants unrestricted networking; proxy environment variables or declared lists do not enforce isolation. No unverified allowlist template is supplied.
- Wasm generic commands and hard resource limits under `SandboxProvider`.
- Coding-agent workspace writeback review, durable sandbox sessions, and general TUI authorization-audit surfaces.
- A first-party remote sandbox.

The early 2026-10-01 adapter, resource mapping, cancellation and cleanup regressions used fake runners. The tmpfs configuration was independently parsed against a subset of the upstream protobuf schema (this QA test skips if protobuf is absent; cleanup/injection tests do not depend on it). Subsequent stable-candidate closing work passed the authorized real Docker smoke. This does not expand earlier mock coverage retroactively or establish acceptance for every host platform, nsjail or Wasmer. Artifact build/upload remains separate from sandbox tests; see the [stable baseline](./stable-release-baseline.en.md).
