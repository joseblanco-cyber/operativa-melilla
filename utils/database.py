# utils/database.py
import streamlit as st
import gspread
import pandas as pd
from datetime import datetime
from google.oauth2.service_account import Credentials

GOOGLE_SHEET_NAME = "Historico Operativas Mercadona Melilla"
GOOGLE_SHEET_TAB = "historico"
GOOGLE_SHEET_ACCESOS_TAB = "accesos_app"
GOOGLE_SHEET_USUARIOS_TAB = "usuarios_app"
APP_VERSION = "1.7.8"

def conectar_google_sheets():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    
    # Extraemos las credenciales guardadas en st.secrets
    info_creds = dict(st.secrets["gcp_service_account"])
    
    # Limpieza automática robusta: reemplazamos saltos de línea literales, 
    # quitamos espacios huérfanos y nos aseguramos de que el PEM sea puro.
    if "private_key" in info_creds:
        pk = info_creds["private_key"]
        # Si viene con '\n' textuales, los convertimos en saltos de línea reales
        pk = pk.replace("\\n", "\n")
        # Aseguramos que las líneas iniciales y finales queden limpias
        pk = pk.replace("-----BEGIN PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----\n")
        pk = pk.replace("-----END PRIVATE KEY-----", "\n-----END PRIVATE KEY-----")
        # Compactamos saltos de línea dobles accidentales
        pk = re.sub(r"\n+", "\n", pk)
        info_creds["private_key"] = pk.strip()

    creds = Credentials.from_service_account_info(
        info_creds,
        scopes=scope,
    )
    return gspread.authorize(creds)

def obtener_worksheet_historico():
    client = conectar_google_sheets()
    spreadsheet = client.open(GOOGLE_SHEET_NAME)
    try:
        return spreadsheet.worksheet(GOOGLE_SHEET_TAB)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=GOOGLE_SHEET_TAB, rows=1000, cols=30)

def asegurar_cabeceras_google_sheets(worksheet, columnas):
    """
    Optimizado para evitar exceso de cuota en Google Sheets.
    Solo lee la primera fila en vez de toda la hoja.
    """
    try:
        actuales = worksheet.row_values(1)
    except Exception:
        actuales = []

    if not actuales:
        worksheet.append_row(columnas, value_input_option="USER_ENTERED")
        return

    if actuales != columnas:
        faltantes = [c for c in columnas if c not in actuales]
        if faltantes:
            for i, col in enumerate(faltantes, start=len(actuales) + 1):
                worksheet.update_cell(1, i, col)

def guardar_historico_google_sheets_raw(df_hist, fecha_objetivo, modo):
    if df_hist.empty:
        raise ValueError("No hay servicios incluidos para guardar en Google Sheets.")

    df_hist = df_hist.copy()
    df_hist.insert(0, "fecha_registro", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    df_hist.insert(1, "id_generacion", f"{fecha_objetivo.strftime('%Y-%m-%d')}_{modo}")

    columnas = df_hist.columns.tolist()
    filas = df_hist.astype(str).values.tolist()

    worksheet = obtener_worksheet_historico()
    asegurar_cabeceras_google_sheets(worksheet, columnas)

    ultimo_error = None
    for intento in range(3):
        try:
            worksheet.append_rows(filas, value_input_option="USER_ENTERED")
            return len(filas)
        except Exception as e:
            ultimo_error = e
            texto_error = str(e)
            if "Quota exceeded" in texto_error or "Read requests" in texto_error or "Write requests" in texto_error:
                import time
                time.sleep(2 + intento * 3)
                continue
            raise

    raise ultimo_error

def cargar_historico_google_sheets():
    worksheet = obtener_worksheet_historico()
    registros = worksheet.get_all_records()
    if not registros:
        return pd.DataFrame()
    df = pd.DataFrame(registros)
    if "fecha_operativa" in df.columns:
        df["fecha_operativa"] = pd.to_datetime(df["fecha_operativa"], errors="coerce")
    return df

def obtener_worksheet_accesos():
    client = conectar_google_sheets()
    spreadsheet = client.open(GOOGLE_SHEET_NAME)
    try:
        worksheet = spreadsheet.worksheet(GOOGLE_SHEET_ACCESOS_TAB)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=GOOGLE_SHEET_ACCESOS_TAB, rows=1000, cols=20)

    columnas = ["fecha_hora", "session_id", "usuario", "nombre", "rol", "accion", "detalle", "app_version"]
    if not worksheet.get_all_values():
        worksheet.append_row(columnas, value_input_option="USER_ENTERED")
    return worksheet

def obtener_worksheet_usuarios():
    client = conectar_google_sheets()
    spreadsheet = client.open(GOOGLE_SHEET_NAME)
    try:
        worksheet = spreadsheet.worksheet(GOOGLE_SHEET_USUARIOS_TAB)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=GOOGLE_SHEET_USUARIOS_TAB, rows=1000, cols=20)

    columnas = [
        "usuario", "nombre", "rol", "activo", "salt",
        "password_hash", "forzar_cambio", "fecha_alta",
        "ultimo_cambio", "creado_por"
    ]
    valores = worksheet.get_all_values()
    if not valores:
        worksheet.append_row(columnas, value_input_option="USER_ENTERED")
        return worksheet

    primera_fila = [str(v).strip() for v in valores[0]]
    if primera_fila[:len(columnas)] != columnas:
        worksheet.insert_row(columnas, index=1, value_input_option="USER_ENTERED")
    return worksheet

def registros_usuarios_app():
    worksheet = obtener_worksheet_usuarios()
    valores = worksheet.get_all_values()
    if not valores:
        return []

    cabeceras = [str(v).strip() for v in valores[0]]
    registros = []
    for fila in valores[1:]:
        if not any(str(v).strip() for v in fila):
            continue
        registro = {}
        for i, cabecera in enumerate(cabeceras):
            if not cabecera:
                continue
            registro[cabecera] = fila[i] if i < len(fila) else ""
        registros.append(registro)
    return registros

def registrar_evento_app(accion, detalle=""):
    try:
        if "usuario_login" not in st.session_state:
            return
        worksheet = obtener_worksheet_accesos()
        fila = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            st.session_state.get("session_id", ""),
            st.session_state.get("usuario_login", ""),
            st.session_state.get("usuario_nombre", ""),
            st.session_state.get("usuario_rol", ""),
            accion,
            str(detalle),
            APP_VERSION,
        ]
        worksheet.append_row(fila, value_input_option="USER_ENTERED")
    except Exception:
        pass

def obtener_usuario_sheet(usuario):
    usuario = str(usuario).strip()
    if not usuario:
        return None, None
    try:
        registros = registros_usuarios_app()
        for idx, r in enumerate(registros, start=2):
            if str(r.get("usuario", "")).strip() == usuario:
                return idx, r
    except Exception:
        return None, None
    return None, None

def actualizar_password_usuario_sheet(usuario, nueva_password):
    row_idx, datos = obtener_usuario_sheet(usuario)
    if not row_idx or not datos:
        raise ValueError("Usuario no encontrado.")

    worksheet = obtener_worksheet_usuarios()
    from utils.auth import hash_password
    salt, password_hash = hash_password(nueva_password)
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cabeceras = worksheet.row_values(1)
    mapa = {c: i + 1 for i, c in enumerate(cabeceras)}

    worksheet.update_cell(row_idx, mapa["salt"], salt)
    worksheet.update_cell(row_idx, mapa["password_hash"], password_hash)
    worksheet.update_cell(row_idx, mapa["forzar_cambio"], "NO")
    worksheet.update_cell(row_idx, mapa["ultimo_cambio"], ahora)

def actualizar_estado_usuario_sheet(usuario, activo="NO"):
    row_idx, datos = obtener_usuario_sheet(usuario)
    if not row_idx or not datos:
        raise ValueError("Usuario no encontrado.")

    worksheet = obtener_worksheet_usuarios()
    cabeceras = worksheet.row_values(1)
    mapa = {c: i + 1 for i, c in enumerate(cabeceras)}

    if "activo" not in mapa:
        raise ValueError("La hoja usuarios_app no tiene columna activo.")

    worksheet.update_cell(row_idx, mapa["activo"], str(activo).strip().upper())

def eliminar_usuario_sheet(usuario):
    row_idx, datos = obtener_usuario_sheet(usuario)
    if not row_idx or not datos:
        raise ValueError("Usuario no encontrado.")

    worksheet = obtener_worksheet_usuarios()
    worksheet.delete_rows(row_idx)