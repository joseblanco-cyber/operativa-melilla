# utils/config_manager.py
import json
from pathlib import Path
import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).parent.parent
CONFIG_DIR = APP_DIR / "config"

DEFAULT_CHOFERES = [
    {"nombre": "ABDEL ALI", "activo": "SI", "telefono": "641371386"},
    {"nombre": "ABDESLAM ZAKOUR", "activo": "SI", "telefono": "671617508"},
    {"nombre": "ABDU", "activo": "SI", "telefono": "666573404"},
    {"nombre": "AMIN", "activo": "SI", "telefono": "665975989"},
    {"nombre": "BRAHIM", "activo": "NO", "telefono": "662668908"},
    {"nombre": "CHAFIK", "activo": "SI", "telefono": "600877912"},
    {"nombre": "CUCU", "activo": "SI", "telefono": "629588545"},
    {"nombre": "IBRAHIM", "activo": "SI", "telefono": "612200766"},
    {"nombre": "KARIM HALIFA", "activo": "NO", "telefono": "662926599"},
    {"nombre": "MOHAMED CHILAH", "activo": "SI", "telefono": "687131337"},
    {"nombre": "RAFA", "activo": "NO", "telefono": "687813994"},
    {"nombre": "REVERTE", "activo": "SI", "telefono": "696132484"},
    {"nombre": "YERAY", "activo": "NO", "telefono": "697637644"}
]

DEFAULT_NAVIERAS = [
    {"puerto": "P.MOTRIL", "naviera": "TRASMEDITERRANEA", "llegada_estimada": "06:30"},
    {"puerto": "PMOTRIL", "naviera": "TRASMEDITERRANEA", "llegada_estimada": "06:30"},
    {"puerto": "P.ALMERIA", "naviera": "TRASMEDITERRANEA", "llegada_estimada": "06:30"},
    {"puerto": "PALMERIA", "naviera": "TRASMEDITERRANEA", "llegada_estimada": "06:30"},
    {"puerto": "P.MALAGA", "naviera": "BALEARIA", "llegada_estimada": "21:00"},
    {"puerto": "PMALAGA", "naviera": "BALEARIA", "llegada_estimada": "21:00"},
]

DEFAULT_PALABRAS_CARGA = [
    {"palabra": "CONGELADO", "categoria": "CONGELADO_25", "activo": "SI"},
    {"palabra": "CARNE", "categoria": "REFRIGERADO_3", "activo": "SI"},
    {"palabra": "FRUTA", "categoria": "REFRIGERADO_3", "activo": "SI"},
    {"palabra": "PESCADO", "categoria": "REFRIGERADO_3", "activo": "SI"},
    {"palabra": "REFRIGERADO", "categoria": "REFRIGERADO_3", "activo": "SI"},
    {"palabra": "REPESCA", "categoria": "REFRIGERADO_3", "activo": "SI"},
    {"palabra": "AGUA", "categoria": "SECO", "activo": "SI"},
    {"palabra": "SP", "categoria": "SECO", "activo": "SI"},
    {"palabra": "SP AGUA", "categoria": "SECO", "activo": "SI"},
    {"palabra": "ALCOHOL SP", "categoria": "SECO", "activo": "SI"},
    {"palabra": "PICKING", "categoria": "SECO", "activo": "SI"},
    {"palabra": "DROGERIA", "categoria": "SECO", "activo": "SI"},
    {"palabra": "DROGUERIA", "categoria": "SECO", "activo": "SI"},
    {"palabra": "COSMETICA", "categoria": "SECO", "activo": "SI"},
    {"palabra": "COSMÉTICA", "categoria": "SECO", "activo": "SI"},
    {"palabra": "DROGERIA/COSMETICA", "categoria": "SECO", "activo": "SI"},
    {"palabra": "DROGUERIA/COSMETICA", "categoria": "SECO", "activo": "SI"},
    {"palabra": "DROGERIA Y COSMETICA", "categoria": "SECO", "activo": "SI"},
    {"palabra": "DROGUERIA Y COSMETICA", "categoria": "SECO", "activo": "SI"},
    {"palabra": "ALCOHOL", "categoria": "SECO", "activo": "SI"},
    {"palabra": "DEP. FISCAL", "categoria": "SECO", "activo": "SI"},
    {"palabra": "FISCAL", "categoria": "SECO", "activo": "SI"},
]

DEFAULT_TEXTOS = {
    "aviso_entrada": "⛔️ *Respetar hora de entrada MERCADONA*",
    "esperar_barco": "_AL NO VENIR TRACTORAS, ESPERAR REMOLQUES A PIE DE BARCO (MACISTAS)._",
    "lunes_adelantado": "📢 *ESTAD ATENTOS:* Más adelante publicaremos la operativa correspondiente a las llegadas por BALEARIA 20:40h y posteriores entregas, cuando recibamos el archivo actualizado.",
    "aviso_final_normal": "📢 *ESTAD ATENTOS:* Más adelante publicaremos la *OPERATIVA DE TTES. NIEVES* asignada, *ADICIONAL* a lo actual.",
    "cierre": "*BUEN SERVICIO - GRACIAS - TODOS SOMOS COMPAÑEROS Y TODOS NOS AYUDAMOS*",
    "post_parcial_sin_envases": "*TRAS DESCARGA PARCIAL: DEJEN EL CEPO PUESTO, SAQUEN 📸 y APARQUEN EN EXPLANADAS FRENTE ZONA TALLERES*",
    "post_completa_sin_envases": "*Informad de BARRAS, SEPARADORES y ESLINGAS* 👍\n\n*TRAS DESCARGAR: DEJEN EL CEPO JUNTO A LAS ESLINGAS, SAQUEN 📸 y APARQUEN FRENTE AL REGISTRO*",
    "post_completa_con_envases": "*Enviad 📸 de la carga e informad de BARRAS, SEPARADORES y ESLINGAS*\n\n*TRAS DESCARGAR: DEJEN EL CEPO DENTRO EN UN LADO, SAQUEN 📸 y APARQUEN FRENTE AL REGISTRO*",
    "post_0530_envases_pendientes": "*TRAS DESCARGAR: DEJEN EL CEPO DENTRO EN UN LADO, SAQUEN 📸 y APARQUEN FRENTE A ZONA TALLERES*\n\n⚠️ *ENVASES PENDIENTES:* Tras realizar la entrega de las 07:00h, volver a tienda con este semi para cargar envases.",
}

def crear_config_si_no_existe():
    CONFIG_DIR.mkdir(exist_ok=True)
    archivos = {
        "choferes.csv": DEFAULT_CHOFERES,
        "navieras.csv": DEFAULT_NAVIERAS,
        "palabras_carga.csv": DEFAULT_PALABRAS_CARGA,
    }
    for nombre, datos in archivos.items():
        ruta = CONFIG_DIR / nombre
        if not ruta.exists():
            pd.DataFrame(datos).to_csv(ruta, index=False, encoding="utf-8-sig")

    ruta_textos = CONFIG_DIR / "textos_operativa.json"
    if not ruta_textos.exists():
        ruta_textos.write_text(json.dumps(DEFAULT_TEXTOS, ensure_ascii=False, indent=2), encoding="utf-8")

def fusionar_telefonos_default_choferes(df_choferes):
    return pd.DataFrame(DEFAULT_CHOFERES, columns=["nombre", "activo", "telefono"])

# --- OPTIMIZACIÓN CON CACHÉ ---
# Guardamos los datos en caché para evitar lecturas de disco innecesarias.
# Agregamos un ttl (Time To Live) de 600 segundos por seguridad, o hasta que se limpie manualmente.
@st.cache_data(ttl=600)
def cargar_csv_config(nombre_archivo, datos_default, columnas):
    ruta = CONFIG_DIR / nombre_archivo
    if not ruta.exists():
        pd.DataFrame(datos_default).to_csv(ruta, index=False, encoding="utf-8-sig")
    try:
        df = pd.read_csv(ruta, dtype=str).fillna("")
    except Exception:
        df = pd.DataFrame(datos_default)
        df.to_csv(ruta, index=False, encoding="utf-8-sig")

    for col in columnas:
        if col not in df.columns:
            df[col] = ""
    return df[columnas]

@st.cache_data(ttl=600)
def cargar_textos():
    ruta = CONFIG_DIR / "textos_operativa.json"
    if not ruta.exists():
        ruta.write_text(json.dumps(DEFAULT_TEXTOS, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        textos = json.loads(ruta.write_text(encoding="utf-8"))
    except Exception:
        textos = DEFAULT_TEXTOS.copy()

    for clave, valor in DEFAULT_TEXTOS.items():
        if clave not in textos:
            textos[clave] = valor
    return textos

# Funciones de guardado (¡Importante!: Aquí limpiamos la caché para que la app se actualice al momento)
def guardar_csv_config(nombre_archivo, df):
    ruta = CONFIG_DIR / nombre_archivo
    df.to_csv(ruta, index=False, encoding="utf-8-sig")
    st.cache_data.clear()  # Borra la caché para forzar la relectura de los nuevos datos guardados

def guardar_textos(textos):
    ruta = CONFIG_DIR / "textos_operativa.json"
    ruta.write_text(json.dumps(textos, ensure_ascii=False, indent=2), encoding="utf-8")
    st.cache_data.clear()  # Borra la caché para forzar la relectura de los nuevos textos guardados

# Inicialización automática al importar el módulo
crear_config_si_no_existe()