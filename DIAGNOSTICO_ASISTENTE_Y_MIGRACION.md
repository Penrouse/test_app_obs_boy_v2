# Diagnóstico del asistente y plan de migración de ingesta (alternativa a Supabase Free)

Fecha: 2026-04-09

## 1) Diagnóstico rápido del repositorio

### Arquitectura actual
- **Interfaz:** Streamlit (`app.py`).
- **Motor RAG:** búsqueda semántica en Postgres + generación con Anthropic (`rag_motor.py`).
- **Ingesta:** scripts separados por dimensión (`ingestar_pib.py`, `ingestar_salud.py`, `ingestar_violencia.py`) y enriquecimiento (`agregar_resumenes.py`).
- **Base de datos:** PostgreSQL con `pgvector`, hoy en Supabase.

### Hallazgos clave
1. **Conexión a BD por consulta, sin pool**
   - `rag_motor.py` abre/cierra conexión en cada llamada de recuperación.
   - Impacto: latencia innecesaria y peor comportamiento bajo concurrencia.

2. **Sin umbral mínimo de similitud para contexto**
   - Siempre se envían `top_k` chunks al LLM aunque puedan ser poco relevantes.
   - Impacto: respuestas más ruidosas y potenciales “alucinaciones por contexto incorrecto”.

3. **Ingesta no idempotente (riesgo de duplicados)**
   - Las ingestas hacen `INSERT` directo sin `ON CONFLICT`.
   - Impacto: si corres scripts varias veces, puedes duplicar registros y sesgar resultados.

4. **Sin esquema explícito de versionado de ingestas**
   - No hay trazabilidad de lote (`batch_id`, `ingested_at`, hash de fuente).
   - Impacto: difícil auditar qué datos entraron y cuándo.

5. **Dependencia directa de proveedor para disponibilidad (Supabase Free)**
   - Si el proyecto entra en pausa por inactividad, el asistente queda “frío/no disponible”.

6. **Observabilidad mínima**
   - No hay métricas de recuperación (recall efectivo, similitud promedio) ni trazas por consulta.
   - Impacto: complicado diagnosticar calidad y costos.

## 2) Mejoras priorizadas para este asistente

## Prioridad alta (hacer primero)
1. **Agregar idempotencia en ingesta**
   - Crear clave única natural (por ejemplo: `dimension, anio, departamento, actividad, sector, tipo_precio, fuente, texto_hash`).
   - Cambiar a `INSERT ... ON CONFLICT ... DO UPDATE`.

2. **Filtrar chunks por similitud mínima**
   - Ejemplo inicial: descartar resultados `< 0.35` (ajustable por evaluación).
   - Si no supera umbral, devolver mensaje de “no disponible” en vez de inventar.

3. **Pool de conexiones + timeouts SQL**
   - Usar `psycopg2.pool.SimpleConnectionPool` o SQLAlchemy pool.
   - Definir `statement_timeout` y `connect_timeout`.

4. **Separar configuración por entorno**
   - Variables como `TOP_K`, `SIMILARITY_MIN`, `MODEL_NAME`, `DB_POOL_SIZE`.

## Prioridad media
5. **Re-ranking híbrido (semántico + keyword/BM25)**
   - Mejora preguntas exactas de indicador/municipio/año.

6. **Telemetría mínima**
   - Guardar: pregunta, latencia, top similitud, dimensión, número de chunks útiles.

7. **Pruebas automáticas de calidad RAG**
   - Set de 20–50 preguntas canónicas con expected facts.

## 3) ¿A qué base de datos gratuita migrar para evitar la pausa de Supabase Free?

## Recomendación principal: **Neon (Postgres serverless + pgvector)**

### Por qué encaja con tu repo
- Tu código ya usa `psycopg2` y SQL de Postgres con `vector`.
- Migración de bajo esfuerzo: normalmente cambias `SUPABASE_DB_URL` por `NEON_DB_URL` (o reutilizas el mismo nombre de variable).
- Neon mantiene `pgvector` en su propuesta para AI/RAG y ofrece plan Free con autoscaling.

### Consideraciones reales
- Neon también es serverless: puede escalar a cero si configuras autosuspend.
- Diferencia práctica: en muchos casos el “cold start” es más corto y configurable, pero **no existe “always on gratis ilimitado”** en casi ningún proveedor.

## Alternativas gratuitas a evaluar
- **Turso (SQLite distribuido):** muy buen free tier para apps ligeras, pero implica cambiar de Postgres a SQLite + capa vectorial alternativa.
- **Qdrant Cloud Free:** excelente si separas vector DB del relacional, pero te obliga a rediseñar parte del pipeline (metadatos + vectores fuera de Postgres).
- **Cloudflare D1:** útil para SQL serverless económico, pero no es reemplazo 1:1 de Postgres+pgvector para este diseño.

## 4) Plan de migración sugerido (Supabase -> Neon) sin romper la app

1. **Crear proyecto en Neon** y habilitar extensión:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

2. **Replicar esquema `indicadores`** (mismo DDL que usas en Supabase).

3. **Backfill inicial**
   - Exporta de Supabase (`COPY`/dump) e importa en Neon.
   - Verifica conteos por dimensión y rango de años.

4. **Cambiar variable de entorno**
   - `.env`:

```bash
SUPABASE_DB_URL="postgresql://...neon..."
```

5. **Prueba smoke local**
   - Ejecutar una consulta de similitud y una pregunta end-to-end.

6. **Activar dual-run temporal (opcional)**
   - Durante 24–72h, comparar respuestas Supabase vs Neon para detectar desviaciones.

## 5) Mejora de ingesta para cualquier DB (incluida Neon)

## Checklist técnico
- [ ] `batch_id` por corrida.
- [ ] `ingested_at` en UTC.
- [ ] hash determinístico por registro (`sha256(texto_normalizado + claves)`), con índice único.
- [ ] `ON CONFLICT DO UPDATE`.
- [ ] validación de nulos y tipos antes de embed.
- [ ] logging por lote: insertados, actualizados, rechazados.
- [ ] reintentos exponenciales para fallos transitorios de red.

## Patrón SQL recomendado

```sql
INSERT INTO indicadores (
  dimension, texto, anio, departamento, actividad, sector,
  tipo_precio, valor, fuente, embedding, texto_hash, batch_id, ingested_at
)
VALUES (...)
ON CONFLICT (texto_hash)
DO UPDATE SET
  valor = EXCLUDED.valor,
  embedding = EXCLUDED.embedding,
  ingested_at = EXCLUDED.ingested_at,
  batch_id = EXCLUDED.batch_id;
```

---

## 6) Verificación de información de planes (consultada hoy)

- Supabase docs confirman que proyectos Free con actividad muy baja pueden pausarse tras ~7 días; además, hay ventana de restauración de 90 días desde 2024-06-24.
- Neon pricing/docs muestran plan Free y enfoque serverless con autoscaling/scale-to-zero.
- Turso publica plan Free con límites claros y novedades sobre comportamiento de “cold starts”.
- Qdrant Cloud documenta clúster Free y también suspensión por inactividad en su free tier.

> Conclusión práctica: si tu objetivo es “cero pausas en free tier”, no hay bala de plata; la estrategia robusta es (a) proveedor más compatible (Neon), (b) idempotencia + backups, y (c) mecanismo de calentamiento/control de latencia si aplica.
