"""
ReadVenture
-----------
App de lectura: el usuario lee textos, responde preguntas y su chango
sube de nivel conforme completa lecturas. Además hay que cuidarlo:
su felicidad baja con el tiempo y se recupera dándole plátanos.

Para correrla:
    pip install -r requirements.txt
    flask --debug run
"""
import json
import math
import sqlite3
from datetime import datetime, timedelta

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = "cambia-esta-clave"  # necesaria para usar session (login)

BASE_DE_DATOS = "readventure.db"

# Una lectura se aprueba con al menos 2 respuestas correctas
ACIERTOS_PARA_APROBAR = 2

# Cuántas letras caben más o menos en una página del "libro"
LETRAS_POR_PAGINA = 600

# Mascota tipo Pou: felicidad y plátanos
FELICIDAD_MAXIMA = 100
MINUTOS_POR_PUNTO = 15       # pierde 1 punto de felicidad cada 15 minutos (de 100 a 0 en 25 horas)
FELICIDAD_POR_PLATANO = 20   # cuánto sube la felicidad al darle un plátano
PLATANOS_MAXIMOS = 5
MINUTOS_POR_PLATANO = 60     # se recarga 1 plátano cada hora

# Tipos de lectura que el usuario puede elegir
CATEGORIAS = {
    "cuentos": "Cuentos",
    "novelas": "Fragmentos de novela",
    "articulos": "Artículos",
    "ciencia": "Ciencia y curiosidades",
}

# Etapas del chango. "lecturas" = cuántas lecturas hay que completar para llegar a esa etapa.
# Las imágenes van en static/img/
ETAPAS = [
    {"nombre": "Chango Bebé", "imagen": "chango1.png", "lecturas": 0},
    {"nombre": "Chango Curioso", "imagen": "chango2.png", "lecturas": 1},
    {"nombre": "Chango Lector", "imagen": "chango3.png", "lecturas": 3},
    {"nombre": "Chango Sabio", "imagen": "chango4.png", "lecturas": 5},
    {"nombre": "Gran Simio Erudito", "imagen": "chango5.png", "lecturas": 7},
]

# Las lecturas se cargan una sola vez desde el archivo JSON
with open("lecturas.json", encoding="utf-8") as archivo:
    LECTURAS = json.load(archivo)


# ---------------------------------------------------------------
# Base de datos (SQLite)
# ---------------------------------------------------------------
def conectar():
    conexion = sqlite3.connect(BASE_DE_DATOS)
    conexion.row_factory = sqlite3.Row  # permite usar fila["columna"]
    return conexion


def crear_tablas():
    conexion = conectar()
    conexion.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            nombre_chango TEXT DEFAULT 'Chango',
            preferencias TEXT DEFAULT '',
            creado_en TEXT DEFAULT (date('now')),
            felicidad INTEGER DEFAULT 100,
            platanos INTEGER DEFAULT 3,
            felicidad_desde TEXT,   -- última vez que se le bajó la felicidad
            platanos_desde TEXT     -- última vez que se le recargó un plátano
        )
    """)
    conexion.execute("""
        CREATE TABLE IF NOT EXISTS progreso (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            lectura_id TEXT NOT NULL,
            aciertos INTEGER NOT NULL,
            UNIQUE (usuario_id, lectura_id)
        )
    """)
    conexion.commit()
    conexion.close()


crear_tablas()


# ---------------------------------------------------------------
# Funciones de ayuda
# ---------------------------------------------------------------
def usuario_actual():
    """Devuelve el usuario que inició sesión, o None si nadie ha iniciado sesión."""
    if "usuario_id" not in session:
        return None
    conexion = conectar()
    usuario = conexion.execute(
        "SELECT * FROM usuarios WHERE id = ?", (session["usuario_id"],)
    ).fetchone()
    conexion.close()
    return usuario


def lecturas_con_estado(usuario):
    """
    Regresa la lista de lecturas del usuario (según sus gustos) y el estado de cada una:
      - "completada": ya la aprobó
      - "disponible": puede leerla ahora
      - "bloqueada": primero debe aprobar la anterior
    """
    preferencias = usuario["preferencias"].split(",")

    conexion = conectar()
    filas = conexion.execute(
        "SELECT lectura_id, aciertos FROM progreso WHERE usuario_id = ?", (usuario["id"],)
    ).fetchall()
    conexion.close()
    aciertos_por_lectura = {fila["lectura_id"]: fila["aciertos"] for fila in filas}

    resultado = []
    anterior_completada = True  # la primera lectura siempre está disponible
    for lectura in LECTURAS:
        # Solo mostramos las categorías que eligió (la lectura "especial" es para todos)
        if lectura["categoria"] not in preferencias and lectura["categoria"] != "especial":
            continue

        aciertos = aciertos_por_lectura.get(lectura["id"], 0)
        if aciertos >= ACIERTOS_PARA_APROBAR:
            estado = "completada"
        elif anterior_completada:
            estado = "disponible"
        else:
            estado = "bloqueada"

        resultado.append({"lectura": lectura, "estado": estado, "aciertos": aciertos})
        anterior_completada = estado == "completada"
    return resultado


def leer_formulario_de_gustos():
    """Lee el nombre del chango y los gustos del formulario. Devuelve (nombre, gustos, error)."""
    nombre_chango = request.form.get("nombre_chango", "").strip() or "Chango"
    gustos = request.form.getlist("categorias")  # lista de checkboxes marcados
    error = None
    if len(gustos) < 2:
        error = "Elige al menos dos tipos de lectura."
    return nombre_chango[:30], gustos, error


def progreso_del_chango(completadas):
    """Calcula la etapa del chango y cuánto le falta para la siguiente (para la barra)."""
    numero = numero_de_etapa(completadas)
    etapa = ETAPAS[numero]
    if numero == len(ETAPAS) - 1:
        # Ya está en la última etapa: barra llena
        return {"etapa": etapa, "numero": numero + 1, "siguiente": None,
                "porcentaje": 100, "hechas": 0, "necesarias": 0}

    siguiente = ETAPAS[numero + 1]
    necesarias = siguiente["lecturas"] - etapa["lecturas"]  # lecturas entre una etapa y otra
    hechas = completadas - etapa["lecturas"]                 # las que ya llevas de ese tramo
    return {"etapa": etapa, "numero": numero + 1, "siguiente": siguiente,
            "porcentaje": int(hechas * 100 / necesarias), "hechas": hechas,
            "necesarias": necesarias}


def actualizar_mascota(usuario_id):
    """
    Aplica el paso del tiempo a la mascota y guarda el resultado:
      - baja 1 punto de felicidad por cada MINUTOS_POR_PUNTO que pasaron
      - recarga 1 plátano por cada MINUTOS_POR_PLATANO que pasaron (hasta PLATANOS_MAXIMOS)
    Regresa un diccionario con el estado de la mascota para mostrarlo en la página.
    """
    conexion = conectar()
    fila = conexion.execute(
        "SELECT felicidad, platanos, felicidad_desde, platanos_desde FROM usuarios WHERE id = ?",
        (usuario_id,),
    ).fetchone()

    ahora = datetime.now()
    felicidad = fila["felicidad"]
    platanos = fila["platanos"]
    # Si todavía no hay fecha guardada (usuario nuevo), empezamos a contar desde ahora
    felicidad_desde = datetime.fromisoformat(fila["felicidad_desde"]) if fila["felicidad_desde"] else ahora
    platanos_desde = datetime.fromisoformat(fila["platanos_desde"]) if fila["platanos_desde"] else ahora

    # 1) Felicidad: cuántos puntos completos se perdieron desde la última vez
    minutos = (ahora - felicidad_desde).total_seconds() / 60
    puntos_perdidos = int(minutos // MINUTOS_POR_PUNTO)
    if puntos_perdidos > 0:
        felicidad = max(0, felicidad - puntos_perdidos)
        # Avanzamos el reloj solo lo que ya contamos, así no se pierden los minutos que sobran
        felicidad_desde += timedelta(minutes=puntos_perdidos * MINUTOS_POR_PUNTO)

    # 2) Plátanos: cuántos se recargaron desde la última vez
    if platanos >= PLATANOS_MAXIMOS:
        platanos_desde = ahora  # está lleno: el reloj empieza a correr cuando gaste uno
    else:
        minutos = (ahora - platanos_desde).total_seconds() / 60
        recargados = int(minutos // MINUTOS_POR_PLATANO)
        if recargados > 0:
            platanos = min(PLATANOS_MAXIMOS, platanos + recargados)
            platanos_desde += timedelta(minutes=recargados * MINUTOS_POR_PLATANO)
            if platanos == PLATANOS_MAXIMOS:
                platanos_desde = ahora

    conexion.execute(
        "UPDATE usuarios SET felicidad = ?, platanos = ?, felicidad_desde = ?, platanos_desde = ? "
        "WHERE id = ?",
        (felicidad, platanos, felicidad_desde.isoformat(), platanos_desde.isoformat(), usuario_id),
    )
    conexion.commit()
    conexion.close()

    # Minutos que faltan para el siguiente plátano (None si ya tiene todos)
    minutos_para_platano = None
    if platanos < PLATANOS_MAXIMOS:
        pasados = (ahora - platanos_desde).total_seconds() / 60
        minutos_para_platano = math.ceil(MINUTOS_POR_PLATANO - pasados)

    # Ánimo según la felicidad (se usa para el color de la barra y el mensaje)
    if felicidad >= 60:
        animo = "feliz"
    elif felicidad >= 30:
        animo = "normal"
    else:
        animo = "triste"

    return {"felicidad": felicidad, "platanos": platanos, "platanos_maximos": PLATANOS_MAXIMOS,
            "minutos_para_platano": minutos_para_platano, "animo": animo}


def dividir_en_paginas(texto):
    """
    Junta los párrafos del texto en páginas de más o menos LETRAS_POR_PAGINA letras.
    Regresa una lista de páginas; cada página es una lista de párrafos.
    """
    paginas = []
    pagina_actual = []
    letras = 0
    for parrafo in texto.split("\n\n"):
        # Si este párrafo ya no cabe, cerramos la página y empezamos otra
        if pagina_actual and letras + len(parrafo) > LETRAS_POR_PAGINA:
            paginas.append(pagina_actual)
            pagina_actual = []
            letras = 0
        pagina_actual.append(parrafo)
        letras += len(parrafo)
    if pagina_actual:
        paginas.append(pagina_actual)
    return paginas


def numero_de_etapa(completadas):
    """Devuelve el índice de la etapa del chango (0 a 4) según las lecturas completadas."""
    etapa = 0
    for i, info in enumerate(ETAPAS):
        if completadas >= info["lecturas"]:
            etapa = i
    return etapa


# ---------------------------------------------------------------
# Rutas: registro e inicio de sesión
# ---------------------------------------------------------------
@app.route("/")
def index():
    """Pantalla de bienvenida. Si ya inició sesión, lo mandamos directo a sus niveles."""
    if usuario_actual():
        return redirect(url_for("inicio"))
    return render_template("intro.html", etapas=ETAPAS)


@app.route("/registro", methods=["GET", "POST"])
def registro():
    error = None
    if request.method == "POST":
        nombre_usuario = request.form["usuario"].strip()
        password = request.form["password"]

        if len(nombre_usuario) < 3 or " " in nombre_usuario:
            error = "El usuario debe tener al menos 3 caracteres y no llevar espacios."
        elif len(password) < 6:
            error = "La contraseña debe tener al menos 6 caracteres."
        else:
            conexion = conectar()
            existe = conexion.execute(
                "SELECT id FROM usuarios WHERE usuario = ?", (nombre_usuario,)
            ).fetchone()
            if existe:
                error = "Ese usuario ya existe. Elige otro."
            else:
                cursor = conexion.execute(
                    "INSERT INTO usuarios (usuario, password) VALUES (?, ?)",
                    (nombre_usuario, generate_password_hash(password)),
                )
                conexion.commit()
                session["usuario_id"] = cursor.lastrowid
                conexion.close()
                return redirect(url_for("preferencias"))
            conexion.close()
    return render_template("registro.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        nombre_usuario = request.form["usuario"].strip()
        password = request.form["password"]

        conexion = conectar()
        usuario = conexion.execute(
            "SELECT * FROM usuarios WHERE usuario = ?", (nombre_usuario,)
        ).fetchone()
        conexion.close()

        if usuario and check_password_hash(usuario["password"], password):
            session["usuario_id"] = usuario["id"]
            return redirect(url_for("inicio"))
        error = "Usuario o contraseña incorrectos."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------------------------------------------------------------
# Rutas: preferencias de lectura
# ---------------------------------------------------------------
@app.route("/preferencias", methods=["GET", "POST"])
def preferencias():
    """Primera configuración después de registrarse: nombre del chango y gustos."""
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for("login"))

    error = None
    if request.method == "POST":
        nombre_chango, gustos, error = leer_formulario_de_gustos()
        if not error:
            conexion = conectar()
            conexion.execute(
                "UPDATE usuarios SET nombre_chango = ?, preferencias = ? WHERE id = ?",
                (nombre_chango, ",".join(gustos), usuario["id"]),
            )
            conexion.commit()
            conexion.close()
            return redirect(url_for("inicio"))

    return render_template("preferencias.html", usuario=usuario, categorias=CATEGORIAS,
                           actuales=usuario["preferencias"].split(","), error=error)


@app.route("/perfil", methods=["GET", "POST"])
def perfil():
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for("login"))

    error = None
    mensaje = None
    if request.method == "POST":
        nombre_chango, gustos, error = leer_formulario_de_gustos()
        if not error:
            conexion = conectar()
            conexion.execute(
                "UPDATE usuarios SET nombre_chango = ?, preferencias = ? WHERE id = ?",
                (nombre_chango, ",".join(gustos), usuario["id"]),
            )
            conexion.commit()
            conexion.close()
            mensaje = "Cambios guardados."
            usuario = usuario_actual()  # volvemos a leerlo para mostrar los datos nuevos

    lista = lecturas_con_estado(usuario)
    completadas = len([item for item in lista if item["estado"] == "completada"])
    gustos = [CATEGORIAS[c] for c in usuario["preferencias"].split(",") if c in CATEGORIAS]

    return render_template("perfil.html", usuario=usuario, categorias=CATEGORIAS,
                           actuales=usuario["preferencias"].split(","), gustos=gustos,
                           completadas=completadas, total=len(lista),
                           chango=progreso_del_chango(completadas),
                           mascota=actualizar_mascota(usuario["id"]),
                           error=error, mensaje=mensaje)


# ---------------------------------------------------------------
# Rutas: pantalla principal y lecciones
# ---------------------------------------------------------------
@app.route("/inicio")
def inicio():
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for("login"))
    if not usuario["preferencias"]:
        return redirect(url_for("preferencias"))

    lista = lecturas_con_estado(usuario)
    completadas = len([item for item in lista if item["estado"] == "completada"])

    return render_template("inicio.html", usuario=usuario, lista=lista,
                           completadas=completadas, chango=progreso_del_chango(completadas),
                           mascota=actualizar_mascota(usuario["id"]),
                           total_etapas=len(ETAPAS), categorias=CATEGORIAS)


@app.route("/alimentar", methods=["POST"])
def alimentar():
    """Le da un plátano al chango (si hay plátanos y no está lleno de felicidad)."""
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for("login"))

    mascota = actualizar_mascota(usuario["id"])  # primero aplicamos el paso del tiempo
    if mascota["platanos"] > 0 and mascota["felicidad"] < FELICIDAD_MAXIMA:
        conexion = conectar()
        conexion.execute(
            "UPDATE usuarios SET platanos = platanos - 1, felicidad = MIN(?, felicidad + ?) WHERE id = ?",
            (FELICIDAD_MAXIMA, FELICIDAD_POR_PLATANO, usuario["id"]),
        )
        conexion.commit()
        conexion.close()

    # Regresamos a la página desde donde se dio el plátano (Inicio o Perfil)
    if request.form.get("volver") == "perfil":
        return redirect(url_for("perfil"))
    return redirect(url_for("inicio"))


@app.route("/leccion/<lectura_id>", methods=["GET", "POST"])
def leccion(lectura_id):
    usuario = usuario_actual()
    if not usuario:
        return redirect(url_for("login"))

    # Revisamos que la lectura exista y que no esté bloqueada
    lista = lecturas_con_estado(usuario)
    item = next((i for i in lista if i["lectura"]["id"] == lectura_id), None)
    if item is None or item["estado"] == "bloqueada":
        return redirect(url_for("inicio"))
    lectura = item["lectura"]

    if request.method == "GET":
        # El libro: las páginas de texto y al final una página con las preguntas
        paginas = dividir_en_paginas(lectura["texto"])
        total_paginas = len(paginas) + 1  # +1 por la página de preguntas

        # ?pagina=2 en la URL indica qué página ver (si no viene, es la 1)
        pagina = request.args.get("pagina", 1, type=int)
        pagina = max(1, min(pagina, total_paginas))  # que no se salga del rango

        return render_template("leccion.html", lectura=lectura, categorias=CATEGORIAS,
                               lista=lista, pagina=pagina, total_paginas=total_paginas,
                               parrafos=paginas[pagina - 1] if pagina < total_paginas else [],
                               es_pagina_de_preguntas=pagina == total_paginas)

    # ----- POST: calificar respuestas -----
    revision = []  # para mostrar en el resultado qué contestó en cada pregunta
    aciertos = 0
    for i, pregunta in enumerate(lectura["preguntas"]):
        respuesta = request.form.get(f"pregunta{i}")  # viene como texto, ej. "2"
        elegida = int(respuesta) if respuesta is not None else -1
        correcta = elegida == pregunta["correcta"]
        if correcta:
            aciertos += 1
        revision.append({"pregunta": pregunta, "elegida": elegida, "correcta": correcta})

    completadas_antes = len([i for i in lista if i["estado"] == "completada"])

    # Guardamos el mejor resultado de esa lectura
    conexion = conectar()
    anterior = conexion.execute(
        "SELECT aciertos FROM progreso WHERE usuario_id = ? AND lectura_id = ?",
        (usuario["id"], lectura_id),
    ).fetchone()
    if anterior is None:
        conexion.execute(
            "INSERT INTO progreso (usuario_id, lectura_id, aciertos) VALUES (?, ?, ?)",
            (usuario["id"], lectura_id, aciertos),
        )
    elif aciertos > anterior["aciertos"]:
        conexion.execute(
            "UPDATE progreso SET aciertos = ? WHERE usuario_id = ? AND lectura_id = ?",
            (aciertos, usuario["id"], lectura_id),
        )
    conexion.commit()
    conexion.close()

    # Premio: la primera vez que apruebas una lectura ganas 1 plátano y tu chango se alegra
    primera_vez = aciertos >= ACIERTOS_PARA_APROBAR and (
        anterior is None or anterior["aciertos"] < ACIERTOS_PARA_APROBAR
    )
    if primera_vez:
        actualizar_mascota(usuario["id"])
        conexion = conectar()
        conexion.execute(
            "UPDATE usuarios SET platanos = MIN(?, platanos + 1), felicidad = MIN(?, felicidad + 10) "
            "WHERE id = ?",
            (PLATANOS_MAXIMOS, FELICIDAD_MAXIMA, usuario["id"]),
        )
        conexion.commit()
        conexion.close()

    # ¿El chango subió de nivel con esta lectura?
    completadas_despues = len([i for i in lecturas_con_estado(usuario) if i["estado"] == "completada"])
    etapa_antes = numero_de_etapa(completadas_antes)
    etapa_despues = numero_de_etapa(completadas_despues)

    return render_template("resultado.html", lectura=lectura, aciertos=aciertos,
                           total=len(lectura["preguntas"]),
                           aprobada=aciertos >= ACIERTOS_PARA_APROBAR,
                           revision=revision, subio=etapa_despues > etapa_antes,
                           etapa=ETAPAS[etapa_despues], usuario=usuario, premio=primera_vez)
