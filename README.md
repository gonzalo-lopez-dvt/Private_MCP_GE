# Private MCP en Cloud Run para Gemini Enterprise (PoC)

Servidor **MCP (Model Context Protocol)** mínimo, desplegado en un **Cloud Run privado** (solo con autenticación IAM), para probar la funcionalidad de Gemini Enterprise que permite conectar MCPs privados.

El servidor no tiene lógica de negocio: expone 3 tools de prueba cuyo único objetivo es comprobar que Gemini Enterprise es capaz de descubrirlas y llamarlas.

---

## Índice

1. [Qué hace](#qué-hace)
2. [Ficheros](#ficheros)
3. [Cómo funciona un MCP (y cómo se usa)](#cómo-funciona-un-mcp-y-cómo-se-usa)
4. [Requisitos en esta máquina (Windows)](#requisitos-en-esta-máquina-windows)
5. [Despliegue paso a paso](#despliegue-paso-a-paso)
6. [Verificación](#verificación)
7. [Problemas encontrados y cómo se resolvieron](#problemas-encontrados-y-cómo-se-resolvieron)
8. [Despliegues realizados](#despliegues-realizados)
9. [Conexión con Gemini Enterprise](#conexión-con-gemini-enterprise)
10. [Estado y siguientes pasos](#estado-y-siguientes-pasos)

---

## Qué hace

Expone por HTTP tres tools:

| Tool | Argumentos | Devuelve |
|---|---|---|
| `saluda` | `nombre: str` | `"¡Hola, {nombre}! Soy un MCP de prueba corriendo en Cloud Run 🚀"` |
| `suma` | `a: float`, `b: float` | `a + b` |
| `tira_dado` | `caras: int = 6` | número aleatorio entre 1 y `caras` |

`saluda` es la mejor prueba de integración: devuelve una frase fija reconocible (con el 🚀), así que si el agente la reproduce literalmente es que **de verdad** ha llamado al MCP y no se la ha inventado.

Detalles técnicos:

- SDK oficial de Python **`mcp==2.0.0`**, clase `MCPServer`.
- Transporte **Streamable HTTP** (el transporte MCP moderno para servidores remotos), endpoint en la ruta **`/mcp`**.
- Modo **stateless** (`stateless_http=True`): cada petición es independiente, sin afinidad de sesión, lo que encaja con el autoescalado de Cloud Run.
- Escucha en `0.0.0.0` y en el puerto de la variable `$PORT` que inyecta Cloud Run (8080 por defecto).

## Ficheros

| Fichero | Para qué |
|---|---|
| `server.py` | El servidor MCP con las 3 tools. |
| `requirements.txt` | `mcp==2.0.0` (versión fijada a propósito, ver [problemas](#3-modulenotfounderror-no-module-named-mcpserverfastmcp)). |
| `Dockerfile` | Imagen `python:3.12-slim` que instala dependencias y arranca `python server.py`. |
| `.gcloudignore` | Excluye `.git`, venvs, cachés y este README de lo que se sube a Cloud Build. |

No hace falta Docker en local: `gcloud run deploy --source .` sube el código a **Cloud Build**, que construye la imagen usando el `Dockerfile` y la guarda en Artifact Registry.

## Cómo funciona un MCP (y cómo se usa)

Un servidor MCP **no hace nada por sí solo**: es un servicio pasivo que espera a que un *cliente* (un agente LLM: Gemini Enterprise, Claude, Cursor, código propio…) se conecte. El flujo del protocolo (JSON-RPC 2.0) es siempre:

1. `initialize` → handshake, el servidor anuncia sus capacidades.
2. `tools/list` → el cliente descubre qué tools hay y sus esquemas de entrada.
3. `tools/call` → el modelo decide llamar a una tool con unos argumentos y recibe el resultado.

Si el servidor no tuviera tools, arrancaría y respondería al `initialize` igualmente, pero `tools/list` devolvería una lista vacía y el agente no tendría nada que llamar.

## Requisitos en esta máquina (Windows)

- Google Cloud SDK instalado en `C:\Users\glopez\AppData\Local\Google\Cloud SDK`.
- **Docker no es necesario.**
- **Python local no es necesario** (las dependencias se instalan dentro del contenedor). Pylance marcará el import `mcp.server` como no resuelto en el editor; es normal y no afecta al despliegue.

**Importante:** en git-bash, `gcloud` falla con `Python was not found` porque el alias de la Microsoft Store intercepta `python`. La solución es apuntar `gcloud` al Python que trae el propio SDK antes de cualquier comando:

```bash
export CLOUDSDK_PYTHON="/c/Users/glopez/AppData/Local/Google/Cloud SDK/google-cloud-sdk/platform/bundledpython/python.exe"
```

## Despliegue paso a paso

Ejecutar desde el directorio que contiene `server.py`, `Dockerfile` y `requirements.txt`:

```bash
# 0) gcloud necesita el Python del SDK en esta máquina
export CLOUDSDK_PYTHON="/c/Users/glopez/AppData/Local/Google/Cloud SDK/google-cloud-sdk/platform/bundledpython/python.exe"

PROJECT="TU-PROYECTO"
REGION="europe-west1"

# 1) Habilitar las APIs necesarias
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project "$PROJECT"

# 2) Dar permiso de build a la compute SA por defecto (si no, el build falla con PERMISSION_DENIED)
NUM=$(gcloud projects describe "$PROJECT" --format="value(projectNumber)")
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${NUM}-compute@developer.gserviceaccount.com" \
  --role="roles/cloudbuild.builds.builder" --condition=None

# 3) Desplegar como servicio PRIVADO (sin acceso anónimo)
gcloud run deploy mcp-test \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --no-allow-unauthenticated \
  --port 8080
```

Al terminar, `gcloud` muestra la **Service URL**. El endpoint MCP es esa URL + `/mcp`.

- `--no-allow-unauthenticated` es lo que lo hace privado: solo pueden llamarlo identidades con `roles/run.invoker` sobre el servicio.
- El paso 2 es idempotente: si el proyecto ya tiene el permiso, no pasa nada.
- La primera vez, `gcloud` crea automáticamente un repositorio en Artifact Registry (`cloud-run-source-deploy`) y un bucket `run-sources-<proyecto>-<región>`.

## Verificación

```bash
URL="https://<SERVICE-URL>/mcp"

# 1) Sin autenticación -> debe devolver 403 (prueba de que es privado)
curl -s -o /dev/null -w "HTTP %{http_code}\n" "$URL"

# 2) Con token de identidad -> handshake initialize (debe devolver 200)
TOKEN=$(gcloud auth print-identity-token)
curl -s -X POST "$URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'

# 3) Listar tools
curl -s -X POST "$URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | tr '\n' ' ' | grep -oE '"name":"[a-z_]+"'

# 4) Llamar a una tool
curl -s -X POST "$URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"saluda","arguments":{"nombre":"Gonzalo"}}}'
```

Notas:

- La cabecera `Accept: application/json, text/event-stream` es **obligatoria** en Streamable HTTP.
- La respuesta llega como SSE (`content-type: text/event-stream`), con líneas `event: message` / `data: {...}`.
- La respuesta va con `Transfer-Encoding: chunked`; pasarla por `sed ... | tail -1` puede dejar la salida vacía aunque la petición haya ido bien. Usa `curl -s -D -` para ver cabeceras y cuerpo crudo si dudas.

Resultado obtenido:

```
HTTP 403                                   # sin auth
HTTP/1.1 200 OK                            # con auth
content-type: text/event-stream
event: message
data: {"jsonrpc":"2.0","id":1,"result":{"capabilities":{...,"tools":{"listChanged":false}},
       "protocolVersion":"2025-06-18","serverInfo":{"name":"mcp-test","version":""}}}

"name":"saluda"                            # tools/list
"name":"suma"
"name":"tira_dado"
```

## Problemas encontrados y cómo se resolvieron

### 1. `gcloud`: `Python was not found`

**Causa:** el alias de Windows (`App execution aliases`) redirige `python` a la Microsoft Store y `gcloud` no encuentra intérprete.
**Solución:** `export CLOUDSDK_PYTHON=".../google-cloud-sdk/platform/bundledpython/python.exe"` (ver [requisitos](#requisitos-en-esta-máquina-windows)).

### 2. Build: `PERMISSION_DENIED ... IAM permission denied for service account <NUM>-compute@developer.gserviceaccount.com`

**Causa:** en los proyectos nuevos, Cloud Build usa por defecto la compute SA, que no tiene permisos para leer el código fuente subido al bucket ni para escribir en Artifact Registry.
**Solución:** dar `roles/cloudbuild.builds.builder` a esa SA (paso 2 del despliegue) y esperar unos segundos a que IAM propague.

### 3. `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`

**Causa:** con `mcp>=1.9.0` en `requirements.txt`, pip instaló **mcp 2.0.0**, que es una versión mayor con la API reestructurada. El build terminó bien, pero el contenedor se caía al arrancar y Cloud Run daba el error genérico *"The user-provided container failed to start and listen on the port defined provided by the PORT=8080 environment variable"*. El traceback real solo aparecía en los logs:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="mcp-test"' \
  --project "$PROJECT" --limit 40 --freshness=15m --format="value(textPayload)"
```

**Cambios de API entre mcp 1.x y 2.0** (comprobados instalando el paquete e inspeccionando su código fuente):

| mcp 1.x | mcp 2.0 |
|---|---|
| `from mcp.server.fastmcp import FastMCP` | `from mcp.server import MCPServer` |
| `FastMCP(name=..., host=..., port=..., stateless_http=True)` | `MCPServer(name=...)` |
| `mcp.run(transport="streamable-http")` | `mcp.run(transport="streamable-http", host=..., port=..., stateless_http=True)` |

`@mcp.tool()` y la ruta por defecto `/mcp` no cambian.

**Solución:** adaptar `server.py` a la API 2.0 y **fijar** `mcp==2.0.0` en `requirements.txt` para que el build sea reproducible.

Nota: al probar `mcp` 2.0 en local (Windows) da `No module named 'pywintypes'`, porque el SDK importa utilidades específicas de Windows. En el contenedor Linux esa rama no se ejecuta.

## Despliegues realizados

| Proyecto | Nº proyecto | Región | Servicio | Endpoint MCP |
|---|---|---|---|---|
| `gonzalo-lopez-sandbox` | `1026234172407` | `europe-west1` | `mcp-test` | `https://mcp-test-1026234172407.europe-west1.run.app/mcp` |
| `mcp-ge-private-poc` | `298348811414` | `europe-west1` | `mcp-test` | `https://mcp-test-298348811414.europe-west1.run.app/mcp` |

Los dos están verificados: 403 sin auth, `initialize` 200 con auth y `tools/list` devuelve las 3 tools.

## Conexión con Gemini Enterprise

### Prompts de prueba

Hay que pedir algo que **solo** se pueda resolver con una de las tools, y al principio mejor ser explícito ("usando tus herramientas"), porque con operaciones fáciles el modelo tiende a resolverlas solo:

- *"Usa la tool `saluda` para saludar a Gonzalo"* → debe devolver literalmente `¡Hola, Gonzalo! Soy un MCP de prueba corriendo en Cloud Run 🚀`.
- *"Súmame 1234 y 5678 usando tus herramientas"* → `6912`, y en la traza del agente debe aparecer la llamada a `suma`.
- *"Tírame un dado de 20 caras"* → `tira_dado(caras=20)`.
- *"¿Qué herramientas tienes disponibles?"* → debería listar las tres.

Si el agente muestra los pasos o la traza, debe verse la llamada a la tool con sus argumentos.

### Lo que pasó en la primera prueba

Con el MCP ya conectado en Gemini Enterprise, al pedirle *"salúdame utilizando el mcp aws poc"*, Gemini **se inventó la respuesta**: habló de un servidor "mcp-aws-poc-server" en AWS (el servidor real está en Cloud Run) y el saludo no era el texto de la tool. Al pedirle explícitamente la tool `saluda`, reconoció que *"no se encuentra disponible ni declarada en mi conjunto de funciones activas"*.

**Diagnóstico** (en `mcp-ge-private-poc`):

1. **El servidor está bien:** `tools/list` con un token válido devuelve `saluda`, `suma` y `tira_dado`.
2. **La política IAM del servicio estaba vacía.** Nadie tiene `roles/run.invoker`, así que ninguna identidad de Gemini Enterprise podría autenticarse:
   ```bash
   gcloud run services get-iam-policy mcp-test --region europe-west1 --project mcp-ge-private-poc
   # -> {"etag": "ACAB"}   (sin bindings)
   ```
3. **Gemini Enterprise no llegó a llamar al servicio.** En los logs de peticiones de las 2 horas anteriores solo había llamadas de `curl` y de `gonzalo.lopez@devoteam.com`; ninguna de una identidad de Google, ni siquiera 403:
   ```bash
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="mcp-test" AND httpRequest.status!=""' \
     --project mcp-ge-private-poc --limit 25 --freshness=2h \
     --format="table(timestamp, httpRequest.status, httpRequest.requestMethod, protoPayload.authenticationInfo.principalEmail, httpRequest.userAgent)"
   ```

**Conclusión:** el problema está en la configuración del lado de Gemini Enterprise, no en el servidor. Causas probables:

- Las tools del conector no se han descubierto o sincronizado (el paso que hace `tools/list`).
- El conector o sus tools no están asociados al agente concreto con el que se chatea (o se está hablando con el asistente genérico en lugar de con el agente que tiene el MCP).
- Falta dar `roles/run.invoker` a la identidad que usa Gemini Enterprise para llamar al Cloud Run.

## Estado y siguientes pasos

- [x] Servidor MCP con 3 tools (mcp 2.0, Streamable HTTP, stateless).
- [x] Desplegado como Cloud Run privado en `gonzalo-lopez-sandbox` y en `mcp-ge-private-poc`, y verificado.
- [x] MCP dado de alta como conector en Gemini Enterprise.
- [ ] **Averiguar qué service account usa Gemini Enterprise** para llamar al MCP (en la configuración del conector o en la documentación de la funcionalidad) y darle permiso de invoker:
  ```bash
  gcloud run services add-iam-policy-binding mcp-test \
    --region europe-west1 --project mcp-ge-private-poc \
    --member="serviceAccount:<SA-DE-GEMINI-ENTERPRISE>" \
    --role="roles/run.invoker"
  ```
- [ ] Comprobar que las tools aparecen sincronizadas en el conector y que están habilitadas en el agente con el que se prueba.
- [ ] Repetir la prueba con *"Usa la tool `saluda` para saludar a Gonzalo"* y confirmar en los logs de Cloud Run que entra una petición `POST /mcp` de la identidad de Gemini.

> No se pudo consultar la documentación oficial de la funcionalidad de MCP privado de Gemini Enterprise durante el desarrollo (la búsqueda web estaba bloqueada por una política de la organización), así que el flujo exacto de registro del conector no está documentado aquí.
