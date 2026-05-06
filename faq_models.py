from datetime import datetime
from pydantic import BaseModel, Field
from typing import List, Optional


# Parametros que recibe el servicio de ingesta para leer conversaciones historicas.
class IngestRequest(BaseModel):
    # Cantidad maxima de mensajes que se consultaran en PostgreSQL.
    limit: int = Field(15000, ge=100, le=50000)
    # Ventana de tiempo, en dias, para traer solo conversaciones recientes.
    since_days: int = Field(90, ge=1, le=365)


# Respuesta del servicio de ingesta despues de crear el archivo JSONL.
class IngestResponse(BaseModel):
    # Numero de pares usuario/asistente importados.
    imported_records: int
    # Ruta del archivo donde quedaron guardadas las conversaciones procesadas.
    output_file: str


# Cuerpo que recibe el servicio de embeddings.
class EncodeRequest(BaseModel):
    # Lista de textos que se convertiran en vectores numericos.
    texts: List[str]


# Respuesta con los embeddings generados.
class EncodeResponse(BaseModel):
    # Un embedding por cada texto valido recibido.
    embeddings: List[List[float]]
    # Cantidad final de textos procesados.
    count: int


# Representa una sugerencia individual de FAQ.
class SuggestionResponse(BaseModel):
    # Identificador unico para validar la sugerencia mas adelante.
    id: str
    # Empresa a la que pertenece la sugerencia.
    company_id: str
    # Nombre de empresa si pudo extraerse desde la base de datos.
    company_name: Optional[str] = None
    # Pregunta representativa del grupo de conversaciones similares.
    question: str
    # Respuesta sugerida segun las respuestas historicas del asistente.
    answer: str
    # Cantidad de ejemplos que cayeron en el mismo cluster.
    cluster_size: int
    # Ejemplos reales que soportan la sugerencia.
    support_examples: List[str]
    # Porcentaje aproximado de soporte del cluster sobre el total.
    cluster_score: float


# Resumen completo de la ejecucion del servicio de sugerencias.
class SuggestionSummary(BaseModel):
    # Numero de empresas analizadas en la ejecucion.
    company_count: int
    # Numero total de grupos detectados.
    cluster_count: int
    # Cantidad de textos usados para generar los clusters.
    total_examples: int
    # Tamano promedio de cada cluster.
    average_cluster_size: float
    # Metrica opcional de separacion entre clusters.
    silhouette_score: Optional[float]
    # Lista de sugerencias generadas.
    suggestions: List[SuggestionResponse]


# Datos que envia una persona para aprobar, rechazar o pedir cambios.
class ValidationRequest(BaseModel):
    # ID de la sugerencia que se va a revisar.
    suggestion_id: str
    # Nombre o identificador de quien revisa.
    reviewer: str
    # Estado de la revision: approved, rejected o needs_changes.
    status: str
    # Comentario opcional de la revision.
    notes: Optional[str] = None
    # Fecha opcional; si no se envia, el servicio usa la fecha actual.
    reviewed_at: Optional[datetime] = None


# Respuesta guardada despues de validar una sugerencia.
class ValidationResponse(BaseModel):
    # ID de la sugerencia revisada.
    suggestion_id: str
    # Revisor que hizo la validacion.
    reviewer: str
    # Estado final registrado.
    status: str
    # Comentarios asociados a la revision.
    notes: Optional[str] = None
    # Fecha exacta en la que quedo registrada la revision.
    reviewed_at: datetime
