# Proyecto: Analisis y Prototipo de FAQs con PostgreSQL

Este proyecto documenta el proceso para analizar un dump de PostgreSQL, configurar la conexion desde Python y ejecutar un prototipo de microservicios que genera sugerencias automaticas de FAQs a partir de conversaciones historicas.

## Que hace el proyecto

El flujo completo parte de la base de datos `everwod_db`, lee mensajes historicos desde PostgreSQL, crea pares de conversacion usuario/asistente, agrupa preguntas parecidas con embeddings locales y guarda sugerencias de FAQs para que una persona las valide.

Tambien incluye un script simple para verificar que la conexion con la base de datos funciona antes de ejecutar los servicios.

## Requisitos previos

- Linux, recomendado Ubuntu.
- PostgreSQL instalado y corriendo.
- Python 3 instalado.
- Base de datos `everwod_db` restaurada desde el dump.
- Archivo `.env` en la raiz del proyecto.

## Archivos principales

- `pgdump_production_08-04-2026-22-02-09.sql`: dump de PostgreSQL.
- `test_connection.py`: prueba la conexion con PostgreSQL.
- `faq_models.py`: define las clases de entrada y salida de la API.
- `faq_common.py`: utilidades compartidas, conexion a base de datos y lectura/escritura JSON.
- `ingest_service.py`: extrae conversaciones desde la tabla `chat_messages`.
- `embed_service.py`: genera embeddings semanticos locales.
- `suggestion_service.py`: agrupa conversaciones y crea sugerencias de FAQs.
- `validation_service.py`: permite validar o rechazar sugerencias.
- `scheduler.py`: ejecuta automaticamente la ingesta y las sugerencias cada 24 horas.
- `requirements.txt`: dependencias del proyecto.
- `ARCHITECTURE.md`: explicacion tecnica de la arquitectura.

## 1. Analizar el dump SQL

El archivo analizado fue:

```bash
pgdump_production_08-04-2026-22-02-09.sql
```

Durante el analisis se reviso:

- Estructura general de tablas.
- Sentencias `CREATE TABLE`.
- Bloques de datos tipo `COPY`.
- Posibles comillas inconsistentes.
- Tablas disponibles para consultar desde Python.

No se encontraron inconsistencias de comillas en el dump.

Si la base de datos aun no esta restaurada, usar:

```bash
psql -U postgres -d everwod_db < pgdump_production_08-04-2026-22-02-09.sql
```

## 2. Instalar dependencias

Primero instalar dependencias del sistema:

```bash
sudo apt update
sudo apt install -y libpq-dev python3-dev python3-psycopg2 python3-dotenv
```

Luego instalar las dependencias Python del prototipo:

```bash
pip3 install -r requirements.txt
```

Si Python esta gestionado por el sistema operativo, usar paquetes del sistema cuando sea posible.

## 3. Configurar variables de entorno

Crear un archivo `.env` en la raiz del proyecto:

```env
DB_NAME=everwod_db
DB_USER=postgres
DB_PASSWORD=<tu_password>
DB_HOST=localhost
DB_PORT=5432

# Opcional: modelo local para redactar respuestas sugeridas.
FAQ_LLM_ENABLED=true
FAQ_LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct
FAQ_CLUSTER_EPS=0.34
FAQ_MIN_CLUSTER_SIZE=3
FAQ_SKIP_EXISTING=true
FAQ_DUPLICATE_THRESHOLD=0.78
```

Estas variables son usadas por `test_connection.py`, `faq_common.py` y `suggestion_service.py`.

## 4. Verificar que PostgreSQL este activo

Revisar el estado del servicio:

```bash
sudo systemctl status postgresql
```

Si no esta activo, iniciarlo:

```bash
sudo systemctl start postgresql
```

## 5. Verificar la conexion con la base de datos

Antes de crear o levantar los servicios, probar la conexion:

```bash
python3 test_connection.py
```

El script hace lo siguiente:

- Carga las variables desde `.env`.
- Intenta conectarse a PostgreSQL.
- Consulta el conteo de filas en `chat_messages`.
- Lista las tablas del esquema `public`.
- Cierra la conexión.

Resultado esperado:

```text
Conexión exitosa a PostgreSQL.
Número de filas en 'chat_messages': <cantidad>
Tablas en la base de datos:
- ...
Conexión cerrada.
```

Si falla, revisar usuario, password, puerto, nombre de base de datos y que PostgreSQL este corriendo.

## 6. Orden recomendado para crear las clases y archivos

Este orden ayuda a construir el proyecto paso a paso sin romper dependencias.

### Paso 1: Crear `faq_models.py`

Primero se crean las clases Pydantic porque los servicios las usan para validar requests y responses.

Orden de clases:

1. `IngestRequest`: parametros para importar conversaciones.
2. `IngestResponse`: respuesta despues de importar conversaciones.
3. `EncodeRequest`: textos que se enviaran al servicio de embeddings.
4. `EncodeResponse`: embeddings devueltos por el modelo.
5. `SuggestionResponse`: una sugerencia individual de FAQ.
6. `SuggestionSummary`: resumen completo de todas las sugerencias.
7. `ValidationRequest`: datos enviados por el revisor humano.
8. `ValidationResponse`: confirmacion de la validacion guardada.

### Paso 2: Crear `faq_common.py`

Luego se crea el archivo de utilidades compartidas:

- Define `ROOT_DIR` y `DATA_DIR`.
- Carga `.env`.
- Construye la configuracion de PostgreSQL.
- Crea conexiones con `get_db_connection()`.
- Normaliza texto.
- Guarda y lee archivos JSON y JSONL.

Este archivo se crea antes de los servicios porque todos reutilizan estas funciones.

### Paso 3: Crear `test_connection.py`

Antes de tocar los microservicios, se crea el script de prueba de conexion.

Este paso confirma que:

- El archivo `.env` esta bien configurado.
- PostgreSQL acepta la conexion.
- La tabla `chat_messages` existe.
- Python puede leer la base de datos.

### Paso 4: Crear `ingest_service.py`

Despues se crea el servicio de ingesta.

Responsabilidad:

- Leer mensajes desde `chat_messages`.
- Extraer texto desde estructuras JSON.
- Emparejar mensajes de usuario con respuestas del asistente.
- Guardar el resultado en `data/conversations.jsonl`.

Puerto usado:

```text
8001
```

### Paso 5: Crear `embed_service.py`

Luego se crea el servicio de embeddings.

Responsabilidad:

- Cargar el modelo local `all-MiniLM-L6-v2`.
- Recibir textos.
- Devolver vectores numericos para cada texto.

Puerto usado:

```text
8002
```

### Paso 6: Crear `suggestion_service.py`

Despues se crea el servicio que genera sugerencias.

Responsabilidad:

- Leer `data/conversations.jsonl`.
- Separar conversaciones por empresa usando `company_id`.
- Generar embeddings.
- Agrupar preguntas parecidas por empresa con DBSCAN, descartando ruido conversacional.
- Comparar contra `agent_faqs` por empresa para evitar sugerir FAQs duplicadas.
- Redactar datos personales como nombres, correos y telefonos antes de exponer respuestas o ejemplos.
- Escoger preguntas representativas.
- Redactar respuestas sugeridas con un modelo local tipo Qwen cuando esta habilitado.
- Guardar resultados en `data/faq_suggestions.json`.

Puerto usado:

```text
8003
```

### Paso 7: Crear `validation_service.py`

Luego se crea el servicio de validacion humana.

Responsabilidad:

- Mostrar sugerencias generadas.
- Recibir aprobaciones o rechazos.
- Guardar revisiones en `data/faq_validations.json`.

Puerto usado:

```text
8004
```

### Paso 8: Crear `scheduler.py`

Finalmente se crea el job programado.

Responsabilidad:

- Ejecutar la ingesta.
- Generar sugerencias.
- Repetir el proceso cada 24 horas.

## 7. Paso a paso completo para probar todo con Postman

### 1. Preparar el entorno

En una terminal:

```bash
cd /home/alejandro/Documentos/GenAI/Everwod_IA_FAQs
source venv/bin/activate
```

### 2. Iniciar los servicios

Abrir 3 terminales separadas y ejecutar:

Terminal 1:

```bash
cd /home/alejandro/Documentos/GenAI/Everwod_IA_FAQs
source venv/bin/activate
python3 ingest_service.py
```

Debería mostrar:

```text
INFO:     Uvicorn running on http://127.0.0.1:8001
```

Terminal 2:

```bash
cd /home/alejandro/Documentos/GenAI/Everwod_IA_FAQs
source venv/bin/activate
python3 suggestion_service.py
```

Debería mostrar:

```text
INFO:     Uvicorn running on http://127.0.0.1:8003
```

Nota: si `FAQ_LLM_ENABLED=true`, el primer arranque puede tardar mientras se descarga o carga `Qwen/Qwen2.5-0.5B-Instruct`. Si el modelo no carga, el servicio sigue funcionando con fallback a respuestas historicas.

Terminal 3:

```bash
cd /home/alejandro/Documentos/GenAI/Everwod_IA_FAQs
source venv/bin/activate
python3 validation_service.py
```

Debería mostrar:

```text
INFO:     Uvicorn running on http://127.0.0.1:8004
```

### 3. Crear colección en Postman

Abrir Postman y crear una nueva colección llamada:

```text
Everwod FAQ Prototype
```

Dentro de la colección, crear las siguientes requests.

### 4. Probar estado de servicios

Crear 3 requests `GET`.

Request 1: `Health Ingest`

- Método: `GET`
- URL: `http://127.0.0.1:8001/health`

Enviar y verificar esta respuesta:

```json
{
  "status": "ok",
  "service": "ingest"
}
```

Request 2: `Health Suggestion`

- Método: `GET`
- URL: `http://127.0.0.1:8003/health`

Enviar y verificar esta respuesta:

```json
{
  "status": "ok",
  "service": "suggestion",
  "embedding_model": "all-MiniLM-L6-v2",
  "answer_model": "Qwen/Qwen2.5-0.5B-Instruct"
}
```

Si Qwen no pudo cargarse o se ejecuta con `FAQ_LLM_ENABLED=false`, `answer_model` puede aparecer como:

```json
"historical_fallback"
```

Request 3: `Health Validation`

- Método: `GET`
- URL: `http://127.0.0.1:8004/health`

Enviar y verificar esta respuesta:

```json
{
  "status": "ok",
  "service": "validation"
}
```

### 5. Ejecutar ingesta de conversaciones

Request: `POST Ingest`

- Método: `POST`
- URL: `http://127.0.0.1:8001/ingest`
- Headers: `Content-Type: application/json`

Body > raw > JSON:

```json
{
  "limit": 1000,
  "since_days": 90
}
```

Enviar y verificar una respuesta como esta:

```json
{
  "imported_records": 460,
  "output_file": "/home/alejandro/Documentos/GenAI/Everwod_IA_FAQs/data/conversations.jsonl"
}
```

Nota: en el código actual `output_file` devuelve la ruta completa del archivo. `imported_records` puede ser menor que `limit` porque se guardan pares usuario/asistente, no mensajes individuales. Cada registro queda asociado a `company_id` y `company_name`.

### 6. Generar sugerencias de FAQ

Request: `POST Suggest`

- Método: `POST`
- URL: `http://127.0.0.1:8003/suggest`
- Headers: `Content-Type: application/json`
- Body: vacío

Enviar la request. Puede tardar mientras procesa embeddings, clustering y, si esta habilitado, generacion local con Qwen.

Verificar una respuesta con esta estructura:

```json
{
  "company_count": 4,
  "cluster_count": 2,
  "total_examples": 31,
  "average_cluster_size": 15.5,
  "silhouette_score": null,
  "suggestions": [
    {
      "id": "COPIAR_ESTE_ID",
      "company_id": "74",
      "company_name": "Empire Box Cf",
      "question": "Quiero reservar una clase de cortesía",
      "answer": "Respuesta sugerida basada en conversaciones de la misma empresa",
      "cluster_size": 6,
      "support_examples": [
        "Quiero reservar una clase de cortesía",
        "Quiero empezar a entrenar con Uds, puedo agendar",
        "Si saber si la clase queda reservada para ellos o no?"
      ],
      "cluster_score": 33.33
    }
  ]
}
```

Los valores de `company_count`, `cluster_count`, `total_examples`, `average_cluster_size`, `silhouette_score`, `cluster_size` y `cluster_score` pueden cambiar segun el rango de fechas, el limite usado y los ajustes `FAQ_CLUSTER_EPS` / `FAQ_MIN_CLUSTER_SIZE`.

Importante: `total_examples` representa candidatos reales a FAQ despues de filtrar saludos, respuestas cortas, PII, mensajes conversacionales y preguntas operativas sobre usuarios/personas agendadas. Por eso normalmente sera menor que `imported_records`.

Antes de guardar una sugerencia, el servicio revisa `agent_faqs` para la misma empresa. Si la pregunta sugerida es semanticamente parecida a una FAQ existente, no la incluye en la respuesta.

### 7. Consultar sugerencias generadas

Request: `GET Suggestions`

- Método: `GET`
- URL: `http://127.0.0.1:8003/suggestions`

Enviar y verificar que la respuesta sea un JSON con:

- `company_count`
- `cluster_count`
- `total_examples`
- `suggestions`

La propiedad `suggestions` debe ser una lista de FAQs sugeridas. Cada sugerencia debe incluir `company_id` y `company_name`; esto confirma que no se estan mezclando empresas. Copiar un `id` real de esa lista para usarlo como `suggestion_id` en el siguiente paso.

### 8. Validar una sugerencia

Request: `POST Validate`

- Método: `POST`
- URL: `http://127.0.0.1:8004/validate`
- Headers: `Content-Type: application/json`

Body > raw > JSON:

```json
{
  "suggestion_id": "COPIA_EL_ID_AQUI",
  "reviewer": "Alejandro",
  "status": "approved",
  "notes": "Esta sugerencia es válida"
}
```

Enviar y verificar una respuesta con los detalles de la validación:

```json
{
  "suggestion_id": "COPIA_EL_ID_AQUI",
  "reviewer": "Alejandro",
  "status": "approved",
  "notes": "Esta sugerencia es válida",
  "reviewed_at": "2026-05-03T12:00:00.000000"
}
```

Estados sugeridos para `status`:

- `approved`
- `rejected`
- `needs_changes`

### 9. Ver validaciones guardadas

Request: `GET Validations`

- Método: `GET`
- URL: `http://127.0.0.1:8004/validations`

Enviar y verificar que la respuesta sea una lista de validaciones humanas:

```json
[
  {
    "suggestion_id": "COPIA_EL_ID_AQUI",
    "reviewer": "Alejandro",
    "status": "approved",
    "notes": "Esta sugerencia es válida",
    "reviewed_at": "2026-05-03T12:00:00.000000"
  }
]
```

## Notas adicionales

- El dump contiene datos de produccion; manejarlo con cuidado.
- Si cambia el nombre de la base de datos, actualizar `.env`.
- Si `chat_messages` no existe, revisar el nombre real de la tabla en la salida de `test_connection.py`.
- El primer arranque de los modelos de embeddings puede tardar porque se carga el modelo local.
