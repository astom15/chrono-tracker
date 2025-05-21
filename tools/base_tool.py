import logging
from abc import ABC, abstractmethod
from typing import Any

from core.protocol_definitions import ToolRequest, ToolResponse


class BaseTool(ABC):
    "Abstract base class for all tools"

    def __init__(self, tool_name: str, config: dict[str, Any] | None = None):
        self.tool_name = tool_name
        self.config = config if config is not None else {}
        self.logger = logging.getLogger(f"tool.{self.tool_name}")
        self.logger.info(f"Tool '{self.tool_name}' initialized.")

    @abstractmethod
    async def execute(self, request: ToolRequest) -> ToolResponse:
        pass

    def _create_success_response(
        self, data: dict[str, Any] | None = None, request_params: dict[str, Any] | None = None
    ):
        self.logger.debug(f"Action successful. Data: {str(data)[:200]}...")
        return ToolResponse(status="success", data=data, error_message=None)

    def _create_error_response(self, error_message: str, request_params: dict[str, Any] | None = None) -> ToolResponse:
        self.logger.error(f"Action failed. Error: {error_message}. Request params: {request_params}")
        return ToolResponse(status="error", data=None, error_message=error_message)
