# CLAUDE.md

Proyecto final del curso **Build Autonomous Multi-Agent Systems** (Saras AI Institute).

Referencia completa (guía + rúbrica, transcritas): **`docs/course_reference.txt`**. Consúltala antes de implementar o cerrar cualquier criterio; aquí solo está lo que hay que tener presente siempre.

## Contexto del proyecto

Un equipo de desarrollo de software autónomo hecho con LLMs: recibe un requisito en lenguaje natural y produce código Python testeado y funcional, **sin intervención humana después del prompt inicial**.

- **PM Agent** (`agents/pm_agent.py`): convierte el requisito en una especificación técnica y una lista de tareas.
- **Coder Agent** (`agents/coder_agent.py`): implementa las tareas, aplica el feedback de QA e itera.
- **QA & Debugger Agent** (`agents/qa_agent.py`): genera tests pytest, los ejecuta, reporta issues y coordina las correcciones.

El proyecto se construye de forma incremental, un módulo cada vez, y **cada módulo debe mantener todo lo de los anteriores funcionando**:

| Módulo | Hito | Criterios |
|---|---|---|
| 1 | Coder Agent v1.0: memoria, tools, ReACT | C1.1–C1.6 |
| 2 | Multi-Agent v2.0: PM + handoff con estado compartido | C2.1–C2.6 |
| 3 | Agent Team v3.0: QA + bucle de revisión + MCP **o** A2A | C3.1–C3.6 |
| 4 | Production v4.0: tracing, retries, circuit breaker, coste, caché, tests, Docker | C4.1–C4.9 |
| 5 | Entrega final: integración, docs, demo, reflexión | C5.1–C5.6 |

## Cómo se evalúa (importante)

- Cada criterio es **Met** o **Not Yet**. No hay notas parciales ni medias: **un solo criterio Not Yet suspende esa competencia**.
- El evaluador revisa el **repo público + un commit SHA concreto**, y ejecuta pruebas propias (timeouts, límites de iteraciones, >8 tareas, fallos forzados). Todo lo que se diga tiene que **ocurrir de verdad en ejecución**, no basta con un JSON de ejemplo, un diagrama o una mención en el README.
- Las regresiones cuentan: si un cambio rompe una capacidad de un módulo anterior, ese criterio vuelve a Not Yet.
- No es obligatorio: implementar los dos protocolos, usar varios frameworks, el debate lab, la comparativa entre frameworks ni llegar al 100 % de cobertura.

## Reglas estrictas (aplicarlas siempre)

**Estructura del repo** (C1.1, C5.3). Debe existir desde el principio: `agents/`, `tools/`, `orchestration/`, `tests/`, `docs/`, `.env.example`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `README.md`. Los nombres deben ser exactamente estos.

**Seguridad y validación** (C1.3, C4.6)
- Nunca usar `eval()`/`exec()` directos. El código se ejecuta con `subprocess` y un timeout configurable (**10 s por defecto**).
- Toda salida de un LLM se valida con un schema **Pydantic** antes de actuar sobre ella. Una salida inválida nunca debe llegar a las tools ni a la ejecución.
- Validar las entradas externas y los argumentos de las tools antes de usarlos.
- Credenciales solo mediante variables de entorno (`.env`). Ningún secreto real en el código, en `.env.example`, en las imágenes Docker ni en los commits.

**Límites numéricos** (el evaluador los fuerza)
- ReACT del Coder: **máximo 10 iteraciones** (C1.4).
- PM: **máximo 8 tareas**. Si genera más, se consolidan sin perder cobertura de requisitos; borrarlas no vale (C2.4).
- Bucle QA→Coder: límite configurable por **variable de entorno**, **5 por defecto**. Al llegar al límite con fallos, QA devuelve un informe de issues sin resolver y **nunca dice que ha tenido éxito** (C3.3).
- Retries: en **cada** llamada a LLM o tool, **≤3 reintentos**, backoff exponencial **con jitter**, en el límite de la llamada individual (sin repetir todo el loop del agente) (C4.2).
- Circuit breaker: se abre tras **3 fallos consecutivos**, pasa a half-open tras un cool-down configurable, registra las transiciones a nivel **WARNING** y, mientras está abierto, devuelve caché o un error estructurado sin crashear (C4.3).

**Memoria** (C1.2): las dos capas son obligatorias. Un buffer deslizante de N turnos y un store semántico en **Chroma**, consultado **antes de cada llamada al LLM**, cuyo contexto recuperado se inyecta realmente en el prompt.

**Salidas y estado**
- El Coder devuelve un modelo Pydantic con `code`, `explanation`, `plan` y `result`. `code` debe coincidir con el archivo escrito y `result` debe salir de una ejecución real (C1.5).
- Estado compartido tipado (Pydantic/TypedDict), sin dicts ad-hoc, con: requisito original, spec, lista de tareas, estado de cada tarea y código acumulado (C2.2).
- Spec del PM: `name`, `description`, acceptance criteria y tasks (C2.1). El handoff es JSON-serializable, con task ID, descripción, acceptance criteria y prioridad, y todo corre dentro del mismo grafo de orquestación (C2.3).
- Self-reflection del Coder **antes** de QA, y el artefacto revisado es el que se envía a QA (C3.4).
- QA escribe tests pytest **reales** que comprueban comportamiento y los ejecuta en un subprocess con timeout. Una revisión hecha solo por el LLM no cuenta (C3.1).

**Observabilidad y coste** (C4.1, C4.4, C4.5)
- Una única traza raíz por ejecución (LangSmith o Phoenix/Arize), con cada invocación de PM, Coder y QA como span hijo. Cada span incluye `agent_name`, `token_count`, `tool_calls` y `duration_ms`.
- Tras **cada** llamada al LLM se registran tokens de prompt y de completion y el coste en USD por agente. Al terminar cada ejecución se escribe automáticamente un JSON en `docs/cost_reports/` y los totales deben cuadrar.
- Caché con TTL configurable. Modelo grande para el PM y modelos pequeños/rápidos para Coder y QA.

**Tests**: cada funcionalidad nueva lleva sus tests. Hacen falta tests unitarios mockeados de cada agente, tests de integración mockeados (handoff PM→Coder y terminación del bucle Coder↔QA) y E2E que ejecuten el código generado contra fixtures (API `/health` y `/echo`, linked list con 4 métodos, BST con insert/search/in-order). Los tests deben comprobar comportamiento, no objetos fijos ni texto.

**Docker** (C4.8): Python **3.11**, `ENTRYPOINT`, servicios del agente y de Chroma con **healthcheck** y `env_file`. Un `docker compose up` desde cero debe ejecutar la tarea de principio a fin.

**Documentación**: el README y `docs/` deben coincidir con lo que está implementado (diagramas incluidos). Deben documentar el framework elegido y por qué, las decisiones de implementación, el protocolo elegido y su justificación, cómo ejecutar los tests, dónde están las trazas y los informes de coste, y cómo distinguir un éxito de una salida con issues sin resolver.

## Decisiones del proyecto

- Framework: **pendiente** (LangGraph / AutoGen / CrewAI). Cuando se elija, documentarlo en el README. Si se cambia de framework, justificarlo (C2.6).
- LLM: la guía permite GPT-4o, Claude Sonnet u Ollama. Si se usa un equivalente, por ejemplo vía OpenRouter, indicarlo en el README.
- Patrón del agente: **ReACT** (lo exige la guía).
- Protocolo del Módulo 3: **pendiente** (MCP con el SDK oficial de Python, **o** A2A con `sender`, `receiver`, `intent`, `payload`, `correlation_id` y validación de intent).

## Notas del repo

- Los nombres ya coinciden con el scaffold de la guía. Los tests van en `tests/`; no crear `test/`.
- Git no versiona carpetas vacías. Antes de entregar, comprobar que `orchestration/` tiene algún archivo para que aparezca en el repo (C1.1).
- `config.yaml` es la configuración del IDE (Continue) y no forma parte del sistema. Nunca debe contener una API key real.

## Estado actual

Trabajando en: **Lab 1.1** (memoria de dos capas, C1.2) → leer `docs/labs/lab_1_1_memory.md`.

Actualiza esta línea al empezar o cerrar cada lab.

## Commits

Al terminar un TODO o una tarea grande, propón un commit: qué archivos incluir y el mensaje. No hagas el commit hasta que el usuario lo confirme. Nunca incluyas `.env`, datos de `.chroma/` ni archivos ajenos a la tarea.

## Labs

Cada lab tiene su enunciado en `docs/labs/lab_<n>_<m>_<tema>.md` (por ejemplo, `lab_1_1_memory.md`). **No lo cargues por defecto.** Léelo solo cuando la tarea sea de ese lab, cuando el usuario lo mencione o cuando se toquen los archivos que ese lab trabaja.

- Los labs se implementan dentro de la estructura del proyecto, no en archivos sueltos en la raíz.
- Si un lab y un criterio de la rúbrica no coinciden, se aplica lo que cumpla el criterio.
