"""Orquestador PQRS con persistencia local y lógica mínima de BPMS (CMP-02).

Implementa el flujo TO-BE: radicar -> duplicados -> IA -> umbral 0,70 ->
asignación por menor carga -> respuesta -> cierre, más alertas 70/90/100 % y
consulta de estado. Es un PROTOTIPO académico: guarda todo en memoria.

Ejecutar:   uvicorn main:app --reload      (desde esta carpeta)
Documentación interactiva:  http://127.0.0.1:8000/docs
"""
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import joblib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

RUTA_MODELO = Path(__file__).resolve().parent.parent / "clasificador" / "modelo_pqrs.joblib"
RUTA_DATOS = Path(
    os.getenv("PQRS_DATA_DIR", str(Path(__file__).resolve().parent))
) / "pqrs.db"

# --- Parámetros (RF-26: configurables sin tocar el código de negocio) ---
PARAMS = {
    "umbral_confianza": 0.70,        # S-11
    "plazo_dias_habiles": 15,        # S-05
    "alerta_1": 0.70, "alerta_2": 0.90,   # S-06
    "ventana_duplicados_dias": 30,   # S-16
    "umbral_similitud": 0.60,        # criterio de "texto muy similar" (a calibrar)
}
DEPENDENCIAS = {                     # S-13: 2 funcionarios por dependencia
    "Obras e Infraestructura": ["Func. Obras 1", "Func. Obras 2"],
    "Movilidad y Tránsito": ["Func. Movilidad 1", "Func. Movilidad 2"],
    "Servicios Públicos y Ambiente": ["Func. Servicios 1", "Func. Servicios 2"],
    "Salud y Bienestar Social": ["Func. Salud 1", "Func. Salud 2"],
    "Hacienda e Impuestos": ["Func. Hacienda 1", "Func. Hacienda 2"],
    "Educación y Cultura": ["Func. Educación 1", "Func. Educación 2"],
    "Secretaría General": ["Func. Secretaría 1", "Func. Secretaría 2"],
}

app = FastAPI(title="Orquestador PQRS - Alcaldía de Villa Serena (ficticia)")
_modelo = joblib.load(RUTA_MODELO) if RUTA_MODELO.exists() else None


def _conexion():
    conexion = sqlite3.connect(RUTA_DATOS)
    conexion.row_factory = sqlite3.Row
    conexion.execute(
        "CREATE TABLE IF NOT EXISTS casos (radicado TEXT PRIMARY KEY, datos TEXT NOT NULL)"
    )
    conexion.commit()
    return conexion


def _cargar_casos() -> dict[str, dict]:
    with _conexion() as conexion:
        return {
            fila["radicado"]: json.loads(fila["datos"])
            for fila in conexion.execute("SELECT radicado, datos FROM casos")
        }


CASOS: dict[str, dict] = _cargar_casos()


def guardar(caso):
    with _conexion() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO casos (radicado, datos) VALUES (?, ?)",
            (caso["radicado"], json.dumps(caso, ensure_ascii=False)),
        )
        conexion.commit()


def siguiente_radicado(ahora: datetime) -> str:
    prefijo = f"PQRS-{ahora.year}-"
    consecutivos = [
        int(radicado.rsplit("-", 1)[1])
        for radicado in CASOS
        if radicado.startswith(prefijo) and radicado.rsplit("-", 1)[1].isdigit()
    ]
    return f"{prefijo}{max(consecutivos, default=0) + 1:06d}"


# ---------------------------------------------------------------- utilidades
def sumar_dias_habiles(inicio: date, n: int) -> date:
    d = inicio
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:           # lunes a viernes (no incluye festivos)
            n -= 1
    return d


def dias_habiles_entre(a: date, b: date) -> int:
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def registrar(caso, estado, quien, detalle=""):
    """RF-25: todo cambio de estado queda en el historial."""
    caso["estado"] = estado
    caso["historial"].append({"fecha": datetime.now().isoformat(timespec="seconds"),
                              "estado": estado, "responsable": quien, "detalle": detalle})
    guardar(caso)


def clasificar(texto: str):
    """CMP-03: servicio de IA. Devuelve (tema, dependencia, confianza) o None si falla (RN-05)."""
    if _modelo is None:
        return None
    m = _modelo["modelo"]
    proba = m.predict_proba([texto])[0]
    i = int(proba.argmax())
    tema = m.classes_[i]
    return tema, _modelo["temas"][tema], round(float(proba[i]), 3)


def posible_duplicado(ciudadano: str, texto: str, ahora: datetime, excluir: str = ""):
    """RF-06: mismo ciudadano, texto muy similar, ventana de 30 días."""
    previos = [c for c in CASOS.values()
               if c["ciudadano"] == ciudadano and c["radicado"] != excluir
               and (ahora - datetime.fromisoformat(c["radicado_en"])).days <= PARAMS["ventana_duplicados_dias"]
               and c["estado"] != "VINCULADA"]
    if not previos:
        return None
    textos = [c["texto"] for c in previos] + [texto]
    tfidf = TfidfVectorizer().fit_transform(textos)
    sims = cosine_similarity(tfidf[-1], tfidf[:-1])[0]
    j = int(sims.argmax())
    return (previos[j]["radicado"], float(sims[j])) if sims[j] >= PARAMS["umbral_similitud"] else None


def asignar(caso, dependencia: str, quien: str):
    """RN-06: funcionario de la dependencia con menos casos abiertos."""
    carga = {f: 0 for f in DEPENDENCIAS[dependencia]}
    for c in CASOS.values():
        if c.get("funcionario") in carga and c["estado"] in ("ASIGNADA", "EN_ATENCION"):
            carga[c["funcionario"]] += 1
    func = min(carga, key=carga.get)
    caso.update(dependencia=dependencia, funcionario=func)
    registrar(caso, "ASIGNADA", quien, f"{dependencia} -> {func}")


# ------------------------------------------------------------------- modelos
class PQRSIn(BaseModel):
    ciudadano: str = Field(..., examples=["Ana Pérez"])
    contacto: str = Field(..., examples=["ana@correo.com"])
    tipo: str = Field(..., examples=["queja"])
    descripcion: str = Field(..., min_length=5)
    canal: str = Field("web", pattern="^(web|correo|presencial)$")


class RevisionIn(BaseModel):
    dependencia: str
    radicador: str = "Radicador 1"


class DuplicadoIn(BaseModel):
    es_duplicado: bool
    radicador: str = "Radicador 1"


class RespuestaIn(BaseModel):
    texto: str = Field(..., min_length=1)


class ReasignarIn(BaseModel):
    funcionario: str
    motivo: str = Field(..., min_length=3)


# ----------------------------------------------------------------- endpoints
@app.post("/pqrs", status_code=201)
def radicar(p: PQRSIn):
    """T-01/T-03/T-04/T-05/T-08/T-10: radicación + duplicados + IA + asignación."""
    ahora = datetime.now()
    rad = siguiente_radicado(ahora)
    caso = {"radicado": rad, "ciudadano": p.ciudadano, "contacto": p.contacto, "tipo": p.tipo,
            "texto": p.descripcion, "canal": p.canal, "radicado_en": ahora.isoformat(timespec="seconds"),
            "fecha_limite": sumar_dias_habiles(ahora.date(), PARAMS["plazo_dias_habiles"]).isoformat(),
            "estado": "", "historial": [], "dependencia": None, "funcionario": None,
            "clasificacion": None, "alertas": []}
    CASOS[rad] = caso
    registrar(caso, "RADICADA", "BPMS", f"canal={p.canal}; notificación de radicado a {p.contacto}")

    # T-05 duplicados
    registrar(caso, "EN_VERIFICACION", "Orquestador")
    dup = posible_duplicado(p.ciudadano, p.descripcion, ahora, excluir=rad)
    if dup:
        caso["posible_duplicado_de"] = dup[0]
        registrar(caso, "POSIBLE_DUPLICADO", "Orquestador", f"similitud {dup[1]:.2f} con {dup[0]}")
        return resumen(caso)

    return clasificar_y_asignar(caso)


def clasificar_y_asignar(caso):
    registrar(caso, "EN_CLASIFICACION", "Orquestador")
    res = clasificar(caso["texto"])
    if res is None:                                   # RN-05: la IA no responde
        caso["clasificacion"] = {"revisada_por_persona": False, "error": "IA no disponible"}
        registrar(caso, "EN_REVISION_HUMANA", "Orquestador", "IA no disponible")
        return resumen(caso)
    tema, dep, conf = res
    caso["clasificacion"] = {"tema": tema, "dependencia_sugerida": dep, "confianza": conf,
                             "revisada_por_persona": False}
    if conf >= PARAMS["umbral_confianza"]:           # RN-04
        asignar(caso, dep, "BPMS (automática)")
    else:
        registrar(caso, "EN_REVISION_HUMANA", "Orquestador", f"confianza {conf} < umbral")
    return resumen(caso)


@app.post("/pqrs/{radicado}/duplicado")
def decidir_duplicado(radicado: str, d: DuplicadoIn):
    """T-06/T-07: el radicador confirma o descarta el posible duplicado."""
    c = obtener(radicado)
    if c["estado"] != "POSIBLE_DUPLICADO":
        raise HTTPException(409, "El caso no está en POSIBLE_DUPLICADO")
    if d.es_duplicado:
        registrar(c, "VINCULADA", d.radicador, f"vinculado a {c['posible_duplicado_de']}; ciudadano notificado")
        return resumen(c)
    registrar(c, "EN_VERIFICACION", d.radicador, "duplicado descartado")
    return clasificar_y_asignar(c)


@app.post("/pqrs/{radicado}/revision")
def revision_humana(radicado: str, r: RevisionIn):
    """T-09: el radicador confirma o corrige la dependencia."""
    c = obtener(radicado)
    if c["estado"] != "EN_REVISION_HUMANA":
        raise HTTPException(409, "El caso no está en EN_REVISION_HUMANA")
    if r.dependencia not in DEPENDENCIAS:
        raise HTTPException(422, f"Dependencia desconocida. Opciones: {list(DEPENDENCIAS)}")
    c["clasificacion"]["revisada_por_persona"] = True
    c["clasificacion"]["dependencia_final"] = r.dependencia
    asignar(c, r.dependencia, r.radicador)
    return resumen(c)


@app.post("/pqrs/{radicado}/respuesta")
def responder(radicado: str, r: RespuestaIn):
    """T-11/T-12: el funcionario responde y el BPMS cierra el caso."""
    c = obtener(radicado)
    if c["estado"] not in ("ASIGNADA", "EN_ATENCION"):
        raise HTTPException(409, "El caso no está asignado")
    c["respuesta"] = {"texto": r.texto, "fecha": datetime.now().isoformat(timespec="seconds")}
    registrar(c, "CERRADA", c["funcionario"],
              "respondida fuera de plazo (vencida)" if c.get("vencida") else "respondida a tiempo")
    return resumen(c)


@app.post("/pqrs/{radicado}/reasignar")
def reasignar(radicado: str, r: ReasignarIn):
    """T-15 / RN-08: el jefe reasigna y el motivo queda registrado."""
    c = obtener(radicado)
    c["funcionario"] = r.funcionario
    registrar(c, c["estado"], "Jefe de dependencia", f"reasignado a {r.funcionario}: {r.motivo}")
    return resumen(c)


@app.post("/alertas/revisar")
def revisar_alertas(hoy: date | None = None):
    """T-13/T-14/T-16: en producción lo hace el temporizador del BPMS (aquí, un endpoint
    que n8n o un cron llama cada hora). Parámetro `hoy` para simular fechas en pruebas."""
    hoy = hoy or date.today()
    emitidas = []
    for c in CASOS.values():
        if c["estado"] not in ("ASIGNADA", "EN_ATENCION"):
            continue
        total = PARAMS["plazo_dias_habiles"]
        usado = dias_habiles_entre(datetime.fromisoformat(c["radicado_en"]).date(), hoy) / total
        for nombre, umbral, destino in (("70%", PARAMS["alerta_1"], "funcionario"),
                                        ("90%", PARAMS["alerta_2"], "jefe de dependencia"),
                                        ("100%", 1.0, "jefe de dependencia (VENCIDO)")):
            if usado >= umbral and nombre not in c["alertas"]:
                c["alertas"].append(nombre)
                if nombre == "100%":
                    c["vencida"] = True
                registrar(c, c["estado"], "BPMS (temporizador)", f"alerta {nombre} -> {destino}")
                emitidas.append({"radicado": c["radicado"], "alerta": nombre, "para": destino})
    return {"fecha": hoy.isoformat(), "alertas_emitidas": emitidas}


@app.get("/pqrs/{radicado}")
def consultar(radicado: str):
    """T-17/T-18 (RN-10): el ciudadano solo ve estado e historial público."""
    c = obtener(radicado)
    return {"radicado": c["radicado"], "estado": c["estado"], "fecha_limite": c["fecha_limite"],
            "historial": [{"fecha": h["fecha"], "estado": h["estado"]} for h in c["historial"]],
            "respuesta": c.get("respuesta"), "tipo": c["tipo"]}


@app.get("/jefe/{dependencia}/casos")
def casos_dependencia(dependencia: str):
    """Vista interna: casos asignados a una dependencia para su atención."""
    if dependencia not in DEPENDENCIAS:
        raise HTTPException(404, "Dependencia no encontrada")
    casos = [
        {
            "radicado": c["radicado"],
            "ciudadano": c["ciudadano"],
            "contacto": c["contacto"],
            "tipo": c["tipo"],
            "descripcion": c["texto"],
            "estado": c["estado"],
            "fecha_limite": c["fecha_limite"],
            "funcionario": c.get("funcionario"),
            "alertas": c.get("alertas", []),
            "respuesta": c.get("respuesta"),
        }
        for c in CASOS.values()
        if c.get("dependencia") == dependencia
    ]
    return {"dependencia": dependencia, "casos": sorted(casos, key=lambda c: c["fecha_limite"])}


@app.get("/jefe/{dependencia}/panel")
def panel_jefe(dependencia: str):
    """T-15 / RF-22: carga por funcionario y casos por vencer."""
    if dependencia not in DEPENDENCIAS:
        raise HTTPException(404, "Dependencia no encontrada")
    abiertos = [c for c in CASOS.values() if c.get("dependencia") == dependencia
                and c["estado"] in ("ASIGNADA", "EN_ATENCION")]
    return {"dependencia": dependencia,
            "carga": {f: sum(1 for c in abiertos if c["funcionario"] == f) for f in DEPENDENCIAS[dependencia]},
            "por_vencer": [c["radicado"] for c in abiertos if {"70%", "90%"} & set(c["alertas"])]}


@app.get("/bandeja")
def bandeja_revision():
    """Casos que necesitan decisión humana: baja confianza o posible duplicado."""
    pendientes = []
    for c in CASOS.values():
        if c["estado"] not in ("EN_REVISION_HUMANA", "POSIBLE_DUPLICADO"):
            continue
        clas = c.get("clasificacion") or {}
        pendientes.append({
            "radicado": c["radicado"], "ciudadano": c["ciudadano"], "tipo": c["tipo"],
            "descripcion": c["texto"], "estado": c["estado"], "radicado_en": c["radicado_en"],
            "dependencia_sugerida": clas.get("dependencia_sugerida"),
            "confianza": clas.get("confianza"),
            "posible_duplicado_de": c.get("posible_duplicado_de"),
        })
    return {"casos": sorted(pendientes, key=lambda c: c["radicado_en"])}


@app.get("/parametros")
def ver_parametros():
    return PARAMS


@app.put("/parametros")
def cambiar_parametros(nuevos: dict):
    """RF-26: cambiar plazo, umbral, etc. sin redeploy."""
    for k, v in nuevos.items():
        if k not in PARAMS:
            raise HTTPException(422, f"Parámetro desconocido: {k}")
        PARAMS[k] = v
    return PARAMS


def obtener(radicado):
    if radicado not in CASOS:
        raise HTTPException(404, "No se encontró el caso")
    return CASOS[radicado]


def resumen(c):
    return {k: c[k] for k in ("radicado", "estado", "fecha_limite", "dependencia", "funcionario", "clasificacion")
            } | {"posible_duplicado_de": c.get("posible_duplicado_de")}
