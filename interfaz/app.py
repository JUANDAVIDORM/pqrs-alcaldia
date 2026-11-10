"""Interfaz web para ciudadanos y funcionarios de la Alcaldía de Villa Serena."""
import os
import subprocess
import sys
import time
from typing import Any

import requests
import streamlit as st

API = os.getenv("PQRS_API", "http://127.0.0.1:8000").rstrip("/")

ESTADOS = {
    "RADICADA": ("Recibida", "Su solicitud fue recibida correctamente."),
    "EN_VERIFICACION": ("En verificación", "Estamos revisando la información de la solicitud."),
    "EN_CLASIFICACION": ("Clasificando", "Estamos identificando el área responsable."),
    "EN_REVISION_HUMANA": ("Revisión por funcionario", "Un funcionario revisará y asignará su solicitud."),
    "POSIBLE_DUPLICADO": ("Pendiente de revisión", "Verificaremos si existe una solicitud similar."),
    "ASIGNADA": ("Asignada", "Su solicitud ya está en manos del área responsable."),
    "EN_ATENCION": ("En atención", "El área responsable está trabajando en su solicitud."),
    "RESPONDIDA": ("Respondida", "Ya existe una respuesta para su solicitud."),
    "CERRADA": ("Cerrada", "La gestión de su solicitud finalizó."),
    "VINCULADA": ("Vinculada", "La solicitud fue vinculada a un caso anterior."),
}


def api_request(method: str, path: str, **kwargs: Any) -> requests.Response:
    """Centraliza las llamadas para mostrar errores entendibles al usuario."""
    kwargs.setdefault("timeout", 10)
    return requests.request(method, f"{API}{path}", **kwargs)


@st.cache_resource
def iniciar_api() -> subprocess.Popen[bytes] | None:
    """Inicia la API como servicio interno; el usuario solo necesita una URL."""
    try:
        requests.get(f"{API}/parametros", timeout=1)
        return None
    except requests.RequestException:
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        proceso = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=os.path.join(raiz, "backend"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(20):
            if proceso.poll() is not None:
                raise RuntimeError("La API interna no pudo iniciar.")
            try:
                requests.get(f"{API}/parametros", timeout=0.5)
                return proceso
            except requests.RequestException:
                time.sleep(0.25)
        raise RuntimeError("La API interna tardó demasiado en iniciar.")


def estado_legible(estado: str) -> str:
    return ESTADOS.get(estado, (estado.replace("_", " ").title(), ""))[0]


def mostrar_estado(estado: str) -> None:
    titulo, ayuda = ESTADOS.get(estado, (estado.replace("_", " ").title(), ""))
    st.metric("Estado actual", titulo)
    if ayuda:
        st.caption(ayuda)


def mostrar_resultado_radicacion(datos: dict[str, Any]) -> None:
    """Presenta la respuesta de la API sin exponer el JSON interno."""
    st.success("Solicitud radicada correctamente", icon=":material/check_circle:")
    principal, fecha, area = st.columns(3)
    principal.metric("Número de radicado", datos["radicado"])
    fecha.metric("Fecha límite", datos["fecha_limite"])
    area.metric("Estado", estado_legible(datos["estado"]))

    with st.container(border=True):
        st.subheader("¿Qué sigue?")
        if datos.get("dependencia"):
            st.write(
                f"El caso fue asignado a **{datos['dependencia']}** "
                f"({datos['funcionario']})."
            )
        elif datos.get("posible_duplicado_de"):
            st.warning(
                f"Encontramos una solicitud posiblemente relacionada ({datos['posible_duplicado_de']}). "
                "Un funcionario la revisará antes de continuar."
            )
        else:
            st.info(
                "La solicitud quedó pendiente de revisión por un funcionario. "
                "Conserve su número de radicado para consultar avances."
            )

    if datos.get("clasificacion"):
        clasificacion = datos["clasificacion"]
        with st.expander("Ver información de clasificación", expanded=False):
            st.write(f"**Tema identificado:** {clasificacion.get('tema', 'Pendiente')}")
            st.write(
                f"**Nivel de confianza:** "
                f"{clasificacion.get('confianza', 'Pendiente')}"
            )


def mostrar_historial(datos: dict[str, Any]) -> None:
    historial = datos.get("historial", [])
    if not historial:
        st.info("Todavía no hay movimientos registrados.")
        return
    for movimiento in reversed(historial):
        fecha = movimiento["fecha"].replace("T", " ")
        st.markdown(
            f"**{estado_legible(movimiento['estado'])}**  \n"
            f"<small>{fecha}</small>",
            unsafe_allow_html=True,
        )
        st.divider()


st.set_page_config(
    page_title="PQRS | Alcaldía de Villa Serena",
    page_icon=":material/account_balance:",
    layout="wide",
)

iniciar_api()

with st.sidebar:
    st.title("Alcaldía de Villa Serena")
    st.caption("Sistema de peticiones, quejas, reclamos y sugerencias")
    st.divider()
    st.success("Sistema conectado", icon=":material/cloud_done:")
    with st.expander("Información del sistema"):
        st.caption("Los casos se conservan en una base local y no se borran al reiniciar.")
        st.caption("La documentación técnica está disponible para administradores.")

st.title("Gestión de PQRS")
st.write("Radique una solicitud o consulte el avance de un caso existente.")

tab_radicar, tab_consultar, tab_gestion = st.tabs(
    ["Radicar solicitud", "Consultar radicado", "Panel de gestión"]
)

with tab_radicar:
    st.subheader("Cuéntenos cómo podemos ayudarle")
    st.caption("Los campos marcados son necesarios. La respuesta se gestiona en días hábiles.")
    with st.form("form_pqrs", clear_on_submit=True):
        ciudadano = st.text_input("Nombre completo", placeholder="Ej. María López")
        contacto = st.text_input(
            "Correo o teléfono de contacto",
            placeholder="Ej. maria@correo.com",
        )
        tipo = st.selectbox(
            "Tipo de solicitud",
            ["petición", "queja", "reclamo", "sugerencia"],
            format_func=str.capitalize,
        )
        canal = st.selectbox(
            "¿Cómo desea registrar la solicitud?",
            ["web", "correo", "presencial"],
            format_func=str.capitalize,
        )
        descripcion = st.text_area(
            "Descripción de la solicitud",
            placeholder="Describa de forma clara qué ocurrió o qué necesita...",
            height=170,
        )
        enviar = st.form_submit_button(
            "Radicar solicitud",
            type="primary",
            icon=":material/send:",
            width="stretch",
        )

    if enviar:
        if not ciudadano.strip() or not contacto.strip() or len(descripcion.strip()) < 5:
            st.error(
                "Complete su nombre, un medio de contacto y una descripción de al menos 5 caracteres.",
                icon=":material/error:",
            )
        else:
            try:
                respuesta = api_request(
                    "POST",
                    "/pqrs",
                    json={
                        "ciudadano": ciudadano.strip(),
                        "contacto": contacto.strip(),
                        "tipo": tipo,
                        "descripcion": descripcion.strip(),
                        "canal": canal,
                    },
                )
                respuesta.raise_for_status()
                mostrar_resultado_radicacion(respuesta.json())
            except requests.RequestException:
                st.error(
                    "No fue posible conectar con el sistema. Verifique que la API esté encendida.",
                    icon=":material/cloud_off:",
                )

with tab_consultar:
    st.subheader("Consulte el estado de su solicitud")
    st.caption("Ingrese el número que recibió al radicar, por ejemplo: PQRS-2026-000001")
    with st.form("form_consulta"):
        radicado = st.text_input("Número de radicado", placeholder="PQRS-2026-000001")
        consultar = st.form_submit_button(
            "Consultar estado",
            type="primary",
            icon=":material/search:",
        )

    if consultar:
        if not radicado.strip():
            st.warning("Ingrese un número de radicado para continuar.")
        else:
            try:
                respuesta = api_request("GET", f"/pqrs/{radicado.strip()}")
                if respuesta.status_code == 404:
                    st.error("No encontramos un caso con ese número de radicado.")
                else:
                    respuesta.raise_for_status()
                    datos = respuesta.json()
                    st.success("Radicado encontrado", icon=":material/check_circle:")
                    mostrar_estado(datos["estado"])
                    st.write(f"**Número:** {datos['radicado']}")
                    st.write(f"**Fecha límite de respuesta:** {datos['fecha_limite']}")
                    if datos.get("respuesta"):
                        with st.container(border=True):
                            st.subheader("Respuesta")
                            st.write(datos["respuesta"])
                    with st.expander("Ver historial del caso", expanded=True):
                        mostrar_historial(datos)
            except requests.RequestException:
                st.error(
                    "No fue posible consultar el sistema. Intente nuevamente en unos minutos.",
                    icon=":material/cloud_off:",
                )

with tab_gestion:
    st.subheader("Panel para funcionarios")
    st.caption("Resumen operativo por dependencia y casos que requieren atención.")
    try:
        parametros = api_request("GET", "/parametros")
        parametros.raise_for_status()
        dependencias = list(
            {
                "Obras e Infraestructura",
                "Movilidad y Tránsito",
                "Servicios Públicos y Ambiente",
                "Salud y Bienestar Social",
                "Hacienda e Impuestos",
                "Educación y Cultura",
                "Secretaría General",
            }
        )
        dependencia = st.selectbox("Dependencia", sorted(dependencias))
        panel = api_request("GET", f"/jefe/{dependencia}/panel")
        panel.raise_for_status()
        datos_panel = panel.json()
        total = sum(datos_panel["carga"].values())
        metrica_total, metrica_alertas = st.columns(2)
        metrica_total.metric("Casos abiertos", total)
        metrica_alertas.metric("Casos por vencer", len(datos_panel["por_vencer"]))
        with st.container(border=True):
            st.subheader("Carga por funcionario")
            for funcionario, carga in datos_panel["carga"].items():
                st.write(f"**{funcionario}** — {carga} caso(s)")
        if datos_panel["por_vencer"]:
            st.warning(
                "Radicados que requieren atención: "
                + ", ".join(datos_panel["por_vencer"]),
                icon=":material/priority_high:",
            )
        else:
            st.success("No hay casos con alertas activas.", icon=":material/check_circle:")

        casos_response = api_request("GET", f"/jefe/{dependencia}/casos")
        casos_response.raise_for_status()
        casos = casos_response.json()["casos"]
        st.subheader("Casos de la dependencia")
        if not casos:
            st.info("Todavía no hay casos asignados a esta dependencia.")
        else:
            etiquetas = {
                caso["radicado"]: (
                    f"{caso['radicado']} · {caso['tipo'].capitalize()} · "
                    f"{estado_legible(caso['estado'])}"
                )
                for caso in casos
            }
            seleccionado = st.selectbox(
                "Seleccione un caso para atender",
                list(etiquetas),
                format_func=etiquetas.get,
            )
            caso = next(caso for caso in casos if caso["radicado"] == seleccionado)
            with st.container(border=True):
                izquierda, derecha = st.columns(2)
                izquierda.write(f"**Ciudadano:** {caso['ciudadano']}")
                izquierda.write(f"**Contacto:** {caso['contacto']}")
                izquierda.write(f"**Responsable:** {caso.get('funcionario') or 'Pendiente'}")
                derecha.write(f"**Estado:** {estado_legible(caso['estado'])}")
                derecha.write(f"**Fecha límite:** {caso['fecha_limite']}")
                if caso["alertas"]:
                    derecha.warning("Alertas: " + ", ".join(caso["alertas"]))
                st.write(f"**Descripción:** {caso['descripcion']}")
                with st.form(f"respuesta_{seleccionado}"):
                    respuesta = st.text_area(
                        "Respuesta al ciudadano",
                        value=(caso.get("respuesta") or {}).get("texto", ""),
                        placeholder="Escriba aquí la respuesta oficial...",
                    )
                    enviar_respuesta = st.form_submit_button(
                        "Guardar respuesta y cerrar caso",
                        type="primary",
                        icon=":material/check:",
                    )
                if enviar_respuesta:
                    if not respuesta.strip():
                        st.error("Escriba una respuesta antes de cerrar el caso.")
                    else:
                        guardar_respuesta = api_request(
                            "POST",
                            f"/pqrs/{seleccionado}/respuesta",
                            json={"texto": respuesta.strip()},
                        )
                        if guardar_respuesta.ok:
                            st.success("Respuesta guardada y caso cerrado.")
                            st.rerun()
                        else:
                            st.error(
                                guardar_respuesta.json().get(
                                    "detail", "No fue posible guardar la respuesta."
                                )
                            )
        st.divider()
        st.subheader("Bandeja de revisión")
        st.caption("Casos con baja confianza de la clasificación o posibles duplicados que requieren decisión humana.")
        pendientes = api_request("GET", "/bandeja")
        pendientes.raise_for_status()
        casos_pendientes = pendientes.json()["casos"]
        if not casos_pendientes:
            st.success("No hay casos pendientes de revisión.", icon=":material/check_circle:")
        else:
            etiquetas_pendientes = {
                c["radicado"]: f"{c['radicado']} · {'Posible duplicado' if c['estado'] == 'POSIBLE_DUPLICADO' else 'Clasificación dudosa'}"
                for c in casos_pendientes
            }
            elegido = st.selectbox(
                "Seleccione un caso pendiente",
                list(etiquetas_pendientes),
                format_func=etiquetas_pendientes.get,
                key="bandeja_caso",
            )
            pendiente = next(c for c in casos_pendientes if c["radicado"] == elegido)
            with st.container(border=True):
                st.write(f"**Descripción:** {pendiente['descripcion']}")
                if pendiente["estado"] == "POSIBLE_DUPLICADO":
                    st.warning(f"Este caso podría ser duplicado de {pendiente['posible_duplicado_de']}.")
                    col_si, col_no = st.columns(2)
                    if col_si.button("Confirmar duplicado", key=f"dup_si_{elegido}", type="primary"):
                        r = api_request("POST", f"/pqrs/{elegido}/duplicado", json={"es_duplicado": True, "radicador": "Funcionario"})
                        if r.ok:
                            st.rerun()
                        st.error(r.json().get("detail", "No fue posible registrar la decisión."))
                    if col_no.button("No es duplicado", key=f"dup_no_{elegido}"):
                        r = api_request("POST", f"/pqrs/{elegido}/duplicado", json={"es_duplicado": False, "radicador": "Funcionario"})
                        if r.ok:
                            st.rerun()
                        st.error(r.json().get("detail", "No fue posible registrar la decisión."))
                else:
                    sugerida = pendiente.get("dependencia_sugerida") or "Secretaría General"
                    st.write(
                        f"**Sugerencia del sistema:** {sugerida} "
                        f"(confianza {pendiente.get('confianza', 'N/D')}, por debajo del umbral de 0,70)."
                    )
                    opciones = sorted(dependencias)
                    asignada = st.selectbox(
                        "Dependencia responsable",
                        opciones,
                        index=opciones.index(sugerida) if sugerida in opciones else 0,
                        key=f"dep_{elegido}",
                    )
                    if st.button("Confirmar asignación", key=f"asig_{elegido}", type="primary"):
                        r = api_request("POST", f"/pqrs/{elegido}/revision", json={"dependencia": asignada, "radicador": "Funcionario"})
                        if r.ok:
                            st.rerun()
                        st.error(r.json().get("detail", "No fue posible asignar el caso."))

        st.divider()
        st.subheader("Alertas de vencimiento")
        st.caption("Revisa los plazos de los casos asignados y emite las alertas del 70 %, 90 % y 100 %.")
        if st.button("Revisar alertas ahora", icon=":material/notifications_active:"):
            r = api_request("POST", "/alertas/revisar")
            r.raise_for_status()
            emitidas = r.json()["alertas_emitidas"]
            if emitidas:
                st.warning(f"Se emitieron {len(emitidas)} alerta(s).")
                st.dataframe(emitidas, hide_index=True)
            else:
                st.success("No hay nuevas alertas.")
    except requests.RequestException:
        st.warning(
            "No fue posible cargar los casos de la dependencia. Intente actualizar la página.",
            icon=":material/cloud_off:",
        )
