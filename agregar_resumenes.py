import os
import psycopg2
from psycopg2.extras import execute_values
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("SUPABASE_DB_URL")
FUENTE = "DANE – Observatorio Boyacá"

print("Cargando modelo de embeddings...")
model = SentenceTransformer("all-MiniLM-L6-v2")

# ── Leer totales anuales desde Supabase ───────────────────────────────────────
print("Consultando totales anuales...")
conn = psycopg2.connect(DB_URL)
cur  = conn.cursor()

cur.execute("""
    SELECT anio,
           ROUND(SUM(valor)::numeric, 2) AS pib_corriente
    FROM indicadores
    WHERE tipo_precio = 'PIB a precios corrientes'
    GROUP BY anio
    ORDER BY anio;
""")
corrientes = {row[0]: float(row[1]) for row in cur.fetchall()}

cur.execute("""
    SELECT anio,
           ROUND(SUM(valor)::numeric, 2) AS pib_constante
    FROM indicadores
    WHERE tipo_precio = 'PIB a precios constantes de 2015'
    GROUP BY anio
    ORDER BY anio;
""")
constantes = {row[0]: float(row[1]) for row in cur.fetchall()}

cur.close()
conn.close()

# ── Construir chunks de resumen con variación interanual ──────────────────────
años = sorted(set(list(corrientes.keys()) + list(constantes.keys())))
chunks = []

for i, anio in enumerate(años):
    pib_c = corrientes.get(anio)
    pib_k = constantes.get(anio)

    # Variación corriente
    var_c = ""
    if i > 0:
        anio_ant = años[i - 1]
        if anio_ant in corrientes and pib_c:
            delta = ((pib_c - corrientes[anio_ant]) / corrientes[anio_ant]) * 100
            var_c = f" Esto representa una variación de {delta:+.1f}% respecto a {anio_ant} (precios corrientes)."

    # Variación constante
    var_k = ""
    if i > 0:
        anio_ant = años[i - 1]
        if anio_ant in constantes and pib_k:
            delta = ((pib_k - constantes[anio_ant]) / constantes[anio_ant]) * 100
            var_k = f" En términos reales (precios constantes de 2015), la variación fue de {delta:+.1f}% respecto a {anio_ant}."

    # Nota especial para años clave
    nota = ""
    if anio == 2020:
        nota = " Este año coincide con la pandemia de COVID-19, que afectó significativamente la actividad económica."
    elif anio == 2021:
        nota = " Este año corresponde a la recuperación post-pandemia de COVID-19."

    texto = (
        f"Resumen del PIB total de Boyacá en {anio}: "
        f"{'El PIB a precios corrientes fue de $' + f'{pib_c:,.2f}' + ' miles de millones de pesos colombianos.' if pib_c else ''}"
        f"{var_c}"
        f"{'El PIB a precios constantes de 2015 fue de $' + f'{pib_k:,.2f}' + ' miles de millones.' if pib_k else ''}"
        f"{var_k}"
        f"{nota}"
        f" Fuente: {FUENTE}."
    )

    chunks.append({
        "texto":       texto,
        "anio":        anio,
        "actividad":   "PIB Total Boyacá",
        "sector":      "Todos los sectores",
        "tipo_precio": "Resumen anual",
        "valor":       pib_c or pib_k or 0,
        "dimension":   "Económica",
        "fuente":      FUENTE,
    })

print(f"Generando embeddings para {len(chunks)} resúmenes anuales...")
textos     = [c["texto"] for c in chunks]
embeddings = model.encode(textos, batch_size=32, show_progress_bar=True)

# ── Insertar en Supabase ──────────────────────────────────────────────────────
print("Subiendo resúmenes a Supabase...")
conn = psycopg2.connect(DB_URL)
cur  = conn.cursor()

registros = [
    (
        c["dimension"],
        c["texto"],
        c["anio"],
        "Boyacá",
        c["actividad"],
        c["sector"],
        c["tipo_precio"],
        c["valor"],
        c["fuente"],
        embeddings[i].tolist(),
    )
    for i, c in enumerate(chunks)
]

execute_values(
    cur,
    """
    INSERT INTO indicadores
        (dimension, texto, anio, departamento, actividad, sector,
         tipo_precio, valor, fuente, embedding)
    VALUES %s
    """,
    registros,
    template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)",
)
conn.commit()
cur.close()
conn.close()

print(f"\n✅ {len(chunks)} resúmenes anuales insertados correctamente.")
print("Ahora el asistente puede comparar años y responder sobre el impacto del COVID.")
