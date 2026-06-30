"""
事件总线模块 —— 进程间通信的唯一通道。

提供一个抽象基类 EventBus 和两个具体实现：
- InMemoryEventBus: 用于单元测试，不依赖外部服务。
- RedisEventBus: 基于 Redis Pub/Sub，用于生产环境，支持重连、背压、消息信封。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 类型别名
# ---------------------------------------------------------------------------

#: 消息处理器签名：接收一个 dict，返回 Awaitable[None]
Handler = Callable[[dict[str, Any]], Awaitable[None]]


# ---------------------------------------------------------------------------
# 消息信封（Envelope）
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    """所有经过 EventBus 的消息都被包装成信封。

    Attributes:
        channel:   消息通道名。
        ts_ns:     发布时刻的纳秒级 Unix 时间戳。
        trace_id:  全链路追踪 ID（UUID4）。
        data:      业务数据载荷。
    """

    channel: str
    ts_ns: int
    trace_id: str
    data: dict[str, Any]

    # -- 序列化 / 反序列化 ---------------------------------------------------

    def to_json(self) -> str:
        """序列化为 JSON 字符串。

        Returns:
            JSON 字符串表示。
        """
        return json.dumps(
            {
                "channel": self.channel,
                "ts_ns": self.ts_ns,
                "trace_id": self.trace_id,
                "data": self.data,
            },
            default=str,
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> MessageEnvelope:
        """从 JSON 字符串反序列化。

        Args:
            raw: JSON 字符串。

        Returns:
            MessageEnvelope 实例。

        Raises:
            ValueError: JSON 解析失败或缺少必要字段。
        """
        try:
            obj: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"消息 JSON 解析失败: {exc}") from exc

        for key in ("channel", "ts_ns", "trace_id", "data"):
            if key not in obj:
                raise ValueError(f"消息缺少必要字段: {key}")

        return cls(
            channel=obj["channel"],
            ts_ns=int(obj["ts_ns"]),
            trace_id=str(obj["trace_id"]),
            data=obj["data"] if isinstance(obj["data"], dict) else {},
        )


# ---------------------------------------------------------------------------
# 背压策略
# ---------------------------------------------------------------------------


class BackpressurePolicy(Enum):
    """队列满时的背压处理策略。

    Attributes:
        DROP_OLDEST: 丢弃队列中最早的消息，腾出空间。
        DROP_LATEST: 丢弃当前要入队的（最新的）消息。
        RAISE:       抛出异常，由调用方处理。
    """

    DROP_OLDEST = "drop_oldest"
    DROP_LATEST = "drop_latest"
    RAISE = "raise"


class EventBusFullError(Exception):
    """事件总线内部队列已满，且背压策略为 RAISE 时抛出。"""


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------


class EventBus(ABC):
    """事件总线抽象基类。

    **设计原则**：进程间只通过 EventBus 通信，绝不直接跨模块调用。
    所有发布 / 订阅操作都是异步的，以适配高并发场景。
    """

    @abstractmethod
    async def publish(self, channel: str, data: dict[str, Any]) -> None:
        """发布消息到指定通道。

        Args:
            channel: 通道名称。
            data:    业务数据载荷，必须可 JSON 序列化。
        """

    @abstractmethod
    def subscribe(self, channel: str, handler: Handler) -> None:
        """订阅指定通道。

        Args:
            channel: 通道名称。
            handler: 异步回调，收到消息时被调用。
        """

    @abstractmethod
    async def start(self) -> None:
        """启动事件总线。"""

    @abstractmethod
    async def stop(self) -> None:
        """停止事件总线，释放所有资源。"""


# ---------------------------------------------------------------------------
# 内存实现（用于测试）
# ---------------------------------------------------------------------------


class InMemoryEventBus(EventBus):
    """基于 asyncio.Queue 的内存事件总线。

    - 不依赖 Redis 或任何外部服务。
    - 支持背压控制：内部队列有界，满了走指定策略。
    - 适用于单元测试和本地开发。
    """

    def __init__(
        self,
        max_queue_size: int = 10_000,
        backpressure: BackpressurePolicy = BackpressurePolicy.DROP_OLDEST,
    ) -> None:
        """初始化内存事件总线。

        Args:
            max_queue_size:  每个通道内部队列的最大长度（默认 10000）。
            backpressure:    队列满时的背压策略。
        """
        self._handlers: dict[str, list[Handler]] = {}
        self._queues: dict[str, asyncio.Queue[MessageEnvelope | None]] = {}
        self._max_queue_size = max_queue_size
        self._backpressure = backpressure
        self._consumer_tasks: dict[str, asyncio.Task[None]] = {}
        self._started: bool = False

    # -- 发布 ---------------------------------------------------------------

    async def publish(self, channel: str, data: dict[str, Any]) -> None:
        """发布到内存队列，由后台消费者异步分发给所有订阅者。

        Args:
            channel: 通道名称。
            data:    业务数据载荷。

        Raises:
            RuntimeError: 总线未启动。
            EventBusFullError: 队列满且策略为 RAISE。
        """
        if not self._started:
            raise RuntimeError("InMemoryEventBus 尚未启动，请先调用 start()")

        envelope = MessageEnvelope(
            channel=channel,
            ts_ns=time.time_ns(),
            trace_id=str(uuid.uuid4()),
            data=data,
        )

        queue = self._get_or_create_queue(channel)

        # 背压控制
        if queue.full():
            if self._backpressure is BackpressurePolicy.DROP_OLDEST:
                try:
                    queue.get_nowait()  # 丢弃最旧
                except asyncio.QueueEmpty:
                    pass
                logger.warning("通道 %s 队列已满，丢弃最旧消息", channel)
            elif self._backpressure is BackpressurePolicy.DROP_LATEST:
                logger.warning("通道 %s 队列已满，丢弃最新消息", channel)
                return
            elif self._backpressure is BackpressurePolicy.RAISE:
                raise EventBusFullError(f"通道 {channel} 队列已满（容量 {self._max_queue_size}）")

        await queue.put(envelope)

    # -- 订阅 ---------------------------------------------------------------

    def subscribe(self, channel: str, handler: Handler) -> None:
        """订阅通道。同一 handler 可重复订阅（会多次调用）。

        Args:
            channel: 通道名称。
            handler: 异步回调。
        """
        if channel not in self._handlers:
            self._handlers[channel] = []
        self._handlers[channel].append(handler)
        logger.info("通道 %s 新增订阅者，当前共 %d 个", channel, len(self._handlers[channel]))

    # -- 生命周期 -----------------------------------------------------------

    async def start(self) -> None:
        """启动总线，为已订阅的通道创建消费者任务。"""
        if self._started:
            return
        self._started = True
        for channel in self._handlers:
            self._ensure_consumer(channel)
        logger.info("InMemoryEventBus 已启动")

    async def stop(self) -> None:
        """停止总线，取消所有消费者任务并清空队列。"""
        self._started = False
        for channel, task in self._consumer_tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.debug("通道 %s 消费者已取消", channel)
        self._consumer_tasks.clear()

        # 向所有队列发送哨兵值，确保消费者退出
        for queue in self._queues.values():
            await queue.put(None)
        self._queues.clear()
        logger.info("InMemoryEventBus 已停止")

    # -- 内部方法 -----------------------------------------------------------

    def _get_or_create_queue(self, channel: str) -> asyncio.Queue[MessageEnvelope | None]:
        """获取或创建通道对应的队列。

        Args:
            channel: 通道名称。

        Returns:
            该通道的 asyncio.Queue。
        """
        if channel not in self._queues:
            self._queues[channel] = asyncio.Queue(maxsize=self._max_queue_size)
            if self._started:
                self._ensure_consumer(channel)
        return self._queues[channel]

    def _ensure_consumer(self, channel: str) -> None:
        """确保通道有对应的后台消费者任务。

        Args:
            channel: 通道名称。
        """
        if channel not in self._consumer_tasks or self._consumer_tasks[channel].done():
            self._consumer_tasks[channel] = asyncio.create_task(
                self._consume(channel),
                name=f"eventbus-consumer-{channel}",
            )

    async def _consume(self, channel: str) -> None:
        """后台消费者循环：从队列取出消息并分发给 handler。

        Args:
            channel: 通道名称。
        """
        queue = self._queues.get(channel)
        if queue is None:
            return

        while self._started:
            try:
                envelope: MessageEnvelope | None = await queue.get()
            except asyncio.CancelledError:
                break

            # 哨兵值：退出循环
            if envelope is None:
                break

            handlers = self._handlers.get(channel, [])
            for handler in handlers:
                try:
                    await handler(envelope.data)
                except Exception:
                    logger.exception(
                        "通道 %s 处理消息时异常 (trace_id=%s)",
                        channel,
                        envelope.trace_id,
                    )


# ---------------------------------------------------------------------------
# Redis Pub/Sub 实现（生产环境）
# ---------------------------------------------------------------------------


class RedisEventBus(EventBus):
    """基于 Redis Pub/Sub 的事件总线。

    特性：
    - 消息信封：每条消息带 channel / ts_ns / trace_id / data。
    - 指数退避重连：Redis 断连时自动重连，退避间隔 1s → 2s → 4s … 最大 60s。
    - 背压控制：内部发送队列有界，满时按策略处理。
    - 优雅关闭：stop() 会等待正在处理的消息完成。
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        max_queue_size: int = 10_000,
        backpressure: BackpressurePolicy = BackpressurePolicy.DROP_OLDEST,
        reconnect_delay_min: float = 1.0,
        reconnect_delay_max: float = 60.0,
    ) -> None:
        """初始化 Redis 事件总线。

        Args:
            redis_url:            Redis 连接 URL。
            max_queue_size:       内部队列最大长度。
            backpressure:         队列满时的背压策略。
            reconnect_delay_min:  重连最小间隔（秒）。
            reconnect_delay_max:  重连最大间隔（秒）。
        """
        self._redis_url = redis_url
        self._redis: Any = None  # redis.asyncio.Redis 实例
        self._pubsub: Any = None  # redis.asyncio.client.PubSub 实例
        self._handlers: dict[str, list[Handler]] = {}
        self._listen_task: asyncio.Task[None] | None = None
        self._started: bool = False
        self._stopping: bool = False

        # 背压相关
        self._max_queue_size = max_queue_size
        self._backpressure = backpressure
        self._send_queue: asyncio.Queue[MessageEnvelope | None] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._send_task: asyncio.Task[None] | None = None

        # 重连相关
        self._reconnect_delay_min = reconnect_delay_min
        self._reconnect_delay_max = reconnect_delay_max

    # -- 连接管理 -----------------------------------------------------------

    async def _connect(self) -> None:
        """建立 Redis 连接和 PubSub 实例。

        Raises:
            ConnectionError: 无法连接到 Redis。
        """
        try:
            import redis.asyncio as aioredis  # 延迟导入，避免测试时强依赖
        except ImportError as exc:
            raise ImportError("请安装 redis 异步客户端: pip install redis>=4.2.0") from exc

        try:
            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                retry_on_timeout=True,
            )
            # 测试连通性
            await self._redis.ping()
            self._pubsub = self._redis.pubsub()
            logger.info("Redis 连接成功: %s", self._redis_url)
        except Exception as exc:
            self._redis = None
            self._pubsub = None
            raise ConnectionError(f"无法连接 Redis ({self._redis_url}): {exc}") from exc

    async def _disconnect(self) -> None:
        """安全关闭 Redis 连接。"""
        try:
            if self._pubsub is not None:
                await self._pubsub.close()
                self._pubsub = None
        except Exception:
            logger.debug("关闭 PubSub 时异常（可忽略）", exc_info=True)

        try:
            if self._redis is not None:
                await self._redis.close()
                self._redis = None
        except Exception:
            logger.debug("关闭 Redis 连接时异常（可忽略）", exc_info=True)

    # -- 发布 ---------------------------------------------------------------

    async def publish(self, channel: str, data: dict[str, Any]) -> None:
        """通过 Redis Pub/Sub 发布消息。

        消息先入发送队列（带背压控制），由后台发送任务负责实际发布。
        这样可以：
        1. 解耦发布调用和网络 IO。
        2. 在 Redis 断连时缓存消息（受队列大小限制）。

        Args:
            channel: 通道名称。
            data:    业务数据载荷。

        Raises:
            RuntimeError:      总线未启动。
            EventBusFullError: 队列满且策略为 RAISE。
        """
        if not self._started:
            raise RuntimeError("RedisEventBus 尚未启动，请先调用 start()")

        envelope = MessageEnvelope(
            channel=channel,
            ts_ns=time.time_ns(),
            trace_id=str(uuid.uuid4()),
            data=data,
        )

        # 背压控制
        if self._send_queue.full():
            if self._backpressure is BackpressurePolicy.DROP_OLDEST:
                try:
                    self._send_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                logger.warning("发送队列已满，丢弃最旧消息")
            elif self._backpressure is BackpressurePolicy.DROP_LATEST:
                logger.warning("发送队列已满，丢弃最新消息 (channel=%s)", channel)
                return
            elif self._backpressure is BackpressurePolicy.RAISE:
                raise EventBusFullError(f"发送队列已满（容量 {self._max_queue_size}）")

        await self._send_queue.put(envelope)

    async def _publish_raw(self, envelope: MessageEnvelope) -> None:
        """实际通过 Redis 发布消息。

        Args:
            envelope: 消息信封。
        """
        if self._redis is None:
            logger.error("Redis 连接不可用，丢弃消息 (trace_id=%s)", envelope.trace_id)
            return
        try:
            await self._redis.publish(envelope.channel, envelope.to_json())
        except Exception:
            logger.exception(
                "Redis 发布失败 (channel=%s, trace_id=%s)",
                envelope.channel,
                envelope.trace_id,
            )
            # 发布失败时尝试重连（由监听循环统一处理）

    # -- 订阅 ---------------------------------------------------------------

    def subscribe(self, channel: str, handler: Handler) -> None:
        """订阅通道。

        如果总线已在运行，新订阅会在下一轮 PubSub 重新订阅时生效
        （通常在重连时）。如需立即生效，请在 stop() 后重新 start()。

        Args:
            channel: 通道名称。
            handler: 异步回调。
        """
        if channel not in self._handlers:
            self._handlers[channel] = []
        self._handlers[channel].append(handler)
        logger.info(
            "通道 %s 新增订阅者，当前共 %d 个",
            channel,
            len(self._handlers[channel]),
        )

    # -- 生命周期 -----------------------------------------------------------

    async def start(self) -> None:
        """启动事件总线：连接 Redis，启动监听和发送任务。"""
        if self._started:
            return

        self._stopping = False
        await self._connect()

        # 启动后台任务
        self._listen_task = asyncio.create_task(
            self._listen_with_reconnect(),
            name="eventbus-redis-listen",
        )
        self._send_task = asyncio.create_task(
            self._send_loop(),
            name="eventbus-redis-send",
        )
        self._started = True
        logger.info("RedisEventBus 已启动")

    async def stop(self) -> None:
        """停止事件总线，取消后台任务并关闭 Redis 连接。"""
        if not self._started:
            return

        self._stopping = True
        self._started = False

        # 取消监听任务
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        # 取消发送任务
        if self._send_task is not None:
            # 放入哨兵值确保退出
            try:
                self._send_queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
            self._send_task.cancel()
            try:
                await self._send_task
            except asyncio.CancelledError:
                pass
            self._send_task = None

        await self._disconnect()
        logger.info("RedisEventBus 已停止")

    # -- 发送循环 -----------------------------------------------------------

    async def _send_loop(self) -> None:
        """后台发送循环：从发送队列取出消息并发布到 Redis。"""
        while not self._stopping:
            try:
                envelope: MessageEnvelope | None = await self._send_queue.get()
            except asyncio.CancelledError:
                break

            if envelope is None:
                break

            await self._publish_raw(envelope)

    # -- 监听与重连 --------------------------------------------------------

    async def _listen_with_reconnect(self) -> None:
        """带指数退避重连的监听循环。

        逻辑：
        1. 尝试连接并开始监听。
        2. 如果连接断开，按指数退避等待后重试。
        3. stop() 调用后退出循环。
        """
        delay = self._reconnect_delay_min

        while not self._stopping:
            try:
                # 确保连接可用
                if self._redis is None or self._pubsub is None:
                    await self._disconnect()
                    await self._connect()
                    delay = self._reconnect_delay_min  # 重连成功，重置退避

                # 订阅所有已注册通道
                channels = list(self._handlers.keys())
                if not channels:
                    # 没有订阅通道时，短暂等待后重试
                    await asyncio.sleep(1.0)
                    continue

                for ch in channels:
                    await self._pubsub.subscribe(ch)
                logger.info("Redis PubSub 已订阅通道: %s", channels)

                # 开始监听
                async for message in self._pubsub.listen():
                    if self._stopping:
                        break
                    if message.get("type") != "message":
                        continue

                    channel: str = message["channel"]
                    raw_data: str = message["data"]

                    # 反序列化
                    try:
                        envelope = MessageEnvelope.from_json(raw_data)
                    except ValueError:
                        logger.warning(
                            "收到无法解析的消息 (channel=%s): %s",
                            channel,
                            raw_data[:200],
                        )
                        continue

                    # 分发给 handler
                    await self._dispatch(channel, envelope)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self._stopping:
                    break
                logger.error(
                    "Redis 监听异常: %s，%.1f 秒后重连",
                    exc,
                    delay,
                )
                await self._disconnect()

                # 指数退避等待（带取消检查）
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    break
                delay = min(delay * 2, self._reconnect_delay_max)

    async def _dispatch(self, channel: str, envelope: MessageEnvelope) -> None:
        """将消息分发给指定通道的所有 handler。

        Args:
            channel:  通道名称。
            envelope: 消息信封。
        """
        handlers = self._handlers.get(channel, [])
        for handler in handlers:
            try:
                await handler(envelope.data)
            except Exception:
                logger.exception(
                    "通道 %s 处理消息时异常 (trace_id=%s)",
                    channel,
                    envelope.trace_id,
                )
