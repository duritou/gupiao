"""Manually rerun the current day's pre-market workflow in dependency order."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai_os.scheduler import MORNING_ROUTINE
from src.ai_os.task_executor import task_executor


async def main() -> None:
    executions = []
    for task in MORNING_ROUTINE:
        execution = await task_executor.execute_task(task)
        executions.append(execution.to_dict())
    print(json.dumps(executions, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
