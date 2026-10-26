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
                "page_width": float(page.rect.width),
                "page_height": float(page.rect.height),
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
    Lee las columnas visuales de DESCARGA del bloque sin depender de una
    coordenada X fija.

    En la plantilla Mercadona, dentro de cada bloque, la primera pareja
    hora/fecha de izquierda a derecha corresponde a CARGA y las siguientes
    corresponden a DESCARGA. Algunos PDFs desplazan horizontalmente estas
    columnas, por lo que una frontera absoluta de X puede confundir la hora
    de carga con una descarga.

    Reglas:
    - Si se detectan dos o mas horas alineadas, la primera (mas a la izquierda)
      se considera CARGA y se excluye.
    - Las horas restantes se consideran DESCARGAS, incluidas horas no estandar
      como 07:15, 14:30, 16:00, 19:30, etc.
    - Si una segunda descarga carece de fecha, hereda la unica fecha explicita
      de descarga del mismo bloque.
    - Nunca se heredan fechas entre matriculas.
    """
    page = semi_word["page"]
    semi_y = semi_word["y0"]

    # Las plantillas PDF de Mercadona pueden venir exportadas a escalas muy
    # distintas (por ejemplo ~842 pt o ~2406 pt de ancho). Por eso las columnas
    # de carga/descarga se localizan por PORCENTAJE del ancho de la página y no
    # con coordenadas X absolutas.
    page_width = float(semi_word.get("page_width") or 0)
    if page_width <= 0:
        xs = [p.get("x1", 0) for p in palabras if p.get("page") == page]
        page_width = max(xs) if xs else 842.0

    # Esta banda cubre las columnas Fecha/hora de carga y descarga en las
    # plantillas conocidas, pero excluye notas amarillas y horas de EMBARQUE.
    x_min_servicio = page_width * 0.36
    x_max_servicio = page_width * 0.52

    # 1) Horas de la fila cabecera del bloque.
    candidatos_hora = []
    for p in palabras:
        if p["page"] != page:
            continue
        if not (semi_y - 28 <= p["y0"] <= semi_y - 2):
            continue
        if not (x_min_servicio <= p["x0"] <= x_max_servicio):
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

        candidatos_hora.append({
            "hora": f"{hh:02d}:{mm:02d}",
            "x": p["x0"],
        })

    # Deduplicar por posicion/hora y ordenar de izquierda a derecha.
    candidatos_hora = sorted(candidatos_hora, key=lambda x: x["x"])
    horas_ordenadas = []
    for item in candidatos_hora:
        if not any(abs(item["x"] - h["x"]) < 2 and item["hora"] == h["hora"] for h in horas_ordenadas):
            horas_ordenadas.append(item)

    if not horas_ordenadas:
        return []

    # 2) Fechas situadas bajo esas columnas.
    fechas_ordenadas = []
    for p in palabras:
        if p["page"] != page:
            continue
        if not (semi_y - 3 <= p["y0"] <= semi_y + 9):
            continue
        if not (x_min_servicio <= p["x0"] <= x_max_servicio):
            continue
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", p["text"]):
            fecha = parse_fecha_pdf(p["text"])
            if fecha:
                fechas_ordenadas.append({"fecha": fecha, "x": p["x0"]})
    fechas_ordenadas = sorted(fechas_ordenadas, key=lambda x: x["x"])

    # 3) Separar CARGA de DESCARGA por orden relativo, no por X absoluta.
    if len(horas_ordenadas) >= 2:
        # La primera hora es la hora de carga.
        horas_descarga = horas_ordenadas[1:]
    else:
        # Caso degradado: si solo queda una hora, intentamos decidir por las
        # fechas. Con dos o mas fechas, la primera es carga y las demas descarga.
        unica = horas_ordenadas[0]
        if len(fechas_ordenadas) >= 2:
            fecha_carga = fechas_ordenadas[0]
            fechas_descarga_tmp = fechas_ordenadas[1:]
            dist_carga = abs(unica["x"] - fecha_carga["x"])
            dist_desc = min(abs(unica["x"] - f["x"]) for f in fechas_descarga_tmp)
            horas_descarga = [unica] if dist_desc < dist_carga else []
        else:
            # Si el PDF no ofrece suficiente contexto, preferimos conservar la
            # unica hora antes que perder un servicio real.
            horas_descarga = [unica]

    if not horas_descarga:
        return []

    # Primera fecha = carga cuando hay varias columnas de fecha.
    fechas_descarga = fechas_ordenadas[1:] if len(fechas_ordenadas) >= 2 else fechas_ordenadas

    fechas_unicas_descarga = []
    for f in fechas_descarga:
        if f["fecha"] not in fechas_unicas_descarga:
            fechas_unicas_descarga.append(f["fecha"])

    salida = []
    for h in horas_descarga:
        fecha_servicio = None
        fecha_inferida = False

        # Fecha explicita de la misma columna si esta razonablemente alineada.
        if fechas_descarga:
            cercana = min(fechas_descarga, key=lambda f: abs(f["x"] - h["x"]))
            if abs(cercana["x"] - h["x"]) <= 14:
                fecha_servicio = cercana["fecha"]

        # Si una descarga no trae fecha y solo hay una fecha de descarga
        # explicita en el bloque, heredarla para conservar el doble arrastre.
        if fecha_servicio is None and len(fechas_unicas_descarga) == 1:
            fecha_servicio = fechas_unicas_descarga[0]
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
        semi_y = float(semi_word["y0"])
        page_width = float(semi_word.get("page_width") or 842.0)
        page_height = float(semi_word.get("page_height") or 595.2)

        # Delimitar cada bloque por los puntos medios entre matriculas.
        # Esto evita depender de margenes Y fijos que dejan de funcionar
        # cuando Mercadona exporta el mismo PDF a otra escala.
        if i > 0 and bloques[i - 1]["page"] == page:
            y_ini = (float(bloques[i - 1]["y0"]) + semi_y) / 2.0
        else:
            y_ini = max(0.0, semi_y - page_height * 0.05)

        if i + 1 < len(bloques) and bloques[i + 1]["page"] == page:
            y_fin = (semi_y + float(bloques[i + 1]["y0"])) / 2.0
        else:
            y_fin = min(page_height, semi_y + page_height * 0.20)

        # El limite horizontal historico era x<=520 sobre una pagina de
        # ~842 pt (aprox. 61,8%). Escalarlo al ancho real conserva Puerto,
        # mercancia, envases y notas utiles en PDFs grandes sin invadir las
        # tablas administrativas de la derecha.
        x_fin_bloque = page_width * (520.0 / 842.0)

        bloque_words = [
            p for p in palabras
            if p["page"] == page
            and y_ini <= p["y0"] <= y_fin
            and p["x0"] <= x_fin_bloque
        ]
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
