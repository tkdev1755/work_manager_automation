from __future__ import annotations

import json
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class WorkManagerError(RuntimeError):
    """Raised when a work_manager MCP tool call returns is_error=True."""


class WorkManagerClient(AbstractAsyncContextManager["WorkManagerClient"]):
    """Thin typed wrapper around the work_manager MCP server's 11 tools.
    One-to-one with lib/mcp_server.dart in the work_manager repo - update
    both together if that contract changes."""

    def __init__(self, binary: Path):
        self._binary = binary
        self._stack: list[Any] = []
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "WorkManagerClient":
        params = StdioServerParameters(command=str(self._binary), args=[])
        self._stdio_cm = stdio_client(params)
        read, write = await self._stdio_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        # Deliberately NOT forwarding exc_info: passing a foreign exception
        # (one that didn't originate inside ClientSession's own task group)
        # into ClientSession.__aexit__ hangs there indefinitely - confirmed
        # empirically. Closing both as if nothing happened avoids that path;
        # the real exception (if any) still propagates on its own once this
        # method returns, since we neither suppress nor replace it.
        if self._session is not None:
            await self._session_cm.__aexit__(None, None, None)
        await self._stdio_cm.__aexit__(None, None, None)

    async def _call(self, tool: str, **arguments: Any) -> Any:
        assert self._session is not None, "use WorkManagerClient as an async context manager"
        result = await self._session.call_tool(tool, arguments=arguments)
        text = result.content[0].text if result.content else ""
        if result.is_error:
            raise WorkManagerError(text)
        return json.loads(text) if text else None

    # -- Discovery ------------------------------------------------------

    async def list_presets(self) -> list[dict]:
        return await self._call("list_presets")

    async def get_preset_info(self, preset: str) -> dict:
        return await self._call("get_preset_info", preset=preset)

    # -- Application lifecycle ------------------------------------------

    async def list_applications(self) -> list[dict]:
        return await self._call("list_applications")

    async def get_current_application(self) -> dict:
        return await self._call("get_current_application")

    async def create_application(self, name: str, preset: str | None = None) -> dict:
        kwargs = {"name": name}
        if preset is not None:
            kwargs["preset"] = preset
        return await self._call("create_application", **kwargs)

    async def load_application(self, application_id: str) -> dict:
        return await self._call("load_application", id=application_id)

    # -- Files & export ---------------------------------------------------

    async def resolve_template_path(self, template_key: str, application_id: str | None = None) -> dict:
        kwargs = {"templateKey": template_key}
        if application_id is not None:
            kwargs["applicationId"] = application_id
        return await self._call("resolve_template_path", **kwargs)

    async def open_template(self, template_key: str, application_id: str | None = None) -> dict:
        kwargs = {"templateKey": template_key}
        if application_id is not None:
            kwargs["applicationId"] = application_id
        return await self._call("open_template", **kwargs)

    async def export_application(self, application_id: str | None = None) -> dict:
        kwargs = {}
        if application_id is not None:
            kwargs["applicationId"] = application_id
        return await self._call("export_application", **kwargs)

    # -- Preset administration -------------------------------------------

    async def add_preset(self, name: str, path: str, from_preset: str | None = None) -> dict:
        kwargs = {"name": name, "path": path}
        if from_preset is not None:
            kwargs["fromPreset"] = from_preset
        return await self._call("add_preset", **kwargs)

    async def remove_preset(self, name: str) -> dict:
        return await self._call("remove_preset", name=name)
