# Synergia Client

CLI `synergia` (paquete PyPI `synergia`, v0.1.5) para la plataforma de computación distribuida Synergia. Hace de **publisher** (crea/gestiona tareas) y de **worker** (ejecuta chunks de tareas ajenas dentro de un contenedor Docker aislado y sube resultados).
Stack: Python (argparse, requests, websockets, rich, psutil, GPUtil), Docker, `perf`, C (wrappers curl/wget). Servidor: `/home/yago/repos/synergia-server` (REST :8000, WS :8001).
Mapa detallado por archivo: `CODEBASE_MAP.md`. Si el README contradice al código, manda el código.

## Estructura
- `client/client.py` — CLI: un handler por subcomando, todo registrado en `main()` (argparse, `set_defaults(func=...)`).
- `client/config.py` — carga sesión, dispositivo y `config.ini` **al importar**. `client/scheduler.py` — `start-scheduler`.
- `worker/worker.py` — lógica de suscripción, ejecución, confirmación y subida. `worker/docker_util.py` — todo lo que toca Docker.
- `worker/Dockerfile` + `worker/container/` — imagen `task-worker:latest`: `iptables.sh`, `hash_util.py`, `upload_results.py`, wrappers `curl`/`wget` en C.
- `worker/utils/` — `configuration_interpreter.py` y `github_util.py` (copias del servidor), `logger.py` (Rich).
- `tests/` — scripts bash de integración manual (no hay pytest). `synergia.egg-info/` — generado, pero versionado.

## Comandos (no hay Makefile, lint, CI ni tests unitarios)
```
pip install -e .                  # instala el comando `synergia`
synergia --help                   # o: python -m client.client
synergia login-user --username U --passwd P
bash tests/test.sh                # flujo de consenso manual contra un servidor real (ver Delicados)
cd tests && bash create_tasks.sh  # crea tareas de tests/tasks.txt (usa bc; debe ejecutarse desde tests/)
```
- Requisitos: Docker en el PATH, `perf` con `kernel.perf_event_paranoid <= 2`, servidor accesible. GPU opcional (`nvidia-smi`).
- La imagen `task-worker:latest` se construye sola (`docker build --no-cache` sobre `worker/`) la primera vez.
- Empaquetado: `pyproject.toml` (setuptools) + `MANIFEST.in`; entry point `synergia = client.client:main`. TODO: confirmar comando de publicación en PyPI.

## Estado local del usuario (fuera del repo)
- `~/.cn_profile.json` (token, username, email) y `~/.cn_device.json` (cpu_threads, gpu_device, ram).
- `~/.config/synergia/config.ini` — URLs del servidor; se copia de `client/config.ini.example` al primer import y se monta **solo lectura** en el contenedor como `/scripts/config.ini`.

## Convenciones
- **HTTP**: `requests` contra el servidor; JWT en el header **`token`** (`config.TOKEN`). WS: `/ws/task/{id}?token=&n_consumes=`.
- **Errores/salida**: `except requests.exceptions.ConnectionError: fail(...)`; `fail(msg, True)` termina el proceso. Siempre `worker/utils/logger.py` (`section, ok, fail, warn, info, debug`; `debug` solo se ve con `SYNERGIA_VERBOSE=1`), nunca `print` nuevo. Tablas con Rich y colores hardcodeados.
- **Subcomandos de estado**: `pause/active/cancel/close-task` son `partial(change_status, status=...)`.
- **Estilo**: comentarios y mensajes en español. Commits `[ADD]/[MOD]/[FIX]/[BUMP] - …`. Ramas: `develop` + `feature/*`.
- **Contenedor por tarea**: nombre `worker_<sha256(task_id)[:8]>`, persistente entre ejecuciones (caché). El publisher usa uno temporal `client-task` que borra al terminar.
- **Usuarios dentro del contenedor**: `worker` (sin privilegios) ejecuta el código de la tarea; `net_user` solo para red (`network=True`, p. ej. `git clone`); `root` para apt, iptables, `hash_util` y la subida. API: `run_in_docker(command, name, stats, root, output, stdin, gpu, network)`.
- **Contrato del repo de una tarea**: `config.toml` (lo parsea `configuration_interpreter`; formato en `synergia-server/docs/CONFIG_REFERENCE.md`) + `Makefile` con targets `setup`, `run`, `clean`. `make run` recibe `START= END=` (rangos), `WORDS=` (`file_single`) o `WORD=` (dinámica). Salida: `outputs.mode = file` (`outputs.dir/filename_pattern`) o `stdout`.

## Flujo (lo que no se ve en un solo archivo)
- **Crear tarea**: `get_hash_by_github_url` (client.py) levanta `client-task`, clona, instala `requirements.packages`, aplica `[download]`, calcula hash antes de `make setup`, ejecuta `make setup` + `make clean` y calcula hash después. `repo_hash = sha256(pre + post)`; se envía con el commit a `POST /task`.
- **Worker**: `init_environment` (worker.py) repite ese cálculo y compara con `repo_snapshot_hash` del servidor; si no coincide con caché, recrea el contenedor sin caché. El servidor devuelve 409 si el hash enviado en `create_process` no coincide.
- **Ejecución**: pide chunks por WS (`next`, `n` adaptativo para ~60 s de trabajo), `POST /task/{id}/process`, `make run` bajo `perf stat` (ciclos CPU; RAM media muestreada; VRAM/TDP con `nvidia-smi`), y sube vía `/scripts/upload_results.py` (modo `file`: `tar` + `gzip -n`).
- **Verificación**: al recibir `verification_required` por WS, `confirm()` hace checkout del commit del proceso, comprueba hash, crea execution, re-ejecuta y sube; después envía `confirmation_done`.
- **Aislamiento de red**: `iptables.sh` descarta la salida salvo loopback, DNS, `root`, `net_user`, uid 42 y `network.allowed_hosts` de la tarea. Las reglas se pierden al reiniciar el contenedor y `init_environment` las reaplica.
- **Descargas externas**: los wrappers `curl`/`wget` (setuid `net_user`) anotan el sha256 de lo descargado en `external_deps.log`, que entra en el hash.
- **OAuth**: `_oauth_login` abre el navegador y levanta un `HTTPServer` en `127.0.0.1:8080`; debe coincidir con `redirect_uri_*` de `synergia-server/src/config.json`.
- **Scheduler**: `round-robin` (`--rotation` chunks por tarea) o `split` (reparte CPUs mutando `config.CPU_THREADS`); `--on-idle` limita CPUs con `docker update`.

## Dónde NO tocar
- `worker/utils/configuration_interpreter.py` y `github_util.py` son **copias** de `synergia-server/src/utils/` (diferencias actuales: import relativo, `case None`, un `print`). Cualquier cambio debe replicarse en ambos.
- `worker/container/*` y `Dockerfile`: determinan el hash y el aislamiento. No cambiar flags de `tar --sort=name --mtime=… -n` ni `gzip -n` (cambian el hash del resultado y rompen el consenso).
- La lógica de hash está duplicada (`get_hash_by_github_url` y `init_environment`) y usa `hash_util.py`; un cambio en una sola parte invalida todas las tareas existentes.
- No editar `synergia.egg-info/` a mano.

## Puntos delicados
- **Python**: `pyproject` declara `>=3.10`, pero `client.py` usa f-strings con comillas anidadas (`f"{r.json().get("detail")}"`, PEP 701, solo ≥3.12). El README dice probado con 3.14. TODO: confirmar versión mínima.
- **`input()` interactivo**: tras un fallo, `run_in_docker` pregunta «¿Desea ejecutarlo como usuario privilegiado? [S/N]»; bloquea el scheduler y, si se acepta, ejecuta como root el comando de la tarea.
- **Token en argumentos**: el JWT va como argumento de `docker exec … upload_results.py` (visible en `ps` dentro de un contenedor donde corre código de terceros). TODO: confirmar riesgo real.
- **Estados en minúsculas**: `INACTIVE_STATUSES` (worker.py) está en minúsculas, pero `GET /task/{id}` devuelve mayúsculas; `get_continue_information` no detecta pausa/cancelación por REST (por WS sí). Además envía `fields=…`, que el servidor ignora. TODO: confirmar.
- **scheduler.py**: `BASE_URL = "http://127.0.0.1:8000"` fijo (ignora `config.ini`); el throttle hace `docker update … worker`, pero el contenedor se llama `worker_<hash>` → posiblemente sin efecto. TODO: confirmar.
- **Código roto/heredado**: `test()` usa `cfg.inputs.file_single.index_file` (sin llamar `cfg()`); `file_multi` llama a `GithubUtil.list_glob`, que no existe (igual que en el servidor).
- **Imagen y contenedor**: la imagen solo se construye si no existe; tras cambiar `Dockerfile` o `container/` hay que `docker rmi task-worker:latest`. Si el contenedor de la tarea ya corre, `start_docker` hace `exit()`. Se arranca siempre con `--cap-add=PERFMON,NET_ADMIN` y `--add-host=host.docker.internal` (comentado como «solo desarrollo»).
- **`perf`**: sin permisos los ciclos salen 0 y el servidor los sube a 1 (cobro casi nulo); revisar `perf_event_paranoid`.
- **`config.py` al importar**: URLs, token y dispositivo se leen una vez por proceso; `BASE_URL` se calcula en el import.
- **`tests/test.sh`**: usa usuarios con emails `@test.test` y contraseña fija; el servidor solo admite dominios de `ALLOWED_DOMAINS` y exige email verificado para el login, y el script pide editar un repo en GitHub a mitad. TODO: confirmar que sigue funcionando.
- **Dependencias duplicadas** en `pyproject.toml` y `requirements.txt` (fijadas, `setuptools` incluido): mantener sincronizadas.
- **README desactualizado**: lista `worker/container/config.ini` (eliminado; el real vive en `~/.config/synergia/`), menciona `synergia.yml` (el código usa `config.toml`) y el banner dice v1.0.0 frente a 0.1.5.
