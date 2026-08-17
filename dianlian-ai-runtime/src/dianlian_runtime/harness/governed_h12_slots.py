from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from dianlian_runtime.harness.governed_model_gateway import (
        GovernedInitialModelCallResponse,
    )
    from dianlian_runtime.harness.governed_model_intent import (
        GovernedInitialModelIntent,
    )
    from dianlian_runtime.harness.governed_model_receipt import (
        GovernedAfterToolModelRequestReceipt,
        GovernedInitialModelRequestReceipt,
    )
    from dianlian_runtime.harness.governed_tool_gateway import (
        GovernedToolCallResponse,
    )
    from dianlian_runtime.harness.governed_tool_receipt import (
        GovernedToolRequestReceipt,
    )
    from dianlian_runtime.harness.h12_durable import (
        DurableIntent,
        GovernedAfterToolTerminalEvidence,
        GovernedInitialTerminalEvidence,
        GovernedToolTerminalEvidence,
        ModelPhase,
    )
    from dianlian_runtime.supervisor.driver import DriverFence


class GovernedH12Slots(Protocol):
    """Durable governed H12 operations used by the execution Driver.

    Implementations persist evidence only. They never replace the live Supervisor
    gate and never select an implicitly usable receipt from history.
    """

    async def load_governed_initial_model_intent(
        self,
        execution_id: UUID,
    ) -> GovernedInitialModelIntent | None: ...

    async def prepare_model(
        self,
        execution_id: UUID,
        call_index: int,
        phase: ModelPhase,
        request_without_hash: dict[str, Any],
    ) -> DurableIntent: ...

    async def load_governed_initial_terminal_evidence(
        self,
        execution_id: UUID,
    ) -> GovernedInitialTerminalEvidence | None: ...

    async def persist_governed_initial_model_receipt(
        self,
        receipt: GovernedInitialModelRequestReceipt,
    ) -> GovernedInitialModelRequestReceipt: ...

    async def begin_governed_initial_model_dispatch(
        self,
        receipt: GovernedInitialModelRequestReceipt,
        fence: DriverFence,
    ) -> None: ...

    async def require_governed_initial_model_dispatch_binding(
        self,
        receipt: GovernedInitialModelRequestReceipt,
    ) -> None: ...

    async def complete_governed_initial_model(
        self,
        execution_id: UUID,
        fence: DriverFence,
        response: GovernedInitialModelCallResponse,
    ) -> None: ...

    async def prepare_tool(
        self,
        execution_id: UUID,
        *,
        source_model_call_id: UUID,
        model_tool_selection_id: UUID,
        request_without_hash: dict[str, Any],
    ) -> DurableIntent: ...

    async def load_governed_tool_terminal_evidence(
        self,
        execution_id: UUID,
    ) -> GovernedToolTerminalEvidence | None: ...

    async def persist_governed_tool_receipt(
        self,
        receipt: GovernedToolRequestReceipt,
    ) -> GovernedToolRequestReceipt: ...

    async def begin_governed_tool_dispatch(
        self,
        receipt: GovernedToolRequestReceipt,
        fence: DriverFence,
    ) -> None: ...

    async def require_governed_tool_dispatch_binding(
        self,
        receipt: GovernedToolRequestReceipt,
    ) -> None: ...

    async def complete_governed_tool(
        self,
        execution_id: UUID,
        fence: DriverFence,
        response: GovernedToolCallResponse,
    ) -> None: ...

    async def load_governed_after_tool_terminal_evidence(
        self,
        execution_id: UUID,
    ) -> GovernedAfterToolTerminalEvidence | None: ...

    async def persist_governed_after_tool_model_receipt(
        self,
        receipt: GovernedAfterToolModelRequestReceipt,
    ) -> GovernedAfterToolModelRequestReceipt: ...

    async def begin_governed_after_tool_model_dispatch(
        self,
        receipt: GovernedAfterToolModelRequestReceipt,
        fence: DriverFence,
    ) -> None: ...

    async def require_governed_after_tool_model_dispatch_binding(
        self,
        receipt: GovernedAfterToolModelRequestReceipt,
    ) -> None: ...

    async def complete_governed_after_tool_model(
        self,
        execution_id: UUID,
        fence: DriverFence,
        response: GovernedInitialModelCallResponse,
    ) -> None: ...


class GovernedH12SlotsFactory(Protocol):
    def __call__(
        self,
        fence: DriverFence,
    ) -> AbstractAsyncContextManager[GovernedH12Slots]: ...
