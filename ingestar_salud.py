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
DIMENSION  = "Salud"
FUENTE_DEF = "Secretaría de Salud de Boyacá – Observatorio"
BATCH_SIZE = 100

ARCHIVOS = [
    "data/BD SALUD AFILIADOS SSS 2025 cleaned.xlsx",
    "data/MATRIZ SALUD 2025-2 cleaned.xlsx",
]

SHEETS_OMITIR = {"DATOS V2", "INDICE"}

COLS_NO_VALOR = {
    "MES", "AÑO", "MUNICIPIO RESIDENCIA", "MUNICIPIO RESIDENCIA ",
    "CÓDIGO MUNICIPIO", "CÓDIGO MUNICIPIO.1", "MUNICIPIO", "MUNICIPIO.1",
    "MUNICIPIO DE OCURRENCIA", "MUNICIPIO DE RESIDENCIA",
    "MUNICIPIO DE RESIDENCIA ", "MUNCIPIO DE OCURRENCIA",
    "EDAD", "EDAD GESTANTE", "GENERO", "FUENTE DE LA INFORMACION",
    "DISCAPACIDAD", "ETNIA", "FEMENIMO", "FEMENINO", "MASCULINO",
    "TIPO DE MALARIA (Malaria Asociada, Malaria Complicada, Malaria Falciparum, Malaria Vivax)",
    "TIPO LEUCEMIA PEDIATRICA (Linfoide o Mieloide)",
    "TIPO MORTALIDAD (Perinatal o Neonatal)",
    "SEMANAS DE GESTACIÓN O DIAS DE VIDA\n (Por favor dar claridad si es semanas de gestación o días de vida)",
    "Unnamed: 15", "Unnamed: 16", "Unnamed: 17",
}

print("Cargando modelo de embeddings...")
model = SentenceTransformer("all-MiniLM-L6-v2")

chunks_totales = []

# ══════════════════════════════════════════════════════════════════════════════
# PARTE ESPECIAL — Afiliados SGSSS (requiere agregación por volumen)
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Procesando afiliados SGSSS (agregando 208K filas)...")
df_af = pd.read_excel(ARCHIVOS[0], sheet_name="PERSONAS AFILIADAS AL SGSSS")
df_af.columns = df_af.columns.str.strip()

agg = (
    df_af.groupby(["ANIO", "MUNICIPIO", "NOMBRE_MUNICIPIO_DANE", "GENERO"])
    ["PERSONAS_AFILIADAS"].sum().reset_index()
)
agg_total = (
    df_af.groupby(["ANIO", "MUNICIPIO", "NOMBRE_MUNICIPIO_DANE"])
    ["PERSONAS_AFILIADAS"].sum().reset_index()
)
agg_total["GENERO"] = "TOTAL"
df_aff = pd.concat([agg, agg_total], ignore_index=True)

for _, row in df_aff.iterrows():
    municipio  = str(row["NOMBRE_MUNICIPIO_DANE"]).strip().title()
    genero     = str(row["GENERO"]).strip().capitalize()
    anio       = int(row["ANIO"])
    valor      = float(row["PERSONAS_AFILIADAS"])
    genero_txt = f"de género {genero}" if genero != "Total" else "en total (ambos géneros)"

    texto = (
        f"En {anio}, el municipio de {municipio} (Boyacá) tenía "
        f"{valor:,.0f} personas afiliadas al Sistema General de Seguridad Social en Salud (SGSSS) "
        f"{genero_txt}. "
        f"Fuente: {FUENTE_DEF}."
    )
    chunks_totales.append({
        "texto":     texto,
        "anio":      anio,
        "municipio": municipio,
        "indicador": "Personas afiliadas al SGSSS",
        "valor":     valor,
        "fuente":    FUENTE_DEF,
    })

print(f"  Chunks afiliados generados: {len(chunks_totales)}")

# ══════════════════════════════════════════════════════════════════════════════
# PARTE PRINCIPAL — Todas las sheets de indicadores de ambos archivos
# ══════════════════════════════════════════════════════════════════════════════
def procesar_sheets(ruta_archivo):
    xf     = pd.ExcelFile(ruta_archivo)
    sheets = [
        s for s in xf.sheet_names
        if s not in SHEETS_OMITIR and s != "PERSONAS AFILIADAS AL SGSSS"
    ]
    nombre_archivo = ruta_archivo.split("/")[-1]
    print(f"\n── {nombre_archivo} → {len(sheets)} sheets de indicadores")

    chunks = []
    for sheet in sheets:
        df = pd.read_excel(xf, sheet_name=sheet)
        df.columns = df.columns.str.strip()
        df = df.dropna(how="all")

        if df.empty:
            print(f"  Omitida (vacía): {sheet}")
            continue

        # Detectar columna de valor numérico
        col_valor = None
        for col in df.columns:
            if col in COLS_NO_VALOR or "ETNIA" in str(col):
                continue
            try:
                if pd.api.types.is_numeric_dtype(df[col]):
                    col_valor = col
                    break
                elif df[col].dropna().apply(
                    lambda x: str(x).replace(".", "").replace(",", "").strip().isdigit()
                ).any():
                    col_valor = col
                    break
            except Exception:
                continue

        if not col_valor:
            print(f"  Omitida (sin columna numérica): {sheet}")
            continue

        nombre_indicador = col_valor.replace("\n", " ").strip()

        col_municipio = next(
            (c for c in ["MUNICIPIO", "MUNICIPIO RESIDENCIA", "MUNICIPIO RESIDENCIA "]
             if c in df.columns), None
        )
        col_anio   = next((c for c in ["AÑO", "ANIO"] if c in df.columns), None)
        col_mes    = "MES" if "MES" in df.columns else None
        col_fuente = "FUENTE DE LA INFORMACION" if "FUENTE DE LA INFORMACION" in df.columns else None

        filas_ok = 0
        for _, row in df.iterrows():
            try:
                valor = float(str(row[col_valor]).replace(",", ".").strip())
            except (ValueError, KeyError, TypeError):
                continue

            municipio = str(row[col_municipio]).strip().title() if col_municipio and pd.notna(row.get(col_municipio)) else "Boyacá"
            anio      = int(row[col_anio]) if col_anio and pd.notna(row.get(col_anio)) else 2025
            mes       = str(row[col_mes]).strip().capitalize() if col_mes and pd.notna(row.get(col_mes)) else ""
            fuente    = str(row[col_fuente]).strip() if col_fuente and pd.notna(row.get(col_fuente)) else FUENTE_DEF
            periodo   = f"en {mes} de {anio}" if mes and mes.lower() not in ("nan", "") else f"en {anio}"

            texto = (
                f"{periodo.capitalize()}, en el municipio de {municipio} (Boyacá), "
                f"se registraron {valor:,.0f} casos/personas para el indicador: "
                f"'{nombre_indicador}'. "
                f"Fuente: {fuente}."
            )
            chunks.append({
                "texto":     texto,
                "anio":      anio,
                "municipio": municipio,
                "indicador": nombre_indicador,
                "valor":     valor,
                "fuente":    fuente,
            })
            filas_ok += 1

        print(f"  ✓ {sheet[:50]:<52} → {filas_ok} registros")

    return chunks

for archivo in ARCHIVOS:
    chunks_totales.extend(procesar_sheets(archivo))

print(f"\nTotal chunks a insertar: {len(chunks_totales)}")

# ══════════════════════════════════════════════════════════════════════════════
# Generar embeddings
# ══════════════════════════════════════════════════════════════════════════════
print("\nGenerando embeddings...")
textos     = [c["texto"] for c in chunks_totales]
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
        "Salud",
        "Indicador salud",
        c["valor"],
        c["fuente"],
        embeddings[i].tolist(),
    )
    for i, c in enumerate(chunks_totales)
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

print(f"\n✅ Ingesta completada: {total} registros de salud cargados en Supabase.")
print("\nVerifica con:")
print("  SELECT dimension, COUNT(*) FROM indicadores GROUP BY dimension;")
