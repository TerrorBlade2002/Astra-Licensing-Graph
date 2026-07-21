"""Worker heartbeat upserts."""

from __future__ import annotations

import os
import socket

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WorkerHeartbeat
from app.models.mixins import utcnow


async def beat(session: AsyncSession, *, worker_id: str, worker_type: str) -> None:
    now = utcnow()
    stmt = pg_insert(WorkerHeartbeat).values(
        worker_id=worker_id,
        worker_type=worker_type,
        hostname=socket.gethostname(),
        process_id=os.getpid(),
        started_at=now,
        last_heartbeat_at=now,
        heartbeat_metadata={},
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[WorkerHeartbeat.worker_id],
        set_={"last_heartbeat_at": now, "worker_type": worker_type},
    )
    await session.execute(stmt)
    await session.commit()
