# ReadVenture

## Archivos

```
app.py              <- toda la lógica (rutas, base de datos, niveles del chango)
lecturas.json       <- los textos y sus preguntas
requirements.txt
templates/          <- las páginas HTML (_chango.html es la tarjeta del chango, se usa en Inicio y Perfil)
static/css/estilos.css
static/img/         <- chango1.png ... chango5.png (cámbialas por tus imágenes)
```

## Correr

```
pip install -r requirements.txt
flask --debug run
```

La base de datos `readventure.db` se crea sola. Si la borras, se reinician los usuarios.

## Pantallas

- **Bienvenida**: la primera pantalla, con el botón "Comenzar a leer".
- **Login / Registro**: solo usuario y contraseña.
- **Conoce a tu chango**: después de registrarte, le pones nombre y eliges tus gustos.
- **Inicio**: tu chango a la izquierda con su barra de nivel y la lista de niveles a la derecha.
- **Lección**: panel de niveles a la izquierda y en el centro un libro con flechas para cambiar de página. La última página tiene las preguntas.
- **Resultado**: tu calificación, la revisión de cada pregunta y si tu chango subió de nivel.
- **Perfil**: tus datos, editar tu nombre, el del chango y tus gustos, y cerrar sesión.

## Cómo funciona

- Cada lectura tiene 3 preguntas. Se aprueba con 2 correctas.
- Las lecturas se desbloquean en orden: hay que aprobar la anterior.
- El chango cambia de etapa al completar 1, 3, 5 y 7 lecturas (se cambia en la lista ETAPAS de app.py).

## Felicidad y plátanos (tipo Pou)

- La felicidad del chango baja 1 punto cada 15 minutos (de 100 a 0 en unas 25 horas).
- Darle un plátano sube 20 de felicidad. Tienes máximo 5 plátanos y se recarga 1 cada hora.
- Aprobar una lectura por primera vez te da 1 plátano y +10 de felicidad.
- Todo se calcula con la hora guardada en la base de datos cada vez que abres Inicio o Perfil,
  así que no hace falta tener nada corriendo en segundo plano.
- Los números se cambian al inicio de app.py (MINUTOS_POR_PUNTO, MINUTOS_POR_PLATANO, etc.).

## Tamaño de las páginas del libro

En app.py, `LETRAS_POR_PAGINA = 600` controla cuánto texto cabe en cada página.
Bájalo (por ejemplo a 400) para tener más páginas con menos texto.

## Imágenes del chango

Guarda tus 5 imágenes en `static/img/` con los nombres `chango1.png` a `chango5.png`.
Si usas otro nombre o formato (por ejemplo .jpg), cámbialo en la lista ETAPAS de app.py.

## Agregar lecturas

Copia un bloque de `lecturas.json` y cambia el `id` (debe ser único), título, texto y preguntas.
En `correcta` va la posición de la respuesta correcta, empezando en 0.
Los párrafos del texto se separan con `\n\n`.
