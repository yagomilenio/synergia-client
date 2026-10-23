# CODEBASE_MAP

Una línea por archivo/módulo relevante. Convenciones y trampas: ver `CLAUDE.md`. Rutas relativas a la raíz del repo.

## client/

- `client.py` — CLI (`main()` registra los subcomandos con argparse). Constantes `VALID_RESOURCES` (cpu 1, gpu 2, ram 3) y `VALID_METRICS` (`min_threads`, `min_freq_mhz`, `min_vram_mb`, `min_cuda_cc`, `min_ram_mb`). Handlers:
  - Sesión/cuenta: `save_session`, `clear_session` (`logout-user`), `login_user`, `sign_up_user`, `get_account_details`, `_oauth_login` + `login_google`/`login_github` (callback local en `127.0.0.1:8080`).
  - Dispositivo: `save_device_config`/`configure_device` (valida contra CPU, RAM y GPUs reales; guarda `~/.cn_device.json`).
  - Publisher: `create_task` (+ `get_hash_by_github_url`, `parse_requirements`), `add_inputs`, `sync_task`, `change_status` (pause/active/cancel/close), `get_outputs` (listado o zip `--download` en `./<task_id>/`), `task_info`, `process_info`.
  - Consulta: `find_task` (`--global-search`, `--name`, `--status`, `--subscribed`), `get_task`. `get_my_tasks` no está registrado como comando.
  - Worker: `subscribe_task` (muestra el Makefile y pide confirmación salvo `--yes`), `unsubscribe_task`, `confirm_process`, `test_task` (`--word` o `--range START END`).
  - `start-scheduler` → `scheduler.start_scheduler`.
- `config.py` — Al importar: lee `~/.cn_profile.json` y `~/.cn_device.json`, crea `~/.config/synergia/config.ini` si falta y lo parsea. Exporta `TOKEN`, `USERNAME`, `EMAIL`, `GPU_DEVICE`, `CPU_THREADS`, `RAM`, `REST_BASE_URL/PORT`, `WS_BASE_URL/PORT`, `SESSION_FILE`, `DEVICE_FILE`, `CONFIG_INI`.
- `scheduler.py` — `start_scheduler(args)` → `_scheduler_main` (carga tareas suscritas ACTIVE). `_run_round_robin(task_ids, stop_event, rotation)`, `_run_split(task_ids, total_cpus, stop_event)`, `_cpu_throttle_controller` (`--on-idle`), `_available_cpus`, `_get_subscribed_tasks`.
- `config.ini.example` — Plantilla de URLs `[rest]`/`[ws]` (`base_url`, `base_port`).

## worker/

- `worker.py` — Núcleo del worker:
  - `subscribe(task_id, cache, rotation, handle_signals)` → `subscribe_with_input` (WS: `next` → process/execution → `make run` → subida) o `subscribe_without_input` (tareas sin `[inputs]`, bucle `make run`).
  - `init_environment(task_id, cache, commit, show_run)` — prepara el contenedor, clona, instala paquetes, descargas, hash pre/post `make setup`, iptables; devuelve `(cfg, repo_hash, repo_commit)`.
  - `confirm(task_id, process_id, cache, …)` — re-ejecución de un proceso ajeno. `test` / `test_input` — prueba local de una tarea (rango / palabra).
  - REST: `create_process`, `create_execution`, `get_task`, `get_process`, `get_continue_information`, `getConfirmationProcessId`, `getProcessByIndex`.
  - Utilidades: `get_container_name`, `merge_consecutive_ranges`, `sanitize_command` (expande `~`, `$HOME`, `$USER`, `$UID` para el usuario del contenedor). Constantes `UPLOAD_INTERVAL = 60`, `INACTIVE_STATUSES`.
- `docker_util.py` — `start_docker` (construye la imagen si falta, crea/arranca el contenedor con `--cpuset-cpus`, `--memory`, `--gpus`, monta `config.ini` RO), `run_in_docker` (exec como `worker`/`net_user`/`root`; con `stats=True` mide ciclos con `perf stat`, RAM y VRAM/TDP), `end_docker`, `docker_exists`, `docker_is_running`, `build_image`, `_run_streaming`.
- `Dockerfile` — `python:3.12-slim` + `make git linux-perf iptables gcc …`; sustituye `curl`/`wget` por los wrappers compilados (setuid `net_user`); usuarios `worker`, `net_user`; `/repo`.

### worker/container/ (se copia a la imagen)
- `iptables.sh` — Política de salida: descarta todo salvo loopback, DNS, `root`, `net_user` y uid 42.
- `hash_util.py` — `hash_directory(path, excludes)` (sha256 de rutas relativas + contenido, ignora `.git`), `hash_external_deps(log_path)`; como script imprime el hash combinado.
- `upload_results.py` — Sube el resultado: `--stdin|--no-stdin <token> <task> <process> <execution> [fichero] <cpu_cycles> <ram_avg> [vram_avg tdp_w]`; lee `/scripts/config.ini`; `POST …/execution/{id}/result`.
- `curl_wrapper.c`, `wget_wrapper.c` — Ejecutan el binario real como `net_user` y registran el sha256 de las descargas en `/home/net_user/external_deps.log`.

### worker/utils/
- `configuration_interpreter.py` — Copia del parser de `config.toml` del servidor: `load_config(github_url)` → singleton `Config`, `cfg()`; `InputsConfig.active_items()/total()`, `OutputsConfig.resolve_filename`.
- `github_util.py` — `GithubUtil(url)`: `list_dir`, `read_file`, `get_commit`, `get_repo_link`, `get_branch` (copia del servidor).
- `logger.py` — Helpers Rich: `section`, `ok`, `fail(msg, exit)`, `warn`, `info`, `info_inline`, `run`, `muted`, `debug` (solo con `SYNERGIA_VERBOSE=1`), `container_started`, `commit_info`, `result_stats`, `summary`; paleta `THEME`.

## tests/
- `test.sh` — Escenario manual de consenso: 4 usuarios, un publisher y tres workers; pide editar el repo de prueba a mitad y compara cuentas.
- `create_tasks.sh` — Crea una tarea por URL de `tasks.txt` (ignora líneas `#`) y cuenta aciertos/fallos. `tasks.txt` — repos de ejemplo de `yagomilenio/*`.

## Empaquetado
- `pyproject.toml` — Metadatos, dependencias fijadas, entry point `synergia`, `package-data` (`config.ini.example`, `Dockerfile`, `container/*`). `MANIFEST.in` — Incluye los mismos ficheros en el sdist. `requirements.txt` — Misma lista de dependencias.
