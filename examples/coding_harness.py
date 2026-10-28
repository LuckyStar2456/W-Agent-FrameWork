"""Configured offline coding Harness; edits memory only, never executes code."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Annotated

from w_agent import (
    AgentComponent, ApplicationOperation, ApplicationProject, Aspect, Bean,
    Before, Configuration, Finally, PostConstruct, PreDestroy,
    RepositoryComponent, ToolComponent, Value, compile_configured,
)


@dataclass(frozen=True)
class PatchProposal:
    path: str
    before: str
    after: str

    @property
    def digest(self) -> str:
        data = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(data).hexdigest()


class PatchModel:
    """Custom domain parameters and return type, independent of model providers."""

    def __init__(self, language: str):
        if language != "python":
            raise ValueError("offline template implements only python")
        self.language = language

    async def propose(self, path: str, source: str, *, greeting: str) -> PatchProposal:
        if not isinstance(greeting, str) or len(greeting) > 80:
            raise ValueError("greeting must be short text")
        return PatchProposal(path, source, f"greeting = {greeting!r}\nprint(greeting)\n")


@Configuration("coding_models")
class ModelConfiguration:
    @Bean(name="patch_model")
    def model(self, language: Annotated[str, Value("coding.language", required=True)]) -> PatchModel:
        return PatchModel(language)


@RepositoryComponent("coding_store")
class MemoryWorkspace:
    def __init__(self):
        self.files = {"hello.py": "greeting = 'hello'\nprint(greeting)\n"}
        self.revisions: list[str] = []
        self.closed = False

    def read(self, path: str) -> str:
        if self.closed:
            raise RuntimeError("workspace closed")
        return self.files[path]

    @PreDestroy
    def close(self):
        self.closed = True


@ToolComponent("patch_tool")
class PatchTool:
    def __init__(self, workspace: MemoryWorkspace):
        self.workspace = workspace

    def apply(self, proposal: PatchProposal, *, approved_digest: str) -> str:
        # Enforcement stays at the side-effect boundary, not in removable AOP.
        if not approved_digest or approved_digest != proposal.digest:
            raise PermissionError("exact preview digest approval is required")
        if self.workspace.read(proposal.path) != proposal.before:
            raise ValueError("source changed after preview")
        self.workspace.files[proposal.path] = proposal.after
        self.workspace.revisions.append(proposal.digest)
        return proposal.digest


@Aspect("coding_trace", component="coding", methods=("preview", "apply"))
class CodingTrace:
    def __init__(self):
        self.events: list[str] = []

    @Before
    def started(self, invocation):
        self.events.append(f"before:{invocation.method}")

    @Finally
    def finished(self, invocation, outcome):
        self.events.append(f"finally:{outcome.status}")


@AgentComponent("coding", scope="run")
class CodingHarness:
    def __init__(self, model: PatchModel, workspace: MemoryWorkspace, tool: PatchTool):
        self.model, self.workspace, self.tool = model, workspace, tool
        self.ready = False

    @PostConstruct
    def initialize(self):
        self.ready = True

    async def preview(self, path: str, *, greeting: str) -> dict:
        if not self.ready:
            raise RuntimeError("harness not initialized")
        proposal = await self.model.propose(path, self.workspace.read(path), greeting=greeting)
        return {**asdict(proposal), "digest": proposal.digest}

    async def apply(self, path: str, *, greeting: str, approved_digest: str) -> dict:
        if not self.ready:
            raise RuntimeError("harness not initialized")
        proposal = await self.model.propose(path, self.workspace.read(path), greeting=greeting)
        digest = self.tool.apply(proposal, approved_digest=approved_digest)
        return {"path": path, "digest": digest, "content": self.workspace.read(path)}

    @PreDestroy
    def close(self):
        self.ready = False


def create_project() -> ApplicationProject:
    # Configuration selects only these already imported objects. No import path
    # in JSON can grant code-loading authority or replace this allowlist.
    catalog = {"models": ModelConfiguration, "workspace": MemoryWorkspace,
               "tool": PatchTool, "harness": CodingHarness, "trace": CodingTrace}
    document = json.loads(Path(__file__).with_name("coding_project.json").read_text(encoding="utf-8"))
    plan = compile_configured(document, catalog=catalog)
    return ApplicationProject(plan, {
        "preview": ApplicationOperation("coding", "preview"),
        "apply": ApplicationOperation("coding", "apply"),
    }, name="coding-demo")


async def run_demo() -> dict:
    async with create_project().open() as host:
        workspace = host.context.resolve("coding_store")
        trace = host.context.resolve("coding_trace")
        preview = await host.invoke("preview", "hello.py", greeting="framework")
        # The demo itself explicitly approves its deterministic, memory-only
        # preview. Production applications must collect real user approval.
        applied = await host.invoke("apply", "hello.py", greeting="framework",
                                    approved_digest=preview["digest"])
    return {"applied": applied, "revisions": len(workspace.revisions),
            "trace": trace.events, "closed": workspace.closed}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_demo()), ensure_ascii=False))
