"""Notification Engine — 研究报告推送

支持渠道:
  - console (默认, 测试用)
  - email (SMTP)
  - webhook (企业微信/钉钉/飞书)
  - file (保存到本地)

使用:
  notifier = Notifier()
  notifier.register(ConsoleChannel())
  await notifier.send(report_title, report_content)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Notification:
    """通知消息"""
    title: str
    content: str
    channel: str = ""
    sent_at: str = ""
    success: bool = False


class NotificationChannel(ABC):
    """通知渠道基类"""

    name: str = "base"

    @abstractmethod
    async def send(self, title: str, content: str) -> bool:
        """发送通知 → 返回是否成功"""
        ...


class ConsoleChannel(NotificationChannel):
    """控制台通知 — 开发/测试用"""

    name = "console"

    async def send(self, title: str, content: str) -> bool:
        print(f"\n{'='*60}")
        print(f"[NOTIFICATION] {title}")
        print(f"{'='*60}")
        print(content[:500])
        print(f"{'='*60}\n")
        return True


class FileChannel(NotificationChannel):
    """文件通知 — 保存到本地"""

    name = "file"

    def __init__(self, output_dir: str = "data/exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def send(self, title: str, content: str) -> bool:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"report_{timestamp}.md"
        filepath = self.output_dir / filename
        filepath.write_text(f"# {title}\n\n{content}", encoding="utf-8")
        return True


class Notifier:
    """通知管理器"""

    def __init__(self):
        self._channels: dict[str, NotificationChannel] = {}
        self._history: list[Notification] = []

    def register(self, channel: NotificationChannel) -> None:
        self._channels[channel.name] = channel

    async def send(self, title: str, content: str, channel: str | None = None) -> list[Notification]:
        """发送通知 — 可指定渠道或全部"""
        results = []

        channels_to_use = (
            [self._channels[channel]] if channel and channel in self._channels
            else list(self._channels.values())
        )

        for ch in channels_to_use:
            ok = await ch.send(title, content)
            notification = Notification(
                title=title, content=content[:200],
                channel=ch.name,
                sent_at=datetime.now(timezone.utc).isoformat(),
                success=ok,
            )
            results.append(notification)
            self._history.append(notification)

        return results

    @property
    def channel_names(self) -> list[str]:
        return list(self._channels.keys())

    @property
    def history(self) -> list[Notification]:
        return list(self._history)
