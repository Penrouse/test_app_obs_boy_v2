import os
import base64
import streamlit as st
from rag_motor import responder


st.set_page_config(
    page_title="Red de Observatorios – Boyacá",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Solo colores institucionales, sin tocar el layout de Streamlit ────────────
st.markdown("""
<style>
[data-testid="stSidebar"] { background-color: #0D1B2A; }
[data-testid="stSidebar"] * { color: #C5D8E8 !important; }
[data-testid="stSidebar"] .stButton > button {
    background: #132030 !important;
    border: 1px solid #1E3A5A !important;
    color: #C5D8E8 !important;
    font-size: 12px !important;
    text-align: left !important;
    width: 100%;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: #0D7377 !important;
    color: #fff !important;
}
[data-testid="stSidebar"] hr { border-color: #1E3A5A !important; }
.stChatMessage [data-testid="stChatMessageContent"] { font-size: 14px; }
</style>
""", unsafe_allow_html=True)

# ── Paleta por dimensión ──────────────────────────────────────────────────────
DIM = {
    "Todas":     {"bg": "#1A3A5C", "ac": "#0D7377", "em": "🌐"},
    "Económica": {"bg": "#145A32", "ac": "#1E8449", "em": "📈"},
    "Salud":     {"bg": "#1A5276", "ac": "#2E86C1", "em": "🏥"},
    "Violencia": {"bg": "#78281F", "ac": "#C0392B", "em": "🛡️"},
}

EJEMPLOS = {
    "Económica": [
        "¿Cuál fue el PIB de Boyacá en 2024?",
        "¿Cuánto creció el PIB entre 2023 y 2024?",
        "¿Qué sector aporta más al PIB de Boyacá?",
        "¿Cómo evolucionó la agricultura entre 2010 y 2024?",
        "¿Cuál fue el impacto del COVID en el PIB de Boyacá?",
        "¿Cuánto aporta la construcción al PIB?",
        "¿Qué actividad económica creció más en 2024?",
    ],
    "Salud": [
        "¿Cuántas personas están afiliadas al SGSSS en Boyacá?",
        "¿Cuál es la tasa de mortalidad materna en Boyacá?",
        "¿Qué municipio tiene más casos de dengue?",
        "¿Cuántos nacidos vivos hubo en 2025?",
        "¿Cómo está la cobertura de vacunación BCG en Boyacá?",
        "¿Cuántos casos de tuberculosis se registraron?",
        "¿Cuál es la situación del embarazo en adolescentes?",
    ],
    "Violencia": [
        "¿Cuántos feminicidios se registraron en Boyacá en 2025?",
        "¿Qué municipio tiene más casos de violencia de género?",
        "¿Cuántos intentos de suicidio hubo en Boyacá?",
        "¿Cuál es la principal causa de lesiones fatales en Boyacá?",
        "¿Cuántos casos de violencia sexual se reportaron?",
        "¿Qué municipios registraron violencia en entornos educativos?",
        "¿Cuántos casos de conflicto armado se reportaron en 2025?",
    ],
    "Todas": [
        "¿Qué información tienes disponible?",
        "¿Cuál fue el PIB de Boyacá en 2024?",
        "¿Cuántos feminicidios se registraron en Boyacá en 2025?",
        "¿Cuántas personas están afiliadas al SGSSS en Boyacá?",
        "¿Cuál fue el impacto del COVID en el PIB de Boyacá?",
        "¿Qué municipio tiene más casos de violencia de género?",
        "¿Qué municipio tiene más casos de dengue?",
        "¿Cuántos intentos de suicidio hubo en Boyacá?",
    ],
}

# ── Estado de sesión ──────────────────────────────────────────────────────────
if "mensajes"  not in st.session_state: st.session_state.mensajes  = []
if "dimension" not in st.session_state: st.session_state.dimension = "Todas"

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    if os.path.exists("img/gobboy.png"):
        st.image("img/gobboy.png", use_container_width=True)
    else:
        st.title("🏛️ Observatorio Boyacá")

    st.markdown("---")
    st.markdown("### ⚙️ Dimensión")
    dim = st.selectbox(
        "Filtrar por dimensión",
        options=list(DIM.keys()),
        index=list(DIM.keys()).index(st.session_state.dimension),
        label_visibility="collapsed",
    )
    if dim != st.session_state.dimension:
        st.session_state.dimension = dim
        st.rerun()

    cfg = DIM[dim]

    st.markdown("---")
    st.markdown("### 💡 Preguntas de ejemplo")
    for idx, ej in enumerate(EJEMPLOS.get(dim, [])):
        if st.button(ej, key=f"ej_{dim}_{idx}", use_container_width=True):
            st.session_state["pregunta_rapida"] = ej

    mostrar_fuentes = st.toggle("Mostrar fuentes", value=True)

    st.markdown("---")
    if st.button("🗑️ Limpiar conversación", use_container_width=True):
        st.session_state.mensajes = []
        st.rerun()

    st.markdown(
        "<p style='font-size:10px;text-align:center;margin-top:8px;'>"
        "Fuentes: DANE · Sec. Salud · Fiscalía<br>Boyacá © 2025</p>",
        unsafe_allow_html=True,
    )

# ── Contenido principal ───────────────────────────────────────────────────────
cfg = DIM[st.session_state.dimension]

st.markdown(
    f"## {cfg['em']} Asistente del Observatorio de Boyacá",
)
st.caption(
    "Consulta indicadores oficiales en lenguaje natural · "
    "Respuestas basadas exclusivamente en datos del Observatorio"
)
st.markdown("---")

# ── Historial de chat ─────────────────────────────────────────────────────────
for msg in st.session_state.mensajes:
    with st.chat_message(msg["role"],
                         avatar="🧑" if msg["role"] == "user" else cfg["em"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and mostrar_fuentes and msg.get("fuentes"):
            with st.expander(f"📎 {len(msg['fuentes'])} fuentes utilizadas"):
                for f in msg["fuentes"][:4]:
                    st.markdown(
                        f"**{f['actividad'][:60]}** · {f['anio']} · "
                        f"similitud: `{f['similitud']}`  \n"
                        f"_{f['fuente']}_"
                    )

# ── Input ─────────────────────────────────────────────────────────────────────
pregunta_rapida = st.session_state.pop("pregunta_rapida", None)
pregunta = st.chat_input(
    f"Consulta sobre indicadores de Boyacá · {st.session_state.dimension}..."
) or pregunta_rapida

if pregunta:
    with st.chat_message("user", avatar="🧑"):
        st.markdown(pregunta)
    st.session_state.mensajes.append({"role": "user", "content": pregunta})

    with st.chat_message("assistant", avatar=cfg["em"]):
        with st.spinner("Consultando base de conocimiento..."):
            dim_filtro = None if st.session_state.dimension == "Todas" else st.session_state.dimension
            resultado  = responder(pregunta, dimension=dim_filtro)
        st.markdown(resultado["respuesta"])
        if mostrar_fuentes and resultado["fuentes"]:
            with st.expander(f"📎 {len(resultado['fuentes'])} fuentes utilizadas"):
                for f in resultado["fuentes"][:4]:
                    st.markdown(
                        f"**{f['actividad'][:60]}** · {f['anio']} · "
                        f"similitud: `{f['similitud']}`  \n"
                        f"_{f['fuente']}_"
                    )

    st.session_state.mensajes.append({
        "role":    "assistant",
        "content": resultado["respuesta"],
        "fuentes": resultado["fuentes"],
    })
