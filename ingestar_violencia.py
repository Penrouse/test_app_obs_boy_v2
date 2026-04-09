import os
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
from tqdm import tqdm

# ── Configuración ─────────────────────────────────────────────────────────────
load_dotenv()
DB_URL     = os.getenv("SUPABASE_DB_URL")
DIMENSION  = "Violencia"
FUENTE_DEF = "Observatorio de Seguridad y Convivencia – Gobernación de Boyacá"
BATCH_SIZE = 100

RUTA = "data/"

# Mapeo códigos violencia de género
TIPO_VIOLENCIA_MAP = {
    1.0: "Violencia física",
    2.0: "Violencia sexual",
    3.0: "Violencia psicológica",
    4.0: "Negligencia y abandono",
}

print("Cargando modelo de embeddings...")
model = SentenceTransformer("all-MiniLM-L6-v2")

chunks = []

# ══════════════════════════════════════════════════════════════════════════════
# 1 — FEMINICIDIOS
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Feminicidios...")
df = pd.read_excel(RUTA + "FISCALIA_FEMINICIDIOS_SEG_SEMESTRE_2025_RED_OBSERVATORIOS_GOBERNACION_cleaned.xlsx",
                   sheet_name="Feminicidios").dropna(how="all")

# Agregar por municipio + año + mes
agg = df.groupby(["MUNICIPIO DANE", "AÑO", "MES"]).size().reset_index(name="casos")
for _, row in agg.iterrows():
    municipio = str(row["MUNICIPIO DANE"]).strip().title()
    anio      = int(row["AÑO"])
    mes       = int(row["MES"])
    casos     = int(row["casos"])
    texto = (
        f"En el mes {mes} de {anio}, en el municipio de {municipio} (Boyacá) "
        f"se registraron {casos} caso(s) de feminicidio. "
        f"Fuente: Fiscalía General de la Nación – Observatorio Boyacá."
    )
    chunks.append({"texto": texto, "anio": anio, "municipio": municipio,
                   "indicador": "Feminicidios", "valor": float(casos),
                   "fuente": "Fiscalía General de la Nación"})

# Resumen total
total = len(df)
texto = (
    f"En el segundo semestre de 2025, en Boyacá se registraron "
    f"{total} casos de feminicidio según la Fiscalía General de la Nación. "
    f"Los municipios afectados fueron: {', '.join(df['MUNICIPIO DANE'].str.title().unique())}."
)
chunks.append({"texto": texto, "anio": 2025, "municipio": "Boyacá",
               "indicador": "Feminicidios", "valor": float(total),
               "fuente": "Fiscalía General de la Nación"})
print(f"  ✓ {len(agg)} chunks + 1 resumen")

# ══════════════════════════════════════════════════════════════════════════════
# 2 — LESIONES FATALES (filtrar Boyacá)
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Lesiones fatales (filtrando Boyacá)...")
df = pd.read_excel(RUTA + "LESIONES_FATALES_AÑO_2025_cleaned.xlsx",
                   sheet_name="Data").dropna(how="all")
df_boy = df[df["Departamento del hecho DANE"].str.upper().str.contains("BOYAC", na=False)].copy()

# Agregar por municipio + año + manera de muerte
agg = df_boy.groupby(["Municipio del hecho DANE", "Año del hecho", "Manera de Muerte"]).size().reset_index(name="casos")
for _, row in agg.iterrows():
    municipio = str(row["Municipio del hecho DANE"]).strip().title()
    anio      = int(row["Año del hecho"])
    manera    = str(row["Manera de Muerte"]).strip()
    casos     = int(row["casos"])
    texto = (
        f"En {anio}, en el municipio de {municipio} (Boyacá) "
        f"se registraron {casos} caso(s) de '{manera}'. "
        f"Fuente: Instituto Nacional de Medicina Legal – Observatorio Boyacá."
    )
    chunks.append({"texto": texto, "anio": anio, "municipio": municipio,
                   "indicador": f"Lesiones fatales – {manera}", "valor": float(casos),
                   "fuente": "Instituto Nacional de Medicina Legal"})

# Resumen por manera de muerte
resumen = df_boy.groupby("Manera de Muerte").size().reset_index(name="casos")
partes  = [f"{r['Manera de Muerte']}: {r['casos']} casos" for _, r in resumen.iterrows()]
texto = (
    f"En 2025, en Boyacá se registraron {len(df_boy)} lesiones fatales en total. "
    f"Distribución: {'; '.join(partes)}. "
    f"Fuente: Instituto Nacional de Medicina Legal – Observatorio Boyacá."
)
chunks.append({"texto": texto, "anio": 2025, "municipio": "Boyacá",
               "indicador": "Lesiones fatales – resumen", "valor": float(len(df_boy)),
               "fuente": "Instituto Nacional de Medicina Legal"})
print(f"  ✓ {len(agg)} chunks + 1 resumen  ({len(df_boy)} casos Boyacá)")

# ══════════════════════════════════════════════════════════════════════════════
# 3 — LESIONES NO FATALES
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Lesiones no fatales...")
df = pd.read_excel(RUTA + "LESIONES_NO_FATALES_AÑO_2025_cleaned.xlsx",
                   sheet_name="Data").dropna(how="all")
df_boy = df[df["Departamento del hecho DANE"].str.upper().str.contains("BOYAC", na=False)].copy() \
         if "Departamento del hecho DANE" in df.columns else df.copy()

agg = df_boy.groupby(["Municipio del hecho DANE", "Año del hecho", "Circunstancia del Hecho"]).size().reset_index(name="casos")
for _, row in agg.iterrows():
    municipio    = str(row["Municipio del hecho DANE"]).strip().title()
    anio         = int(row["Año del hecho"])
    circunstancia = str(row["Circunstancia del Hecho"]).strip()
    casos        = int(row["casos"])
    texto = (
        f"En {anio}, en el municipio de {municipio} (Boyacá) "
        f"se registraron {casos} caso(s) de lesiones no fatales por '{circunstancia}'. "
        f"Fuente: Instituto Nacional de Medicina Legal – Observatorio Boyacá."
    )
    chunks.append({"texto": texto, "anio": anio, "municipio": municipio,
                   "indicador": "Lesiones no fatales", "valor": float(casos),
                   "fuente": "Instituto Nacional de Medicina Legal"})

texto = (
    f"En 2025, en Boyacá se registraron {len(df_boy)} casos de lesiones no fatales "
    f"según el Instituto Nacional de Medicina Legal."
)
chunks.append({"texto": texto, "anio": 2025, "municipio": "Boyacá",
               "indicador": "Lesiones no fatales – resumen", "valor": float(len(df_boy)),
               "fuente": "Instituto Nacional de Medicina Legal"})
print(f"  ✓ {len(agg)} chunks + 1 resumen  ({len(df_boy)} casos)")

# ══════════════════════════════════════════════════════════════════════════════
# 4 — SSB: INTENTOS DE SUICIDIO
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Intentos de suicidio...")
df = pd.read_excel(RUTA + "SSB_VIOLENCIA_2025_cleaned.xlsx",
                   sheet_name="Intento Suicidios").dropna(how="all")
df["ANIO"] = pd.to_datetime(df["FECHA NOTIFICACION"], dayfirst=True, errors="coerce").dt.year.fillna(2025).astype(int)

agg = df.groupby(["MUNICIPIO DANE", "ANIO"]).size().reset_index(name="casos")
for _, row in agg.iterrows():
    municipio = str(row["MUNICIPIO DANE"]).strip().title()
    anio      = int(row["ANIO"])
    casos     = int(row["casos"])
    texto = (
        f"En {anio}, en el municipio de {municipio} (Boyacá) "
        f"se registraron {casos} intento(s) de suicidio. "
        f"Fuente: Secretaría de Salud de Boyacá – SIVIGILA."
    )
    chunks.append({"texto": texto, "anio": anio, "municipio": municipio,
                   "indicador": "Intentos de suicidio", "valor": float(casos),
                   "fuente": "Secretaría de Salud de Boyacá – SIVIGILA"})

texto = (
    f"En Boyacá se registraron {len(df)} casos de intento de suicidio "
    f"en los registros disponibles de 2025. "
    f"Fuente: Secretaría de Salud de Boyacá – SIVIGILA."
)
chunks.append({"texto": texto, "anio": 2025, "municipio": "Boyacá",
               "indicador": "Intentos de suicidio – resumen", "valor": float(len(df)),
               "fuente": "Secretaría de Salud de Boyacá – SIVIGILA"})
print(f"  ✓ {len(agg)} chunks + 1 resumen  ({len(df)} casos)")

# ══════════════════════════════════════════════════════════════════════════════
# 5 — SSB: VIOLENCIA DE GÉNERO
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Violencia de género...")
df = pd.read_excel(RUTA + "SSB_VIOLENCIA_2025_cleaned.xlsx",
                   sheet_name="Violencia Género").dropna(how="all")
df["ANIO"] = pd.to_datetime(df["FECHA ATENCIÓN"], dayfirst=True, errors="coerce").dt.year.fillna(2025).astype(int)
df["TIPO_TEXTO"] = df["TIPO DE VIOLENCIA"].map(TIPO_VIOLENCIA_MAP).fillna("Otro tipo de violencia")

agg = df.groupby(["MUNICIPIO DANE", "ANIO", "TIPO_TEXTO"]).size().reset_index(name="casos")
for _, row in agg.iterrows():
    municipio = str(row["MUNICIPIO DANE"]).strip().title()
    anio      = int(row["ANIO"])
    tipo      = str(row["TIPO_TEXTO"])
    casos     = int(row["casos"])
    texto = (
        f"En {anio}, en el municipio de {municipio} (Boyacá) "
        f"se registraron {casos} caso(s) de {tipo.lower()}. "
        f"Fuente: Secretaría de Salud de Boyacá – SIVIGILA."
    )
    chunks.append({"texto": texto, "anio": anio, "municipio": municipio,
                   "indicador": f"Violencia de género – {tipo}", "valor": float(casos),
                   "fuente": "Secretaría de Salud de Boyacá – SIVIGILA"})

resumen = df.groupby("TIPO_TEXTO").size().reset_index(name="casos")
partes  = [f"{r['TIPO_TEXTO']}: {r['casos']}" for _, r in resumen.iterrows()]
texto = (
    f"En 2025, en Boyacá se registraron {len(df)} casos de violencia de género. "
    f"Distribución por tipo: {'; '.join(partes)}. "
    f"Fuente: Secretaría de Salud de Boyacá – SIVIGILA."
)
chunks.append({"texto": texto, "anio": 2025, "municipio": "Boyacá",
               "indicador": "Violencia de género – resumen", "valor": float(len(df)),
               "fuente": "Secretaría de Salud de Boyacá – SIVIGILA"})
print(f"  ✓ {len(agg)} chunks + 1 resumen  ({len(df)} casos)")

# ══════════════════════════════════════════════════════════════════════════════
# 6 — VIOLENCIA EDUCATIVA
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Violencia educativa...")
df = pd.read_excel(RUTA + "VIOLENCIA_EDUCATIVA_2DO_SEMESTRE_2025_cleaned.xlsx",
                   sheet_name="Hoja1").dropna(how="all")

agg = df.groupby(["MUNICIPIO DANE", "AÑO"]).size().reset_index(name="casos")
for _, row in agg.iterrows():
    municipio = str(row["MUNICIPIO DANE"]).strip().title()
    anio      = int(row["AÑO"])
    casos     = int(row["casos"])
    texto = (
        f"En el segundo semestre de {anio}, en el municipio de {municipio} (Boyacá) "
        f"se registraron {casos} caso(s) de violencia en entornos educativos. "
        f"Fuente: {FUENTE_DEF}."
    )
    chunks.append({"texto": texto, "anio": anio, "municipio": municipio,
                   "indicador": "Violencia educativa", "valor": float(casos),
                   "fuente": FUENTE_DEF})

texto = (
    f"En el segundo semestre de 2025, en Boyacá se registraron {len(df)} casos "
    f"de violencia en entornos educativos. "
    f"Municipios afectados: {', '.join(df['MUNICIPIO DANE'].str.title().unique())}. "
    f"Fuente: {FUENTE_DEF}."
)
chunks.append({"texto": texto, "anio": 2025, "municipio": "Boyacá",
               "indicador": "Violencia educativa – resumen", "valor": float(len(df)),
               "fuente": FUENTE_DEF})
print(f"  ✓ {len(agg)} chunks + 1 resumen  ({len(df)} casos)")

# ══════════════════════════════════════════════════════════════════════════════
# 7 — VIOLENCIA POR CONFLICTO ARMADO
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Violencia por conflicto armado...")
df = pd.read_excel(RUTA + "VIOLENCIA_POR_CONFLICTO_ARMADO_2_SEMESTRE_2025_cleaned.xlsx",
                   sheet_name="Exportar Hoja de Trabajo").dropna(how="all")

agg = df.groupby(["MUNICIPIO DANE", "ANNIO_OCU", "HECHO"]).size().reset_index(name="casos")
for _, row in agg.iterrows():
    municipio = str(row["MUNICIPIO DANE"]).strip().title()
    anio      = int(row["ANNIO_OCU"])
    hecho     = str(row["HECHO"]).strip()
    casos     = int(row["casos"])
    texto = (
        f"En el segundo semestre de {anio}, en el municipio de {municipio} "
        f"se registraron {casos} caso(s) de '{hecho}' en el marco del conflicto armado. "
        f"Fuente: Unidad para las Víctimas – Observatorio Boyacá."
    )
    chunks.append({"texto": texto, "anio": anio, "municipio": municipio,
                   "indicador": f"Conflicto armado – {hecho}", "valor": float(casos),
                   "fuente": "Unidad para las Víctimas"})

resumen_hechos = df.groupby("HECHO").size().reset_index(name="casos")
partes = [f"{r['HECHO']}: {r['casos']}" for _, r in resumen_hechos.iterrows()]
texto = (
    f"En el segundo semestre de 2025, en los registros del observatorio de Boyacá "
    f"se reportaron {len(df)} hechos relacionados con conflicto armado. "
    f"Tipos: {'; '.join(partes)}. "
    f"Fuente: Unidad para las Víctimas."
)
chunks.append({"texto": texto, "anio": 2025, "municipio": "Boyacá",
               "indicador": "Conflicto armado – resumen", "valor": float(len(df)),
               "fuente": "Unidad para las Víctimas"})
print(f"  ✓ {len(agg)} chunks + 1 resumen  ({len(df)} casos)")

# ══════════════════════════════════════════════════════════════════════════════
# Generar embeddings
# ══════════════════════════════════════════════════════════════════════════════
print(f"\nTotal chunks a insertar: {len(chunks)}")
print("Generando embeddings...")
textos     = [c["texto"] for c in chunks]
embeddings = model.encode(textos, batch_size=32, show_progress_bar=True)

# ══════════════════════════════════════════════════════════════════════════════
# Insertar en Supabase
# ══════════════════════════════════════════════════════════════════════════════
print("\nConectando a Supabase...")
conn = psycopg2.connect(DB_URL)
cur  = conn.cursor()
cur.execute("SET ivfflat.probes = 5;")

registros = [
    (
        DIMENSION,
        c["texto"],
        c["anio"],
        "Boyacá",
        c["indicador"],
        "Violencia",
        "Indicador violencia",
        c["valor"],
        c["fuente"],
        embeddings[i].tolist(),
    )
    for i, c in enumerate(chunks)
]

print(f"Insertando {len(registros)} registros en lotes de {BATCH_SIZE}...")
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

print(f"\n✅ Ingesta completada: {total} registros de violencia cargados en Supabase.")
print("\nVerifica con:")
print("  SELECT dimension, COUNT(*) FROM indicadores GROUP BY dimension;")
