import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
from tqdm import tqdm

# ── Configuración ─────────────────────────────────────────────────────────────
load_dotenv()
DB_URL = os.getenv("SUPABASE_DB_URL")
CSV_PATH = "data/PIB_kgyi-qc7j.csv"   # ajusta si tu archivo tiene otro nombre
DIMENSION = "Económica"
FUENTE = "DANE – Observatorio Boyacá"
BATCH_SIZE = 100                  # filas por inserción a la base de datos

# ── Cargar modelo de embeddings (corre local, gratuito) ───────────────────────
print("Cargando modelo de embeddings...")
model = SentenceTransformer("all-MiniLM-L6-v2")

# ── Leer CSV ──────────────────────────────────────────────────────────────────
print(f"Leyendo {CSV_PATH}...")
df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")
df.columns = df.columns.str.strip()

# Renombrar columnas al esquema esperado
df = df.rename(columns={
    "a_o":                          "anio",
    "actividad":                    "actividad",
    "sector":                       "sector",
    "tipo_de_precios":              "tipo_precio",
    "c_digo_departamento_divipola": "codigo_depto",
    "departamento":                 "departamento",
    "valor_miles_de_millones_de":   "valor",
})

# Filtrar solo Boyacá para la primera carga
df_boyaca = df[df["departamento"] == "Boyacá"].copy()
print(f"Filas de Boyacá encontradas: {len(df_boyaca)}")

# ── Convertir cada fila en un chunk de texto legible ─────────────────────────
def fila_a_texto(row):
    return (
        f"En {int(row['anio'])}, la actividad '{row['actividad']}' "
        f"del sector {row['sector']} de Boyacá aportó "
        f"${row['valor']:,.2f} miles de millones de pesos colombianos "
        f"al PIB ({row['tipo_precio']}). "
        f"Fuente: {FUENTE}."
    )

df_boyaca["texto"] = df_boyaca.apply(fila_a_texto, axis=1)

# ── Generar embeddings en lotes ───────────────────────────────────────────────
print("Generando embeddings (esto puede tomar 1-2 minutos)...")
textos = df_boyaca["texto"].tolist()
embeddings = model.encode(textos, batch_size=32, show_progress_bar=True)

# ── Insertar en Supabase ──────────────────────────────────────────────────────
print("Conectando a Supabase...")
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

# Preparar registros
registros = []
for i, row in df_boyaca.iterrows():
    registros.append((
        DIMENSION,
        row["texto"],
        int(row["anio"]),
        row["departamento"],
        row["actividad"],
        row["sector"],
        row["tipo_precio"],
        float(row["valor"]),
        FUENTE,
        embeddings[df_boyaca.index.get_loc(i)].tolist(),
    ))

# Insertar en lotes
print(f"Insertando {len(registros)} registros en Supabase...")
total = 0
for inicio in tqdm(range(0, len(registros), BATCH_SIZE)):
    lote = registros[inicio: inicio + BATCH_SIZE]
    execute_values(
        cur,
        """
        INSERT INTO indicadores
            (dimension, texto, anio, departamento, actividad, sector,
             tipo_precio, valor, fuente, embedding)
        VALUES %s
        """,
        lote,
        template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)",
    )
    conn.commit()
    total += len(lote)

cur.close()
conn.close()

print(f"\n✅ Ingesta completada: {total} registros cargados en Supabase.")
print("Ya puedes hacer preguntas sobre el PIB de Boyacá.")
