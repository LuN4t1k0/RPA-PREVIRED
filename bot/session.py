import queue
import threading
from typing import Callable

from models import BotMessage


class PlaywrightSession(threading.Thread):
    """
    Hilo persistente que posee todos los objetos Playwright.
    Toda operación de browser debe ejecutarse aquí (mismo hilo = mismo greenlet).
    """

    def __init__(self):
        super().__init__(daemon=True)
        self._tasks: queue.Queue = queue.Queue()
        self.msg_queue: queue.Queue = queue.Queue()
        self.pw = None
        self.browser = None
        self.page = None

    def submit(self, fn: Callable) -> None:
        """Encola fn(session) para ejecutarse en el hilo Playwright."""
        self._tasks.put(fn)

    def drain(self) -> None:
        """Descarta mensajes pendientes antes de iniciar una nueva tarea."""
        while not self.msg_queue.empty():
            try:
                self.msg_queue.get_nowait()
            except Exception:
                break

    def stop(self) -> None:
        self._tasks.put(None)

    def run(self) -> None:
        while True:
            fn = self._tasks.get()
            if fn is None:
                for obj, method in [(self.browser, "close"), (self.pw, "stop")]:
                    if obj:
                        try:
                            getattr(obj, method)()
                        except Exception:
                            pass
                break
            try:
                fn(self)
            except Exception as e:
                self.msg_queue.put(BotMessage(tipo="error_fatal", datos={"msg": str(e)}))
