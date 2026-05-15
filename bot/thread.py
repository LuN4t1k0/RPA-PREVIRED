import queue
import threading
from typing import Callable

from models import BotMessage


class BotThread(threading.Thread):
    def __init__(self, fn: Callable, msg_queue: queue.Queue, stop_event: threading.Event):
        super().__init__(daemon=True)
        self._fn = fn
        self.msg_queue = msg_queue
        self.stop_event = stop_event
        self.exception: Exception | None = None

    def run(self):
        try:
            self._fn(self.msg_queue, self.stop_event)
        except Exception as e:
            self.exception = e
            self.msg_queue.put(BotMessage(tipo="error_fatal", datos={"msg": str(e)}))
