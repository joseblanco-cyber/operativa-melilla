# utils/auth.py
import re
import secrets
import hashlib
import hmac
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
    # Limpiar posibles espacios/caracteres de presentación procedentes de Sheets.
    salt_limpio = str(salt or "").strip()
    hash_limpio = str(password_hash or "").strip().lower()
    if not salt_limpio or not hash_limpio:
        return False
    _, digest = hash_password(password, salt=salt_limpio)
    return hmac.compare_digest(digest.lower(), hash_limpio)

def obtener_usuarios_secrets():
    try:
        return st.secrets.get("usuarios", {})
    except Exception:
        return {}

def verificar_login_usuario(usuario, password):
    usuario_key = str(usuario).strip()

    # 1. SOLO el usuario master definido en Secrets tiene prioridad absoluta.
    #    Así puede acceder para administrar la app aunque Google Sheets falle.
    usuarios = obtener_usuarios_secrets()
    datos_secret = usuarios.get(usuario_key) if usuario_key in usuarios else None
    es_master_secret = bool(
        datos_secret
        and str(datos_secret.get("rol", "")).strip().lower() == "master"
    )

    if es_master_secret:
        password_guardada = str(datos_secret.get("password", ""))
        if str(password) != password_guardada:
            hash_introducido = hashlib.sha256(str(password).encode("utf-8")).hexdigest()
            if not hmac.compare_digest(hash_introducido, password_guardada):
                return None, "Usuario o contraseña incorrectos."

        return {
            "usuario": usuario_key,
            "nombre": datos_secret.get("nombre", usuario_key),
            "rol": datos_secret.get("rol", "master"),
            "forzar_cambio": False,
            "origen": "secrets",
        }, ""

    # 2. Todos los usuarios operativos se validan PRIMERO contra usuarios_app.
    #    Esto evita que una copia antigua del mismo usuario en Secrets intercepte
    #    la contraseña vigente almacenada en Google Sheets.
    try:
        _, datos_sheet = obtener_usuario_sheet(usuario_key, propagar_error=True)
    except Exception as e:
        detalle = str(e).replace("\n", " ").replace("\r", " ").strip()
        detalle = re.sub(
            r"(?i)(private[_ -]?key\s*[:=]\s*)([^,;]+)",
            r"\1[OCULTO]",
            detalle
        )
        if len(detalle) > 450:
            detalle = detalle[:450] + "…"
        return None, (
            "No se pudo consultar la base de usuarios de Google Sheets. "
            f"Detalle técnico: {detalle}"
        )

    if datos_sheet:
        if str(datos_sheet.get("activo", "")).strip().upper() != "SI":
            return None, "Usuario desactivado."

        ok = verificar_hash_password(
            password,
            datos_sheet.get("salt", ""),
            datos_sheet.get("password_hash", "")
        )
        if not ok:
            return None, "Usuario o contraseña incorrectos."

        return {
            "usuario": usuario_key,
            "nombre": datos_sheet.get("nombre", usuario_key),
            "rol": datos_sheet.get("rol", "usuario"),
            "forzar_cambio": str(datos_sheet.get("forzar_cambio", "")).strip().upper() == "SI",
            "origen": "sheet",
        }, ""

    # 3. Compatibilidad con algún usuario legado que exista SOLO en Secrets.
    #    Nunca se ejecuta si ese usuario ya existe en usuarios_app.
    if datos_secret:
        password_guardada = str(datos_secret.get("password", ""))
        if str(password) != password_guardada:
            hash_introducido = hashlib.sha256(str(password).encode("utf-8")).hexdigest()
            if not hmac.compare_digest(hash_introducido, password_guardada):
                return None, "Usuario o contraseña incorrectos."

        return {
            "usuario": usuario_key,
            "nombre": datos_secret.get("nombre", usuario_key),
            "rol": datos_secret.get("rol", "usuario"),
            "forzar_cambio": False,
            "origen": "secrets_legacy",
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
