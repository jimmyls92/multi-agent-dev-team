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

**Docstrings** (DEC-046): todos los módulos, clases y funciones siguen la [guía de estilo de Google](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings): resumen de una línea en estilo descriptivo ("Returns...", no "Return...") y secciones `Args:`, `Returns:`, `Raises:` y `Attributes:` cuando apliquen. Se incluyen los helpers privados y las funciones anidadas. En los tests llevan docstring los módulos, las clases, los fixtures y los helpers; los métodos `test_*` con nombre descriptivo no lo necesitan, como dice la guía. Los docstrings describen lo que hace el código, no instrucciones del lab.

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

Trabajando en: **Lab 1.3** (bucle ReACT del Coder, C1.4) → leer `docs/labs/` del Lab 1.3 al empezar.

Progreso:
- ✅ Lab 1.1 cerrado: memoria de dos capas (C1.2), DEC-004..DEC-031. El test oficial pasa con una key real.
- ✅ Lab 1.2 scaffold en el repo (DEC-033..DEC-035): `tools/schemas.py`, `agents/tools_demo.py`, `llm_client.py` (cliente compartido) y `memory.py` en la raíz. El test de memoria sigue pasando con key real tras el refactor.
- ✅ Producto y técnico de las tools cerrados: DEC-036..DEC-045 (workspace, timeout, salida de `exec_python`, entorno, `cwd`, tope de lectura, wrappers Pydantic, grupo de procesos, configuración).
- ✅ `read_file`/`write_file` (`tools/file_io.py`) implementados; `tests/test_file_io.py` pasa.
- ✅ `exec_python` (`tools/code_executor.py`) implementado; `tests/test_code_executor.py` pasa.
- ✅ Wrappers Pydantic estrictos + confinamiento a `workspace/` en `tools/handlers.py` (DEC-036, DEC-042); `workspace/` en `.gitignore` y variables en `.env.example`.
- ✅ Lab 1.2 cerrado: `python -m agents.tools_demo` con key real escribe `workspace/word_freq.py`, lo ejecuta y termina con DONE (C1.3).
- ✅ Lab 1.3: handout en `docs/labs/lab_1_3_react_agent.md`. El código del lab (incluido `agent_solution.py`) está en `lab_1_3_src/`, que **nunca se commitea**.
- ✅ Lab 1.3, producto cerrado: sin framework por ahora (DEC-047); sesión con un bucle ReACT por mensaje y una tarea con sus iteraciones = un turno (DEC-048); se guarda también "tarea + respuesta final" (DEC-049, sustituye a DEC-008); consulta antes de cada iteración por la tarea (DEC-050, mejora IMP-006); un único Coder en `agents/coder_agent.py`, `chat()` como entrada y `tools_demo.py` se elimina (DEC-051).
- ✅ C1.5/C1.6, producto cerrado dentro del Lab 1.3 (no hay más labs en el Módulo 1): el LLM declara el archivo principal y `code` se lee del disco (DEC-052); el plan es el primer Thought (DEC-053); smoke test con LLM real que ejecuta el código generado (DEC-054); `result` de la última ejecución válida y estados `success`/`failed_execution`/`unverified`/`max_iterations` (DEC-055) y `answered` para respuestas sin código (DEC-056).
- ✅ Lab 1.3, técnico cerrado (DEC-057..DEC-065): turno completo en la ventana con `add_turn` (DEC-057, refina DEC-004); `build_context()` ampliado y llamado en cada iteración (DEC-058); recuerdo del resultado sin código (DEC-059); formato de texto del lab validado con Pydantic (DEC-060, refina DEC-029); tools descritas en el prompt desde los schemas (DEC-061); `dispatch_tool` en `tools/handlers.py` sin excepciones (DEC-062); resultado estructurado bajo `exec_python` (DEC-063); todo el Coder en `coder_agent.py` con modo de una tarea (DEC-064); `CoderResult` (DEC-065).
- ✅ Lab 1.3, tests: en el Módulo 1 solo el smoke test (DEC-054), como test de pytest que solo corre con `--run-llm` vía `tests/conftest.py` (DEC-066).
- ⏭️ **Siguiente: código del Lab 1.3, pieza a pieza** (el usuario revisa cada una antes de seguir; leer antes las fichas citadas):
  1. **Tools:** función interna con resultado estructurado (salida, código de salida, timeout) bajo `exec_python`, que sigue devolviendo el mismo texto (DEC-063); `dispatch_tool(name, args)` en `tools/handlers.py` que nunca lanza (DEC-062).
  2. **Memoria:** `SlidingWindowBuffer.add_turn(messages)` (DEC-057); `build_context()` con prompt de sistema y mensajes del turno en curso; id `outcome-` + hash de la tarea para el recuerdo del resultado y su exclusión (DEC-058, DEC-059, DEC-049).
  3. **Coder (1):** prompt ReACT con las tools generadas desde `ALL_TOOL_SCHEMAS` (DEC-061), modelos `ToolStep`/`FinalStep`/`Step`/`CoderResult` (DEC-065) y `parse_llm_response()` con sus reglas (DEC-060).
  4. **Coder (2):** `run_agent(task, window) -> CoderResult`: bucle de 10, estados (DEC-055, DEC-056), `code` leído del disco (DEC-052), plan = primer Thought (DEC-053), guardado de tarea y resultado (DEC-049).
  5. **Coder (3):** `chat()` devuelve la explicación y `main()` interactivo o de una tarea con argumento (DEC-064); borrar `agents/tools_demo.py` (DEC-051).
  6. **Tests:** `tests/conftest.py` + `tests/test_smoke.py` (DEC-054, DEC-066), ejecutarlo con key real; volver a pasar `CHROMA_PATH=.chroma-test python -m tests.test_memory` (C1.2) y `pytest tests/` (Lab 1.2).
  Al terminar: comparar con `lab_1_3_src/agent_solution.py` (no abrirlo antes) y actualizar el README (framework pendiente, cómo ejecutar el Coder y el smoke test).
Pendientes fuera del lab:
- Entorno: `.venv` con Python 3.11 vía `uv` y `.env` con la key real (DEC-032). Falta documentar el setup en el README.
- Tests mockeados de la memoria (sin LLM real), a proponer y aprobar antes de escribirlos: el input actual nunca vuelve como recuerdo (DEC-031), un turno fallido o una respuesta vacía dejan la ventana intacta (DEC-028, DEC-029) y los duplicados exactos se actualizan (DEC-011). Aplazados por decisión del usuario (en el Módulo 1 solo lo que exigen las Cs); como tarde en C4.7.
- Tests propios de las tools (Lab 1.2), aplazados: confinamiento a `workspace/` (DEC-036, DEC-042), entorno sin credenciales (DEC-039, DEC-043), `cwd` del script (DEC-040), stdin cerrado, mensaje sin salida y truncado por el final (DEC-038), tope de lectura (DEC-041) y muerte del grupo de procesos (DEC-044). Proponer y aprobar antes de escribirlos. Aplazados por decisión del usuario (en el Módulo 1 solo lo que exigen las Cs); como tarde en C4.7.
- Tests mockeados del Coder (Lab 1.3), aplazados por decisión del usuario: en el Módulo 1 solo el smoke test que exige C1.6. Propuestos: parser (DEC-060), estados del bucle (DEC-055/056/063), ventana y memoria en el bucle (DEC-049/057/058), `dispatch_tool` (DEC-062), resultado estructurado de la ejecución (DEC-063) y `add_turn` (DEC-057). Como tarde en C4.7 (tests unitarios mockeados de cada agente).
- Mejoras de memoria IMP-001..IMP-005: siguen en `idea`.
- El repo aún no tiene remoto. Tras el primer push no se reescribe historial.
- "Jev" (IMP-003, IMP-004): modelo que el usuario explicará más adelante.
- Pregunta abierta: ¿marcar en las fichas `DEC-` cuándo el motivo lo propuso Claude?
- Elegir framework (LangGraph / AutoGen / CrewAI) antes de entregar el Módulo 1 (C1.1 exige nombrarlo en el README) y como tarde en el Módulo 2 (C2.3); ver DEC-047.

Actualiza esta sección al terminar cada TODO y al empezar o cerrar cada lab.

## Flujo de trabajo: Producto → Técnico → Código

Cada TODO o funcionalidad se trabaja siempre en tres fases, en este orden y sin saltarse ninguna:

1. **Producto (funcional/negocio):** decidir cómo se comporta el agente y por qué. Por ejemplo, qué recuerda, qué alcance tiene o qué pasa en los casos límite. Presenta cada decisión con su impacto y tu recomendación; el usuario decide.
2. **Técnico:** cuando el producto esté cerrado, propón cómo implementarlo: opciones con ventajas e inconvenientes y una recomendación. No le preguntes al usuario el "cómo"; explícale por qué importa.
3. **Código:** cuando lo técnico esté cerrado, transfórmalo en código **paso a paso**, en piezas pequeñas que el usuario revise antes de seguir.

En cada fase, registra en `docs/decisions.md` las decisiones acordadas con su motivo. Si el usuario no da un motivo explícito, usa el que propusiste. Los tests que fijen comportamiento se proponen y se aprueban antes de escribirlos.

## Commits

Al terminar un TODO o una tarea grande, propón un commit: qué archivos incluir y el mensaje. No hagas el commit hasta que el usuario lo confirme. Nunca incluyas `.env`, datos de `.chroma/` ni archivos ajenos a la tarea.

Formato de los commits (Conventional Commits):
- Asunto de ≤ 72 caracteres en imperativo, con prefijo de tipo: `feat`, `fix`, `docs`, `test`, `refactor` o `chore`, y ámbito opcional, por ejemplo `feat(memory): ...`.
- Cuerpo solo si el porqué no es obvio. No listes archivos; cita los `DEC-NNN` o `IMP-NNN` relacionados.
- Un cambio lógico por commit. Separa el código de los cambios de proceso o documentación que no tengan relación con él.

**No reescribas el historial ya subido** (`--amend`, `rebase`, `filter-branch` sobre commits que estén en el remoto): obliga a hacer `push --force` y puede invalidar el SHA entregado al evaluador (C1.1). Solo se reescriben commits locales que todavía no se hayan subido.

## Labs

Cada lab tiene su enunciado en `docs/labs/lab_<n>_<m>_<tema>.md` (por ejemplo, `lab_1_1_memory.md`). **No lo cargues por defecto.** Léelo solo cuando la tarea sea de ese lab, cuando el usuario lo mencione o cuando se toquen los archivos que ese lab trabaja.

- Los labs se implementan dentro de la estructura del proyecto, no en archivos sueltos en la raíz.
- Si un lab y un criterio de la rúbrica no coinciden, se aplica lo que cumpla el criterio.

## Decisiones de diseño

El porqué de cada decisión está en **`docs/decisions.md`** (fichas `DEC-NNN`, en inglés). El código que aplica una decisión lleva un comentario `DEC-NNN`.

- **Antes de modificar código:** busca los `DEC-` del archivo o símbolo afectado (`grep -n "DEC-" <archivo>`) y lee esas fichas. Fíjate en su `Basis`:
  - `Required`: no se cambia salvo que el requisito lo permita.
  - `Preferred`: se puede cambiar con una buena razón.
  - `Provisional`: está pensada para replantearse cuando se cumpla su `Revisit when`.
- **Si el cambio contradice una decisión:** avisa al usuario y explícale el porqué original *antes* de tocar nada. Si decide cambiarla, crea una ficha nueva y marca la antigua como `superseded by DEC-NNN`; nunca la borres.
- **Al tomar una decisión nueva** con alternativas razonables: propón la ficha, con su `Basis` y su porqué, incluido si es una simplificación temporal. Cuando el usuario la valide, añade el ancla `DEC-NNN` en el código.
- **Al empezar un lab:** revisa las decisiones `Provisional` cuyo `Revisit when` se refiera a ese lab.

## Mejoras (backlog)

Las ideas que van más allá de lo requerido se guardan en **`docs/improvements.md`**, agrupadas por área y en inglés.

- **Cuándo leerlo:** cuando el usuario pregunte por mejoras o ideas, sean generales o de un área concreta ("¿qué mejoras tenía para la memoria?"), y siempre al cerrar un lab.
- **Registrar:** el usuario explica la idea como quiera. Pásala a una ficha en inglés con el siguiente `IMP-NNN` y la plantilla del archivo. Indica qué criterio toca y avisa si hay riesgo de romperlo.
- **Al cerrar un lab:** recuerda al usuario las mejoras de esa área que estén en `idea` o `planned`.
- **Implementar:** solo cuando el usuario lo pida, en cualquier momento, cada mejora en su propio commit y sin romper ningún criterio. Después, actualiza su `Status`.
