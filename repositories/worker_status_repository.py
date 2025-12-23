"""Repository for tracking Celery worker health and failure events."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from db import get_async_session
from models import WorkerFailureLog, WorkerStatus

logger = logging.getLogger(__name__)


class WorkerStatusRepository:
    """Manage worker availability records and failure logs."""

    async def upsert_worker_status(
        self,
        worker_name: str,
        hostname: Optional[str] = None,
        is_available: bool = True,
        reason: Optional[str] = None,
        task_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Optional[WorkerStatus]:
        """Create or update a worker heartbeat record."""
        now = datetime.now(timezone.utc)
        try:
            async with get_async_session() as session:
                record = (
                    await session.execute(
                        select(WorkerStatus).where(
                            WorkerStatus.worker_name == worker_name
                        )
                    )
                ).scalar_one_or_none()

                if record is None:
                    record = WorkerStatus(
                        worker_name=worker_name,
                        hostname=hostname,
                        is_available=is_available,
                        last_heartbeat=now,
                        extra=extra,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(record)
                else:
                    record.hostname = hostname or record.hostname
                    record.is_available = is_available
                    record.last_heartbeat = now
                    record.updated_at = now
                    if reason:
                        record.last_failure_reason = reason
                        record.last_failure_task_id = task_id
                    if task_id:
                        record.last_failure_task_id = task_id
                    if extra:
                        existing_extra = record.extra or {}
                        existing_extra.update(extra)
                        record.extra = existing_extra
                    if not is_available:
                        record.failure_count = (record.failure_count or 0) + 1
                        record.last_failure_at = now

                logger.debug(
                    "Upserted worker status %s (available=%s)",
                    worker_name,
                    is_available,
                )
                return record
        except SQLAlchemyError as exc:
            logger.error(
                "Database error updating worker status %s: %s", worker_name, exc
            )
        except Exception as exc:
            logger.error("Failed to upsert worker status %s: %s", worker_name, exc)
        return None

    async def mark_worker_unavailable(
        self,
        worker_name: str,
        task_id: Optional[str],
        reason: str,
        traceback_text: Optional[str] = None,
    ) -> None:
        """Record that a worker is no longer healthy after a task failure."""
        await self.upsert_worker_status(
            worker_name=worker_name,
            is_available=False,
            reason=reason,
            task_id=task_id,
            extra={"error": reason},
        )
        await self.record_failure_log(worker_name, task_id, reason, traceback_text)

    async def record_failure_log(
        self,
        worker_name: str,
        task_id: Optional[str],
        error_message: str,
        traceback_text: Optional[str] = None,
    ) -> None:
        """Persist a worker failure event for auditing."""
        try:
            async with get_async_session() as session:
                log = WorkerFailureLog(
                    worker_name=worker_name,
                    task_id=task_id,
                    error_message=error_message,
                    traceback=traceback_text,
                )
                session.add(log)
                logger.info(
                    "Recorded failure log for worker %s task %s",
                    worker_name,
                    task_id,
                )
        except SQLAlchemyError as exc:
            logger.error("Database error inserting worker failure log: %s", exc)
        except Exception as exc:
            logger.error("Failed to record worker failure log: %s", exc)

    async def list_workers(self) -> List[Dict[str, Any]]:
        """Return all workers with their latest health metadata."""
        try:
            async with get_async_session() as session:
                rows = (await session.execute(select(WorkerStatus))).scalars().all()
                return [self._serialize_worker(row) for row in rows]
        except SQLAlchemyError as exc:
            logger.error("Database error listing workers: %s", exc)
        except Exception as exc:
            logger.error("Failed to list workers: %s", exc)
        return []

    async def list_available_workers(
        self, exclude_worker: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return only workers currently marked as available."""
        try:
            async with get_async_session() as session:
                query = select(WorkerStatus).where(WorkerStatus.is_available.is_(True))
                if exclude_worker:
                    query = query.where(WorkerStatus.worker_name != exclude_worker)
                rows = (await session.execute(query)).scalars().all()
                return [self._serialize_worker(row) for row in rows]
        except SQLAlchemyError as exc:
            logger.error("Database error fetching available workers: %s", exc)
        except Exception as exc:
            logger.error("Failed to fetch available workers: %s", exc)
        return []

    async def count_available_workers(
        self, exclude_worker: Optional[str] = None
    ) -> int:
        """Return the number of available workers (optionally excluding the current one)."""
        try:
            async with get_async_session() as session:
                query = select(WorkerStatus).where(WorkerStatus.is_available.is_(True))
                if exclude_worker:
                    query = query.where(WorkerStatus.worker_name != exclude_worker)
                rows = (await session.execute(query)).scalars().all()
                return len(rows)
        except SQLAlchemyError as exc:
            logger.error("Database error counting available workers: %s", exc)
        except Exception as exc:
            logger.error("Failed to count available workers: %s", exc)
        return 0

    async def list_failure_logs(
        self, worker_name: Optional[str] = None, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Return worker failure logs, optionally filtered by worker_name."""
        try:
            async with get_async_session() as session:
                query = select(WorkerFailureLog)
                if worker_name:
                    query = query.where(WorkerFailureLog.worker_name == worker_name)
                query = query.order_by(WorkerFailureLog.created_at.desc())
                if limit:
                    query = query.limit(limit)
                rows = (await session.execute(query)).scalars().all()
                return [self._serialize_failure_log(row) for row in rows]
        except SQLAlchemyError as exc:
            logger.error("Database error listing failure logs: %s", exc)
        except Exception as exc:
            logger.error("Failed to list failure logs: %s", exc)
        return []

    async def delete_worker(self, worker_name: str) -> bool:
        """Remove a worker from the WorkerStatus table."""
        try:
            async with get_async_session() as session:
                result = await session.execute(
                    select(WorkerStatus).where(WorkerStatus.worker_name == worker_name)
                )
                record = result.scalar_one_or_none()
                if record:
                    await session.delete(record)
                    logger.info("Deleted worker status for %s", worker_name)
                    return True
                logger.warning("Worker %s not found for deletion", worker_name)
                return False
        except SQLAlchemyError as exc:
            logger.error("Database error deleting worker %s: %s", worker_name, exc)
        except Exception as exc:
            logger.error("Failed to delete worker %s: %s", worker_name, exc)
        return False

    @staticmethod
    def _serialize_worker(record: WorkerStatus) -> Dict[str, Any]:
        return {
            "worker_name": record.worker_name,
            "hostname": record.hostname,
            "is_available": record.is_available,
            "last_heartbeat": int(record.last_heartbeat.timestamp())
            if record.last_heartbeat
            else None,
            "last_failure_at": int(record.last_failure_at.timestamp())
            if record.last_failure_at
            else None,
            "last_failure_reason": record.last_failure_reason,
            "last_failure_task_id": record.last_failure_task_id,
            "failure_count": record.failure_count,
            "extra": record.extra,
            "updated_at": int(record.updated_at.timestamp())
            if record.updated_at
            else None,
        }

    @staticmethod
    def _serialize_failure_log(record: WorkerFailureLog) -> Dict[str, Any]:
        return {
            "id": record.id,
            "worker_name": record.worker_name,
            "task_id": record.task_id,
            "error_message": record.error_message,
            "traceback": record.traceback,
            "created_at": int(record.created_at.timestamp())
            if record.created_at
            else None,
        }


_worker_status_repository: Optional[WorkerStatusRepository] = None


def get_worker_status_repository() -> WorkerStatusRepository:
    """Return a singleton instance of the WorkerStatusRepository."""
    global _worker_status_repository
    if _worker_status_repository is None:
        _worker_status_repository = WorkerStatusRepository()
    return _worker_status_repository
