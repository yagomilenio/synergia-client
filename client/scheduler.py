import asyncio
import signal
import os
import subprocess
import psutil
import requests
import json
from collections import deque
from typing import List
from worker.worker import subscribe
from worker.utils.logger import section, ok, fail, warn, info, debug, container_started, commit_info, info_inline
from . import config

BASE_URL = "http://127.0.0.1:8000"


_IDLE_MARGIN = 10


def _get_subscribed_tasks() -> List[str]:
    if not config.TOKEN:
        warn("No has iniciado sesión. Usa 'login-user' primero.")
        return None
    try:
        r = requests.get(
            f"{BASE_URL}/task",
            headers={"token": config.TOKEN},
            params={"subscribed": "true"}
        )
        if r.status_code != 200:
            fail("Error obteniendo tareas:", r.text)
            return None
        tasks = r.json().get("result", [])
        return [t["task_id"] for t in tasks if t.get("status", "ACTIVE") == "ACTIVE"]
    except requests.exceptions.ConnectionError:
        fail("Error de conexión con el servidor.")
        return None


def _available_cpus() -> int:
    total = os.cpu_count() or 1
    if config.CPU_THREADS:
        total = int(config.CPU_THREADS)
    return max(1, total)


async def _cpu_throttle_controller(stop_event: asyncio.Event):
    total_cores = os.cpu_count() or 1
    samples = deque(maxlen=5)

    while not stop_event.is_set():
        sample = psutil.cpu_percent(interval=1)
        samples.append(sample)

        cpu_used = sum(samples) / len(samples)
        cpu_free_pct = max(0, 100 - cpu_used - _IDLE_MARGIN)
        cpus_for_worker = max(0.25, round((cpu_free_pct / 100) * total_cores, 2))

        subprocess.run(
            ["docker", "update", "--cpus", str(cpus_for_worker), "worker"],
            capture_output=True
        )
        info_inline(f"[Throttle] CPU media: {cpu_used:.1f}% → worker limitado a {cpus_for_worker} CPUs")

        await asyncio.sleep(4)



async def _run_round_robin(task_ids: List[str], stop_event: asyncio.Event, rotation: int):

    info(f"[Scheduler] Modo round-robin con {len(task_ids)} tarea(s): {task_ids}")

    idx = 0
    while not stop_event.is_set():
        task_id = task_ids[idx % len(task_ids)]
        idx += 1

        info(f"\n[Scheduler] Ejecutando tarea {task_id}  (slot {idx})")
        try:
            subscribe_task = asyncio.create_task(subscribe(task_id, cache=True, rotation=rotation, handle_signals=False))

            done, pending = await asyncio.wait(
                {subscribe_task, asyncio.create_task(stop_event.wait())},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

            if stop_event.is_set():
                break

        except Exception as e:
            fail(f"[Scheduler] Error en tarea {task_id}: {e}")

        if not stop_event.is_set() and len(task_ids) > 1:
            info(f"[Scheduler] Pasando a la siguiente tarea en 2 s…")
            await asyncio.sleep(2)

    info("[Scheduler] Round-robin detenido.")


async def _run_split(task_ids: List[str], total_cpus: int, stop_event: asyncio.Event):

    n = len(task_ids)
    base_cpus = total_cpus // n
    extra = total_cpus % n          #primeras tareas reciben 1 núcleo más

    assignments = []
    for i, task_id in enumerate(task_ids):
        cpus = base_cpus + (1 if i < extra else 0)
        assignments.append((task_id, max(1, cpus)))

    info(f"[Scheduler] Modo split — {total_cpus} CPU(s) entre {n} tarea(s):")
    for task_id, cpus in assignments:
        debug(f"           • {task_id}  →  {cpus} núcleo(s)")


    original_cpu_threads = config.CPU_THREADS

    async def _run_one(task_id: str, cpus: int):
        config.CPU_THREADS = cpus
        try:
            await subscribe(task_id, cache=True, handle_signals=False)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            fail(f"[Scheduler] Error en tarea {task_id}: {e}")

    tasks = [asyncio.create_task(_run_one(tid, cpus)) for tid, cpus in assignments]
    stop_watcher = asyncio.create_task(stop_event.wait())

    done, pending = await asyncio.wait(
        {*tasks, stop_watcher},
        return_when=asyncio.FIRST_COMPLETED,
    )


    for t in pending:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass

    config.CPU_THREADS = original_cpu_threads
    info("[Scheduler] Split detenido.")





async def _scheduler_main(mode: str, rotation: int, on_idle: bool):
    task_ids = _get_subscribed_tasks()

    if task_ids is None:
        return 

    if not task_ids:
        warn("No hay tareas activas a las que estés suscrito.")
        return

    stop_event = asyncio.Event()

    def _signal_handler():
        info("\n[Scheduler] Señal recibida, deteniendo…")
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT,  _signal_handler)
    loop.add_signal_handler(signal.SIGTERM, _signal_handler)

    throttle = None
    if on_idle:
        throttle = asyncio.create_task(_cpu_throttle_controller(stop_event))

    if mode == "round-robin":
        await _run_round_robin(task_ids, stop_event, rotation)
    elif mode == "split":
        total_cpus = _available_cpus()
        await _run_split(task_ids, total_cpus, stop_event)
    else:
        fail(f"Modo desconocido: {mode}. Usa 'round-robin' o 'split'.")

    if throttle:
        throttle.cancel()
        try:
            await throttle
        except asyncio.CancelledError:
            pass


def start_scheduler(args):

    info(f"[Scheduler] Iniciando en modo '{args.mode}'…  (Ctrl+C para parar)")
    asyncio.run(_scheduler_main(args.mode, args.rotation, args.on_idle))
