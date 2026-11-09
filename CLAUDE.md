# CLAUDE.md

Proyecto final del curso **Build Autonomous Multi-Agent Systems** (Saras AI Institute).

Referencia completa (guía general, guías de cada módulo y rúbrica, transcritas): **`docs/course_reference.txt`**; cada lab en `docs/labs/` (ver "Labs"). Al empezar un módulo se añade su guía como Part A<n>, y al empezar un lab, su archivo en `docs/labs/`. Consúltala antes de implementar o cerrar cualquier criterio; aquí solo está lo que hay que tener presente siempre.

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

- Framework: **LangGraph** desde el Módulo 1 (DEC-068, sustituye a DEC-047); el Coder usa `create_agent` de LangChain con tool calling nativo y middleware (DEC-069). Documentarlo en el README. Si se cambia de framework, justificarlo (C2.6).
- LLM: la guía permite GPT-4o, Claude Sonnet u Ollama. Si se usa un equivalente, por ejemplo vía OpenRouter, indicarlo en el README.
- Patrón del agente: **ReACT** (lo exige la guía).
- Protocolo del Módulo 3: **pendiente** (MCP con el SDK oficial de Python, **o** A2A con `sender`, `receiver`, `intent`, `payload`, `correlation_id` y validación de intent).

## Notas del repo

- Los nombres ya coinciden con el scaffold de la guía. Los tests van en `tests/`; no crear `test/`.
- Git no versiona carpetas vacías. Antes de entregar, comprobar que `orchestration/` tiene algún archivo para que aparezca en el repo (C1.1).
- `config.yaml` es la configuración del IDE (Continue) y no forma parte del sistema. Nunca debe contener una API key real.
- Remoto: `origin` = https://github.com/jimmyls92/multi-agent-dev-team (público). Se trabaja en la rama de la semana (`week-1`, ...); `master` es la rama por defecto y se adelanta con fast-forward (`git fetch . week-1:master`) a lo que esté listo.
- Entorno: `.venv` con Python 3.11 vía `uv` y `.env` con la key real (DEC-032); instalar con `UV_LINK_MODE=copy uv pip install -r requirements.txt`. Setup en el README.
- El material de los labs (`lab_1_3_src/`, `lab-2-1/`) es solo referencia local y **nunca se commitea**.

## Estado actual

Spec activo: **Lab 2.1 (PM Agent)**, spec **aprobado**. Spec: `docs/specs/lab_2_1_pm_agent.md`. Enunciado y diferencias lab ↔ proyecto en `docs/labs/lab_2_1_pm_agent.md`; guía del Módulo 2 en `docs/course_reference.txt` (Part A2). Material original en `lab-2-1/` (fuera de git).

Producto cerrado (DEC-081..DEC-088) y técnico cerrado (DEC-089..DEC-094). T1 hecha. Siguiente: mapa de T2 (helper de llamada estructurada).

Los tests de `lab-2-1/test_lab21.py` sirven de inspiración para los AC; no se ejecutan contra nuestro código.

Módulo 1: cerrado y subido (C1.1–C1.6). Memoria de dos capas (Lab 1.1), tools (Lab 1.2) y Coder con LangChain `create_agent` (Lab 1.3, DEC-068..DEC-080). Detalle en `docs/decisions.md` y el README.

Actualiza esta sección al cambiar de spec o de tarea; el detalle de las tareas vive en el spec.

## Pendientes

Tests aplazados por decisión del usuario (como tarde en C4.7; proponer y aprobar antes de escribirlos):
- **Memoria** (mockeados): el input actual nunca vuelve como recuerdo (DEC-031); un turno fallido o una respuesta vacía dejan la ventana intacta (DEC-028, DEC-029); los duplicados exactos se actualizan (DEC-011).
- **Tools:** confinamiento a `workspace/` (DEC-036, DEC-042), entorno sin credenciales (DEC-039, DEC-043), `cwd` del script (DEC-040), stdin cerrado, mensaje sin salida y truncado por el final (DEC-038), tope de lectura (DEC-041), muerte del grupo de procesos (DEC-044).
- **Coder** (modelo falso): (a) **prioritario**, un modelo que solo da texto para en 10 con `max_iterations` (fija el orden de DEC-079); (b) uno que llama a tools sin terminar para en 10; (c) argumentos inválidos no ejecutan la tool (DEC-076); (d) `CoderResult` desde mensajes inventados (DEC-078).

Otros:
- Mejoras de memoria IMP-001..IMP-005 en `idea`. "Jev" (IMP-003, IMP-004): modelo que el usuario explicará más adelante.
- Pregunta abierta: ¿marcar en las fichas `DEC-` cuándo el motivo lo propuso Claude?

## Notas técnicas de LangChain/LangGraph

Versiones probadas: langchain 1.4.9, langgraph 1.2.20, langchain-openai 1.7.4, langchain-core 1.7.6.
- `from langchain.agents import create_agent` (`create_react_agent` está deprecado). Middleware en `langchain.agents.middleware` (`after_model`, `wrap_model_call`, `wrap_tool_call`, `ModelCallLimitMiddleware`); `ToolStrategy` en `langchain.agents.structured_output`.
- Los `after_model` se ejecutan en orden inverso de la lista; el límite cuenta en su `after_model`, por eso va el último (DEC-079). Al llegar al límite termina sin excepción, sin `structured_response`, y añade un `AIMessage` "Model call limits exceeded: run limit (10/10)".
- Con `ToolStrategy`, `create_agent` usa `bind_tools(..., tool_choice="any")`. La tool final se llama como la clase (`Finish`) y, tras un `Finish` válido, el último mensaje es un `ToolMessage`.
- Argumentos inválidos o tool inexistente: `ToolMessage` con `status="error"` y la tool no se ejecuta (`ToolErrorMiddleware` no lo ve). Una excepción dentro de una tool la relanza `ToolNode` y para el agente; por eso `dispatch_tool` nunca lanza.
- Cambiar el request con `request.override(model_settings=..., messages=..., system_message=...)`; asignar atributos está deprecado.
- Salida estructurada: `with_structured_output(Model, method="function_calling")`.
- Modelos falsos: subclase de `GenericFakeChatModel` con `bind_tools` que devuelve `self`; `AIMessage("", tool_calls=[{"name", "args", "id"}])`.

## Flujo de trabajo: Producto → Técnico → Spec → Tareas

Método en prueba desde el Lab 2.1 (2026-11-09). Objetivo: tests fáciles a partir de los acceptance criteria y que el usuario entienda el código y su porqué, sin alargar mucho el desarrollo. Si se hace demasiado largo, se replantea.

Cada lab (o funcionalidad grande) se trabaja en este orden, sin saltarse fases:

1. **Producto (funcional/negocio):** decidir cómo se comporta el agente y por qué. Por ejemplo, qué recuerda, qué alcance tiene o qué pasa en los casos límite. Presenta cada decisión con su impacto y tu recomendación; el usuario decide.
   - **Al presentar cualquier decisión (producto o técnica):** empieza con una frase introductoria en lenguaje llano que diga de qué se habla y qué problema resuelve, antes de código, campos o jerga. Si hay un esquema o un modelo, explica primero para qué sirve cada pieza y luego enséñalo.
2. **Técnico:** cuando el producto esté cerrado, propón cómo implementarlo: opciones con ventajas e inconvenientes y una recomendación. No le preguntes al usuario el "cómo"; explícale por qué importa.
3. **Spec:** `docs/specs/lab_<n>_<m>_<tema>.md`, a partir de `docs/specs/_template.md` (en inglés). Normalmente uno por lab.
   - Compara el handout del lab, la guía del proyecto del módulo y la rúbrica; los huecos van en la tabla de diferencias. Si chocan, gana el proyecto. Si el lab ya encaja con el proyecto, el spec es mínimo (tabla de AC y 1–2 tareas).
   - Acceptance criteria en **Given/When/Then**, con ID `AC-<n>.<m>-<k>`, `Origin` (`C<x>.<y>`, `lab` o `ours`) y `Verify` (`unit` con modelo falso, `integration`, `llm` con key real o `manual`). Cada AC se tiene que poder convertir en un test sin pensar.
   - **Aprobar el spec es aprobar los tests que fijan comportamiento** (no hace falta otra aprobación).
   - Tareas: cada una cubre al menos un AC, se revisa en ~15 min y acaba en un commit. El número sale de ahí, no es fijo.
4. **Código, tarea a tarea** (no se empieza la siguiente hasta que el usuario acepte la actual):
   1. **Mapa** antes de escribir código: archivos que se crean o tocan, funciones/clases con firma y tipos y una línea de qué hacen, y flujo de datos entre ellas. El usuario lo aprueba.
   2. **TDD ligero:** primero los tests de los AC de la tarea (en rojo, con modelo falso; nombre `test_ac_<n>_<m>_<k>_...`), luego el código hasta verde. Los AC `llm` se ejecutan al final de la tarea.
   3. **Revisión guiada:** seguir un ejemplo concreto (input real → qué pasa en cada función → estado final con valores), con una referencia `archivo:línea` en cada paso para que el usuario lo siga en el código, las 2–3 decisiones no obvias, un **comando para que el usuario lo ejecute** y **2 preguntas "¿qué pasaría si...?"** que el usuario responde y tú corriges; cada pregunta se tiene que poder responder leyendo el código de la tarea actual o el que ya existe, nunca el de tareas futuras. No se añaden comentarios explicativos al código: docstrings Google (DEC-046) y comentarios solo para porqués no obvios con su `DEC-NNN`.
   4. **Hecho cuando:** tests de sus AC en verde (o el AC marcado `llm`/`manual` con su comando ejecutado), docstrings y anclas DEC, estado de la tarea actualizado en el spec y commit propuesto.
   5. Opcional por spec: el usuario escribe él mismo una pieza pequeña con tu revisión.
5. **Cierre del spec:** lanza un agente revisor independiente. Recibe el spec, `docs/course_reference.txt` y el diff del spec completo, **no tu resumen**. Comprueba que cada AC tiene un test que verifica comportamiento real, que no hay regresiones de criterios anteriores y que se respetan los límites que fuerza el evaluador. El usuario clasifica los hallazgos (arreglar, descartar o pasar a `IMP`); lo que se arregla va en una tarea `R1` con el mismo proceso.

En cada fase, registra en `docs/decisions.md` las decisiones acordadas con su motivo. Si el usuario no da un motivo explícito, usa el que propusiste. El porqué vive en las fichas `DEC-NNN`; el spec las enlaza, no las repite. El estado de las tareas vive en el spec; "Estado actual" solo dice qué spec y qué tarea están activos.

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
