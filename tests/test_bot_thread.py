import queue
import threading
import time

from bot.thread import BotThread
from models import BotMessage


def tarea_exitosa(msg_queue: queue.Queue, stop_event: threading.Event):
    msg_queue.put(BotMessage(tipo="progreso_empresa", datos={"empresa": "Test SA"}))
    msg_queue.put(BotMessage(tipo="fin", datos={"total": 1}))


def tarea_con_error(msg_queue: queue.Queue, stop_event: threading.Event):
    raise ValueError("algo salió mal")


def tarea_con_stop(msg_queue: queue.Queue, stop_event: threading.Event):
    for i in range(100):
        if stop_event.is_set():
            return
        time.sleep(0.01)


def test_bot_thread_envia_mensajes():
    q = queue.Queue()
    stop = threading.Event()
    t = BotThread(fn=tarea_exitosa, msg_queue=q, stop_event=stop)
    t.start()
    t.join(timeout=5)
    mensajes = []
    while not q.empty():
        mensajes.append(q.get())
    tipos = [m.tipo for m in mensajes]
    assert "progreso_empresa" in tipos
    assert "fin" in tipos


def test_bot_thread_captura_excepcion():
    q = queue.Queue()
    stop = threading.Event()
    t = BotThread(fn=tarea_con_error, msg_queue=q, stop_event=stop)
    t.start()
    t.join(timeout=5)
    assert t.exception is not None
    assert "algo salió mal" in str(t.exception)
    msg = q.get_nowait()
    assert msg.tipo == "error_fatal"


def test_bot_thread_respeta_stop_event():
    q = queue.Queue()
    stop = threading.Event()
    t = BotThread(fn=tarea_con_stop, msg_queue=q, stop_event=stop)
    t.start()
    time.sleep(0.05)
    stop.set()
    t.join(timeout=3)
    assert not t.is_alive()
