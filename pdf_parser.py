# utils/pdf_parser.py
import re
from datetime import datetime, date

def parse_fecha_pdf(valor):
    try:
        return datetime.strptime(valor, "%d/%m/%Y").date()
    except Exception:
        return None

def detectar_puerto_en_texto(texto):
    texto_up = str(texto).upper().replace(" ", "")
    candidatos = [
        ("P.MOTRIL", "P. MOTRIL"), ("PMOTRIL", "P. MOTRIL"),
        ("P.ALMERIA", "P. ALMERIA"), ("PALMERIA", "P. ALMERIA"),
        ("P.MALAGA", "P. MALAGA"), ("PMALAGA", "P. MALAGA"),
        ("P.MELILLA", "P. MELILLA"), ("PMELILLA", "P. MELILLA"),
    ]
    for c, out in candidatos:
        if c in texto_up:
            return out
    return ""

def detectar_envases_texto_pdf(texto):
    # Función auxiliar para limpiar cadenas (reemplaza normalizar interno)
    unido = str(texto).strip().upper().replace(" ", "")
    return ("ENVASES" in unido) or ("RETORNO" in unido)

def extraer_horas(texto):
    if not texto:
        return []
    encontrados = re.findall(r"\b(\d{1,2}:\d{2})(?::\d{2})?\b", str(texto))
    horas = []
    for h in encontrados:
        hh, mm = h.split(":")
        limpia = f"{int(hh):02d}:{mm}"
        if limpia not in horas:
            horas.append(limpia)
    return horas

def limpiar_hora(hora):
    return str(hora).strip().lower().replace("h", "")

def palabras_pdf_por_posicion(bytes_archivo):
    try:
        import fitz  # PyMuPDF
    except Exception as e:
        raise RuntimeError("Falta la librería pymupdf. Añade 'pymupdf' a requirements.txt.") from e

    doc = fitz.open(stream=bytes_archivo, filetype="pdf")
    palabras = []
    for page_index, page in enumerate(doc):
        for w in page.get_text("words"):
            x0, y0, x1, y1, txt = w[:5]
            palabras.append({
                "page": page_index,
                "x0": float(x0),
                "y0": float(y0),
                "x1": float(x1),
                "y1": float(y1),
                "text": str(txt),
                "upper": str(txt).upper(),
            })
    return palabras

def encontrar_bloques_pdf_posicional(palabras):
    semis = []
    for p in palabras:
        if re.fullmatch(r"R\d{4}[A-Z]{3}", p["upper"]):
            if p["x0"] <= 360:
                semis.append(p)

    semis = sorted(semis, key=lambda p: (p["page"], p["y0"], p["x0"]))
    bloques = []
    usados = set()
    for p in semis:
        clave = (p["upper"], round(p["y0"] / 18))
        if clave in usados:
            continue
        usados.add(clave)
        bloques.append(p)
    return bloques

def texto_de_palabras(palabras):
    ordenadas = sorted(palabras, key=lambda p: (p["page"], p["y0"], p["x0"]))
    return " ".join(p["text"] for p in ordenadas)

def horas_fechas_pdf_por_fila_visual(palabras, semi_word, fecha_fallback=None):
    """
    Lee las columnas visuales de DESCARGA del bloque.

    La plantilla sitúa la hora de carga a la izquierda y las horas de descarga
    a partir de x ~= 345. Esto permite aceptar horas no incluidas en una lista
    fija (07:15, 14:30, 16:00, nuevos horarios de sábado, etc.) sin confundir
    normalmente la hora de carga.

    Si una segunda descarga carece de fecha, hereda la única fecha explícita
    de descarga del mismo bloque. Nunca toma una fecha de otra matrícula.
    """
    page = semi_word["page"]
    semi_y = semi_word["y0"]

    posibles_horas = []
    for p in palabras:
        if p["page"] != page:
            continue
        if not (semi_y - 28 <= p["y0"] <= semi_y - 2):
            continue
        if not (345 <= p["x0"] <= 430):
            continue

        texto = limpiar_hora(p["text"])
        if not re.fullmatch(r"\d{1,2}:\d{2}", texto):
            continue
        try:
            hh, mm = [int(x) for x in texto.split(":")]
        except Exception:
            continue
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            continue

        h = f"{hh:02d}:{mm:02d}"
        posibles_horas.append({"hora": h, "x": p["x0"]})

    horas = []
    for item in sorted(posibles_horas, key=lambda x: x["x"]):
        if item["hora"] not in [h["hora"] for h in horas]:
            horas.append(item)

    if not horas:
        return []

    # Solo fechas que están bajo las columnas de descarga. Se excluye la fecha
    # de carga situada más a la izquierda.
    fechas_words = []
    for p in palabras:
        if p["page"] != page:
            continue
        if not (semi_y - 3 <= p["y0"] <= semi_y + 9):
            continue
        if p["x0"] < 345:
            continue
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", p["text"]):
            fecha = parse_fecha_pdf(p["text"])
            if fecha:
                fechas_words.append({"fecha": fecha, "x": p["x0"]})

    fechas_unicas = []
    for f in fechas_words:
        if f["fecha"] not in fechas_unicas:
            fechas_unicas.append(f["fecha"])

    salida = []
    for h in horas:
        fecha_servicio = None
        fecha_inferida = False

        # Fecha explícita de la misma columna si está suficientemente alineada.
        if fechas_words:
            cercana = min(fechas_words, key=lambda f: abs(f["x"] - h["x"]))
            distancia = abs(cercana["x"] - h["x"])
            if distancia <= 14:
                fecha_servicio = cercana["fecha"]

        # Si falta la fecha de una columna y solo existe una fecha explícita de
        # descarga en el bloque, la heredamos: caso típico de doble arrastre.
        if fecha_servicio is None and len(fechas_unicas) == 1:
            fecha_servicio = fechas_unicas[0]
            fecha_inferida = True

        if fecha_servicio is None and fecha_fallback is not None:
            fecha_servicio = fecha_fallback
            fecha_inferida = True

        salida.append({
            "hora": h["hora"],
            "fecha": fecha_servicio,
            "col": None,
            "fecha_inferida": fecha_inferida,
        })

    return salida


def limpiar_horas_administrativas_pdf(texto_bloque, horas):
    texto = str(texto_bloque)
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    horas_limpias = []

    for h in horas:
        operativa = False
        admin = False
        for linea in lineas:
            if h not in linea:
                continue
            l = str(linea).strip().upper().replace(" ", "")
            if "EMBARQUE" in l or "RETORNO" in l or "RETIRAENVASES" in l:
                admin = True
            else:
                operativa = True
        if operativa or not admin:
            if h not in horas_limpias:
                horas_limpias.append(h)
    return horas_limpias

def horas_fechas_pdf_por_bloque(texto_bloque, fecha_fallback=None):
    horas_servicio_validas = ["05:30", "06:15", "07:00", "15:00", "20:30", "21:30", "22:00", "22:30"]
    horas = []
    for h in extraer_horas(texto_bloque):
        if h in horas_servicio_validas and h not in horas:
            horas.append(h)

    horas = limpiar_horas_administrativas_pdf(texto_bloque, horas)
    fechas = []
    for f in re.findall(r"\b\d{2}/\d{2}/\d{4}\b", texto_bloque):
        fecha = parse_fecha_pdf(f)
        if fecha and fecha not in fechas:
            fechas.append(fecha)

    fecha_servicio = fechas[-1] if fechas else fecha_fallback
    return [{"hora": h, "fecha": fecha_servicio, "col": None} for h in horas]

def tipo_bloque_pdf(texto_bloque):
    t = str(texto_bloque).strip().upper().replace(" ", "")
    if "REPESCA" in t or "CONGELADO" in t or "REFRIGERADO" in t:
        return "MIXTO_REPESCA"
    if "REFRIGERADO" in t or "AGUA" in t or "AGUA" in t or "REPESCA" in t:
        return "MIXTO_REFRIGERADO/AGUA/RESTO PERECEDERAS"    
    if "PLANIFICARTODOELSP" in t or re.search(r"\bSP\b", texto_bloque.upper()):
        return "TODO_SECO"
    if "PICKING" in t or "DROGUERIA" in t or "COSMETICA" in t or "ALCOHOL" in t:
        return "TODO_SECO"
    if "CARNE" in t or "FRUTA" in t or "PESCADO" in t:
        return "TODO_REFRIGERADO"
    return ""

def termica_pdf_por_bloque(texto_bloque, categoria_segmento_fn):
    tipo = tipo_bloque_pdf(texto_bloque)
    t = str(texto_bloque).strip().upper().replace(" ", "")

    if tipo == "TODO_REFRIGERADO":
        return ["REFRIGERADO_3"], {"REFRIGERADO_3", "PDF_POSICIONAL"}
    if tipo == "TODO_SECO":
        return ["SECO"], {"SECO", "PDF_POSICIONAL"}

    if tipo == "MIXTO_REPESCA":
        cats = []
        marcas = {"PDF_POSICIONAL"}
        if "REFRIGERADO" in t or "FRIO" in t or "FRÍO" in t:
            cats.append("REFRIGERADO_3")
            marcas.add("REFRIGERADO_3")
        if "SECO" in t or "SECOS" in t or "REPESCA" in t:
            cats.append("SECO")
            marcas.add("SECO")
        if "CONGELADO" in t or "-25" in t:
            cats.append("CONGELADO_25")
            marcas.add("CONGELADO_25")
        if not cats:
            cats = ["REFRIGERADO_3", "SECO", "CONGELADO_25"]
            marcas.update(cats)
        return cats, marcas

    categorias_ordenadas = []
    marcas_detectadas = set()
    for parte in re.split(r"[/,\n; ]+", texto_bloque.upper()):
        cat = categoria_segmento_fn(parte)
        if cat:
            marcas_detectadas.add(cat)
            if cat not in categorias_ordenadas:
                categorias_ordenadas.append(cat)
    return categorias_ordenadas, marcas_detectadas

def ajustar_servicios_pdf_por_tipo(registro, texto_bloque):
    tipo = tipo_bloque_pdf(texto_bloque)
    horas = registro.get("Horas fechas", [])
    if not horas:
        return registro

    if tipo == "MIXTO_REPESCA":
        filtradas = [hf for hf in horas if hf["hora"] in ["07:00", "15:00"]]
        horas_presentes = {hf["hora"] for hf in filtradas}
        if "15:00" in horas_presentes and "07:00" not in horas_presentes:
            ref = next(hf for hf in filtradas if hf["hora"] == "15:00")
            filtradas.insert(0, {"hora": "07:00", "fecha": ref["fecha"], "col": None})
        if "07:00" in horas_presentes and "15:00" not in horas_presentes:
            ref = next(hf for hf in filtradas if hf["hora"] == "07:00")
            filtradas.append({"hora": "15:00", "fecha": ref["fecha"], "col": None})
        if filtradas:
            orden = {"07:00": 1, "15:00": 2}
            registro["Horas fechas"] = sorted(filtradas, key=lambda hf: orden.get(hf["hora"], 99))

    elif tipo in ["TODO_SECO", "TODO_REFRIGERADO"]:
        texto_norm = str(texto_bloque).strip().upper().replace(" ", "")
        horas_filtradas = []
        for hf in horas:
            h = hf["hora"]
            if h == "15:00" and ("EMBARQUE15:00" in texto_norm or "RETORNOENVASES" in texto_norm):
                continue
            horas_filtradas.append(hf)

        if horas_filtradas:
            prioridad = ["05:30", "06:15", "20:30", "21:30", "22:00", "22:30", "15:00", "07:00"]
            for h in prioridad:
                seleccion = [hf for hf in horas_filtradas if hf["hora"] == h]
                if seleccion:
                    registro["Horas fechas"] = [seleccion[0]]
                    break
            else:
                registro["Horas fechas"] = [horas_filtradas[0]]
        else:
            registro["Horas fechas"] = [horas[0]]
    return registro

def extraer_registros_pdf_posicional(bytes_archivo, nombre_archivo, es_excel_operativo, obtener_naviera_fn, categoria_segmento_fn, descripcion_termica_fn):
    palabras = palabras_pdf_por_posicion(bytes_archivo)
    bloques = encontrar_bloques_pdf_posicional(palabras)
    if not bloques:
        return [], "No se detectaron bloques posicionales en el PDF."

    registros = []
    for i, semi_word in enumerate(bloques):
        page = semi_word["page"]
        y_ini = semi_word["y0"] - 18
        y_fin = bloques[i + 1]["y0"] - 18 if i + 1 < len(bloques) and bloques[i + 1]["page"] == page else semi_word["y0"] + 118

        bloque_words = [p for p in palabras if p["page"] == page and y_ini <= p["y0"] <= y_fin and p["x0"] <= 520]
        texto_bloque = texto_de_palabras(bloque_words)
        if not texto_bloque.strip():
            continue

        horas_fechas = horas_fechas_pdf_por_fila_visual(palabras, semi_word)
        horas_desde_fila_visual = bool(horas_fechas)
        if not horas_fechas:
            horas_fechas = horas_fechas_pdf_por_bloque(texto_bloque)
        if not horas_fechas:
            continue

        categorias, marcas = termica_pdf_por_bloque(texto_bloque, categoria_segmento_fn)
        descripcion = descripcion_termica_fn(categorias, sorted(marcas)) if categorias else "REVISAR"
        puerto = detectar_puerto_en_texto(texto_bloque)
        naviera = obtener_naviera_fn(puerto)

        registro = {
            "Archivo": nombre_archivo,
            "Es Excel operativo": es_excel_operativo,
            "Semi": semi_word["upper"],
            "Puerto": puerto,
            "Naviera": naviera,
            "Horas fechas": horas_fechas,
            "Mercancías detectadas": ", ".join(sorted([m for m in marcas if m != "PDF_POSICIONAL"])),
            "Orden térmico detectado": " / ".join([c for c in categorias if c != "PDF_POSICIONAL"]),
            "Descripción térmica": descripcion,
            "Retira envases detectado": "SI" if detectar_envases_texto_pdf(texto_bloque) else "NO",
            "Fila": "",
            "Origen archivo": "PDF_POSICIONAL",
        }
        # Si las horas proceden de las columnas visuales de descarga, no las
        # sustituimos por horas inferidas desde notas/leyendas. Así se conserva
        # lo que realmente figura en la cuadrícula (p. ej. 14:30 frente a una
        # nota que pudiera indicar 15:00). El ajuste histórico se mantiene solo
        # como red de seguridad cuando falla la lectura visual.
        if horas_desde_fila_visual:
            registro["Horas fechas"] = sorted(
                registro["Horas fechas"],
                key=lambda hf: (hf.get("fecha") is None, hf.get("fecha") or date.max, hf.get("hora", ""))
            )
            registros.append(registro)
        else:
            registros.append(ajustar_servicios_pdf_por_tipo(registro, texto_bloque))
    return registros, None

def extraer_texto_pdf(bytes_archivo):
    import fitz
    texto = []
    doc = fitz.open(stream=bytes_archivo, filetype="pdf")
    for page in doc:
        texto.append(page.get_text("text"))
    return "\n".join(texto)

def extraer_registros_pdf_lineal(bytes_archivo, nombre_archivo, es_excel_operativo, obtener_naviera_fn, categoria_segmento_fn, descripcion_termica_fn):
    texto = extraer_texto_pdf(bytes_archivo)
    posiciones = list(re.finditer(r"R\d{4}[A-Z]{3}", texto.upper()))
    if not posiciones:
        return [], f"No se detectaron matrículas en el PDF {nombre_archivo}"

    registros = []
    horas_servicio_validas = {"05:30", "06:15", "07:00", "15:00", "20:30", "21:30", "22:00", "22:30"}
    semis_procesados = set()

    for i, match in enumerate(posiciones):
        semi = match.group(0)
        if semi in semis_procesados:
            continue

        inicio = match.start()
        fin = posiciones[i + 1].start() if i + 1 < len(posiciones) else len(texto)
        bloque = texto[inicio:fin]
        if len(bloque) < 400:
            fin = posiciones[i + 3].start() if i + 3 < len(posiciones) else min(len(texto), inicio + 1600)
            bloque = texto[inicio:fin]

        horas_detectadas = []
        for h in extraer_horas(bloque):
            if h in horas_servicio_validas and h not in horas_detectadas:
                horas_detectadas.append(h)

        fechas_detectadas = []
        for f in re.findall(r"\b\d{2}/\d{2}/\d{4}\b", bloque):
            fecha = parse_fecha_pdf(f)
            if fecha and fecha not in fechas_detectadas:
                fechas_detectadas.append(fecha)

        if not horas_detectadas or not fechas_detectadas:
            continue

        horas_fechas = []
        fecha_ref = fechas_detectadas[-1]
        for h in horas_detectadas:
            horas_fechas.append({"hora": h, "fecha": fecha_ref, "col": None})

        puerto = detectar_puerto_en_texto(bloque)
        naviera = obtener_naviera_fn(puerto)

        categorias_ordenadas, marcas_detectadas = termica_pdf_por_bloque(bloque, categoria_segmento_fn)
        descripcion = descripcion_termica_fn(categorias_ordenadas, sorted(marcas_detectadas)) if categorias_ordenadas else "REVISAR"

        registros.append({
            "Archivo": nombre_archivo,
            "Es Excel operativo": es_excel_operativo,
            "Semi": semi,
            "Puerto": puerto,
            "Naviera": naviera,
            "Horas fechas": horas_fechas,
            "Mercancías detectadas": ", ".join(sorted([m for m in marcas_detectadas if m != "PDF_POSICIONAL"])),
            "Orden térmico detectado": " / ".join([c for c in categorias_ordenadas if c != "PDF_POSICIONAL"]),
            "Descripción térmica": descripcion,
            "Retira envases detectado": "SI" if detectar_envases_texto_pdf(bloque) else "NO",
            "Fila": "",
            "Origen archivo": "PDF_EMERGENCIA",
        })
        semis_procesados.add(semi)
    return registros, None

def extraer_registros_pdf(bytes_archivo, nombre_archivo, es_excel_operativo, obtener_naviera_fn, categoria_segmento_fn, descripcion_termica_fn):
    """
    Lector híbrido PDF:
    1) Usa el parser posicional como fuente principal, porque respeta mejor bloques/filas.
    2) Usa el parser lineal como red de seguridad para semis especiales que el posicional puede saltarse
       por disposición visual distinta, por ejemplo servicios tipo "DESCARGAMOS 6:15".
    3) Fusiona sin duplicar por matrícula.
    """
    aviso = None
    registros_posicional = []
    registros_lineal = []

    try:
        registros_posicional, aviso = extraer_registros_pdf_posicional(
            bytes_archivo,
            nombre_archivo,
            es_excel_operativo,
            obtener_naviera_fn,
            categoria_segmento_fn,
            descripcion_termica_fn
        )
    except Exception as e:
        aviso = f"PDF posicional no disponible: {e}"

    try:
        registros_lineal, aviso_lineal = extraer_registros_pdf_lineal(
            bytes_archivo,
            nombre_archivo,
            es_excel_operativo,
            obtener_naviera_fn,
            categoria_segmento_fn,
            descripcion_termica_fn
        )
    except Exception as e:
        aviso_lineal = f"PDF lineal no disponible: {e}"

    if registros_posicional:
        registros = list(registros_posicional)
        semis_existentes = {str(r.get("Semi", "")).strip().upper() for r in registros}

        for r in registros_lineal:
            semi = str(r.get("Semi", "")).strip().upper()
            if semi and semi not in semis_existentes:
                registros.append(r)
                semis_existentes.add(semi)

        return registros, None

    if registros_lineal:
        return registros_lineal, aviso or aviso_lineal

    return [], aviso_lineal or aviso or f"No se pudieron construir servicios desde el PDF {nombre_archivo}"
