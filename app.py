"""Panel web de consulta para el proyecto de detección vial.

Esta aplicación es de solo lectura. Las credenciales de Supabase se leen
desde los secretos del servidor y nunca se envían al navegador.
"""

from datetime import datetime, timezone
from html import escape
from urllib.parse import quote

import folium
import requests
import streamlit as st
from streamlit_folium import st_folium


st.set_page_config(
    page_title="Dashboard de detección vial",
    page_icon="🚦",
    layout="wide",
)

BUCKET_EVIDENCIAS = "evidencias"
CENTRO_IQUIQUE = (-20.21414, -70.15245)
TIMEOUT = 15


def configuracion():
    try:
        url = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
        clave = str(st.secrets.get("SUPABASE_SECRET_KEY", "")).strip()
    except Exception:
        return "", ""
    if url.endswith("/rest/v1"):
        url = url[:-8]
    return url, clave


def encabezados(json_body=False):
    _, clave = configuracion()
    resultado = {"apikey": clave, "Authorization": f"Bearer {clave}"}
    if json_body:
        resultado["Content-Type"] = "application/json"
    return resultado


def comprobar_respuesta(respuesta):
    if not respuesta.ok:
        # No incluir encabezados ni credenciales en el mensaje que ve el visitante.
        raise RuntimeError(f"Supabase respondió HTTP {respuesta.status_code}.")


@st.cache_data(ttl=15, show_spinner=False)
def leer_detecciones():
    url, _ = configuracion()
    campos = (
        "id,creado_en,nombre_archivo,total,objetos,latitud,longitud,"
        "estado,reparado_en,evidencia_original,evidencia_anotada"
    )
    respuesta = requests.get(
        f"{url}/rest/v1/detecciones",
        params={"select": campos, "order": "creado_en.desc", "limit": "1000"},
        headers=encabezados(),
        timeout=TIMEOUT,
    )
    comprobar_respuesta(respuesta)
    return respuesta.json()


@st.cache_data(ttl=15, show_spinner=False)
def leer_gps_actual():
    url, _ = configuracion()
    respuesta = requests.get(
        f"{url}/rest/v1/gps_actual",
        params={
            "select": "latitud,longitud,actualizado_en",
            "unica": "eq.true",
            "limit": "1",
        },
        headers=encabezados(),
        timeout=TIMEOUT,
    )
    comprobar_respuesta(respuesta)
    filas = respuesta.json()
    return filas[0] if filas else None


@st.cache_data(ttl=300, show_spinner=False)
def url_firmada_evidencia(ruta):
    if not ruta:
        return None
    if str(ruta).startswith("https://"):
        return ruta
    url, _ = configuracion()
    ruta_limpia = str(ruta).lstrip("/")
    endpoint = (
        f"{url}/storage/v1/object/sign/{BUCKET_EVIDENCIAS}/"
        f"{quote(ruta_limpia, safe='/')}"
    )
    respuesta = requests.post(
        endpoint,
        headers=encabezados(json_body=True),
        json={"expiresIn": 3600},
        timeout=TIMEOUT,
    )
    comprobar_respuesta(respuesta)
    firmada = respuesta.json().get("signedURL")
    if not firmada:
        return None
    if firmada.startswith("http://") or firmada.startswith("https://"):
        return firmada
    # Storage devuelve una ruta relativa al prefijo /storage/v1.
    return f"{url}/storage/v1/{firmada.lstrip('/')}"


def cantidad_baches(registro):
    objetos = registro.get("objetos") or {}
    try:
        return int(objetos.get("pothole", 0))
    except (TypeError, ValueError):
        return 0


def fecha_legible(valor):
    if not valor:
        return "Sin fecha"
    try:
        fecha = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        return fecha.astimezone().strftime("%d-%m-%Y %H:%M")
    except (TypeError, ValueError):
        return str(valor)


def gps_reciente(gps):
    if not gps or gps.get("latitud") is None or gps.get("longitud") is None:
        return False
    actualizado = gps.get("actualizado_en")
    if not actualizado:
        return False
    try:
        momento = datetime.fromisoformat(str(actualizado).replace("Z", "+00:00"))
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - momento.astimezone(timezone.utc)).total_seconds() <= 120
    except (TypeError, ValueError):
        return False


def crear_mapa(registros, gps):
    coordenadas = [
        (float(r["latitud"]), float(r["longitud"]))
        for r in registros
        if r.get("latitud") is not None and r.get("longitud") is not None
    ]
    centro = coordenadas[0] if coordenadas else CENTRO_IQUIQUE
    zoom = 15 if coordenadas else 14
    mapa = folium.Map(location=centro, zoom_start=zoom, control_scale=True, tiles=None)
    folium.TileLayer("OpenStreetMap", name="Estándar", show=True).add_to(mapa)
    folium.TileLayer(
        tiles=(
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
            "MapServer/tile/{z}/{y}/{x}"
        ),
        attr=(
            "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, "
            "and the GIS User Community"
        ),
        name="Satélite",
        overlay=False,
        show=False,
        max_zoom=19,
    ).add_to(mapa)

    for registro in registros:
        lat = registro.get("latitud")
        lon = registro.get("longitud")
        if lat is None or lon is None:
            continue
        foto = ""
        try:
            evidencia = url_firmada_evidencia(registro.get("evidencia_anotada"))
        except (requests.RequestException, RuntimeError):
            evidencia = None
        if evidencia:
            foto = (
                '<br><img src="'
                + escape(evidencia, quote=True)
                + '" width="240" alt="Evidencia del bache">'
            )
        contenido = (
            "<b>Bache detectado</b><br>"
            f"Fecha: {escape(fecha_legible(registro.get('creado_en')))}<br>"
            f"Foto: {escape(str(registro.get('nombre_archivo') or 'Sin nombre'))}<br>"
            f"Baches en esta foto: {cantidad_baches(registro)}<br>"
            f"Estado: {escape(str(registro.get('estado') or 'Pendiente'))}"
            f"{foto}"
        )
        folium.Marker(
            location=[float(lat), float(lon)],
            tooltip="Bache detectado",
            popup=folium.Popup(contenido, max_width=300),
            icon=folium.Icon(color="red", icon="warning-sign"),
        ).add_to(mapa)

    if gps_reciente(gps):
        folium.CircleMarker(
            location=[float(gps["latitud"]), float(gps["longitud"])],
            radius=8,
            color="white",
            weight=2,
            fill=True,
            fill_color="#168bff",
            fill_opacity=1,
            tooltip="Ubicación actual del GPS",
        ).add_to(mapa)
    folium.LayerControl(position="topright", collapsed=False).add_to(mapa)
    return mapa


def mostrar_dashboard():
    url, clave = configuracion()
    if not url or not clave:
        st.error(
            "Falta configurar SUPABASE_URL y SUPABASE_SECRET_KEY "
            "en los secretos privados de esta aplicación web."
        )
        st.stop()

    st.title("🚦 Dashboard de detección vial")
    st.caption("Vista web de consulta · datos sincronizados desde el computador del vehículo")
    if st.button("Actualizar ahora", help="Vuelve a consultar los datos guardados en Supabase"):
        leer_detecciones.clear()
        leer_gps_actual.clear()
        url_firmada_evidencia.clear()
        st.rerun()

    try:
        registros = leer_detecciones()
        gps = leer_gps_actual()
    except requests.RequestException as error:
        st.error("No se pudo conectar con Supabase. Revisa la conexión a internet del servidor web.")
        st.caption(str(error))
        st.stop()
    except RuntimeError as error:
        st.error("Supabase no permitió leer los datos. Revisa las claves y permisos configurados.")
        st.caption(str(error))
        st.stop()

    baches = [r for r in registros if cantidad_baches(r) > 0]
    pendientes = [r for r in baches if (r.get("estado") or "Pendiente") == "Pendiente"]
    reparados = [r for r in baches if r.get("estado") == "Reparado"]
    col1, col2, col3 = st.columns(3)
    col1.metric("Registros pendientes", len(pendientes))
    col2.metric("Baches pendientes", sum(cantidad_baches(r) for r in pendientes))
    col3.metric("Registros reparados", len(reparados))

    st.subheader("Mapa de baches")
    filtro = st.radio(
        "Mostrar en el mapa",
        ["Pendientes", "Reparados", "Todos"],
        horizontal=True,
        label_visibility="collapsed",
    )
    if filtro == "Pendientes":
        visibles = pendientes
    elif filtro == "Reparados":
        visibles = reparados
    else:
        visibles = baches

    mapa = crear_mapa(visibles, gps)
    st_folium(mapa, height=560, width=None, key="mapa_dashboard_web")
    if gps_reciente(gps):
        st.success("GPS conectado · posición reciente del vehículo")
    else:
        st.info("Esperando una posición GPS reciente del vehículo.")

    st.subheader("Evidencias")
    if not visibles:
        st.info(f"No hay registros de baches para mostrar: {filtro.lower()}.")
    else:
        opciones = {r["id"]: r for r in visibles}
        seleccionado = st.selectbox(
            "Selecciona un registro para ver sus fotos",
            list(opciones),
            format_func=lambda item: (
                f"{fecha_legible(opciones[item].get('creado_en'))} · "
                f"{opciones[item].get('nombre_archivo') or 'Foto'} · "
                f"{cantidad_baches(opciones[item])} bache(s)"
            ),
        )
        registro = opciones[seleccionado]
        izquierda, derecha = st.columns(2)
        for contenedor, campo, titulo in (
            (izquierda, "evidencia_original", "Foto original"),
            (derecha, "evidencia_anotada", "Foto con detecciones"),
        ):
            with contenedor:
                st.markdown(f"**{titulo}**")
                try:
                    foto = url_firmada_evidencia(registro.get(campo))
                except (requests.RequestException, RuntimeError):
                    foto = None
                if foto:
                    st.image(foto, caption=registro.get("nombre_archivo"), width="stretch")
                else:
                    st.caption("Esta evidencia no está disponible.")
        if registro.get("latitud") is not None and registro.get("longitud") is not None:
            st.caption(
                f"Ubicación: {float(registro['latitud']):.6f}, "
                f"{float(registro['longitud']):.6f}"
            )
        else:
            st.caption("Este registro no tiene coordenadas GPS.")

    st.subheader("Historial de baches")
    if baches:
        tabla = []
        for r in baches[:50]:
            tabla.append(
                {
                    "Fecha": fecha_legible(r.get("creado_en")),
                    "Imagen": r.get("nombre_archivo") or "Sin nombre",
                    "Baches": cantidad_baches(r),
                    "Estado": r.get("estado") or "Pendiente",
                    "Ubicación GPS": (
                        f"{float(r['latitud']):.6f}, {float(r['longitud']):.6f}"
                        if r.get("latitud") is not None and r.get("longitud") is not None
                        else "Sin GPS"
                    ),
                }
            )
        st.dataframe(tabla, hide_index=True, width="stretch")
    else:
        st.caption("Todavía no hay baches registrados en Supabase.")

    st.caption("Esta página permite visualizar la información; no permite modificar ni borrar registros.")


@st.fragment(run_every="15s")
def panel_actualizable():
    mostrar_dashboard()


panel_actualizable()
