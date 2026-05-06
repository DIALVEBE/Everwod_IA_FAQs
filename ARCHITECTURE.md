# Arquitectura Técnica del Sistema de Sugerencia Automática de FAQs

## Objetivo

El sistema analiza conversaciones históricas almacenadas en PostgreSQL para detectar preguntas frecuentes nuevas por empresa. El resultado no se inserta directamente como FAQ final: se guarda como sugerencia en `data/faq_suggestions.json` para revisión humana posterior.

El diseño evita tres problemas importantes:

- Mezclar conversaciones de empresas distintas.
- Generar FAQs a partir de saludos, mensajes operativos o datos personales.
- Proponer una FAQ que ya existe en la tabla `agent_faqs`.

## Componentes

### 1. PostgreSQL

La base de datos es la fuente principal. Las tablas usadas por el pipeline son:

- `chat_messages`: mensajes crudos del historial conversacional.
- `agent_chats`: metadatos de la conversación, incluido `workspace_id`.
- `workspaces`: empresa o workspace asociado al chat.
- `agents`: relaciona agentes con `workspace_id`.
- `agent_faqs`: FAQs existentes, usadas para deduplicación.

Relaciones relevantes:

```text
chat_messages.agent_chat_id -> agent_chats.id
agent_chats.workspace_id    -> workspaces.id
agent_faqs.agent_id         -> agents.id
agents.workspace_id         -> workspaces.id
```

### 2. Ingest Service

Archivo: `ingest_service.py`

Responsabilidad:

- Leer mensajes recientes desde PostgreSQL.
- Unir cada mensaje con su `workspace_id` y nombre de empresa.
- Extraer texto desde JSON usando `json_text`.
- Emparejar cada mensaje de usuario con la siguiente respuesta del asistente.
- Guardar los pares en `data/conversations.jsonl`.

Consulta base:

```sql
SELECT cm.agent_chat_id, cm.message, cm.created_at, ac.workspace_id, w.name
FROM chat_messages cm
JOIN agent_chats ac ON ac.id = cm.agent_chat_id
LEFT JOIN workspaces w ON w.id = ac.workspace_id
WHERE cm.created_at >= %s
ORDER BY ac.workspace_id, cm.agent_chat_id, cm.created_at
LIMIT %s
```

Formato de salida JSONL:

```json
{
  "company_id": "74",
  "company_name": "Empire Box Cf",
  "conversation_id": "uuid-del-chat",
  "user_text": "Quisiera agendar clase de cortesía",
  "assistant_text": "Respuesta histórica del asistente",
  "created_at": "2026-05-06T10:30:00"
}
```

### 3. Suggestion Service

Archivo: `suggestion_service.py`

Responsabilidad:

- Leer `data/conversations.jsonl`.
- Separar conversaciones por `company_id`.
- Filtrar candidatos no útiles.
- Calcular embeddings semánticos.
- Agrupar preguntas similares dentro de la misma empresa.
- Comparar contra FAQs ya existentes en `agent_faqs`.
- Generar una respuesta sugerida con un modelo local tipo Qwen o fallback histórico.
- Guardar el resumen en `data/faq_suggestions.json`.

### 4. Validation Service

Archivo: `validation_service.py`

Responsabilidad:

- Exponer las sugerencias generadas.
- Permitir que una persona marque cada sugerencia como `approved`, `rejected` o `needs_changes`.
- Guardar revisiones en `data/faq_validations.json`.

El servicio no escribe todavía en `agent_faqs`; mantiene una etapa de revisión humana antes de cualquier promoción a FAQ real.

### 5. Scheduler

Archivo: `scheduler.py`

Responsabilidad:

- Ejecutar ingesta.
- Ejecutar generación de sugerencias.
- Repetir el pipeline cada 24 horas con `APScheduler`.

## Modelos Usados

### Modelo de Embeddings

Modelo configurado:

```text
all-MiniLM-L6-v2
```

Uso:

- Convertir preguntas de usuarios a vectores numéricos.
- Medir similitud semántica entre preguntas.
- Clusterizar preguntas recurrentes.
- Detectar duplicados contra FAQs existentes.

Implementación:

```python
SentenceTransformer("all-MiniLM-L6-v2")
```

Características:

- Liviano.
- Ejecutable en CPU.
- Adecuado para textos cortos.
- Buen balance entre velocidad y calidad para clustering semántico.

### Modelo Generativo Local

Modelo por defecto:

```text
Qwen/Qwen2.5-0.5B-Instruct
```

Uso:

- Recibir una pregunta FAQ candidata.
- Recibir ejemplos reales y respuestas históricas de la misma empresa.
- Redactar una respuesta final más limpia y útil.

Implementación:

```python
AutoTokenizer.from_pretrained(FAQ_LLM_MODEL)
AutoModelForCausalLM.from_pretrained(FAQ_LLM_MODEL)
pipeline("text-generation", model=model, tokenizer=tokenizer)
```

El modelo se controla desde `.env`:

```env
FAQ_LLM_ENABLED=true
FAQ_LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct
```

Si el modelo no puede cargarse, el servicio usa fallback histórico: toma una respuesta previa del mismo cluster, pasando primero por limpieza de datos personales.

## Flujo de Trabajo Completo

### Paso 1. Ingesta

Endpoint:

```text
POST /ingest
```

Entrada:

```json
{
  "limit": 1000,
  "since_days": 90
}
```

Proceso:

1. Calcula una fecha mínima con `since_days`.
2. Consulta `chat_messages`, unido a `agent_chats` y `workspaces`.
3. Agrupa mensajes por `agent_chat_id`.
4. Ordena cada conversación por `created_at`.
5. Empareja `role=user` con el siguiente `role=assistant`.
6. Guarda cada par con `company_id` y `company_name`.

Salida:

```json
{
  "imported_records": 460,
  "output_file": "/ruta/data/conversations.jsonl"
}
```

### Paso 2. Separación por Empresa

El servicio de sugerencias agrupa los registros así:

```python
conversations_by_company[company_id].append(item)
```

Esto garantiza que una pregunta de `Empire Box Cf` nunca se agrupe con preguntas de otra empresa.

### Paso 3. Filtro de Candidatos FAQ

Función principal:

```python
is_good_faq_candidate(text)
```

Descarta:

- Mensajes muy cortos.
- Mensajes demasiado largos.
- Saludos simples.
- `si`, `no`, `ok`, `gracias`.
- Correos.
- Teléfonos.
- Preguntas sobre identidad del usuario: “quién soy”, “qué rol tengo”.
- Preguntas temporales: “qué hora es”.
- Preguntas operativas sobre personas agendadas o usuarios asistentes.

Luego exige dos señales:

- Señal de pregunta o intención: `cómo`, `cuánto`, `dónde`, `quiero`, `quisiera`, `me puedes`, etc.
- Intención de negocio: precios, planes, horarios, ubicación, reserva, clase, pago, CrossFit, información, etc.

El objetivo es que `total_examples` represente candidatos reales a FAQ, no todos los mensajes importados.

### Paso 4. Limpieza de Datos Personales

Función principal:

```python
redact_personal_data(text, protected_terms)
```

Redacta:

- Correos como `[correo]`.
- Teléfonos como `[telefono]`.
- Nombres de clientes como `[persona]`.
- Listas de nombres como `[personas]`.

Ejemplo:

```text
¡Hola, Andrea Porras! Gracias por escribir a Empire Box Cf.
```

queda como:

```text
¡Hola! Gracias por escribir a Empire Box Cf.
```

El nombre de la empresa se pasa como término protegido para no borrarlo accidentalmente.

### Paso 5. Embeddings

Para cada empresa se calculan embeddings normalizados:

```python
EMBEDDING_MODEL.encode(
    user_texts,
    convert_to_numpy=True,
    normalize_embeddings=True
)
```

La normalización permite usar producto punto y distancia coseno de forma estable.

### Paso 6. Clustering Semántico

Algoritmo usado:

```text
DBSCAN
```

Configuración:

```env
FAQ_CLUSTER_EPS=0.34
FAQ_MIN_CLUSTER_SIZE=3
```

Implementación:

```python
DBSCAN(
    eps=FAQ_CLUSTER_EPS,
    min_samples=FAQ_MIN_CLUSTER_SIZE,
    metric="cosine"
)
```

Motivo para usar DBSCAN:

- No obliga todos los mensajes a pertenecer a un cluster.
- Marca como ruido los mensajes aislados.
- Funciona mejor cuando no sabemos cuántas FAQs nuevas hay.

La versión anterior usaba KMeans, pero KMeans siempre asigna cada punto a un cluster. Eso hacía que saludos, respuestas sueltas o preguntas de baja calidad terminaran mezcladas como si fueran una FAQ real.

### Paso 7. Selección de Pregunta Representativa

Para cada cluster:

1. Calcula el centro promedio de los embeddings del cluster.
2. Normaliza ese centro.
3. Escoge la pregunta con mayor similitud al centro.

Esto selecciona la pregunta más representativa del grupo, no necesariamente la primera.

Además calcula un soporte interno:

```python
support = mean(dot(embedding, cluster_center))
```

Si el soporte es menor a `0.68`, el cluster se descarta.

### Paso 8. Deduplicación contra FAQs Existentes

Función principal:

```python
load_existing_faqs_by_company()
```

Consulta:

```sql
SELECT a.workspace_id, af.question
FROM agent_faqs af
JOIN agents a ON a.id = af.agent_id
WHERE af.deleted_at IS NULL
  AND af.question IS NOT NULL
```

Luego compara la pregunta sugerida contra las preguntas existentes de la misma empresa.

Umbral:

```env
FAQ_SKIP_EXISTING=true
FAQ_DUPLICATE_THRESHOLD=0.78
```

Si la similitud semántica máxima supera `FAQ_DUPLICATE_THRESHOLD`, la sugerencia se omite.

Esto evita crear otra FAQ igual o demasiado parecida a una que ya existe.

### Paso 9. Generación de Respuesta

Función principal:

```python
generate_answer(question, examples, historical_answers, company_name)
```

Entrada para el modelo:

- Nombre de empresa.
- Pregunta candidata.
- Ejemplos reales del mismo cluster.
- Respuestas históricas del asistente para esos ejemplos.

Reglas del prompt:

- Responder en español.
- Usar solo la evidencia entregada.
- No mezclar empresas.
- No inventar datos.
- No incluir nombres, teléfonos, correos ni datos personales.
- Si falta información, responder de forma prudente.

Si Qwen no está disponible:

```python
most_common_answer(historical_answers)
```

Ese fallback también pasa por `redact_personal_data`.

### Paso 10. Persistencia de Sugerencias

Archivo:

```text
data/faq_suggestions.json
```

Formato:

```json
{
  "company_count": 4,
  "cluster_count": 1,
  "total_examples": 25,
  "average_cluster_size": 25.0,
  "silhouette_score": null,
  "suggestions": [
    {
      "id": "uuid",
      "company_id": "74",
      "company_name": "Empire Box Cf",
      "question": "Quiero reservar una clase de cortesía",
      "answer": "Respuesta sugerida",
      "cluster_size": 4,
      "support_examples": [
        "Quisiera agendar clase de cortesía",
        "Quisiera programar mis clases de cortesía"
      ],
      "cluster_score": 57.14
    }
  ]
}
```

Campos:

- `company_count`: empresas analizadas en el archivo de conversaciones.
- `cluster_count`: sugerencias finales generadas.
- `total_examples`: mensajes que pasaron filtros como candidatos FAQ.
- `average_cluster_size`: promedio aproximado de ejemplos por sugerencia.
- `silhouette_score`: métrica de separación cuando hay suficientes clusters válidos.
- `cluster_size`: cantidad de ejemplos dentro del cluster.
- `cluster_score`: porcentaje de soporte dentro de los candidatos FAQ de esa empresa.

### Paso 11. Validación Humana

Endpoint:

```text
POST /validate
```

Entrada:

```json
{
  "suggestion_id": "uuid",
  "reviewer": "Alejandro",
  "status": "approved",
  "notes": "Esta FAQ es útil"
}
```

Salida guardada en:

```text
data/faq_validations.json
```

Estados recomendados:

- `approved`
- `rejected`
- `needs_changes`

## APIs

### Ingest

```text
GET  /health
POST /ingest
```

Puerto:

```text
8001
```

### Embedding

```text
GET  /health
POST /encode
```

Puerto:

```text
8002
```

Nota: el pipeline actual usa embeddings directamente dentro de `suggestion_service.py`; `embed_service.py` queda disponible como servicio independiente para pruebas o integraciones.

### Suggestion

```text
GET  /health
POST /suggest
GET  /suggestions
```

Puerto:

```text
8003
```

### Validation

```text
GET  /health
GET  /suggestions
GET  /validations
POST /validate
```

Puerto:

```text
8004
```

## Configuración

Variables de entorno principales:

```env
DB_NAME=everwod_db
DB_USER=postgres
DB_PASSWORD=<password>
DB_HOST=localhost
DB_PORT=5432

FAQ_LLM_ENABLED=true
FAQ_LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct

FAQ_CLUSTER_EPS=0.34
FAQ_MIN_CLUSTER_SIZE=3

FAQ_SKIP_EXISTING=true
FAQ_DUPLICATE_THRESHOLD=0.78
```

Impacto de variables:

- `FAQ_LLM_ENABLED`: activa o desactiva la generación con Qwen.
- `FAQ_LLM_MODEL`: permite cambiar el modelo generativo local.
- `FAQ_CLUSTER_EPS`: controla qué tan cerca deben estar las preguntas para agruparse. Menor valor significa clusters más estrictos.
- `FAQ_MIN_CLUSTER_SIZE`: mínimo de ejemplos para considerar una FAQ recurrente.
- `FAQ_SKIP_EXISTING`: activa deduplicación contra `agent_faqs`.
- `FAQ_DUPLICATE_THRESHOLD`: similitud mínima para considerar que una FAQ sugerida ya existe.

## Consideraciones de Calidad

### Privacidad

El sistema redácta datos personales antes de generar respuestas y antes de exponer ejemplos. Aun así, se mantiene validación humana porque las respuestas vienen de conversaciones históricas y pueden requerir revisión.

### Precisión

El sistema prioriza precisión sobre cantidad. Es esperable que genere pocas sugerencias si:

- Hay pocos mensajes recientes.
- Las preguntas no se repiten.
- Los mensajes son saludos o conversaciones operativas.
- La FAQ ya existe en `agent_faqs`.
- El cluster no supera el soporte semántico mínimo.

### Separación por empresa

Todo el clustering ocurre después de agrupar por `company_id`. Esto evita que patrones de una empresa contaminen las sugerencias de otra.

### Fallback

Si Qwen no carga, el servicio no falla. Usa una respuesta histórica del cluster, anonimizada. Esto permite que el pipeline siga funcionando en ambientes sin GPU o sin modelo descargado.

## Ejecución Local

Instalar dependencias:

```bash
pip install -r requirements.txt
```

Levantar servicios:

```bash
python3 ingest_service.py
python3 embed_service.py
python3 suggestion_service.py
python3 validation_service.py
```

Ejecutar scheduler:

```bash
python3 scheduler.py
```

Flujo manual recomendado:

1. `POST http://127.0.0.1:8001/ingest`
2. `POST http://127.0.0.1:8003/suggest`
3. `GET http://127.0.0.1:8003/suggestions`
4. `POST http://127.0.0.1:8004/validate`

## Extensiones Futuras

- Crear un endpoint para promover sugerencias aprobadas hacia `agent_faqs`.
- Guardar métricas históricas de clusters por ejecución.
- Agregar pruebas automatizadas para filtros, redacción de PII y deduplicación.
- Evaluar modelos de embeddings multilingües si aparecen consultas en varios idiomas.
- Añadir HDBSCAN si se quiere clustering jerárquico con densidad variable.
- Crear un panel para revisión humana en lugar de depender solo de Postman.
