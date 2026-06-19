import tkinter as tk
from tkinter import ttk, messagebox
import requests
from PIL import Image, ImageTk
from io import BytesIO
import threading
import random
import webbrowser  # Para abrir el navegador al hacer clic en una tarjeta

# ──────────────────────────────────────────────
#  CONFIGURACIÓN GENERAL
# ──────────────────────────────────────────────
CLAVE_API     = "f888ef6c9c494a1da35c236b5ec5508b"
URL_BASE      = "https://api.themoviedb.org/3"
URL_IMAGENES  = "https://image.tmdb.org/t/p/w185"  # Tamaño de póster: 185px de ancho

# Paleta de colores de la interfaz
COLOR_FONDO      = "#141414"
COLOR_TARJETA    = "#1f1f1f"
COLOR_ROJO       = "#e50914"
COLOR_BLANCO     = "#ffffff"
COLOR_GRIS       = "#808080"
COLOR_OSCURO     = "#2a2a2a"


def _oscurecer_color(color_hex, factor=0.82):
    """Oscurece un color hexadecimal un poco, para el efecto hover de los botones."""
    color_hex = color_hex.lstrip("#")
    r, g, b = (int(color_hex[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (max(0, int(c * factor)) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


# ──────────────────────────────────────────────
#  MOTOR DE CONSULTAS A TMDB
# ──────────────────────────────────────────────
class MotorTMDB:
    """Clase encargada de todas las comunicaciones con la API de TMDB."""

    def __init__(self):
        # Sesión reutilizable para mayor eficiencia en las peticiones HTTP
        self.sesion = requests.Session()

    def _obtener(self, endpoint, parametros={}):
        """Realiza una petición GET a la API y devuelve el JSON de respuesta."""
        parametros["api_key"] = CLAVE_API
        parametros["language"] = "es-ES"  # Respuestas en español
        respuesta = self.sesion.get(f"{URL_BASE}{endpoint}", params=parametros, timeout=10)
        respuesta.raise_for_status()
        return respuesta.json()

    def buscar(self, consulta):
        """Busca películas y series según el texto introducido por el usuario."""
        datos = self._obtener("/search/multi", {"query": consulta})
        # Filtrar solo películas (movie) y series (tv), descartar personas u otros
        return [r for r in datos.get("results", [])
                if r.get("media_type") in ("movie", "tv")][:5]

    def obtener_recomendaciones(self, id_media, tipo_media):
        """Devuelve una lista de recomendaciones para una película o serie dada."""
        datos = self._obtener(f"/{tipo_media}/{id_media}/recommendations")
        recomendaciones = []
        for r in datos.get("results", [])[:12]:
            recomendaciones.append({
                "titulo":     r.get("title") or r.get("name", "Sin título"),
                "tipo":       "Película" if tipo_media == "movie" else "Serie",
                "tipo_raw":   tipo_media,   # "movie" o "tv" para construir la URL
                "id_tmdb":    r.get("id"),  # ID necesario para la URL de TMDB
                "puntuacion": r.get("vote_average", 0),
                "sinopsis":   (r.get("overview") or "Sinopsis no disponible.")[:160],
                "poster":     r.get("poster_path", ""),
            })
        return recomendaciones

    def descargar_poster(self, ruta):
        """Descarga un póster desde TMDB y lo devuelve como imagen de tkinter."""
        if not ruta:
            return None
        try:
            respuesta = self.sesion.get(URL_IMAGENES + ruta, timeout=8)
            imagen = Image.open(BytesIO(respuesta.content)).resize((111, 167))
            return ImageTk.PhotoImage(imagen)
        except Exception:
            return None  # Si falla la descarga, devolvemos nada (se mostrará placeholder)

    def obtener_detalles(self, id_media, tipo_media):
        """Obtiene los detalles completos de una película o serie, incluyendo créditos."""
        datos = self._obtener(
            f"/{tipo_media}/{id_media}",
            {"append_to_response": "credits"}
        )
        generos = [g["name"] for g in datos.get("genres", [])]
        return {
            "titulo":     datos.get("title") or datos.get("name", ""),
            "generos":    generos,
            "puntuacion": datos.get("vote_average", 0),
            "sinopsis":   datos.get("overview", ""),
            "poster":     datos.get("poster_path", ""),
        }

    def obtener_generos(self, tipo_media):
        """Devuelve la lista de géneros disponibles en TMDB para 'movie' o 'tv'."""
        datos = self._obtener(f"/genre/{tipo_media}/list")
        return datos.get("genres", [])

    def explorar_por_genero(self, tipo_media, id_genero, puntuacion_minima):
        """Busca películas o series de un género concreto con una puntuación mínima."""
        parametros = {
            "with_genres":      id_genero,
            "vote_average.gte": puntuacion_minima,
            "vote_count.gte":   30,  # Evita títulos con muy pocos votos (puntuación poco fiable)
            "sort_by":          "popularity.desc",
        }
        datos = self._obtener(f"/discover/{tipo_media}", parametros)
        resultados = []
        for r in datos.get("results", [])[:20]:
            resultados.append({
                "titulo":     r.get("title") or r.get("name", "Sin título"),
                "tipo":       "Película" if tipo_media == "movie" else "Serie",
                "tipo_raw":   tipo_media,
                "id_tmdb":    r.get("id"),
                "puntuacion": r.get("vote_average", 0),
                "sinopsis":   (r.get("overview") or "Sinopsis no disponible.")[:160],
                "poster":     r.get("poster_path", ""),
            })
        return resultados


# ──────────────────────────────────────────────
#  TARJETA VISUAL DE CADA RECOMENDACIÓN
# ──────────────────────────────────────────────
class TarjetaPelicula(tk.Frame):
    """Widget que muestra el póster, título, puntuación y tipo de una recomendación."""

    ANCHO  = 130  # Ancho fijo de cada tarjeta en píxeles
    ALTO   = 268  # Alto fijo de cada tarjeta en píxeles

    def __init__(self, padre, recomendacion, motor, **kwargs):
        super().__init__(padre, bg=COLOR_TARJETA,
                         width=self.ANCHO, height=self.ALTO,
                         highlightthickness=2, highlightbackground=COLOR_TARJETA,
                         **kwargs)
        self.pack_propagate(False)  # Evita que el frame se redimensione con su contenido
        self._referencia_imagen = None  # Guardamos referencia para evitar que el GC borre la imagen

        # ── Póster (placeholder oscuro hasta que cargue la imagen) ──
        self.etiqueta_imagen = tk.Label(self, bg=COLOR_OSCURO,
                                        width=self.ANCHO, height=167,
                                        cursor="hand2")
        self.etiqueta_imagen.pack()

        # ── Insignia para las mejor valoradas, para llamar la atención ──
        puntuacion = recomendacion["puntuacion"]
        if puntuacion >= 8.5:
            texto_insignia, color_insignia, color_texto_insignia = "👑 OBRA MAESTRA", "#ffd60a", "#1a1a1a"
        elif puntuacion >= 7.5:
            texto_insignia, color_insignia, color_texto_insignia = "🔥 MUY VALORADA", COLOR_ROJO, COLOR_BLANCO
        else:
            texto_insignia = None

        if texto_insignia:
            tk.Label(self, text=texto_insignia, font=("Arial", 7, "bold"),
                     fg=color_texto_insignia, bg=color_insignia,
                     padx=4, pady=1).pack(pady=(4, 0))

        # ── Título (truncado si es muy largo) ──
        titulo = recomendacion["titulo"]
        if len(titulo) > 22:
            titulo = titulo[:20] + "…"
        tk.Label(self, text=titulo, font=("Arial", 9, "bold"),
                 fg=COLOR_BLANCO, bg=COLOR_TARJETA,
                 wraplength=self.ANCHO - 8,
                 justify="center").pack(pady=(4, 0))

        # ── Puntuación con color según valor ──
        if puntuacion >= 7:
            color_puntuacion = "#f5c518"   # Amarillo: buena puntuación
        elif puntuacion >= 5:
            color_puntuacion = "#e07b39"   # Naranja: puntuación media
        else:
            color_puntuacion = COLOR_GRIS  # Gris: puntuación baja o sin datos

        tk.Label(self, text=f"⭐ {puntuacion:.1f}",
                 font=("Arial", 9),
                 fg=color_puntuacion, bg=COLOR_TARJETA).pack()

        # ── Tipo: Película o Serie ──
        tk.Label(self, text=recomendacion["tipo"],
                 font=("Arial", 8),
                 fg=COLOR_GRIS, bg=COLOR_TARJETA).pack()

        # ── Tooltip con sinopsis al pasar el cursor ──
        self._tooltip = None
        self._sinopsis = recomendacion["sinopsis"]
        self.etiqueta_imagen.bind("<Enter>", self._mostrar_tooltip)
        self.etiqueta_imagen.bind("<Leave>", self._ocultar_tooltip)
        self.bind("<Enter>", self._mostrar_tooltip)
        self.bind("<Leave>", self._ocultar_tooltip)

        # ── Abrir cliver.mom al hacer clic en el póster o la tarjeta ──
        self._titulo_original = recomendacion["titulo"]
        self.etiqueta_imagen.bind("<Button-1>", self._abrir_en_cliver)
        self.bind("<Button-1>", self._abrir_en_cliver)

        # ── Cargar imagen en segundo plano para no bloquear la interfaz ──
        threading.Thread(
            target=self._cargar_imagen,
            args=(motor, recomendacion["poster"]),
            daemon=True
        ).start()

    def _abrir_en_cliver(self, evento=None):
        """Abre cliver.mom en el navegador buscando el título de la película o serie."""
        import urllib.parse
        consulta = urllib.parse.quote(self._titulo_original)
        url = f"https://cliver.mom/index.php?do=search&subaction=search&story={consulta}"
        webbrowser.open(url)

    def _cargar_imagen(self, motor, ruta):
        """Descarga el póster en un hilo secundario y lo muestra al terminar."""
        foto = motor.descargar_poster(ruta)
        if foto:
            self._referencia_imagen = foto  # Mantener referencia para evitar que Python la elimine
            self.etiqueta_imagen.after(
                0,
                lambda: self.etiqueta_imagen.configure(
                    image=self._referencia_imagen, width=111, height=167
                )
            )

    def _mostrar_tooltip(self, evento=None):
        """Resalta la tarjeta y muestra una ventana emergente con la sinopsis."""
        self.configure(highlightbackground=COLOR_ROJO)  # Borde rojo al pasar el cursor
        if self._tooltip or not self._sinopsis:
            return
        x = self.winfo_rootx() + 10
        y = self.winfo_rooty() + 170
        self._tooltip = ventana = tk.Toplevel(self)
        ventana.wm_overrideredirect(True)  # Sin borde ni barra de título
        ventana.wm_geometry(f"+{x}+{y}")
        texto_tooltip = self._sinopsis + "\n\n🖱️ Clic para ver en cliver.mom"
        tk.Label(
            ventana, text=texto_tooltip,
            font=("Arial", 9), bg="#222", fg=COLOR_BLANCO,
            wraplength=220, justify="left", padx=8, pady=6,
            relief="flat"
        ).pack()

    def _ocultar_tooltip(self, evento=None):
        """Quita el resalte del borde y cierra el tooltip al retirar el cursor."""
        self.configure(highlightbackground=COLOR_TARJETA)
        if self._tooltip:
            self._tooltip.destroy()
            self._tooltip = None


# ──────────────────────────────────────────────
#  VENTANA PRINCIPAL DE LA APLICACIÓN
# ──────────────────────────────────────────────
class Aplicacion:
    """Clase principal que construye y gestiona la interfaz gráfica completa."""

    def __init__(self, ventana):
        self.ventana = ventana
        self.ventana.title("Recomendador de Películas y Series · TMDB")
        self.ventana.geometry("980x760")
        self.ventana.configure(bg=COLOR_FONDO)

        self.motor           = MotorTMDB()
        self.resultados_busqueda = []
        self._tarjetas       = []
        self._generos_pelicula = {}  # nombre → id, se rellena al arrancar
        self._generos_serie    = {}

        self._construir_interfaz()

        # Cargar géneros desde TMDB en segundo plano para no bloquear el arranque
        threading.Thread(target=self._cargar_generos, daemon=True).start()

    def _construir_interfaz(self):
        """Construye todos los elementos visuales de la aplicación."""

        # ── Estilo oscuro para los combobox (ttk no hereda el bg por defecto) ──
        estilo = ttk.Style()
        estilo.theme_use("clam")
        estilo.configure(
            "TCombobox",
            fieldbackground=COLOR_TARJETA, background=COLOR_TARJETA,
            foreground=COLOR_BLANCO, arrowcolor=COLOR_BLANCO,
            selectbackground=COLOR_TARJETA, selectforeground=COLOR_BLANCO,
            bordercolor=COLOR_TARJETA, lightcolor=COLOR_TARJETA,
            darkcolor=COLOR_TARJETA, relief="flat", padding=6
        )
        estilo.map(
            "TCombobox",
            fieldbackground=[("readonly", COLOR_TARJETA)],
            foreground=[("readonly", COLOR_BLANCO)],
            # Borde rojo al enfocar el campo, para que destaque al usarlo
            bordercolor=[("focus", COLOR_ROJO), ("!focus", COLOR_TARJETA)],
        )
        # El desplegable (la lista que aparece al hacer clic) también en oscuro
        self.ventana.option_add("*TCombobox*Listbox.background", COLOR_TARJETA)
        self.ventana.option_add("*TCombobox*Listbox.foreground", COLOR_BLANCO)
        self.ventana.option_add("*TCombobox*Listbox.selectBackground", COLOR_ROJO)
        self.ventana.option_add("*TCombobox*Listbox.selectForeground", COLOR_BLANCO)
        self.ventana.option_add("*TCombobox*Listbox.font", ("Arial", 10))

        def crear_boton(padre, texto, comando):
            """Botón rojo con efecto hover, reutilizado en Buscar y Explorar."""
            boton = tk.Button(
                padre, text=texto, font=("Arial", 11, "bold"),
                bg=COLOR_ROJO, fg=COLOR_BLANCO, relief="flat",
                padx=18, pady=7, cursor="hand2", bd=0,
                activebackground="#b20710", activeforeground=COLOR_BLANCO,
                command=comando
            )
            boton.bind("<Enter>", lambda e: boton.configure(bg="#b20710"))
            boton.bind("<Leave>", lambda e: boton.configure(bg=COLOR_ROJO))
            return boton
        self._crear_boton = crear_boton

        # ── Encabezado ──
        encabezado = tk.Frame(self.ventana, bg=COLOR_FONDO)
        encabezado.pack(fill="x", padx=24, pady=(18, 0))
        tk.Label(encabezado, text="TMDB",
                 font=("Arial", 24, "bold"),
                 fg=COLOR_ROJO, bg=COLOR_FONDO).pack(side="left")
        tk.Label(encabezado, text="  Recomendador de Películas y Series",
                 font=("Arial", 15), fg=COLOR_BLANCO, bg=COLOR_FONDO).pack(side="left", pady=4)

        tk.Label(
            self.ventana, text="🍿  Descubre tu próxima película o serie favorita",
            font=("Arial", 10), fg=COLOR_GRIS, bg=COLOR_FONDO
        ).pack(anchor="w", padx=24, pady=(0, 6))

        # ── Barra de búsqueda ──
        marco_busqueda = tk.Frame(self.ventana, bg=COLOR_FONDO)
        marco_busqueda.pack(fill="x", padx=24, pady=4)
        tk.Label(marco_busqueda,
                 text="Escribe el nombre de una película o serie que te haya gustado:",
                 font=("Arial", 11), fg=COLOR_GRIS, bg=COLOR_FONDO).pack(anchor="w")

        fila_entrada = tk.Frame(marco_busqueda, bg=COLOR_FONDO)
        fila_entrada.pack(fill="x", pady=(4, 0))

        self.campo_busqueda = tk.Entry(
            fila_entrada, font=("Arial", 13),
            bg=COLOR_TARJETA, fg=COLOR_BLANCO,
            insertbackground=COLOR_BLANCO, relief="flat", bd=8
        )
        self.campo_busqueda.pack(side="left", fill="x", expand=True, ipady=7)
        self.campo_busqueda.bind("<Return>", lambda e: self._buscar())  # Buscar al pulsar Enter

        self._crear_boton(fila_entrada, "Buscar", self._buscar).pack(side="left", padx=(8, 0))

        # ── Barra de estado ──
        self.texto_estado = tk.StringVar(
            value="Escribe el nombre de una película o serie y pulsa Buscar"
        )
        tk.Label(
            self.ventana, textvariable=self.texto_estado,
            font=("Arial", 10), fg=COLOR_GRIS, bg=COLOR_FONDO
        ).pack(anchor="w", padx=24, pady=2)

        # ── Panel de filtro por género y puntuación mínima (tarjeta destacada) ──
        tarjeta_filtros = tk.Frame(
            self.ventana, bg=COLOR_TARJETA,
            highlightbackground=COLOR_OSCURO, highlightthickness=1
        )
        tarjeta_filtros.pack(fill="x", padx=24, pady=(6, 8))

        contenido_filtros = tk.Frame(tarjeta_filtros, bg=COLOR_TARJETA)
        contenido_filtros.pack(fill="x", padx=18, pady=14)

        tk.Label(
            contenido_filtros, text="🎭  Explorar por género y puntuación",
            font=("Arial", 11, "bold"), fg=COLOR_BLANCO, bg=COLOR_TARJETA
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))

        # Etiquetas pequeñas en mayúsculas sobre cada campo (estilo "label flotante")
        for columna, texto in enumerate(("TIPO", "GÉNERO", "PUNTUACIÓN MÍN.")):
            tk.Label(
                contenido_filtros, text=texto, font=("Arial", 8, "bold"),
                fg=COLOR_GRIS, bg=COLOR_TARJETA
            ).grid(row=1, column=columna, sticky="w", padx=(0 if columna == 0 else 16, 0))

        # Tipo: Película o Serie (cada uno tiene su propia lista de géneros en TMDB)
        self.var_tipo = tk.StringVar(value="Película")
        combo_tipo = ttk.Combobox(
            contenido_filtros, textvariable=self.var_tipo,
            values=["Película", "Serie"], state="readonly",
            width=10, font=("Arial", 10)
        )
        combo_tipo.grid(row=2, column=0, sticky="we", pady=(3, 0))
        combo_tipo.bind("<<ComboboxSelected>>", lambda e: self._actualizar_generos())

        # Género (ciencia ficción, terror, acción, comedia...)
        self.var_genero = tk.StringVar()
        self.combo_genero = ttk.Combobox(
            contenido_filtros, textvariable=self.var_genero,
            state="readonly", width=24, font=("Arial", 10)
        )
        self.combo_genero.set("Cargando géneros…")
        self.combo_genero.grid(row=2, column=1, sticky="we", padx=(16, 0), pady=(3, 0))

        # Puntuación mínima
        self.var_puntuacion = tk.StringVar(value="7+ ⭐")
        combo_puntuacion = ttk.Combobox(
            contenido_filtros, textvariable=self.var_puntuacion,
            values=["5+ ⭐", "6+ ⭐", "7+ ⭐", "8+ ⭐", "9+ ⭐"],
            state="readonly", width=8, font=("Arial", 10)
        )
        combo_puntuacion.grid(row=2, column=2, sticky="we", padx=(16, 0), pady=(3, 0))

        self._crear_boton(contenido_filtros, "Explorar", self._explorar_por_genero).grid(
            row=2, column=3, sticky="we", padx=(16, 0), pady=(3, 0)
        )

        # ── Acceso rápido: chips de géneros populares + botón Sorpréndeme ──
        marco_chips = tk.Frame(contenido_filtros, bg=COLOR_TARJETA)
        marco_chips.grid(row=3, column=0, columnspan=4, sticky="we", pady=(14, 0))

        fila_encabezado_chips = tk.Frame(marco_chips, bg=COLOR_TARJETA)
        fila_encabezado_chips.pack(fill="x", pady=(0, 6))
        tk.Label(fila_encabezado_chips, text="ACCESO RÁPIDO", font=("Arial", 8, "bold"),
                 fg=COLOR_GRIS, bg=COLOR_TARJETA).pack(side="left")

        boton_sorpresa = tk.Button(
            fila_encabezado_chips, text="🎲 Sorpréndeme",
            font=("Arial", 9, "bold"), bg="#ffd60a", fg="#1a1a1a",
            relief="flat", bd=0, padx=10, pady=3, cursor="hand2",
            activebackground="#ffd60a", activeforeground="#1a1a1a",
            command=self._sorprendeme
        )
        boton_sorpresa.bind("<Enter>", lambda e: boton_sorpresa.configure(bg=_oscurecer_color("#ffd60a")))
        boton_sorpresa.bind("<Leave>", lambda e: boton_sorpresa.configure(bg="#ffd60a"))
        boton_sorpresa.pack(side="right")

        # Géneros destacados en dos filas, cada uno con su propio color para dar vida visual
        generos_destacados = [
            [("Acción", "💥", "#ff6b35"), ("Terror", "👻", "#6c3483"),
             ("Comedia", "😂", "#f1c40f"), ("Ciencia ficción", "🚀", "#00b4d8")],
            [("Romance", "💕", "#ff4d6d"), ("Animación", "🎨", "#06d6a0"),
             ("Drama", "🎭", "#5c6bc0"), ("Suspense", "😱", "#2c2c54")],
        ]
        for fila_generos in generos_destacados:
            fila_chips = tk.Frame(marco_chips, bg=COLOR_TARJETA)
            fila_chips.pack(anchor="w", pady=(0, 6))
            for nombre, emoji, color in fila_generos:
                color_texto = "#1a1a1a" if nombre in ("Comedia", "Animación") else COLOR_BLANCO
                chip = tk.Button(
                    fila_chips, text=f"{emoji} {nombre}", font=("Arial", 9, "bold"),
                    bg=color, fg=color_texto, relief="flat", bd=0,
                    padx=10, pady=4, cursor="hand2",
                    activebackground=color, activeforeground=color_texto,
                    command=lambda n=nombre: self._explorar_chip(n)
                )
                chip.bind("<Enter>", lambda e, b=chip, c=color: b.configure(bg=_oscurecer_color(c)))
                chip.bind("<Leave>", lambda e, b=chip, c=color: b.configure(bg=c))
                chip.pack(side="left", padx=(0, 6))

        # ── Panel principal: lista izquierda + tarjetas derecha ──
        panel_principal = tk.Frame(self.ventana, bg=COLOR_FONDO)
        panel_principal.pack(fill="both", expand=True, padx=24, pady=(4, 16))

        # Columna izquierda: lista de resultados de búsqueda
        columna_izquierda = tk.Frame(panel_principal, bg=COLOR_FONDO, width=230)
        columna_izquierda.pack(side="left", fill="y", padx=(0, 14))
        columna_izquierda.pack_propagate(False)

        tk.Label(columna_izquierda, text="Resultados de búsqueda",
                 font=("Arial", 10, "bold"),
                 fg=COLOR_BLANCO, bg=COLOR_FONDO).pack(anchor="w")

        self.lista_resultados = tk.Listbox(
            columna_izquierda, font=("Arial", 11),
            bg=COLOR_TARJETA, fg=COLOR_BLANCO,
            selectbackground=COLOR_ROJO, selectforeground=COLOR_BLANCO,
            relief="flat", bd=0, activestyle="none"
        )
        self.lista_resultados.pack(fill="both", expand=True, pady=(4, 0))
        self.lista_resultados.bind("<<ListboxSelect>>", self._al_seleccionar)

        # Columna derecha: tarjetas con pósters
        columna_derecha = tk.Frame(panel_principal, bg=COLOR_FONDO)
        columna_derecha.pack(side="left", fill="both", expand=True)

        tk.Label(columna_derecha, text="Recomendaciones",
                 font=("Arial", 10, "bold"),
                 fg=COLOR_BLANCO, bg=COLOR_FONDO).pack(anchor="w")

        # Canvas con scroll horizontal para mostrar todas las tarjetas
        marco_canvas = tk.Frame(columna_derecha, bg=COLOR_FONDO)
        marco_canvas.pack(fill="both", expand=True, pady=(4, 0))

        self.canvas = tk.Canvas(marco_canvas, bg=COLOR_FONDO, highlightthickness=0)
        self.canvas.pack(side="top", fill="both", expand=True)

        barra_scroll = ttk.Scrollbar(marco_canvas, orient="horizontal",
                                     command=self.canvas.xview)
        barra_scroll.pack(side="bottom", fill="x")
        self.canvas.configure(xscrollcommand=barra_scroll.set)

        # Frame interno que contiene las tarjetas
        self.marco_tarjetas = tk.Frame(self.canvas, bg=COLOR_FONDO)
        self.canvas.create_window((0, 0), window=self.marco_tarjetas, anchor="nw")
        self.marco_tarjetas.bind("<Configure>", self._actualizar_scroll)

        # ── Área de sinopsis de la selección actual ──
        self.area_sinopsis = tk.Text(
            self.ventana, font=("Arial", 10),
            bg=COLOR_TARJETA, fg=COLOR_GRIS,
            relief="flat", height=3, wrap="word",
            state="disabled", bd=10
        )
        self.area_sinopsis.pack(fill="x", padx=24, pady=(0, 12))

    def _actualizar_scroll(self, evento):
        """Recalcula el área de scroll cuando cambia el tamaño del marco de tarjetas."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _cargar_generos(self):
        """Descarga la lista de géneros de TMDB (películas y series) en segundo plano."""
        try:
            generos_pelicula = self.motor.obtener_generos("movie")
            generos_serie    = self.motor.obtener_generos("tv")
            self._generos_pelicula = {g["name"]: g["id"] for g in generos_pelicula}
            self._generos_serie    = {g["name"]: g["id"] for g in generos_serie}
        except Exception:
            # Si falla la conexión, usamos una lista de respaldo con los géneros más comunes
            self._generos_pelicula = {
                "Acción": 28, "Aventura": 12, "Animación": 16, "Comedia": 35,
                "Crimen": 80, "Documental": 99, "Drama": 18, "Familia": 10751,
                "Fantasía": 14, "Terror": 27, "Misterio": 9648, "Romance": 10749,
                "Ciencia ficción": 878, "Suspense": 53, "Bélica": 10752, "Western": 37,
            }
            self._generos_serie = {
                "Acción y Aventura": 10759, "Animación": 16, "Comedia": 35,
                "Crimen": 80, "Documental": 99, "Drama": 18, "Familia": 10751,
                "Misterio": 9648, "Ciencia ficción y Fantasía": 10765, "Western": 37,
            }
        self.ventana.after(0, self._actualizar_generos)

    def _actualizar_generos(self):
        """Rellena el combobox de géneros según el tipo (Película/Serie) seleccionado."""
        diccionario = (self._generos_pelicula if self.var_tipo.get() == "Película"
                       else self._generos_serie)
        nombres = sorted(diccionario.keys())
        self.combo_genero["values"] = nombres
        if nombres:
            self.var_genero.set(nombres[0])

    def _explorar_chip(self, nombre_genero):
        """Acceso rápido: explora directamente un género popular (chip de un clic)."""
        if not self._generos_pelicula:
            messagebox.showwarning(
                "Espera un momento",
                "Los géneros todavía se están cargando, inténtalo de nuevo en unos segundos."
            )
            return
        self.var_tipo.set("Película")
        self._actualizar_generos()
        if nombre_genero in self._generos_pelicula:
            self.var_genero.set(nombre_genero)
        self.var_puntuacion.set("6+ ⭐")
        self._explorar_por_genero()

    def _sorprendeme(self):
        """Elige un tipo, género y puntuación al azar para descubrir algo nuevo de un clic."""
        if not self._generos_pelicula or not self._generos_serie:
            messagebox.showwarning(
                "Espera un momento",
                "Los géneros todavía se están cargando, inténtalo de nuevo en unos segundos."
            )
            return
        tipo_aleatorio = random.choice(["Película", "Serie"])
        self.var_tipo.set(tipo_aleatorio)
        self._actualizar_generos()
        diccionario = self._generos_pelicula if tipo_aleatorio == "Película" else self._generos_serie
        self.var_genero.set(random.choice(list(diccionario.keys())))
        self.var_puntuacion.set(random.choice(["6+ ⭐", "7+ ⭐", "8+ ⭐"]))
        self._explorar_por_genero()

    def _explorar_por_genero(self):
        """Busca en TMDB títulos del género y puntuación mínima seleccionados."""
        genero_nombre   = self.var_genero.get()
        es_pelicula     = self.var_tipo.get() == "Película"
        tipo_media      = "movie" if es_pelicula else "tv"
        diccionario     = self._generos_pelicula if es_pelicula else self._generos_serie
        id_genero       = diccionario.get(genero_nombre)

        if not id_genero:
            messagebox.showwarning(
                "Espera un momento",
                "Los géneros todavía se están cargando, inténtalo de nuevo en unos segundos."
            )
            return

        puntuacion_minima = int(self.var_puntuacion.get().split("+")[0])

        self.texto_estado.set(
            f"Buscando {self.var_tipo.get().lower()}s de {genero_nombre} "
            f"con {puntuacion_minima}+ estrellas…"
        )
        self.ventana.update()

        try:
            resultados = self.motor.explorar_por_genero(tipo_media, id_genero, puntuacion_minima)

            # Quitar selección de la lista de búsqueda, ya no aplica a este resultado
            self.lista_resultados.selection_clear(0, tk.END)

            for widget in self.marco_tarjetas.winfo_children():
                widget.destroy()
            self._tarjetas.clear()

            if not resultados:
                tk.Label(
                    self.marco_tarjetas,
                    text="No se encontraron títulos con esos filtros.",
                    font=("Arial", 12), fg=COLOR_GRIS, bg=COLOR_FONDO
                ).pack(pady=40)
            else:
                for rec in resultados:
                    tarjeta = TarjetaPelicula(self.marco_tarjetas, rec, self.motor)
                    tarjeta.pack(side="left", padx=8, pady=8)
                    self._tarjetas.append(tarjeta)

            self.area_sinopsis.configure(state="normal")
            self.area_sinopsis.delete("1.0", tk.END)
            self.area_sinopsis.insert(
                "1.0",
                f"{len(resultados)} resultados de {genero_nombre} ({self.var_tipo.get()}) "
                f"con puntuación mínima de {puntuacion_minima} estrellas."
            )
            self.area_sinopsis.configure(state="disabled")

            self.texto_estado.set(
                f"{len(resultados)} resultados · {genero_nombre} · {puntuacion_minima}+ ⭐ · "
                "Pasa el cursor sobre un póster para ver la sinopsis · Clic para ver en cliver.mom"
            )

        except Exception as error:
            messagebox.showerror("Error", f"No se pudo completar la búsqueda:\n{error}")
            self.texto_estado.set("Error al explorar por género")

    def _buscar(self):
        """Realiza la búsqueda en TMDB y muestra los resultados en la lista."""
        consulta = self.campo_busqueda.get().strip()
        if not consulta:
            return

        self.texto_estado.set("Buscando…")
        self.ventana.update()

        try:
            self.resultados_busqueda = self.motor.buscar(consulta)
            self.lista_resultados.delete(0, tk.END)

            for resultado in self.resultados_busqueda:
                icono = "🎬" if resultado.get("media_type") == "movie" else "📺"
                titulo = resultado.get("title") or resultado.get("name", "")
                anio = (resultado.get("release_date") or
                        resultado.get("first_air_date") or "")[:4]
                self.lista_resultados.insert(tk.END, f"{icono} {titulo} ({anio})")

            self.texto_estado.set(
                f"{len(self.resultados_busqueda)} resultados encontrados · "
                "Selecciona uno para ver recomendaciones"
            )
        except Exception as error:
            messagebox.showerror("Error de conexión",
                                 f"No se pudo conectar a TMDB:\n{error}")
            self.texto_estado.set("Error al conectar con TMDB")

    def _al_seleccionar(self, evento):
        """Carga las recomendaciones cuando el usuario selecciona un resultado."""
        seleccion = self.lista_resultados.curselection()
        if not seleccion:
            return

        elemento = self.resultados_busqueda[seleccion[0]]
        id_media   = elemento["id"]
        tipo_media = elemento.get("media_type", "movie")

        self.texto_estado.set("Cargando recomendaciones…")
        self.ventana.update()

        try:
            detalles = self.motor.obtener_detalles(id_media, tipo_media)
            recomendaciones = self.motor.obtener_recomendaciones(id_media, tipo_media)

            # Eliminar tarjetas anteriores
            for widget in self.marco_tarjetas.winfo_children():
                widget.destroy()
            self._tarjetas.clear()

            if not recomendaciones:
                tk.Label(
                    self.marco_tarjetas,
                    text="No hay recomendaciones disponibles para esta selección.",
                    font=("Arial", 12), fg=COLOR_GRIS, bg=COLOR_FONDO
                ).pack(pady=40)
            else:
                # Crear una tarjeta por cada recomendación
                for rec in recomendaciones:
                    tarjeta = TarjetaPelicula(self.marco_tarjetas, rec, self.motor)
                    tarjeta.pack(side="left", padx=8, pady=8)
                    self._tarjetas.append(tarjeta)

            # Actualizar el área de sinopsis con los detalles de la selección
            self.area_sinopsis.configure(state="normal")
            self.area_sinopsis.delete("1.0", tk.END)
            generos = ", ".join(detalles["generos"]) or "No disponible"
            texto_info = (
                f"{detalles['titulo']}  ·  "
                f"Géneros: {generos}  ·  "
                f"⭐ {detalles['puntuacion']:.1f}\n"
                f"{detalles['sinopsis']}"
            )
            self.area_sinopsis.insert("1.0", texto_info)
            self.area_sinopsis.configure(state="disabled")

            self.texto_estado.set(
                f"{len(recomendaciones)} recomendaciones para '{detalles['titulo']}'  ·  "
                "Pasa el cursor sobre un póster para ver la sinopsis · Clic para ver en cliver.mom"
            )

        except Exception as error:
            messagebox.showerror("Error",
                                 f"No se pudieron cargar las recomendaciones:\n{error}")


# ──────────────────────────────────────────────
#  PUNTO DE ENTRADA
# ──────────────────────────────────────────────
if __name__ == "__main__":
    ventana_principal = tk.Tk()
    Aplicacion(ventana_principal)
    ventana_principal.mainloop()
