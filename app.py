import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import re
import json
import base64
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from urllib.parse import quote

# 1. IMPORTACIONES DE NUESTROS MÓDULOS EN /UTILS
import utils.config_manager as cfg_mod
import utils.database as db_mod
import utils.auth as auth_mod
import utils.pdf_parser as pdf_mod
import utils.excel_parser as excel_mod

# =========================================================
# CONFIGURACIÓN GENERAL
# =========================================================
APP_VERSION = "1.8.4"

st.set_page_config(page_title="Op. Mercadona Melilla", page_icon="🚛", layout="wide")

# Estilos CSS inyectados para la plataforma interna
st.markdown(
    """
    <style>
        html, body, [class*="css"] { font-size: 0.96rem; }
        .stMarkdown, .stText, .stCaption, .stDataFrame, .stSelectbox, .stTextInput,
        .stTextArea, .stDateInput, .stFileUploader, .stButton, .stCheckbox { font-size: 0.96rem !important; }
        div[data-testid="stMetricValue"] { font-size: 1.55rem !important; }
        div[data-testid="stMetricLabel"] { font-size: 0.85rem !important; }
        h1 { font-size: 1.75rem !important; }
        h2 { font-size: 1.38rem !important; }
        h3 { font-size: 1.08rem !important; }
        .main-banner { padding: 14px 18px !important; margin-bottom: 14px !important; }
        .main-banner h1 { font-size: 26px !important; }
        .main-banner p { font-size: 13px !important; }
        .tn-chip { font-size: 12px !important; padding: 3px 9px !important; }
        .main-banner {
            background: linear-gradient(90deg, #007a3d 0%, #00994d 55%, #f5c400 100%);
            padding: 18px 22px; border-radius: 14px; color: white; margin-bottom: 18px;
            box-shadow: 0 4px 14px rgba(0,0,0,0.12);
        }
        .main-banner h1 { margin: 0; font-size: 30px; line-height: 1.1; }
        .main-banner p { margin: 6px 0 0 0; font-size: 15px; opacity: 0.95; }
        .tn-chip {
            display: inline-block; background: rgba(255,255,255,0.18);
            border: 1px solid rgba(255,255,255,0.35); padding: 4px 10px;
            border-radius: 999px; margin-top: 10px; font-size: 13px; font-weight: 600;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

APP_DIR = Path(__file__).parent
LOGO_NIEVES_PATH = APP_DIR / "logo_nieves_enterprise.png"
LOGO_OP_MERCADONA_PATH = APP_DIR / "Logo_nieves_mercadona_login_clean.png"

# Cargar configuraciones cacheadas desde el módulo config_manager
df_choferes_cfg = cfg_mod.cargar_csv_config("choferes.csv", cfg_mod.DEFAULT_CHOFERES, ["nombre", "activo", "telefono"])
df_choferes_cfg = cfg_mod.fusionar_telefonos_default_choferes(df_choferes_cfg)
df_navieras_cfg = cfg_mod.cargar_csv_config("navieras.csv", cfg_mod.DEFAULT_NAVIERAS, ["puerto", "naviera", "llegada_estimada"])
df_palabras_cfg = cfg_mod.cargar_csv_config("palabras_carga.csv", cfg_mod.DEFAULT_PALABRAS_CARGA, ["palabra", "categoria", "activo"])
TEXTOS = cfg_mod.cargar_textos()

# =========================================================
# UTILIDADES DE LÓGICA DE NEGOCIO EN UI
# =========================================================
def limpiar_hora(hora):
    return str(hora).strip().lower().replace("h", "")

def normalizar_sin_espacios(texto):
    return str(texto).strip().upper().replace(" ", "")

def dia_semana_es(fecha):
    dias = {0: "LUNES", 1: "MARTES", 2: "MIÉRCOLES", 3: "JUEVES", 4: "VIERNES", 5: "SÁBADO", 6: "DOMINGO"}
    return dias[fecha.weekday()]

def obtener_naviera(puerto):
    puerto_normalizado = normalizar_sin_espacios(puerto)
    for _, fila in df_navieras_cfg.iterrows():
        puerto_cfg = normalizar_sin_espacios(fila.get("puerto", ""))
        if puerto_normalizado == puerto_cfg:
            return str(fila.get("naviera", "REVISAR")).strip().upper()
    return "REVISAR"

def llegada_estimada(naviera):
    nav = str(naviera).strip().upper()
    for _, fila in df_navieras_cfg.iterrows():
        if str(fila.get("naviera", "")).strip().upper() == nav:
            return limpiar_hora(fila.get("llegada_estimada", ""))
    return ""

def llegada_estimada_por_fecha(naviera, fecha_llegada):
    nav = str(naviera).strip().upper()
    if nav == "BALEARIA" and fecha_llegada.weekday() == 6:
        return "23:00"
    return llegada_estimada(naviera)

def palabras_carga_activas():
    df = df_palabras_cfg.copy()
    if "activo" in df.columns:
        df = df[df["activo"].astype(str).str.upper().eq("SI")]
    df["palabra"] = df["palabra"].astype(str)
    df["categoria"] = df["categoria"].astype(str)
    df["longitud"] = df["palabra"].str.len()
    return df.sort_values("longitud", ascending=False)

def categoria_segmento(segmento):
    texto = str(segmento).upper().strip()
    if texto == "PESCADO":
        return "REFRIGERADO_3"
    if "PESCADO" in texto and not any(x in texto for x in ["CONGELADO", "-25", "HELADO"]):
        return "REFRIGERADO_3"
    if not texto:
        return None

    for _, fila in palabras_carga_activas().iterrows():
        palabra = str(fila.get("palabra", "")).upper().strip()
        categoria = str(fila.get("categoria", "")).upper().strip()
        if not palabra or not categoria:
            continue
        if palabra == "SP":
            if re.search(r"(^|[^A-Z0-9])SP([^A-Z0-9]|$)", texto):
                return categoria
        elif palabra in texto:
            if palabra == "PESCADO" and not any(x in texto for x in ["CONGELADO", "-25", "HELADO"]):
                return "REFRIGERADO_3"
            return categoria
    return None

def etiqueta_categoria(cat):
    if cat == "REFRIGERADO_3": return "REFRIGERADO 3º"
    if cat == "CONGELADO_25": return "CONGELADO -25º"
    if cat == "SECO": return "SECO"
    return cat

def descripcion_termica(categories_ordered, marks_detected):
    cats = list(categories_ordered)[:]
    if not cats:
        if "COLOR_ROJO_FRIO" in marks_detected: return "TODO REFRIGERADO 3º"
        if "COLOR_AZUL_SECO" in marks_detected: return "TODO SECO"
        return "REVISAR"
    unicas = list(dict.fromkeys(cats))
    if len(unicas) == 1:
        if unicas[0] == "SECO": return "TODO SECO"
        if unicas[0] == "REFRIGERADO_3": return "TODO REFRIGERADO 3º"
        if unicas[0] == "CONGELADO_25": return "TODO CONGELADO -25º"
    if len(unicas) == 2:
        return f"DELANTERO {etiqueta_categoria(unicas[0])} / TRASERO {etiqueta_categoria(unicas[1])}"
    partes = []
    for i, cat in enumerate(unicas):
        etiqueta = etiqueta_categoria(cat)
        if i == 0: partes.append(f"DELANTERO {etiqueta}")
        elif i == len(unicas) - 1: partes.append(f"TRASERO {etiqueta}")
        else: partes.append(etiqueta)
    return " / ".join(partes)

def debe_mostrar_origen(origen):
    origen_limpio = str(origen).strip()
    return origen_limpio and origen_limpio.upper() != "DESDE EL PUERTO"

def turno_por_hora(hora):
    minutos = hora_a_minutos(hora)
    if minutos < hora_a_minutos("14:00"): return "MAÑANA"
    if minutos < hora_a_minutos("20:00"): return "TARDE"
    return "NOCHE"

def titulo_turno(turno):
    if turno == "MAÑANA": return "🔵 *TURNO MAÑANA*"
    if turno == "TARDE": return "🟡 *TURNO TARDE*"
    return "🟣 *TURNO NOCHE*"

def hora_a_minutos(hora):
    try:
        h, m = limpiar_hora(hora).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 9999

def restar_minutos(hora_str, minutos=30):
    try:
        h, m = limpiar_hora(hora_str).split(":")
        total = int(h) * 60 + int(m) - int(minutos)
        if total < 0: total = 0
        return f"{total // 60:02d}:{total % 60:02d}"
    except Exception:
        return limpiar_hora(hora_str)

def es_carga_fria(descripcion):
    desc = str(descripcion).upper().strip()
    if not desc or "TODO SECO" in desc or desc == "SECO": return False
    return any(clave in desc for clave in ["REFRIGERADO", "CONGELADO", "FRÍO", "FRIO", "3º", "3°", "-25", "TEMPERATURA"])

def texto_aviso_temperatura(descripcion):
    if es_carga_fria(descripcion):
        return f"⚠️ *TEMPERATURA: {descripcion}. Mantener equipo de frío en marcha.*"
    return ""

def termica_operativa_manual(valor_manual, valor_detectado=""):
    manual = str(valor_manual).strip()
    return manual if manual else str(valor_detectado).strip()

# =========================================================
# INTERMEDIARIOS DE EXTRACCIÓN (PUENTE CON /UTILS)
# =========================================================


def _pdf_texto_completo_para_correccion(bytes_archivo):
    """
    Lee texto bruto del PDF solo para afinar la térmica real de cada semi.
    No sustituye al parser principal; solo evita que leyendas generales del PDF
    como "REPESCA / SECO CONGELADO REFRIGERADO" contaminen la mercancía real.
    """
    try:
        import fitz
        doc = fitz.open(stream=bytes_archivo, filetype="pdf")
        return "\n".join(page.get_text("text") for page in doc)
    except Exception:
        return ""


def _bloque_pdf_por_semi(texto_pdf, semi):
    texto = str(texto_pdf or "")
    semi = str(semi or "").strip().upper()
    if not texto or not semi:
        return ""

    pos = texto.upper().find(semi)
    if pos < 0:
        return ""

    inicio = texto.upper().rfind("*0001", 0, pos)
    if inicio < 0:
        inicio = max(0, pos - 700)

    fin = texto.upper().find("*0001", pos + len(semi))
    if fin < 0:
        fin = min(len(texto), pos + 1400)

    return texto[inicio:fin]


def _mercancia_real_pdf_desde_bloque(bloque):
    """
    Extrae la línea real de mercancías situada tras la temperatura decimal del bloque.
    Ejemplo R2140BDK:
    25,0 / REFRIGERADO / AGUA / AGUA / 10% / P. MOTRIL
    """
    b = str(bloque or "")
    if not b:
        return ""

    # Cortar entre temperatura decimal y puerto/CR. Es la zona más fiable de mercancía real.
    m = re.search(r"\n\s*\d{1,2},\d\s*\n(?P<body>.*?)(?:\n\s*P\.\s*(?:MOTRIL|MALAGA|ALMERIA|ALMERÍA)|\n\s*CR[´']?s|\n\s*SECOS\s+\d+)", b, flags=re.I | re.S)
    if not m:
        return ""

    body = m.group("body")
    lineas = []
    for linea in body.splitlines():
        t = linea.strip().upper()
        if not t:
            continue
        # Evitar datos de viaje/fechas/lugares si aparecieran por el orden del PDF.
        if re.search(r"\d{2}/\d{2}/\d{4}|SALIDA|VIERNES|S[ÁA]BADO|JUEVES|P\.\s*", t):
            continue
        lineas.append(t)

    return " ".join(lineas).strip()


def _corregir_termica_registro_pdf(reg, texto_pdf):
    """
    Regla de seguridad para PDFs Mercadona:
    la descripción térmica debe salir de la línea real de mercancías del semi,
    no de leyendas generales del bloque ni de notas amarillas.
    """
    try:
        semi = str(reg.get("Semi", "")).strip().upper()
        bloque = _bloque_pdf_por_semi(texto_pdf, semi)
        mercancia_real = _mercancia_real_pdf_desde_bloque(bloque)
        m = mercancia_real.upper()

        if not m:
            return reg

        # Caso detectado 13/06/2026: R2140BDK = REFRIGERADO / AGUA / AGUA / REPESCA(10%).
        # No debe heredar SECO ni CONGELADO de la leyenda "REPESCA / SECO CONGELADO REFRIGERADO".
        tiene_agua = "AGUA" in m
        tiene_refrigerado = "REFRIGERADO" in m or "REFRIG" in m
        tiene_repesca = "REPESCA" in m or "10%" in m
        tiene_congelado_real = "CONGELADO" in m or "-25" in m
        tiene_seco_real = re.search(r"(^|\s)SECO(S)?($|\s)", m) is not None or " SP " in f" {m} "

        if tiene_agua and (tiene_refrigerado or tiene_repesca) and not tiene_congelado_real and not tiene_seco_real:
            reg["Descripción térmica"] = "MIXTO_REFRIGERADO/AGUA/RESTO PERECEDERAS"
            reg["Mercancías detectadas"] = "REFRIGERADO, AGUA, AGUA, REPESCA"
            reg["Orden térmico detectado"] = "REFRIGERADO / AGUA / AGUA / REPESCA"
            return reg

        # Si en la línea real hay AGUA y refrigerado, pero no congelado, nunca añadir CONGELADO por notas externas.
        if tiene_agua and tiene_refrigerado and not tiene_congelado_real:
            reg["Descripción térmica"] = "MIXTO_REFRIGERADO/AGUA"
            reg["Mercancías detectadas"] = mercancia_real
            reg["Orden térmico detectado"] = mercancia_real.replace(" ", " / ")
            return reg

    except Exception:
        pass

    return reg


def corregir_termicas_pdf_por_mercancia_real(bytes_archivo, registros):
    texto_pdf = _pdf_texto_completo_para_correccion(bytes_archivo)
    if not texto_pdf or not registros:
        return registros
    corregidos = []
    for reg in registros:
        if isinstance(reg, dict):
            corregidos.append(_corregir_termica_registro_pdf(reg.copy(), texto_pdf))
        else:
            corregidos.append(reg)
    return corregidos

def extraer_registros_archivo(bytes_archivo, nombre_archivo, es_excel_operativo):
    extension = Path(str(nombre_archivo)).suffix.lower()
    if extension in [".xlsx", ".xlsm", ".xls"]:
        return excel_mod.extraer_registros_excel(bytes_archivo, nombre_archivo, es_excel_operativo, obtener_naviera, categoria_segmento, descripcion_termica)
    if extension == ".pdf":
        registros, err = pdf_mod.extraer_registros_pdf(bytes_archivo, nombre_archivo, es_excel_operativo, obtener_naviera, categoria_segmento, descripcion_termica)
        if not err:
            registros = corregir_termicas_pdf_por_mercancia_real(bytes_archivo, registros)
        return registros, err
    return [], f"Formato no soportado: {nombre_archivo}"

def construir_servicios(registros, fecha_objetivo):
    servicios = []
    for reg in registros:
        horas_objetivo = [x for x in reg["Horas fechas"] if x["fecha"] == fecha_objetivo]
        if not horas_objetivo: continue
        horas_objetivo = sorted(horas_objetivo, key=lambda x: hora_a_minutos(x["hora"]))

        for idx, hf in enumerate(horas_objetivo):
            es_ultima = idx == len(horas_objetivo) - 1
            completa = "SI" if (len(horas_objetivo) == 1 or es_ultima) else "NO"
            envases = reg["Retira envases detectado"] if (len(horas_objetivo) == 1 or es_ultima) else "NO"

            servicios.append({
                "Archivo": reg["Archivo"], "Semi": reg["Semi"], "Puerto": reg["Puerto"], "Naviera": reg["Naviera"],
                "Hora": hf["hora"], "Fecha": hf["fecha"].strftime("%d/%m/%Y") if hf["fecha"] else "",
                "Descarga completa": completa, "Retira envases": envases, "Descripción térmica": reg["Descripción térmica"],
                "Mercancías detectadas": reg["Mercancías detectadas"], "Orden térmico detectado": reg["Orden térmico detectado"],
            })
    df = pd.DataFrame(servicios)
    if not df.empty:
        df["OrdenHora"] = df["Hora"].apply(hora_a_minutos)
        df = df.sort_values(["OrdenHora", "Semi"]).drop(columns=["OrdenHora"])
    return df

def construir_llegadas(registros, fecha_objetivo, modo):
    llegadas = []
    for reg in registros:
        if not reg["Es Excel operativo"] or reg["Naviera"] == "REVISAR": continue
        if modo == "Operativa adelanto (1 Excel)" and reg["Naviera"] == "BALEARIA": continue
        if fecha_objetivo not in [x["fecha"] for x in reg["Horas fechas"]]: continue

        llegadas.append({
            "Semi": reg["Semi"], "Naviera": reg["Naviera"], "Llegada estimada": llegada_estimada(reg["Naviera"]),
            "Descripción térmica": reg["Descripción térmica"], "Puerto": reg["Puerto"],
        })
    df = pd.DataFrame(llegadas)
    if not df.empty:
        df = df.drop_duplicates(subset=["Semi", "Naviera"])
    return df

def filtrar_servicios_por_modo(df_servicios, modo):
    if df_servicios.empty: return df_servicios
    df = df_servicios.copy()
    df["OrdenHora"] = df["Hora"].apply(hora_a_minutos)
    if modo == "Operativa adelanto (1 Excel)":
        df = df[df["OrdenHora"] <= hora_a_minutos("20:30")]
    elif modo == "Completar operativa de adelanto (2 Excel)":
        df = df[df["OrdenHora"] >= hora_a_minutos("20:30")]
    return df.sort_values(["OrdenHora", "Semi"]).drop(columns=["OrdenHora"])

# =========================================================
# LÓGICA DE TEXTOS Y GENERACIÓN OPERATIVA
# =========================================================
def origen_por_defecto(hora):
    h = limpiar_hora(hora)
    if h == "05:30": return "Desde el puerto"
    if h == "07:00": return "A la llegada del buque “06:30h”"
    return "Desde el puerto"

def texto_post_descarga(completa, envases, gestion_envases_0530="Normal"):
    if str(gestion_envases_0530).startswith("Envases pendientes"):
        return TEXTOS.get("post_0530_envases_pendientes", cfg_mod.DEFAULT_TEXTOS["post_0530_envases_pendientes"])
    if completa == "NO" and envases == "NO":
        return TEXTOS.get("post_parcial_sin_envases", cfg_mod.DEFAULT_TEXTOS["post_parcial_sin_envases"])
    if completa == "SI" and envases == "NO":
        return TEXTOS.get("post_completa_sin_envases", cfg_mod.DEFAULT_TEXTOS["post_completa_sin_envases"])
    if completa == "SI" and envases == "SI":
        return TEXTOS.get("post_completa_con_envases", cfg_mod.DEFAULT_TEXTOS["post_completa_con_envases"])
    return ""

def texto_condicion_descarga(completa, envases, gestion_envases_0530="Normal"):
    if str(gestion_envases_0530).startswith("Envases pendientes"):
        return f"(*{completa}* se descarga completo y *NO* retira envases en este primer pase*)"
    return f"(*{completa}* se descarga completo y *{envases}* retira envases)"

def aviso_final_por_modo(modo):
    if modo == "Operativa adelanto (1 Excel)":
        return TEXTOS.get("lunes_adelantado", cfg_mod.DEFAULT_TEXTOS["lunes_adelantado"])
    return TEXTOS.get("aviso_final_normal", cfg_mod.DEFAULT_TEXTOS["aviso_final_normal"])

def aviso_estad_atentos_individual():
    return "📢 *ESTAD ATENTOS:* Más adelante publicaremos la *OPERATIVA DE TTES. NIEVES* asignada, *ADICIONAL* a lo actual."

def nombre_chofer_formateado(chofer, acompanante):
    c = str(chofer).strip()
    a = str(acompanante).strip()
    return f"{c} junto a {a} (FORMACIÓN)" if (a and a != c) else c

def normalizar_telefono_whatsapp(telefono):
    tel = str(telefono).strip().replace("+", "").replace(" ", "").replace("-", "").replace(".", "").replace("(", "").replace(")", "")
    if not tel: return ""
    if re.fullmatch(r"[67]\d{8}", tel): tel = "34" + tel
    return tel if re.fullmatch(r"\d{10,15}", tel) else ""

def telefono_chofer(nombre_chofer):
    target = str(nombre_chofer).strip().upper()
    if not target or target == "SIN ASIGNAR" or "telefono" not in df_choferes_cfg.columns: return ""
    for _, fila in df_choferes_cfg.iterrows():
        if str(fila.get("nombre", "")).strip().upper() == target:
            return normalizar_telefono_whatsapp(fila.get("telefono", ""))
    return ""

def limpiar_texto_whatsapp(texto):
    lineas = [l.rstrip() for l in str(texto).splitlines()]
    texto = "\n".join(lineas).strip()
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    texto = re.sub(r"\n*(\*----------//----------\*)\n*", r"\n\n\1\n\n", texto)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()

def generar_bloque_llegadas(fecha_objetivo, df_servicios, df_llegadas):
    fecha_txt = fecha_objetivo.strftime("%d/%m/%y")
    dia_txt = dia_semana_es(fecha_objetivo)
    if (df_llegadas is None or df_llegadas.empty) and (df_servicios is None or df_servicios.empty): return ""

    semis_0530_ba = pd.DataFrame()
    if df_servicios is not None and not df_servicios.empty:
        df_tmp = df_servicios.copy()
        df_tmp["HoraLimpia"] = df_tmp["Hora"].apply(limpiar_hora)
        semis_0530_ba = df_tmp[(df_tmp["HoraLimpia"] == "05:30") & (df_tmp["Naviera"] == "BALEARIA")]

    df_tras = pd.DataFrame()
    df_ba_otros = pd.DataFrame()
    if df_llegadas is not None and not df_llegadas.empty:
        df_tras = df_llegadas[df_llegadas["Naviera"] == "TRASMEDITERRANEA"]
        prev_semis = set(semis_0530_ba["Semi"].tolist()) if not semis_0530_ba.empty else set()
        df_ba_otros = df_llegadas[(df_llegadas["Naviera"] == "BALEARIA") & (~df_llegadas["Semi"].isin(prev_semis))]

    if semis_0530_ba.empty and df_tras.empty and df_ba_otros.empty: return ""

    texto = f"_________*OPERATIVA MERCADONA {dia_txt} {fecha_txt} 05:30H EN TIENDA*_________\n\n"
    if not semis_0530_ba.empty:
        f_prev = fecha_objetivo - timedelta(days=1)
        texto += f"*SEMI LLEGADO LA NOCHE ANTES POR BALEARIA {dia_semana_es(f_prev)} {f_prev.strftime('%d/%m/%y')} {llegada_estimada_por_fecha('BALEARIA', f_prev)}H:*\n"
        for _, fila in semis_0530_ba.iterrows():
            texto += f"{fila['Semi']}_____  {fila['Descripción térmica']}\n"
        texto += "\n"
    if not df_tras.empty:
        texto += f"*LLEGAN POR TRASMEDITERRANEA {llegada_estimada('TRASMEDITERRANEA') or '06:30'}H:*\n"
        for _, fila in df_tras.iterrows():
            texto += f"{fila['Semi']}_____  {fila['Descripción térmica']}\n"
        texto += f"\n{TEXTOS.get('esperar_barco', cfg_mod.DEFAULT_TEXTOS['esperar_barco'])}\n\n"
    if not df_ba_otros.empty:
        texto += f"*LLEGAN POR BALEARIA {llegada_estimada_por_fecha('BALEARIA', fecha_objetivo) or '21:00'}H:*\n"
        for _, fila in df_ba_otros.iterrows():
            texto += f"{fila['Semi']}_____  {fila['Descripción térmica']}\n"
        texto += "\n"
    return texto + "\n"

def boton_copiar_texto(texto, clave="operativa", etiqueta="📋 Copiar"):
    texto_json = json.dumps(texto)
    html = f"""
    <div style="margin: 8px 0 12px 0;">
        <button id="copy-btn-{clave}" style="display: inline-flex; align-items: center; gap: 6px; background: linear-gradient(90deg, #007a3d 0%, #00994d 100%); color: white; border: none; border-radius: 8px; padding: 7px 13px; font-size: 13px; cursor: pointer; font-weight: 700; box-shadow: 0 2px 7px rgba(0,0,0,0.14);">{etiqueta}</button>
        <span id="copy-msg-{clave}" style="margin-left: 10px; font-family: sans-serif; color: #007a3d; font-size: 13px; font-weight: 700;"></span>
    </div>
    <script>
    const text_{clave} = {texto_json};
    document.getElementById("copy-btn-{clave}").addEventListener("click", async () => {{
        try {{ await navigator.clipboard.writeText(text_{clave}); document.getElementById("copy-msg-{clave}").innerText = "Copiado"; }}
        catch (err) {{ document.getElementById("copy-msg-{clave}").innerText = "No copiado"; }}
    }});
    </script>
    """
    components.html(html, height=48)

def convertir_emojis_para_whatsapp_url(texto):
    texto = str(texto).replace("\r\n", "\n").replace("\r", "\n")
    reemplazos = {
        "📸": "FOTO", "⛔️": "*ATENCIÓN*", "⛔": "*ATENCIÓN*", "⚠️": "*AVISO*", "⚠": "*AVISO*", "📢": "*ALERTA*",
        "🚛": "*CAMIÓN*", "👤": "*CHOFER*", "🔵": "*TURNO MAÑANA*", "🟠": "*TURNO TARDE/NOCHE*", "🟢": "*WHATSAPP*",
        "🚚": "*OPERATIVA*", "👍": "OK", "➡️": "->", "➡": "->", "→": "->", "1️⃣": "1º", "2️⃣": "2º", "3️⃣": "3º"
    }
    for simbolo, palabra in reemplazos.items(): texto = texto.replace(simbolo, palabra)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]{2,}", " ", texto)).strip()

def boton_abrir_whatsapp(texto, clave="whatsapp", telefono=""):
    texto_limpio = convertir_emojis_para_whatsapp_url(texto)
    texto_encoded = quote(texto_limpio, safe="", encoding="utf-8", errors="ignore")
    tel = normalizar_telefono_whatsapp(telefono)
    url = f"https://wa.me/{tel}?text={texto_encoded}" if tel else f"https://wa.me/?text={texto_encoded}"
    etiqueta = "🟢 WhatsApp directo" if tel else "🟢 Abrir WhatsApp"
    html = f'<div style="margin: 4px 0 12px 0;"><a href="{url}" target="_blank" style="display: inline-flex; align-items: center; gap: 6px; background: linear-gradient(90deg, #128C7E 0%, #25D366 100%); color: white; text-decoration: none; border-radius: 8px; padding: 7px 13px; font-size: 13px; font-weight: 700; box-shadow: 0 2px 7px rgba(0,0,0,0.14);">{etiqueta}</a></div>'
    components.html(html, height=46)

def buscar_config_servicio(config_servicios, fila, idx):
    candidatos = [f"{fila.get('Semi', '')}_{fila.get('Hora', '')}_{fila.get('Fecha', '')}_{idx}", f"{fila.get('Semi', '')}_{fila.get('Hora', '')}_{fila.get('Fecha', '')}", f"{fila.get('Semi', '')}_{fila.get('Hora', '')}"]
    for k in candidatos:
        if k in config_servicios: return config_servicios[k]
    for k, v in config_servicios.items():
        if str(fila.get("Semi", "")).strip() in str(k) and str(fila.get("Hora", "")).strip() in str(k): return v
    return None

def alertas_envases_nocturnos(df_servicios, config_servicios):
    servicios = []
    for idx, fila in df_servicios.iterrows():
        cfg = buscar_config_servicio(config_servicios, fila, idx)
        if not cfg or not cfg.get("incluir", True): continue
        minutos = hora_a_minutos(str(cfg.get("hora", fila.get("Hora", ""))))
        if minutos is None or minutos < 20 * 60: continue
        servicios.append({"semi": str(fila.get("Semi", "")).strip(), "hora": str(cfg.get("hora", fila.get("Hora", ""))), "minutos": minutos, "envases": str(cfg.get("envases", fila.get("Retira envases", "NO"))).strip().upper()})

    servicios = sorted(servicios, key=lambda x: x["minutos"])
    alertas = []
    if len(servicios) <= 1: return alertas
    for s in servicios[:-1]:
        if s["envases"] == "SI":
            post = [p for p in servicios if p["minutos"] > s["minutos"]]
            if post:
                posteriores = ", ".join(f"{p['semi']} ({p['hora']}h)" for p in post)
                alertas.append({
                    "mensaje": f"🚨 Semi {s['semi']} tiene asignado carga envases a las {s['hora']}h, pero posteriormente hay asignado un nuevo servicio cuya matrícula es {post[0]['semi']}.",
                    "detalle": f"Servicios posteriores: {posteriores}. Revisar con MERCADONA si falta recogida adicional."
                })
    return alertas

def pintar_alertas_envases_nocturnos(alertas):
    for a in alertas:
        st.markdown(f'<div style="background: rgb(253, 232, 232); border: 1px solid rgba(220, 38, 38, 0.35); border-left: 6px solid rgb(220, 38, 38); border-radius: 10px; padding: 12px 14px; margin: 10px 0; color: #7f1d1d; font-size: 14px; line-height: 1.45;"><strong>{a["mensaje"]}</strong><br><span>{a["detalle"]}</span></div>', unsafe_allow_html=True)

def detectar_alertas_operativas(df_servicios, config_servicios):
    alertas = []
    if df_servicios is None or df_servicios.empty: return alertas
    asignaciones = []
    for idx, fila in df_servicios.iterrows():
        cfg = config_servicios.get(f"{fila['Semi']}_{fila['Hora']}_{idx}", {})
        if not cfg.get("incluir", True): continue
        chofer = str(cfg.get("chofer", "SIN ASIGNAR")).strip()
        termica = termica_operativa_manual(cfg.get("termica", ""), fila["Descripción térmica"])
        asignaciones.append({"semi": fila["Semi"], "hora": limpiar_hora(fila["Hora"]), "chofer": chofer, "termica": termica})
        if not chofer or chofer.upper() == "SIN ASIGNAR": alertas.append(f"Servicio {limpiar_hora(fila['Hora'])}h con semi {fila['Semi']} sin chófer asignado.")
        if cfg.get("completa", fila["Descarga completa"]) == "NO" and es_carga_fria(termica): alertas.append(f"Semi {fila['Semi']} en servicio {limpiar_hora(fila['Hora'])}h: descarga parcial con carga fría. Revisar equipo de frío.")

    vistos = {}
    for item in asignaciones: vistos.setdefault((item["hora"], item["chofer"].upper()), []).append(item["semi"])
    for (h, ch), semis in vistos.items():
        if ch and ch != "SIN ASIGNAR" and len(semis) > 1: alertas.append(f"{ch} tiene varios servicios a las {h}h: {', '.join(semis)}.")
    return list(dict.fromkeys(alertas))

def resumen_operativo(df_servicios, config_servicios):
    res = {"Servicios incluidos": 0, "Semis únicos": 0, "Chóferes": 0, "Servicios con frío": 0, "Servicios con envases": 0}
    if df_servicios is None or df_servicios.empty: return res
    semi_set, chofer_set = set(), set()
    for idx, fila in df_servicios.iterrows():
        cfg = config_servicios.get(f"{fila['Semi']}_{fila['Hora']}_{idx}", {})
        if not cfg.get("incluir", True): continue
        ch = str(cfg.get("chofer", "SIN ASIGNAR")).strip().upper()
        termica = termica_operativa_manual(cfg.get("termica", ""), fila["Descripción térmica"])
        res["Servicios incluidos"] += 1
        semi_set.add(fila["Semi"])
        if ch and ch != "SIN ASIGNAR": chofer_set.add(ch)
        if es_carga_fria(termica): res["Servicios con frío"] += 1
        if cfg.get("envases", fila["Retira envases"]) == "SI" or str(cfg.get("gestion_envases_0530", "")).startswith("Envases pendientes"): res["Servicios con envases"] += 1
    res["Semis únicos"], res["Chóferes"] = len(semi_set), len(chofer_set)
    return res

def _escape_html(valor):
    import html
    return html.escape(str(valor if valor is not None else ""))


def generar_plan_interno_datos(df_servicios, config_servicios):
    if df_servicios is None or df_servicios.empty:
        return {}, {"servicios": 0, "semis": 0, "choferes": 0, "frio": 0, "envases": 0}

    plan = {}
    semis = set()
    choferes = set()
    servicios = 0
    frio = 0
    envases_total = 0

    for idx, fila in df_servicios.iterrows():
        cfg = config_servicios.get(f"{fila['Semi']}_{fila['Hora']}_{idx}", {})
        if not cfg.get("incluir", True):
            continue

        ch = str(cfg.get("chofer", "SIN ASIGNAR")).strip().upper() or "SIN ASIGNAR"
        semi = str(fila.get("Semi", "")).strip().upper()
        hora = limpiar_hora(fila.get("Hora", ""))
        completa = str(cfg.get("completa", fila.get("Descarga completa", "NO"))).strip().upper()
        env = str(cfg.get("envases", fila.get("Retira envases", "NO"))).strip().upper()
        termica = termica_operativa_manual(cfg.get("termica", ""), fila.get("Descripción térmica", ""))

        plan.setdefault(ch, []).append({
            "hora": hora,
            "semi": semi,
            "descarga": completa,
            "envases": env,
            "accion": "Servicio Mercadona",
            "tipo": "servicio",
        })

        servicios += 1
        semis.add(semi)
        if ch != "SIN ASIGNAR":
            choferes.add(ch)
        if es_carga_fria(termica):
            frio += 1
        if env == "SI":
            envases_total += 1

        if str(cfg.get("gestion_envases_0530", "")).startswith("Envases pendientes"):
            plan.setdefault(ch, []).append({
                "hora": "---",
                "semi": semi,
                "descarga": "---",
                "envases": "SI",
                "accion": "Recogida envases pendiente",
                "tipo": "envases",
            })
            envases_total += 1

    return plan, {
        "servicios": servicios,
        "semis": len(semis),
        "choferes": len(choferes),
        "frio": frio,
        "envases": envases_total,
    }


def generar_plan_interno(df_servicios, config_servicios):
    plan, _ = generar_plan_interno_datos(df_servicios, config_servicios)
    if not plan:
        return ""
    bloques = ["🔧 PLAN INTERNO NIEVES S.A."]
    for ch, lineas in plan.items():
        bloques.append(f"\n{ch}:")
        for item in lineas:
            if item["tipo"] == "envases":
                bloques.append(f"- Tras servicio posterior → {item['semi']} (recogida envases pendiente)")
            else:
                bloques.append(f"- {item['hora']}h → {item['semi']} ({item['descarga']} descarga / {item['envases']} envases)")
    return "\n".join(bloques)


def generar_plan_interno_html(df_servicios, config_servicios, fecha_objetivo=None):
    plan, resumen = generar_plan_interno_datos(df_servicios, config_servicios)
    if not plan:
        return ""

    fecha_txt = fecha_objetivo.strftime("%d/%m/%Y") if fecha_objetivo else ""
    generado_txt = datetime.now().strftime("%d/%m/%Y %H:%M")

    html = f"""
    <style>
        .plan-nieves-wrap {{
            font-family: Arial, Helvetica, sans-serif;
            background: #ffffff;
            color: #111827;
            border: 1px solid #e5e7eb;
            border-radius: 14px;
            padding: 22px 26px;
            box-shadow: 0 8px 24px rgba(15,23,42,.08);
            max-width: 980px;
        }}
        .plan-nieves-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 18px;
            border-bottom: 2px solid #111827;
            padding-bottom: 14px;
            margin-bottom: 18px;
        }}
        .plan-nieves-title {{
            font-size: 25px;
            font-weight: 900;
            margin: 0 0 6px 0;
        }}
        .plan-nieves-sub {{
            font-size: 13px;
            color: #4b5563;
            line-height: 1.45;
        }}
        .plan-nieves-chip {{
            display: inline-block;
            background: #007a3d;
            color: white;
            border-radius: 999px;
            padding: 6px 12px;
            font-size: 12px;
            font-weight: 800;
            white-space: nowrap;
        }}
        .plan-driver {{
            margin-top: 24px;
            padding-top: 8px;
            border-top: 1px solid #d1d5db;
        }}
        .plan-driver h3 {{
            font-size: 20px;
            margin: 10px 0 10px 0;
            font-weight: 900;
            color: #111827;
        }}
        .plan-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            margin-bottom: 22px;
        }}
        .plan-table th {{
            text-align: left;
            padding: 9px 8px;
            border-bottom: 1px solid #cbd5e1;
            color: #111827;
            font-weight: 900;
            background: #f8fafc;
        }}
        .plan-table td {{
            padding: 10px 8px;
            border-bottom: 1px solid #eef2f7;
            vertical-align: top;
        }}
        .plan-table tr.envases-row td {{
            background: #fefce8;
            color: #713f12;
            font-weight: 700;
        }}
        .pill-si {{ color: #166534; font-weight: 900; }}
        .pill-no {{ color: #991b1b; font-weight: 900; }}
        .summary-box {{
            margin-top: 26px;
            border-top: 1px solid #d1d5db;
            padding-top: 18px;
        }}
        .summary-title {{
            font-size: 20px;
            font-weight: 900;
            margin-bottom: 10px;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(5, minmax(110px, 1fr));
            gap: 10px;
        }}
        .summary-card {{
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 12px;
            background: #f8fafc;
        }}
        .summary-card .label {{
            font-size: 12px;
            color: #64748b;
            font-weight: 800;
        }}
        .summary-card .value {{
            font-size: 24px;
            font-weight: 900;
            color: #111827;
            margin-top: 4px;
        }}
        .print-note {{
            margin-top: 18px;
            font-size: 11px;
            color: #64748b;
            text-align: right;
        }}
    </style>
    <div class="plan-nieves-wrap" id="plan-interno-nieves">
        <div class="plan-nieves-header">
            <div>
                <div class="plan-nieves-title">🔧 PLAN INTERNO NIEVES S.A.</div>
                <div class="plan-nieves-sub">
                    <strong>Operativa Mercadona Melilla</strong><br>
                    Fecha operativa: <strong>{_escape_html(fecha_txt)}</strong><br>
                    Generado: {_escape_html(generado_txt)}
                </div>
            </div>
            <div class="plan-nieves-chip">Transportes Nieves S.A. · C-4402</div>
        </div>
    """

    for ch, items in plan.items():
        html += f"""
        <section class="plan-driver">
            <h3>👨 {_escape_html(ch)}</h3>
            <table class="plan-table">
                <thead>
                    <tr>
                        <th style="width:60px;">Nº</th>
                        <th style="width:110px;">Hora</th>
                        <th style="width:130px;">Semi</th>
                        <th style="width:115px;">Descarga</th>
                        <th style="width:115px;">Envases</th>
                        <th>Acción</th>
                    </tr>
                </thead>
                <tbody>
        """
        for n, item in enumerate(items, start=1):
            row_class = "envases-row" if item["tipo"] == "envases" else ""
            descarga = _escape_html(item["descarga"])
            env = _escape_html(item["envases"])
            descarga_html = '<span class="pill-si">✅ SI</span>' if descarga == "SI" else ('<span class="pill-no">❌ NO</span>' if descarga == "NO" else descarga)
            env_html = '<span class="pill-si">✅ SI</span>' if env == "SI" else ('<span class="pill-no">❌ NO</span>' if env == "NO" else env)
            accion = "♻️ " + item["accion"] if item["tipo"] == "envases" else item["accion"]
            html += f"""
                    <tr class="{row_class}">
                        <td>{n}</td>
                        <td>{_escape_html(item["hora"])}</td>
                        <td><strong>{_escape_html(item["semi"])}</strong></td>
                        <td>{descarga_html}</td>
                        <td>{env_html}</td>
                        <td>{_escape_html(accion)}</td>
                    </tr>
            """
        html += """
                </tbody>
            </table>
        </section>
        """

    html += f"""
        <div class="summary-box">
            <div class="summary-title">📊 RESUMEN OPERATIVO</div>
            <div class="summary-grid">
                <div class="summary-card"><div class="label">Servicios</div><div class="value">{resumen["servicios"]}</div></div>
                <div class="summary-card"><div class="label">Semis</div><div class="value">{resumen["semis"]}</div></div>
                <div class="summary-card"><div class="label">Chóferes</div><div class="value">{resumen["choferes"]}</div></div>
                <div class="summary-card"><div class="label">Frío</div><div class="value">{resumen["frio"]}</div></div>
                <div class="summary-card"><div class="label">Envases</div><div class="value">{resumen["envases"]}</div></div>
            </div>
        </div>
        <div class="print-note">Documento interno generado por OP_Mercadona · Transportes Nieves S.A.</div>
    </div>
    """
    return html


def generar_texto(fecha_objetivo, df_servicios, df_llegadas, config_servicios, modo, margen_minutos):
    texto = generar_bloque_llegadas(fecha_objetivo, df_servicios, df_llegadas)
    recogidas_0530_pendientes, historial_semis = [], {}

    if df_servicios is not None and not df_servicios.empty:
        primera_op, primera_hora, turno_act = True, limpiar_hora(df_servicios.iloc[0]["Hora"]), None
        contadores = {"MAÑANA": {}, "TARDE": {}, "NOCHE": {}}

        for hora, grupo in df_servicios.groupby("Hora", sort=False):
            h_limpia = limpiar_hora(hora)
            turno = "MAÑANA" if hora_a_minutos(h_limpia) < 14*60 else ("TARDE" if hora_a_minutos(h_limpia) < 20*60 else "NOCHE")
            if turno != turno_act:
                texto += titulo_turno(turno) + "\n\n"
                turno_act = turno
            texto += f"---------*OPERATIVA MERCADONA {dia_semana_es(fecha_objetivo)} {fecha_objetivo.strftime('%d/%m/%y')} {h_limpia}H EN TIENDA*---------\n\n"
            texto += TEXTOS.get("aviso_entrada", cfg_mod.DEFAULT_TEXTOS["aviso_entrada"]) + "\n\n" if primera_op else "⛔️ *Respetar hora MERCADONA*\n\n"
            primera_op = False

            for idx, fila in grupo.iterrows():
                cfg = config_servicios.get(f"{fila['Semi']}_{fila['Hora']}_{idx}", {})
                if not cfg.get("incluir", True): continue
                semi = fila["Semi"]
                name_ch = nombre_chofer_formateado(cfg.get("chofer", "SIN ASIGNAR"), cfg.get("acompanante", ""))
                comp, env = cfg.get("completa", fila["Descarga completa"]), cfg.get("envases", fila["Retira envases"])
                termica = termica_operativa_manual(cfg.get("termica", ""), fila["Descripción térmica"])
                ch_key = str(cfg.get("chofer", "SIN ASIGNAR")).strip().upper()

                num_serv = contadores.setdefault(turno, {}).get(ch_key, 1)
                if semi in historial_semis and historial_semis[semi]["completa"] == "NO" and comp == "SI":
                    texto += f"{num_serv}º {restar_minutos(h_limpia, margen_minutos)}h _*{name_ch.upper()}*_ recoger en explanadas frente zona talleres el semi *{semi}*\n\n(SEMI PROCEDENTE DE DESCARGA PARCIAL DEL SERVICIO {historial_semis[semi]['hora']}h)\n\n"
                else:
                    texto += f"{num_serv}º {restar_minutos(h_limpia, margen_minutos)}h _*{name_ch.upper()}*_ enganchar el semi *{semi}*\n\n" + ("(SEMI CONTINÚA DE ANTERIOR)\n\n" if semi in historial_semis else "")
                contadores[turno][ch_key] = num_serv + 1

                if debe_mostrar_origen(cfg.get("origen", origen_por_defecto(hora))) and semi not in historial_semis:
                    texto += f"{cfg.get('origen', origen_por_defecto(hora))}\n\n"
                texto += texto_condicion_descarga(comp, env, cfg.get("gestion_envases_0530", "Normal")) + "\n\n"
                if texto_aviso_temperatura(termica): texto += texto_aviso_temperatura(termica) + "\n\n"
                if cfg.get("incidencia", "").strip(): texto += f"⚠️ *INCIDENCIA:* {cfg.get('incidencia')}\n\n"
                if cfg.get("observacion", "").strip(): texto += f"{cfg.get('observacion')}\n\n"
                if texto_post_descarga(comp, env, cfg.get("gestion_envases_0530", "Normal")): texto += texto_post_descarga(comp, env, cfg.get("gestion_envases_0530", "Normal")) + "\n\n"

                if h_limpia == primera_hora and str(cfg.get("gestion_envases_0530", "")).startswith("Envases pendientes"):
                    recogidas_0530_pendientes.append({"semi": semi, "chofer": name_ch.upper(), "ch_key": ch_key, "hora": h_limpia})
                historial_semis[semi] = {"completa": comp, "hora": h_limpia}

            if recogidas_0530_pendientes and h_limpia != primera_hora:
                for p in recogidas_0530_pendientes:
                    num_serv = contadores.setdefault(turno, {}).get(p["ch_key"], 1)
                    texto += f"{num_serv}º _*{p['chofer']}*_ Desde zona talleres enganchar el semi *{p['semi']}* y regresar a Mercadona para cargar envases.\n\n(RECOGIDA ENVASES – SEMI PRIMERA ENTREGA {p['hora']}h)\n\n*Enviad 📸 de la carga e informad de BARRAS, SEPARADORES y ESLINGAS*\n\n"
                    contadores[turno][p["ch_key"]] = num_serv + 1
                    historial_semis[p["semi"]] = {"completa": "SI", "hora": h_limpia}
                recogidas_0530_pendientes = []
            texto += "*----------//----------*\n\n\n"
    return limpiar_texto_whatsapp(texto + aviso_final_por_modo(modo) + "\n\n" + TEXTOS.get("cierre", cfg_mod.DEFAULT_TEXTOS["cierre"]))

def construir_historico_servicios(fecha_objetivo, df_servicios, config_servicios, modo):
    filas = []
    if df_servicios is None or df_servicios.empty: return pd.DataFrame()
    for idx, fila in df_servicios.iterrows():
        cfg = config_servicios.get(f"{fila['Semi']}_{fila['Hora']}_{idx}", {})
        if not cfg.get("incluir", True): continue
        turno_hist = turno_por_hora(fila["Hora"])
        filas.append({
            "generado_por": st.session_state.get("usuario_nombre", ""), "fecha_operativa": fecha_objetivo.strftime("%Y-%m-%d"),
            "dia_semana": dia_semana_es(fecha_objetivo), "modo": modo, "hora_tienda": limpiar_hora(fila["Hora"]),
            "turno": turno_hist, "semi": fila["Semi"],
            "chofer": cfg.get("chofer", "SIN ASIGNAR"), "acompanante_formacion": cfg.get("acompanante", ""),
            "naviera": fila.get("Naviera", ""), "puerto": fila.get("Puerto", ""), "descarga_completa": cfg.get("completa", fila["Descarga completa"]),
            "retira_envases": cfg.get("envases", fila["Retira envases"]), "gestion_envases_0530": cfg.get("gestion_envases_0530", "Normal"),
            "descripcion_termica": termica_operativa_manual(cfg.get("termica", ""), fila["Descripción térmica"]), "origen_instruccion": cfg.get("origen", ""),
            "incidencia": cfg.get("incidencia", "").strip(), "observacion": cfg.get("observacion", "").strip()
        })
    return pd.DataFrame(filas)

def generar_tramo_individual_servicio(idx, fila, cfg, fecha_txt, dia_txt, margen_minutos, historial_semis, numero_servicio):
    h_limpia = limpiar_hora(fila["Hora"])
    name_ch_format = nombre_chofer_formateado(cfg.get("chofer", "SIN ASIGNAR"), cfg.get("acompanante", ""))
    semi = fila["Semi"]
    comp = cfg.get("completa", fila["Descarga completa"])
    env = cfg.get("envases", fila["Retira envases"])
    termica = termica_operativa_manual(cfg.get("termica", ""), fila["Descripción térmica"])

    tramo = f"---------*OPERATIVA MERCADONA {dia_txt} {fecha_txt} {h_limpia}H EN TIENDA*---------\n\n"
    if semi in historial_semis and historial_semis[semi]["completa"] == "NO" and comp == "SI":
        tramo += f"{numero_servicio}º {restar_minutos(h_limpia, margen_minutos)}h _*{name_ch_format.upper()}*_ recoger en explanadas frente zona talleres el semi *{semi}*\n\n(SEMI PROCEDENTE DE DESCARGA PARCIAL DEL SERVICIO {historial_semis[semi]['hora']}h)\n\n"
    else:
        tramo += f"{numero_servicio}º {restar_minutos(h_limpia, margen_minutos)}h _*{name_ch_format.upper()}*_ enganchar el semi *{semi}*\n\n"
        if semi in historial_semis:
            tramo += "(SEMI CONTINÚA DE ANTERIOR)\n\n"

    if debe_mostrar_origen(cfg.get("origen", origen_por_defecto(fila["Hora"]))) and semi not in historial_semis:
        tramo += f"{cfg.get('origen', origen_por_defecto(fila['Hora']))}\n\n"

    tramo += texto_condicion_descarga(comp, env, cfg.get("gestion_envases_0530", "Normal")) + "\n\n"
    if texto_aviso_temperatura(termica):
        tramo += texto_aviso_temperatura(termica) + "\n\n"
    if cfg.get("incidencia", "").strip():
        tramo += f"⚠️ *INCIDENCIA:* {cfg.get('incidencia')}\n\n"
    if cfg.get("observacion", "").strip():
        tramo += f"{cfg.get('observacion')}\n\n"
    if texto_post_descarga(comp, env, cfg.get("gestion_envases_0530", "Normal")):
        tramo += texto_post_descarga(comp, env, cfg.get("gestion_envases_0530", "Normal")) + "\n\n"

    return tramo.strip()

def generar_operativas_individuales(texto_completo, config_servicios, fecha_objetivo, margen_minutos):
    if st.session_state.df_servicios is None or st.session_state.df_servicios.empty:
        return {}

    resultado = {}
    fecha_txt = fecha_objetivo.strftime("%d/%m/%y")
    dia_txt = dia_semana_es(fecha_objetivo)

    footer = ""
    if "*BUEN SERVICIO" in texto_completo:
        inicio_footer = texto_completo.find("*BUEN SERVICIO")
        footer = texto_completo[inicio_footer:].strip()

    plan_por_chofer = {}
    for idx, fila in st.session_state.df_servicios.iterrows():
        key = f"{fila['Semi']}_{fila['Hora']}_{idx}"
        cfg = config_servicios.get(key, {})
        if not cfg.get("incluir", True):
            continue
        ch_principal = str(cfg.get("chofer", "SIN ASIGNAR")).strip().upper()
        if ch_principal == "SIN ASIGNAR" or not ch_principal:
            continue
        plan_por_chofer.setdefault(ch_principal, []).append((idx, fila, cfg))

    for ch_name, servicios_chofer in plan_por_chofer.items():
        servicios_chofer = sorted(servicios_chofer, key=lambda item: hora_a_minutos(limpiar_hora(item[1]["Hora"])))
        salida = [f"👤 *OPERATIVA INDIVIDUAL - {ch_name}*"]
        historial_semis = {}

        # Agrupa los servicios del chófer por turno, manteniendo orden cronológico.
        servicios_por_turno = {}
        orden_turnos = []
        for idx, fila, cfg in servicios_chofer:
            h_limpia = limpiar_hora(fila["Hora"])
            turno = turno_por_hora(h_limpia)
            if turno not in servicios_por_turno:
                servicios_por_turno[turno] = []
                orden_turnos.append(turno)
            servicios_por_turno[turno].append((idx, fila, cfg))

        for turno in orden_turnos:
            salida.append(titulo_turno(turno))
            contador_turno = 1
            pendientes_envases_turno = []

            # Primero: todos los servicios reales del turno.
            for idx, fila, cfg in servicios_por_turno[turno]:
                h_limpia = limpiar_hora(fila["Hora"])
                semi = fila["Semi"]
                comp = cfg.get("completa", fila["Descarga completa"])
                name_ch_format = nombre_chofer_formateado(cfg.get("chofer", "SIN ASIGNAR"), cfg.get("acompanante", ""))

                tramo = generar_tramo_individual_servicio(idx, fila, cfg, fecha_txt, dia_txt, margen_minutos, historial_semis, contador_turno)
                salida.append(tramo)
                contador_turno += 1

                if str(cfg.get("gestion_envases_0530", "")).startswith("Envases pendientes"):
                    pendientes_envases_turno.append({
                        "semi": semi,
                        "chofer": name_ch_format.upper(),
                        "hora": h_limpia,
                    })

                historial_semis[semi] = {"completa": comp, "hora": h_limpia}

            # Segundo: tareas pendientes del turno, después de los servicios normales.
            for pendiente in pendientes_envases_turno:
                salida.append(
                    f"{contador_turno}º _*{pendiente['chofer']}*_ Desde zona talleres enganchar el semi *{pendiente['semi']}* y regresar a Mercadona para cargar envases.\n\n"
                    f"(RECOGIDA ENVASES – SEMI PRIMERA ENTREGA {pendiente['hora']}h)\n\n"
                    "*Enviad 📸 de la carga e informad de BARRAS, SEPARADORES y ESLINGAS*"
                )
                contador_turno += 1
                historial_semis[pendiente["semi"]] = {"completa": "SI", "hora": pendiente["hora"]}

            # Tercero: cierre único del turno individual, una sola vez por turno.
            salida.append("*----------//----------*\n\n" + aviso_estad_atentos_individual())

        if len(salida) > 1:
            if footer:
                salida.append("\n" + footer)
            resultado[ch_name] = limpiar_texto_whatsapp("\n\n".join(salida))

    return resultado

# =========================================================
# FLUJO DE AUTENTICACIÓN Y PANTALLA PRINCIPAL
# =========================================================
if not st.session_state.get("autenticado", False):
    if not auth_mod.obtener_usuarios_secrets():
        st.error("No hay usuario master configurado en Secrets.")
        st.stop()

    st.markdown(
        """
        <style>
            [data-testid="stAppViewContainer"] {
                background:
                    radial-gradient(circle at 18% 10%, rgba(180, 27, 55, 0.22), transparent 30%),
                    radial-gradient(circle at 82% 76%, rgba(14, 116, 85, 0.22), transparent 34%),
                    linear-gradient(135deg, #020617 0%, #071225 48%, #021510 100%) !important;
            }
            [data-testid="stHeader"] { background: rgba(0,0,0,0) !important; }
            .block-container { padding-top: 0.75rem !important; padding-bottom: 0 !important; max-width: 640px !important; }
            .op-version-top { position: fixed; top: 66px; right: 24px; z-index: 9999; color: rgba(226,232,240,.72); font-size: 12px; font-weight: 600; letter-spacing: .01em; font-family: monospace; }
            .op-login-main { width: 100%; max-width: 560px; margin: 0 auto; text-align: center; display: flex; flex-direction: column; align-items: center; }
            .op-chip { display: inline-flex; align-items: center; justify-content: center; width: fit-content; color: #fee2e2; background: rgba(127,29,29,.24); border: 1px solid rgba(248,113,113,.48); border-radius: 999px; padding: 8px 17px; font-size: 13px; font-weight: 800; margin: 0 auto 22px auto !important; box-shadow: 0 8px 24px rgba(127,29,29,.14); }
            .op-logo-wrap { width: 100%; display: flex; justify-content: center; align-items: center; margin: 0 auto 14px auto; animation: logoBreath 5.4s ease-in-out infinite; }
            .op-logo-wrap img { width: min(545px, 88vw); max-height: 158px; object-fit: contain; filter: drop-shadow(0 0 12px rgba(255,255,255,.04)) drop-shadow(0 0 20px rgba(34,197,94,.05)); }
            .op-claim { color: #f3f4f6; font-size: 16.5px; font-weight: 560; text-align: center; margin: 0 auto 44px auto; text-shadow: 0 1px 3px rgba(0,0,0,.55); }
            .op-title { color: #f8fafc; font-size: 29px; font-weight: 900; line-height: 1.1; letter-spacing: -.035em; text-align: center; margin: 0 auto 13px auto; }
            .op-subtitle { color: #e5e7eb; font-size: 14.5px; line-height: 1.45; text-align: center; margin: 0 auto 22px auto; }
            .op-divider { width: min(480px, 82vw); height: 1px; margin: 0 auto 22px auto; background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,.18) 50%, transparent 100%); }
            .op-form-shell { width: 282px; margin: 0 auto; padding: 16px 16px 17px 16px; background: rgba(15,23,42,.26); border: 1px solid rgba(255,255,255,.055); border-radius: 18px; backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); box-shadow: 0 18px 45px rgba(0,0,0,.18), inset 0 1px 0 rgba(255,255,255,.035); }
            div[data-testid="stForm"] { width: 250px !important; max-width: 250px !important; margin: 0 auto !important; border: 0 !important; background: transparent !important; padding: 0 !important; box-shadow: none !important; }
            div[data-testid="stForm"] > div { gap: .18rem !important; }
            div[data-testid="stTextInput"] { width: 250px !important; max-width: 250px !important; margin: 0 auto !important; }
            div[data-testid="stTextInput"] label { color: #f8fafc !important; font-weight: 750 !important; font-size: 13px !important; padding-bottom: .08rem !important; }
            div[data-testid="stTextInput"] input { background: rgba(15,23,42,.58) !important; color: #f8fafc !important; border-radius: 9px !important; border: 1px solid rgba(203,213,225,.45) !important; min-height: 40px !important; height: 40px !important; font-size: 14px !important; padding: 7px 10px !important; box-shadow: inset 0 1px 0 rgba(255,255,255,.04) !important; }
            div[data-testid="stTextInput"] button { background: rgba(15,23,42,.58) !important; color: #e5e7eb !important; border-radius: 0 9px 9px 0 !important; }
            div[data-testid="stFormSubmitButton"] { width: 250px !important; max-width: 250px !important; margin: 10px auto 0 auto !important; }
            div[data-testid="stFormSubmitButton"] button { background: linear-gradient(90deg, #15803d 0%, #16a34a 58%, #22c55e 100%) !important; color: white !important; border-radius: 10px !important; border: none !important; font-size: 15px !important; font-weight: 850 !important; width: 100% !important; min-height: 41px !important; height: 41px !important; box-shadow: 0 10px 24px rgba(22,163,74,.30) !important; }
            @keyframes logoBreath { 0%,100% { transform: translateY(0) scale(1); filter: drop-shadow(0 0 10px rgba(255,255,255,.04)); } 50% { transform: translateY(-2px) scale(1.005); filter: drop-shadow(0 0 14px rgba(255,255,255,.07)) drop-shadow(0 0 24px rgba(34,197,94,.08)); } }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(f'<div class="op-version-top">Versión {APP_VERSION} · JCB</div>', unsafe_allow_html=True)
    st.markdown('<div class="op-login-main">', unsafe_allow_html=True)
    st.markdown('<div class="op-chip">🔒 Acceso autorizado · Transportes Nieves S.A.</div>', unsafe_allow_html=True)

    logo_path = LOGO_OP_MERCADONA_PATH if LOGO_OP_MERCADONA_PATH.exists() else LOGO_NIEVES_PATH
    if logo_path.exists():
        st.markdown(f'<div class="op-logo-wrap"><img src="data:image/png;base64,{base64.b64encode(logo_path.read_bytes()).decode("utf-8")}" alt="OP Mercadona"></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="font-size:48px;font-weight:900;color:#ef4444;">OP_Mercadona</div>', unsafe_allow_html=True)

    st.markdown(
        """
        <div class="op-claim">Alianza Estratégica para la Logística de Distribución.</div>
        <div class="op-title">Operativa Mercadona Melilla</div>
        <div class="op-subtitle">Plataforma privada para planificación servicios Mercadona.</div>
        <div class="op-divider"></div>
        <div class="op-form-shell">
        """,
        unsafe_allow_html=True,
    )

    with st.form("form_login"):
        user = st.text_input("Usuario", max_chars=15)
        pas = st.text_input("Contraseña", type="password", max_chars=15)
        entrar = st.form_submit_button("Entrar")
    st.markdown("</div></div>", unsafe_allow_html=True)

    if entrar:
        datos, err = auth_mod.verificar_login_usuario(user, pas)
        if err: st.error(err)
        else:
            st.session_state.update({"autenticado": True, "usuario_login": datos["usuario"], "usuario_nombre": datos["nombre"], "usuario_rol": datos["rol"], "session_id": str(uuid.uuid4()), "forzar_cambio_password": datos["forzar_cambio"]})
            db_mod.registrar_evento_app("login", "Inicio de sesión")
            st.rerun()
    st.stop()

if st.session_state.get("forzar_cambio_password", False):
    st.markdown('<div class="main-banner"><h1>🔐 Crear contraseña personal</h1><p>Primer acceso detectado. Cambia la contraseña temporal.</p></div>', unsafe_allow_html=True)
    with st.form("form_cambio"):
        n1 = st.text_input("Nueva contraseña", type="password")
        n2 = st.text_input("Repetir nueva contraseña", type="password")
        guardar = st.form_submit_button("Guardar contraseña")
    if guardar:
        ok, msg = auth_mod.validar_password_nueva(n1, n2)
        if not ok: st.error(msg)
        else:
            db_mod.actualizar_password_usuario_sheet(st.session_state["usuario_login"], n1)
            st.session_state["forzar_cambio_password"] = False
            db_mod.registrar_evento_app("cambio_password", "Cambio completado")
            st.success("Contraseña actualizada.")
            st.rerun()
    st.stop()

# Limpiador visual de restos del Login una vez autenticado
st.markdown(
    """
    <style>
        .op-login-main, .op-chip, .op-logo-wrap, .op-claim, .op-title, .op-subtitle, .op-divider, .op-form-shell, .op-version-top {
            display: none !important; visibility: hidden !important; height: 0 !important; margin: 0 !important; padding: 0 !important;
        }
        [data-testid="stAppViewContainer"] { background: #ffffff !important; }
        [data-testid="stHeader"] { background: rgba(255,255,255,0.94) !important; }
    </style>
    """,
    unsafe_allow_html=True
)

# Menú superior de cerrar sesión
col_u, col_o = st.columns([5, 1])
col_u.caption(f"Usuario: {st.session_state.usuario_nombre} · Rol: {st.session_state.usuario_rol} · Versión {APP_VERSION}")
if col_o.button("Salir", key="logout"):
    db_mod.registrar_evento_app("logout", "Cierre de sesión")
    for k in ["autenticado", "usuario_login", "usuario_nombre", "usuario_rol", "session_id", "forzar_cambio_password", "df_servicios", "df_llegadas", "archivos_procesados"]:
        if k in st.session_state: del st.session_state[k]
    st.rerun()

st.markdown('<div class="main-banner"><h1>🚚 Operativa Mercadona Melilla</h1><p>Generador operativo para planificación de semirremolques, chóferes y llegadas.</p></div>', unsafe_allow_html=True)

# Inicializar estados de persistencia temporal en st.session_state
if "df_servicios" not in st.session_state: st.session_state.df_servicios = None
if "df_llegadas" not in st.session_state: st.session_state.df_llegadas = None
if "archivos_procesados" not in st.session_state: st.session_state.archivos_procesados = set()

# Estructura de Pestañas
tabs = ["🚚 Generador", "📊 Dashboard", "⚙️ Configuración"] if st.session_state.usuario_rol == "master" else ["🚚 Generador"]
tabs_rendered = st.tabs(tabs)

# =========================================================
# PESTAÑA: GENERADOR
# =========================================================
with tabs_rendered[0]:
    lista_ch = df_choferes_cfg[df_choferes_cfg["activo"].astype(str).str.upper().eq("SI")]["nombre"].dropna().tolist() + ["OTRO"]

    st.subheader("1. Modo de trabajo")
    modo = st.selectbox("Selecciona el modo", ["Operativa completa normal (2 Excel)", "Operativa adelanto (1 Excel)", "Completar operativa de adelanto (2 Excel)", "Festivo / sin entregas"])
    fecha_obj = st.date_input("Fecha de la operativa", value=date.today())
    margen_minutos = st.selectbox("Margen de enganchar semi antes de entrada a tienda", [20, 30, 45], index=1)

    if modo == "Festivo / sin entregas":
        st.info("Modo festivo seleccionado.")
    else:
        st.subheader("2. Archivos Excel/PDF")
        archivo_unico, archivo_ant, archivo_op = None, None, None

        param_hash = f"{modo}_{fecha_obj.strftime('%Y%m%d')}"

        if modo == "Operativa adelanto (1 Excel)":
            archivo_unico = st.file_uploader("Subir archivo único", type=["xlsm", "xlsx", "pdf"])
            listo = archivo_unico is not None
        else:
            col_a, col_b = st.columns(2)
            archivo_ant = col_a.file_uploader("Subir archivo anterior", type=["xlsm", "xlsx", "pdf"])
            archivo_op = col_b.file_uploader("Subir archivo operativo", type=["xlsm", "xlsx", "pdf"])
            listo = archivo_ant is not None and archivo_op is not None

        current_file_key = f"{archivo_unico.name if archivo_unico else ''}_{archivo_ant.name if archivo_ant else ''}_{archivo_op.name if archivo_op else ''}_{param_hash}"

        if listo and (st.session_state.df_servicios is None or st.session_state.archivos_procesados != current_file_key):
            with st.spinner("Procesando y decodificando archivos por primera vez..."):
                regs = []
                if modo == "Operativa adelanto (1 Excel)":
                    r, err = extraer_registros_archivo(archivo_unico.read(), archivo_unico.name, True)
                    if err: st.error(err); st.stop()
                    regs.extend(r)
                else:
                    r_ant, err_ant = extraer_registros_archivo(archivo_ant.read(), archivo_ant.name, False)
                    r_op, err_op = extraer_registros_archivo(archivo_op.read(), archivo_op.name, True)
                    if err_ant: st.error(err_ant)
                    if err_op: st.error(err_op)
                    if err_ant or err_op: st.stop()
                    regs.extend(r_ant); regs.extend(r_op)

                df_s = construir_servicios(regs, fecha_obj)
                st.session_state.df_servicios = filtrar_servicios_por_modo(df_s, modo)
                df_ll = construir_llegadas(regs, fecha_obj, modo)
                if modo == "Completar operativa de adelanto (2 Excel)" and not df_ll.empty:
                    df_ll = df_ll[df_ll["Naviera"] == "BALEARIA"]
                st.session_state.df_llegadas = df_ll
                st.session_state.archivos_procesados = current_file_key

        if st.session_state.df_servicios is not None:
            st.success("Datos listos en memoria de sesión.")

            st.subheader("3. Llegadas detectadas")
            if st.session_state.df_llegadas.empty: st.warning("Sin llegadas detectadas.")
            else: st.dataframe(st.session_state.df_llegadas, use_container_width=True, hide_index=True)

            st.subheader("4. Servicios detectados")
            if st.session_state.df_servicios.empty: st.warning("Sin servicios asignados.")
            else:
                st.dataframe(st.session_state.df_servicios, use_container_width=True, hide_index=True)
                st.subheader("5. Asignación de chóferes y ajustes")

                config_servicios = {}
                for idx, fila in st.session_state.df_servicios.iterrows():
                    key = f"{fila['Semi']}_{fila['Hora']}_{idx}"
                    h_limpia = limpiar_hora(fila["Hora"])

                    st.markdown(f"### {h_limpia} — {fila['Semi']}")
                    c0, c1, c2, c3, c4 = st.columns([1, 2, 1, 1, 3])

                    incl = c0.checkbox("Incluir", value=True, key=f"incl_{key}")
                    ch_sel = c1.selectbox("Chófer", lista_ch, key=f"ch_{key}")
                    chofer = st.text_input("Escribir chófer", key=f"ch_otro_{key}") if ch_sel == "OTRO" else ch_sel
                    acomp = c1.selectbox("Acompañante", [""] + [c for c in lista_ch if c != chofer and c != "OTRO"], key=f"ac_{key}")
                    comp = c2.selectbox("Completa", ["SI", "NO"], index=0 if fila["Descarga completa"] == "SI" else 1, key=f"co_{key}")
                    env = c3.selectbox("Envases", ["SI", "NO"], index=0 if fila["Retira envases"] == "SI" else 1, key=f"en_{key}")
                    origen = c4.text_input("Origen", value=origen_por_defecto(fila["Hora"]), key=f"or_{key}")

                    g_0530 = "Normal"
                    if h_limpia == "05:30" and comp == "SI" and env == "SI":
                        g_0530 = st.selectbox("Gestión envases 05:30", ["Normal", "Envases pendientes tras servicio 07:00"], key=f"g5_{key}")

                    st.caption(f"Frio detectado: {fila['Descripción térmica']}")
                    term_manual = st.text_input("Descripción térmica manual", value=fila["Descripción térmica"], key=f"te_{key}")
                    obs = st.text_area("Observación adicional", value="", height=70, key=f"ob_{key}")
                    incid = st.text_input("Incidencia (override)", value="", key=f"in_{key}")

                    config_servicios[key] = {"incluir": incl, "chofer": chofer, "acompanante": acomp, "completa": comp, "envases": env, "origen": origen, "hora": h_limpia, "observacion": obs, "incidencia": incid, "termica": term_manual, "gestion_envases_0530": g_0530}

                st.subheader("6. Resumen de Operativa")
                res = resumen_operativo(st.session_state.df_servicios, config_servicios)
                mc0, mc1, mc2, mc3, mc4 = st.columns(5)
                mc0.metric("Servicios", res["Servicios incluidos"])
                mc1.metric("Semis", res["Semis únicos"])
                mc2.metric("Chóferes", res["Chóferes"])
                mc3.metric("Frío", res["Servicios con frío"])
                mc4.metric("Envases", res["Servicios con envases"])

                plan_int = generar_plan_interno(st.session_state.df_servicios, config_servicios)
                plan_int_html = generar_plan_interno_html(st.session_state.df_servicios, config_servicios, fecha_obj)
                if plan_int_html:
                    with st.expander("🔧 Ver plan interno NIEVES S.A.", expanded=False):
                        st.markdown(plan_int_html, unsafe_allow_html=True)

                        html_descarga = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Plan Interno NIEVES S.A.</title>
</head>
<body>
{plan_int_html}
<script>
window.onload = function() {{
    setTimeout(function() {{
        window.print();
    }}, 350);
}};
</script>
</body>
</html>"""

                        col_plan_a, col_plan_b = st.columns([1, 3])
                        with col_plan_a:
                            st.download_button(
                                "🖨️ Descargar / imprimir HTML",
                                data=html_descarga,
                                file_name=f"plan_interno_nieves_{fecha_obj.strftime('%Y%m%d')}.html",
                                mime="text/html",
                                key="descargar_plan_interno_html"
                            )
                        with col_plan_b:
                            with st.expander("Ver texto simple para copiar", expanded=False):
                                st.text_area("Plan simple", plan_int, height=180)

                st.markdown("### Alertas operativas")
                alertas_op = detectar_alertas_operativas(st.session_state.df_servicios, config_servicios)
                if alertas_op:
                    for a in alertas_op: st.warning(f"⚠️ {a}")
                else: st.success("Sin anomalías operativas detectadas.")

                bloqueo = st.checkbox("Bloquear generación si hay alertas", value=False)
                criticas = alertas_envases_nocturnos(st.session_state.df_servicios, config_servicios)
                if criticas: st.markdown("### 🚨 Alertas operativas críticas"); pintar_alertas_envases_nocturnos(criticas)

                if st.button("🚀 GENERAR OPERATIVA"):
                    if bloqueo and alertas_op: st.error("Generación bloqueada por alertas operativas.")
                    else:
                        texto_w = generar_texto(fecha_obj, st.session_state.df_servicios, st.session_state.df_llegadas, config_servicios, modo, margen_minutos)
                        db_mod.registrar_evento_app("genera_operativa", f"Fecha: {fecha_obj} · Modo: {modo}")

                        st.subheader("Operativa completa")
                        boton_copiar_texto(texto_w, clave="completa", etiqueta="📋 Copiar completa")
                        st.text_area("Texto listo para WhatsApp", texto_w, height=450)

                        st.subheader("Operativas individuales por chófer")
                        inds = generar_operativas_individuales(texto_w, config_servicios, fecha_obj, margen_minutos)
                        if not inds:
                            st.info("No hay operativas individuales. Asegúrate de haber asignado chóferes a los servicios incluidos.")
                        else:
                            for ch_ind, txt_ind in inds.items():
                                with st.expander(f"👤 {ch_ind}"):
                                    c_key = f"ind_{ch_ind.replace(' ', '_')}"
                                    boton_copiar_texto(txt_ind, clave=c_key, etiqueta=f"📋 Copiar {ch_ind}")
                                    boton_abrir_whatsapp(txt_ind, clave=f"wa_{c_key}", telefono=telefono_chofer(ch_ind))
                                    st.text_area("Texto", txt_ind, height=250, key=f"txt_area_{c_key}")

                        try:
                            df_h = construir_historico_servicios(fecha_obj, st.session_state.df_servicios, config_servicios, modo)
                            filas_g = db_mod.guardar_historico_google_sheets_raw(df_h, fecha_obj, modo)
                            st.success(f"Histórico consolidado en Google Sheets ({filas_g} servicios).")
                        except Exception as e:
                            st.error(f"⚠️ Alerta: El texto de WhatsApp se generó correctamente, pero no se pudo registrar en el histórico de Google Sheets debido a un fallo de credenciales. Detalles: {e}")

# =========================================================
# SECCIÓN INFERIOR: SEPARACIÓN DE PESTAÑAS MASTER (DASHBOARD Y CONFIG)
# =========================================================
if st.session_state.usuario_rol == "master":
    with tabs_rendered[1]:
        st.subheader("📊 Dashboard Logístico PRO")
        try:
            df_hist_raw = db_mod.cargar_historico_google_sheets()
            if df_hist_raw.empty: st.info("Sin registros históricos.")
            else:
                st.success(f"{len(df_hist_raw)} servicios cargados desde la nube.")
                st.dataframe(df_hist_raw, use_container_width=True)
        except Exception as e:
            st.error(f"Error al cargar el panel de control: {e}")

    with tabs_rendered[2]:
        st.subheader("⚙️ Configuración")
        st.info("Modifica parámetros operativos y chóferes. Los cambios limpian la caché automáticamente.")

        st.markdown("### Usuarios de la app")
        with st.expander("Crear nuevo usuario de acceso", expanded=False):
            n_user = st.text_input("Usuario login")
            n_name = st.text_input("Nombre visible")
            n_rol = st.selectbox("Rol", ["usuario", "master"])
            p_temp = st.text_input("Contraseña temporal", type="password")
            if st.button("Crear usuario"):
                if not n_user or not n_name or not p_temp: st.error("Completa todos los campos.")
                else:
                    try:
                        auth_mod.crear_usuario_sheet_raw(n_user, n_name, n_rol, p_temp, creado_por=st.session_state.usuario_login)
                        st.success("Usuario creado.")
                    except Exception as e: st.error(str(e))

        st.markdown("### Tabla Maestra de Chóferes")
        ed_ch = st.data_editor(df_choferes_cfg, num_rows="dynamic", use_container_width=True, key="ed_choferes")
        if st.button("Guardar chóferes"):
            cfg_mod.guardar_csv_config("choferes.csv", ed_ch)
            st.success("Cambios consolidados. Caché purgada.")
            st.rerun()

        st.markdown("### Tabla Maestra de Navieras / Puertos")
        ed_nv = st.data_editor(df_navieras_cfg, num_rows="dynamic", use_container_width=True, key="ed_navieras")
        if st.button("Guardar navieras"):
            cfg_mod.guardar_csv_config("navieras.csv", ed_nv)
            st.success("Cambios consolidados. Caché purgada.")
            st.rerun()

        st.markdown("### Textos de Operativa Automáticos")
        textos_editados = {}
        for k, v in TEXTOS.items():
            textos_editados[k] = st.text_area(k, value=v, height=70, key=f"t_{k}")
        if st.button("Guardar textos"):
            cfg_mod.guardar_textos(textos_editados)
            st.success("Textos consolidados. Caché purgada.")
            st.rerun()
