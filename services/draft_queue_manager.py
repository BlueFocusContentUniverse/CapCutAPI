"""
按 draft_id 分组的协程队列管理器
用于解决单进程/单 worker 环境下的并发竞态问题

核心思想：
- 为每个 draft_id 维护一个独立的协程队列
- 同一 draft_id 的请求串行处理，避免竞态条件
- 不同 draft_id 的请求可以并行处理
"""

import asyncio
import logging
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# 配置常量
QUEUE_CLEANUP_INTERVAL = 300  # 5分钟清理一次空闲队列
QUEUE_IDLE_TIMEOUT = 300  # 队列空闲5分钟后自动清理
REQUEST_TIMEOUT = 30  # 单个请求超时时间（秒）


class DraftQueueManager:
    """
    按 draft_id 分组的协程队列管理器
    
    每个 draft_id 有独立的队列和处理协程，确保同一 draft_id 的请求串行处理
    """
    
    def __init__(self):
        # draft_id -> (queue, task, last_used_time)
        self._queues: Dict[str, Tuple[asyncio.Queue, Optional[asyncio.Task], float]] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown = False
    
    async def _ensure_queue(self, draft_id: str) -> asyncio.Queue:
        """确保 draft_id 的队列存在，如果不存在则创建"""
        async with self._lock:
            if draft_id not in self._queues:
                queue = asyncio.Queue()
                task = asyncio.create_task(self._process_queue(draft_id, queue))
                self._queues[draft_id] = (queue, task, asyncio.get_event_loop().time())
                logger.info(f"[队列] 为 draft_id={draft_id} 创建新队列，队列处理协程已启动")
            else:
                # 更新最后使用时间
                queue, task, _ = self._queues[draft_id]
                self._queues[draft_id] = (queue, task, asyncio.get_event_loop().time())
                logger.debug(f"[队列] 使用现有队列 draft_id={draft_id}, 队列大小={queue.qsize()}")
            return queue
    
    async def _process_queue(
        self, draft_id: str, queue: asyncio.Queue
    ):
        """
        处理队列中的请求（串行执行）
        
        这个协程会持续运行，从队列中取出请求并处理
        """
        logger.info(f"[队列] 开始处理 draft_id={draft_id} 的队列")
        
        while not self._shutdown:
            try:
                # 从队列中获取请求，设置超时避免永久阻塞
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=QUEUE_IDLE_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    # 队列空闲超时，检查是否需要清理
                    if queue.empty():
                        logger.debug(
                            f"队列 draft_id={draft_id} 空闲超时，准备清理"
                        )
                        async with self._lock:
                            if draft_id in self._queues:
                                queue_check, task_check, _ = self._queues[draft_id]
                                if queue_check is queue and queue.empty():
                                    # 清理空闲队列
                                    if task_check:
                                        task_check.cancel()
                                    del self._queues[draft_id]
                                    logger.debug(
                                        f"已清理空闲队列 draft_id={draft_id}"
                                    )
                                    break
                    continue
                
                future, func, args, kwargs = item
                
                logger.info(f"[队列] 开始处理请求 draft_id={draft_id}, 队列剩余={queue.qsize()}")
                
                # 处理请求（带超时保护）
                try:
                    result = await asyncio.wait_for(
                        func(*args, **kwargs), timeout=REQUEST_TIMEOUT
                    )
                    if not future.done():
                        future.set_result(result)
                        logger.info(f"[队列] 请求处理完成 draft_id={draft_id}")
                except asyncio.TimeoutError:
                    error_msg = f"请求处理超时（>{REQUEST_TIMEOUT}秒）: draft_id={draft_id}"
                    logger.error(error_msg)
                    if not future.done():
                        future.set_exception(TimeoutError(error_msg))
                except Exception as e:
                    logger.error(
                        f"处理请求时出错 draft_id={draft_id}: {e}", exc_info=True
                    )
                    if not future.done():
                        future.set_exception(e)
                
                # 标记任务完成
                queue.task_done()
                
            except asyncio.CancelledError:
                logger.debug(f"队列处理协程被取消: draft_id={draft_id}")
                break
            except Exception as e:
                logger.error(
                    f"队列处理协程异常: draft_id={draft_id}, error={e}",
                    exc_info=True,
                )
                # 发生异常时，等待一小段时间后继续
                await asyncio.sleep(0.1)
        
        logger.debug(f"停止处理 draft_id={draft_id} 的队列")
    
    async def enqueue(
        self,
        draft_id: str,
        func: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        将请求加入队列并等待处理完成
        
        Args:
            draft_id: 草稿ID
            func: 要执行的异步函数
            *args, **kwargs: 传递给函数的参数
        
        Returns:
            函数执行的结果
        """
        # 如果 draft_id 为 None，直接执行（不排队）
        if draft_id is None:
            return await func(*args, **kwargs)
        
        # 确保 kwargs 中包含 draft_id（如果 func 需要它）
        # 注意：enqueue 的 draft_id 参数和 kwargs 中的 draft_id 不会冲突
        # 因为 enqueue 的 draft_id 是 enqueue 自己的参数，kwargs 中的 draft_id 是传递给 func 的
        if 'draft_id' not in kwargs:
            kwargs['draft_id'] = draft_id
        
        # 确保队列存在
        queue = await self._ensure_queue(draft_id)
        
        # 创建 Future 用于返回结果
        future = asyncio.Future()
        
        # 将请求放入队列
        logger.info(f"[队列] 将请求加入队列 draft_id={draft_id}, 当前队列大小={queue.qsize()}")
        await queue.put((future, func, args, kwargs))
        logger.info(f"[队列] 请求已加入队列 draft_id={draft_id}, 队列大小={queue.qsize()}, 等待处理...")
        
        # 等待处理完成
        try:
            result = await future
            logger.info(f"[队列] 请求处理完成并返回结果 draft_id={draft_id}")
            return result
        except Exception as e:
            logger.error(f"[队列] 请求处理异常 draft_id={draft_id}: {e}", exc_info=True)
            raise
    
    async def _cleanup_idle_queues(self):
        """定期清理空闲队列"""
        while not self._shutdown:
            try:
                await asyncio.sleep(QUEUE_CLEANUP_INTERVAL)
                
                if self._shutdown:
                    break
                
                current_time = asyncio.get_event_loop().time()
                async with self._lock:
                    # 找出需要清理的队列
                    to_remove = []
                    for draft_id, (queue, task, last_used) in self._queues.items():
                        if (
                            current_time - last_used > QUEUE_IDLE_TIMEOUT
                            and queue.empty()
                        ):
                            to_remove.append(draft_id)
                    
                    # 清理空闲队列
                    for draft_id_to_remove in to_remove:
                        _, task_to_cancel, _ = self._queues[draft_id_to_remove]
                        if task_to_cancel:
                            task_to_cancel.cancel()
                        del self._queues[draft_id_to_remove]
                        logger.debug(f"清理空闲队列: draft_id={draft_id_to_remove}")
                    
                    if to_remove:
                        logger.info(f"清理了 {len(to_remove)} 个空闲队列")
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理空闲队列时出错: {e}", exc_info=True)
    
    async def start(self):
        """启动队列管理器（启动清理任务）"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_idle_queues())
            logger.info("队列管理器已启动")
    
    async def shutdown(self):
        """关闭队列管理器（清理所有队列）"""
        self._shutdown = True
        
        # 取消清理任务
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass  # 正常取消，无需处理
        
        # 取消所有队列处理任务
        async with self._lock:
            for _, (_, task, _) in self._queues.items():
                if task:
                    task.cancel()
            self._queues.clear()
        
        logger.info("队列管理器已关闭")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取队列统计信息"""
        async def _get_stats():
            async with self._lock:
                stats = {
                    "total_queues": len(self._queues),
                    "queues": {},
                }
                current_time = asyncio.get_event_loop().time()
                for draft_id, (queue, task, last_used) in self._queues.items():
                    stats["queues"][draft_id] = {
                        "queue_size": queue.qsize(),
                        "idle_seconds": current_time - last_used,
                        "task_running": task is not None and not task.done(),
                    }
                return stats
        
        # 注意：这个方法需要在事件循环中调用
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果事件循环正在运行，需要创建任务
                # 但这里简化处理，直接返回同步信息
                return {
                    "total_queues": len(self._queues),
                    "note": "详细统计需要在异步上下文中获取",
                }
            else:
                return loop.run_until_complete(_get_stats())
        except RuntimeError:
            return {
                "total_queues": len(self._queues),
                "note": "无法获取详细统计（无事件循环）",
            }


# 全局单例
_queue_manager: Optional[DraftQueueManager] = None


def get_queue_manager() -> DraftQueueManager:
    """获取全局队列管理器实例"""
    global _queue_manager
    if _queue_manager is None:
        _queue_manager = DraftQueueManager()
    return _queue_manager

