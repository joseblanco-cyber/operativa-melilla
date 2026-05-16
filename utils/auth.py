# utils/auth.py
import secrets
import hashlib
from datetime import datetime
import streamlit as st

# Importamos las funciones necesarias de nuestro módulo database recién creado
from utils.database import (
    obtener_usuario_sheet,
    registros_usuarios_app,
    obtener_worksheet_usuarios,
    actualizar_password_usuario_sheet,
    actualizar_estado_usuario_sheet,
    eliminar_usuario_sheet,
    registrar_evento_app
)

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + str(password)).encode("utf-8")).hexdigest()
    return salt, digest

def verificar_hash_password(password, salt, password_hash):
    if not salt or not password_hash:
        return False
    _, digest = hash_password(password, salt=salt)
    return digest == str(password_hash)

def obtener_usuarios_secrets():
    try:
        return st.secrets.get("usuarios", {})
    except Exception:
        return {}

def verificar_login_usuario(usuario, password):
    usuario_key = str(usuario).strip()

    # 1. Validar usuarios operativos guardados en la base de datos (Google Sheets)
    _, datos_sheet = obtener_usuario_sheet(usuario_key)
    if datos_sheet:
        if str(datos_sheet.get("activo", "")).strip().upper() != "SI":
            return None, "Usuario desactivado."

        ok = verificar_hash_password(password, datos_sheet.get("salt", ""), datos_sheet.get("password_hash", ""))
        if not ok:
            return None, "Usuario o contraseña incorrectos."

        return {
            "usuario": usuario_key,
            "nombre": datos_sheet.get("nombre", usuario_key),
            "rol": datos_sheet.get("rol", "usuario"),
            "forzar_cambio": str(datos_sheet.get("forzar_cambio", "")).strip().upper() == "SI",
            "origen": "sheet",
        }, ""

    # 2. Validar usuario master inicial configurado en Secrets
    usuarios = obtener_usuarios_secrets()
    if usuario_key in usuarios:
        datos = usuarios[usuario_key]
        password_guardada = str(datos.get("password", ""))

        if str(password) != password_guardada:
            hash_introducedcido = hashlib.sha256(str(password).encode("utf-8")).hexdigest()
            if hash_introducedcido != password_guardada:
                return None, "Usuario o contraseña incorrectos."

        return {
            "usuario": usuario_key,
            "nombre": datos.get("nombre", usuario_key),
            "rol": datos.get("rol", "usuario"),
            "forzar_cambio": False,
            "origen": "secrets",
        }, ""

    return None, "Usuario o contraseña incorrectos."

def validar_password_nueva(p1, p2):
    if p1 != p2:
        return False, "Las contraseñas no coinciden."
    if len(p1) < 6:
        return False, "La contraseña debe tener al menos 6 caracteres."
    return True, ""

def crear_usuario_sheet_raw(usuario, nombre, rol, password_temporal, creado_por="master", forzar_cambio=True, activo="SI"):
    worksheet = obtener_worksheet_usuarios()

    _, existente = obtener_usuario_sheet(usuario)
    if existente:
        raise ValueError(f"El usuario '{usuario}' ya existe.")

    salt, password_hash = hash_password(password_temporal)
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fila = [
        str(usuario).strip(),
        str(nombre).strip(),
        str(rol).strip(),
        str(activo).strip().upper(),
        salt,
        password_hash,
        "SI" if forzar_cambio else "NO",
        ahora,
        "",
        creado_por,
    ]
    worksheet.append_row(fila, value_input_option="USER_ENTERED")