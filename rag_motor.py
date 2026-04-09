import os
import psycopg2
import anthropic
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

# ── Compatibilidad local (.env) y Streamlit Cloud (secrets) ──────────────────
try:
    import streamlit as st
    DB_URL     = os.getenv("SUPABASE_DB_URL") or st.secrets.get("SUPABASE_DB_URL")
    CLAUDE_KEY = os.getenv("ANTHROPIC_API_KEY") or st.secrets.get("ANTHROPIC_API_KEY")
except Exception:
    DB_URL     = os.getenv("SUPABASE_DB_URL")
    CLAUDE_KEY = os.getenv("ANTHROPIC_API_KEY")

# ── Singletons ────────────────────────────────────────────────────────────────
_model  = None
_client = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model

def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=CLAUDE_KEY)
    return _client


# ── Búsqueda semántica ────────────────────────────────────────────────────────
def buscar_chunks(pregunta: str, top_k: int = 15, dimension: str = None) -> list[dict]:
    """Convierte la pregunta en embedding y recupera los chunks más similares."""
    embedding     = get_model().encode(pregunta).tolist()
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

    if dimension:
        query  = """
            SELECT texto, anio, actividad, sector, tipo_precio, valor, fuente,
                   1 - (embedding <=> %s::vector) AS similitud
            FROM indicadores
            WHERE dimension = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
        """
        params = [embedding_str, dimension, embedding_str, top_k]
    else:
        query  = """
            SELECT texto, anio, actividad, sector, tipo_precio, valor, fuente,
                   1 - (embedding <=> %s::vector) AS similitud
            FROM indicadores
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
        """
        params = [embedding_str, embedding_str, top_k]

    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()
    cur.execute("SET ivfflat.probes = 5;")
    cur.execute(query, params)
    filas = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            "texto":       f[0],
            "anio":        f[1],
            "actividad":   f[2],
            "sector":      f[3],
            "tipo_precio": f[4],
            "valor":       f[5],
            "fuente":      f[6],
            "similitud":   round(float(f[7]), 3),
        }
        for f in filas
    ]


# ── Prompt ────────────────────────────────────────────────────────────────────
def construir_prompt(pregunta: str, chunks: list[dict]) -> str:
    contexto = "\n\n".join(
        f"[{i+1}] {c['texto']}" for i, c in enumerate(chunks)
    )
    return f"""Eres el Asistente del Observatorio de Boyacá, una herramienta de consulta ciudadana
que responde preguntas sobre indicadores oficiales del departamento de Boyacá, Colombia.

REGLAS:
- Responde ÚNICAMENTE con base en el contexto provisto. Si la información no está disponible,
  dilo de forma clara y neutral, sin recomendar otras fuentes externas.
- Nunca menciones que "no tienes acceso" ni hables en primera persona como sistema técnico.
- Habla como un asistente informativo dirigido al ciudadano: claro, directo y en español.
- Siempre menciona el año, el municipio y la fuente al citar un dato.
- Si hay datos parciales, preséntales y aclara que corresponden a los registros disponibles.
- Si preguntan por un indicador que no está en el contexto, responde:
  "En este momento no se cuenta con información disponible sobre ese indicador en el observatorio."

INSTRUCCIONES ADICIONALES:
- Los datos están desagregados por municipio y período. Si preguntan por el total
  departamental, suma los valores disponibles y acláralo.
- Si hay datos de varios años, puedes calcular variaciones porcentuales entre ellos.
- Cuando pregunten por impacto de un evento (COVID, crisis, etc.), busca datos de los años
  inmediatamente anteriores y posteriores para mostrar la variación.
- Sé concreto con los números: menciona valores en sus unidades originales.

CONTEXTO:
{contexto}

PREGUNTA:
{pregunta}

RESPUESTA:"""


# ── Meta-preguntas (¿qué información tienes?) ─────────────────────────────────
META_KEYWORDS = [
    "qué información", "que información",
    "qué datos", "que datos",
    "qué tienes disponible", "información disponible", "datos disponibles",
    "qué puedes responder", "sobre qué puedes",
    "qué dimensiones", "qué temas", "que temas",
    "qué indicadores", "que indicadores",
    "qué hay disponible", "que hay disponible",
    "qué contiene", "que contiene",
]

def es_meta_pregunta(pregunta: str) -> bool:
    p = pregunta.lower()
    return any(kw in p for kw in META_KEYWORDS)

def respuesta_meta(dimension: str = None) -> dict:
    """Consulta directamente la BD y devuelve un resumen real de los datos disponibles."""
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    if dimension:
        cur.execute("""
            SELECT dimension,
                   COUNT(DISTINCT actividad) AS indicadores,
                   COUNT(*)                  AS registros,
                   MIN(anio)                 AS desde,
                   MAX(anio)                 AS hasta
            FROM indicadores
            WHERE dimension = %s
            GROUP BY dimension;
        """, (dimension,))
    else:
        cur.execute("""
            SELECT dimension,
                   COUNT(DISTINCT actividad) AS indicadores,
                   COUNT(*)                  AS registros,
                   MIN(anio)                 AS desde,
                   MAX(anio)                 AS hasta
            FROM indicadores
            GROUP BY dimension
            ORDER BY dimension;
        """)

    filas = cur.fetchall()
    cur.close()
    conn.close()

    if not filas:
        return {
            "respuesta": "En este momento no se encontró información en la base de datos del observatorio.",
            "fuentes":   [],
        }

    emojis = {"Económica": "📈", "Salud": "🏥", "Violencia": "🛡️"}
    lineas = []
    for dim, indicadores, registros, desde, hasta in filas:
        em = emojis.get(dim, "📊")
        lineas.append(
            f"{em} **{dim}**: {indicadores} indicadores distintos · "
            f"{registros:,} registros · período {desde}–{hasta}"
        )

    respuesta = (
        "El Observatorio de Boyacá cuenta actualmente con la siguiente información disponible:\n\n" +
        "\n\n".join(lineas) +
        "\n\nPuedes usar el selector de dimensión para filtrar y hacer preguntas específicas "
        "sobre municipios, años o indicadores de tu interés."
    )
    return {"respuesta": respuesta, "fuentes": []}


# ── Función principal ─────────────────────────────────────────────────────────
def responder(pregunta: str, dimension: str = None) -> dict:
    """Recibe una pregunta y devuelve respuesta + fuentes utilizadas."""

    # Detectar preguntas sobre disponibilidad de datos
    if es_meta_pregunta(pregunta):
        return respuesta_meta(dimension)

    chunks = buscar_chunks(pregunta, top_k=15, dimension=dimension)

    if not chunks:
        return {
            "respuesta": "En este momento no se cuenta con información disponible sobre ese indicador en el observatorio.",
            "fuentes":   [],
        }

    prompt  = construir_prompt(pregunta, chunks)
    mensaje = get_client().messages.create(
        model      = "claude-haiku-4-5",
        max_tokens = 1024,
        messages   = [{"role": "user", "content": prompt}],
    )

    return {
        "respuesta": mensaje.content[0].text,
        "fuentes":   chunks,
    }


# ── Test rápido ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    preguntas = [
        "¿Qué información tienes disponible?",
        "¿Cuál fue el PIB de Boyacá en 2023 y cuánto creció respecto a 2022?",
        "¿Cuántos feminicidios se registraron en Boyacá en 2025?",
    ]
    for p in preguntas:
        print(f"\n{'='*60}")
        print(f"Pregunta: {p}")
        print(f"{'='*60}")
        r = responder(p)
        print(r["respuesta"])
        if r["fuentes"]:
            print(f"\nFuentes ({len(r['fuentes'])}):")
            for f in r["fuentes"][:2]:
                print(f"  · {f['texto'][:90]}...")
