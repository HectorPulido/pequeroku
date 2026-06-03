# Pequenin — el asistente de IA de Pequeroku

Este documento explica, de punta a punta, cómo funciona el sistema de IA de
Pequeroku: el asistente **Pequenin**, un agente de código autónomo que opera la
VM del usuario (leer/editar archivos, ejecutar comandos, levantar servicios) desde
un chat en el IDE.

> Audiencia: cualquiera que vaya a tocar el agente, el consumer, las tools o la
> capa de acceso a la VM. Las rutas de archivo son relativas a `source/`.

---

## 1. Visión general

Tres servicios colaboran:

| Servicio | Stack | Rol |
|---|---|---|
| **web_service** | Django + DRF + Channels, servido con `gunicorn -k uvicorn.workers.UvicornWorker -w 8`. Postgres + Redis. | App/API, auth, cuotas, el **chat de IA** (WebSocket) y el motor del agente (`minicode`). System of record. |
| **vm_service** | FastAPI (un proceso uvicorn). Store en Redis, auth por bearer. | Ciclo de vida de las VMs (QEMU) y **acceso a la VM por SSH** (archivos, exec, terminal, búsqueda, procesos en background). |
| **VM del usuario** | Debian (qcow2 overlay sobre un golden). | Sandbox del usuario; el workspace vive en `/app`. |

El "cerebro" (LLM + bucle agéntico) corre dentro de web_service; las "manos"
(archivos/exec) son llamadas HTTP→SSH al vm_service, que las ejecuta dentro de la
VM. El front (React) solo habla con web_service.

```
Browser (React, AiAssistantPanel)
   │  WebSocket  /ws/ai/<container_pk>/
   ▼
web_service · AIConsumer (Channels)         ── auth, cuota, conversaciones, streaming
   │  run_pipeline(...)                         (ai_services/ai_consumers.py)
   ▼
minicode · Agent.run()  (genera eventos)     ── bucle: pensar → tools → observar → repetir
   │  tools (read/write/edit/grep/bash/…)       (ai_services/minicode/)
   ▼  HTTP (VMServiceClient)
vm_service · /vms/{id}/…  (FastAPI)          ── pool SSH por VM + lane dedicada de terminal
   │  SSH / SFTP
   ▼
VM Debian  ── /app (workspace del usuario)
```

---

## 2. Flujo de un mensaje (end-to-end)

1. El browser abre `wss://…/ws/ai/<container_pk>/`. `AIConsumer.connect()`
   (`ai_services/ai_consumers.py`) valida usuario, **cuota diaria**
   (`ResourceQuota.ai_uses_left_today()`), propiedad del contenedor, resuelve la
   **conversación activa** (puntero en DB) y reproduce su historial.
2. El usuario manda `{"text": "..."}`. El consumer revisa cuota y llama a
   **`run_pipeline(...)`** (`ai_services/minicode/frontends/pipeline.py`).
3. `run_pipeline` corre **todo lo bloqueante en un hilo** (`asyncio.to_thread`):
   construye el `Config` de minicode (credenciales de la tabla `Config`,
   `workdir=/app`, el `container`), crea el `LLM` y ejecuta `Agent.run()`.
4. `Agent.run()` es un **generador**: hace `yield` de eventos
   (`AssistantTextDelta`, `ToolCallStarted`, `ToolResult`, `Usage`, …). El bridge
   marshaliza cada evento al event loop y dispara los callbacks async del consumer,
   que los reenvía al browser como mensajes WS. Esto **no bloquea** el loop de
   Channels.
5. Cada tool del agente llama al **vm_service** vía `VMServiceClient`, que ejecuta
   la operación dentro de la VM por SSH.
6. Al terminar el turno, el consumer registra `AIUsageLog` (tokens), persiste la
   conversación (archivo en la VM) y devuelve la cuota restante.

---

## 3. El motor `minicode` (`ai_services/minicode/`)

Núcleo agéntico portado de opencode, **desacoplado de la interfaz por eventos**.
El bucle lo controla minicode, no el SDK de OpenAI: cada llamada al modelo es **un
paso**; el "seguir hasta terminar" lo lleva el `Agent`.

| Archivo | Qué hace |
|---|---|
| `agent.py` | El bucle (`Agent.run`): ensambla contexto → un paso del LLM → ejecuta tools → realimenta resultados → repite, hasta que el modelo responde sin pedir tools. `yield` de eventos; soporta subagentes (`task`). Cap `max_steps` (default 50). |
| `llm.py` | Puente con un endpoint estilo OpenAI, en streaming. `stream()` hace `yield` del texto y acumula tool-calls; devuelve `{content, tool_calls, usage}`. |
| `session.py` | Historial en formato OpenAI (`role`/`content`/`tool_calls`/`tool`). `sanitize()` repara historiales rotos (un `assistant` con `tool_calls` sin su `tool`) que de otro modo harían que la API rechace todo. |
| `events.py` | Dataclasses de eventos (único canal de salida del core). `depth`: 0 = principal, >0 = subagente. |
| `context.py` | `build_system()`: prompt de sistema + bloque `<env>` (describe la VM Debian / `/app`). **No** lee el filesystem del servidor. |
| `prompts.py` | System prompts (Pequenin + subagentes `explore`/`general` + aviso de fin de pasos). Documenta el entorno y `config.json`. |
| `config.py` | `Config` dataclass: credenciales/modelo, `workdir=/app`, `container`, `foreground_timeout`. |
| `frontends/pipeline.py` | Adaptador a Django Channels: `run_pipeline()` + `agent` (su `.model`). Puente sync↔async (hilo worker + `run_coroutine_threadsafe`). |
| `tools/` | Las "manos" del modelo (ver §4). |

**Subagentes**: la tool `task` lanza un `Agent` hijo (`explore` = read-only, o
`general`) con su propio bucle y set de tools restringido; reenvía sus eventos con
más `depth` y devuelve su reporte final.

---

## 4. Tools (`ai_services/minicode/tools/`)

Operan sobre la **VM** vía `VMServiceClient` (no sobre el filesystem del servidor).
Las rutas relativas se resuelven contra `/app` (POSIX).

| Tool | Acción | Backend VM |
|---|---|---|
| `read` | Lee un archivo (numerado, paginado) | `read-file` |
| `write` | Crea/sobrescribe un archivo | `upload-files` |
| `edit` | Reemplazo puntual (cascada exact → flexible → block-anchor, tolerante a whitespace) | `read-file` + `upload-files` |
| `glob` | Busca archivos por patrón | `list-dirs` (depth) + fnmatch |
| `grep` | Busca contenido (texto/regex) | `search` (grep en la VM) |
| `bash` | Comando shell. **Foreground** (~25 s) o **`background=true`** (sobrevive al turno) | `execute-sh` / `start-process` |
| `process` | Estado/log o stop de un job en background | `process-status` / `stop-process` |
| `todowrite` | Lista de tareas del agente (planificación) | — (en sesión) |
| `task` | Delega en un subagente (`explore`/`general`) | — (subagente) |
| `search_on_internet` / `read_from_internet` | Búsqueda web (DDGS) y fetch de URL (requests+bs4) | — (corre en el server) |

Sets por tipo de agente (`tools/__init__.py`): `build` (principal) = todas;
`general` = sin `task`/`todowrite`; `explore` = solo lectura + internet.

El puente con la VM (cliente, resolución de rutas, auditoría) está en `tools/vm.py`.

---

## 5. `config.json`, run y preview

`/app/config.json` es el descriptor del proyecto que lee el IDE. Esquema
implementado (ambos opcionales):

```json
{ "run": "<comando shell>", "port": <int> }
```

- **`run`** — el botón **Run** del IDE guarda los archivos y **pega el comando en
  la terminal interactiva** (no lo lanza detached). Por eso debe ser **no
  bloqueante** (`… &`, `setsid -f`, `nohup … &`, `docker compose up -d`); si no,
  congela la terminal.
- **`port`** — el mini-browser hace preview ejecutando **dentro de la VM**
  `curl http://localhost:<port>/<path>` y proxyeando el HTML/CSS/JS (reescribe
  URLs absolutas) — ver `web_service/vm_manager/proxy_browser_utils.py`. El
  servicio debe escuchar en ese puerto (bind `0.0.0.0`) y responder rápido.
- Un workspace nuevo se siembra con `readme.txt` + `config.json` (plantilla
  `default`); un **reset** del workspace borra todo en `/app` **excepto esos dos**.

El agente está instruido (en `prompts.py`) para mantener `config.json` correcto y
para levantar/verificar servicios con `bash(background=true)` + `process`.

---

## 6. Conversaciones y memoria

Soporta **múltiples conversaciones** por contenedor, conmutables. Lógica única en
`ai_services/conversations.py` (compartida por el consumer y el endpoint REST).

| Dato | Dónde vive | ¿Sobrevive a reset/rebuild de la VM? |
|---|---|---|
| **Contenido** de cada conversación: `/app/.pequenin/ai_memory_<id>.json` (`{"messages":[…]}`) | **VM** | ❌ (por diseño) |
| **Puntero** de conversación activa: `AIMemory.current_conversation` por `(user, container)` | **DB** | ✅ |

Al conectar, el consumer lee el puntero (DB), carga esa conversación (VM) y
reproduce su historial. `/clear` limpia la conversación activa.

> Nota: el contenido es VM-only a propósito (no hay backup en DB). El puntero sí es
> durable en DB para no depender de la VM al reconectar.

---

## 7. Protocolo WebSocket (`/ws/ai/<container_pk>/`)

### Cliente → servidor
| Mensaje | Efecto |
|---|---|
| `{"text": "..."}` | Mensaje de chat en la conversación activa (consume cuota) |
| `"/clear"` (como `text`) | Limpia la conversación activa |
| `{"action":"list_conversations"}` | Devuelve `conversations` |
| `{"action":"new_conversation"}` | Crea el siguiente id y cambia a él |
| `{"action":"switch_conversation","id":N}` | Carga N y reproduce su historial |
| `{"action":"delete_conversation","id":N}` | Borra N (si era activa, cae a otra) |

### Servidor → cliente
| Evento | Campos | Para |
|---|---|---|
| `start_text` / `text` / `finish_text` | `content` | Respuesta del asistente en streaming |
| `connected` | `ai_uses_left_today` | Cuota restante |
| `conversations` | `conversations[]`, `current` | Lista + conversación activa |
| `clear` | — | Reset de la vista (al cambiar/limpiar) |
| `memory_data` | `memory[]`, `conversation` | Historial completo persistido |
| `tool_call` | `name`, `args`, `command`, `depth` | La tool invocada + sus argumentos |
| `tool_result` | `name`, `output` (≤4000 chars), `depth` | Lo que devolvió la tool |
| `todos` | `todos[]`, `depth` | Lista de tareas del agente |
| `subagent_started` / `subagent_finished` | `agent_type`, `prompt`, `depth` | Actividad de subagentes |
| `info` / `error` | `message`, `depth` | Avisos del bucle |
| `usage` | `prompt_tokens`, `completion_tokens`, `total_tokens`, `depth` | Tokens por paso |

> Los eventos estructurados (`tool_call`, `tool_result`, `todos`, `usage`, …) se
> emiten siempre; el front puede ignorarlos hasta que los implemente.

---

## 8. Endpoints REST (DRF, `ContainersViewSet`)

| Método | Ruta | Respuesta |
|---|---|---|
| `GET` | `/api/containers/{id}/conversations/` | `{"conversations":[…],"current":N}` |
| `GET` | `/api/containers/{id}/conversations/{n}/` | `{"conversation_id":n,"messages":[…]}` |
| `DELETE` | `/api/containers/{id}/conversations/{n}/` | `{"conversations":[…],"current":N}` |

Auth + ownership por el `ContainersViewSet` habitual.

---

## 9. Capa de acceso a la VM (vm_service) — coexistencia

El vm_service sirve, en **un solo event loop**, tanto la terminal interactiva como
las operaciones del agente/editor. Para que convivan sin bloquearse:

- **Handlers SSH fuera del loop**: los endpoints de datos son `def` (Starlette los
  corre en su threadpool) → el loop sigue libre para la terminal.
- **Pool de conexiones SSH por VM** (`implementations/ssh_pool.py`): cada operación
  de archivo/exec toma prestada una conexión con su **propio SFTP** (sin carreras),
  acotado por VM (no agota `MaxSessions`).
- **Lane dedicada de terminal**: el shell interactivo abre **su propia** conexión
  (`generate_console`), aislada del churn del agente.
- **Cierre de canales** (`exec_and_close`): cada `exec_command` cierra su canal →
  no se filtran sesiones (evita `ChannelException: Connect failed`).

Comandos largos (`pip install`, `pytest`, servidores) van por `start-process`
(detached con `setsid`, sobreviven al request) y se consultan con
`process-status`.

---

## 10. Configuración y cuotas

- **Credenciales del LLM**: tabla `Config` (`internal_config`) con
  `openai_api_key`, `openai_api_url`, `openai_model`. El pipeline las lee por
  request (ai_service queda sin estado).
- **Cuota**: `ResourceQuota.ai_uses_left_today()` limita usos/día; cada turno
  registra `AIUsageLog` (modelo + tokens).
- **Modelo**: `agent.model` lo lee de `Config` (default `gpt-4o`).

---

## 11. Mapa de archivos (lo esencial)

```
web_service/
  ai_services/
    ai_consumers.py            # AIConsumer (WebSocket): auth, cuota, conversaciones, streaming
    conversations.py           # almacenamiento de conversaciones (VM) + puntero (DB)
    minicode/
      agent.py  llm.py  session.py  events.py  context.py  prompts.py  config.py
      frontends/pipeline.py    # run_pipeline + agent (puente Django/Channels)
      tools/                   # read/write/edit/glob/grep/shell/process/internet/task/todo/vm
  vm_manager/
    views.py                   # ContainersViewSet (incl. endpoints de conversaciones + curl/preview)
    vm_client.py               # VMServiceClient (HTTP al vm_service)
    proxy_browser_utils.py     # proxy del preview (curl dentro de la VM + reescritura de URLs)
  internal_config/models.py    # Config, AIMemory (puntero), AIUsageLog
  pequeroku/routing.py         # ruta WS /ws/ai/<pk>/
  front-react/src/components/ide/AiAssistantPanel.tsx   # chat del IDE

vm_service/
  routes/vms.py                # endpoints REST (files/exec/search/process/listening-ports/tty)
  implementations/
    ssh_pool.py                # pool de conexiones SSH por VM (lane agente/editor)
    ssh_cache.py               # conexión dedicada de terminal + exec_and_close
    bridge.py                  # TTYBridge (terminal interactiva)
    process.py                 # start/status/stop de procesos en background
    read_from_vm.py  send_file.py
```

---

## 12. Restricciones y gotchas

- **Foreground bash ≈ 25 s** (límite del round-trip SSH/HTTP). Para algo más largo,
  `background=true` + `process`.
- **El contenido de las conversaciones es VM-only**: un reset/rebuild de la VM lo
  borra (el puntero en DB sobrevive, no el contenido).
- **`run` debe ser no bloqueante** o congela la terminal del IDE.
- **El preview** necesita el servicio escuchando en `config.json.port` y
  respondiendo rápido (el `curl` interno tiene timeout corto).
- **`max_steps=50`** por turno (cap del bucle) — un mensaje puede disparar hasta 50
  llamadas al LLM; ajustable en `minicode/config.py`.

---

## 13. Roadmap (dirección, no implementado)

- Extraer la IA a su propio microservicio (`ai_service`) con **cola** (Redis
  Streams) para orquestar runs + **pub/sub** (channel layer) para devolver el
  stream al browser. Caps de concurrencia por VM/usuario.
- **gRPC** como capa RPC interna web↔vm_service (contrato tipado, streaming nativo
  para tty/logs/search). Ortogonal al fix de coexistencia (que ya está en el pool).
