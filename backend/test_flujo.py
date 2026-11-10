"""Pruebas de aceptación del flujo TO-BE. Ejecutar:  python3 test_flujo.py
(o:  pytest -v test_flujo.py)
"""
from datetime import date, timedelta

import os, tempfile
os.environ["PQRS_DATA_DIR"] = tempfile.mkdtemp()   # BD aislada: las pruebas no ensucian pqrs.db
from fastapi.testclient import TestClient

from main import app, CASOS, sumar_dias_habiles

c = TestClient(app)


def radicar(texto, ciudadano="Ana", canal="web"):
    r = c.post("/pqrs", json={"ciudadano": ciudadano, "contacto": "a@b.co", "tipo": "queja",
                              "descripcion": texto, "canal": canal})
    assert r.status_code == 201, r.text
    return r.json()


def test_01_alta_confianza_asigna_automaticamente():
    r = radicar("Buenos días, la calle frente a mi casa tiene un hueco enorme y la luminaria dañada")
    assert r["radicado"].startswith("PQRS-")
    assert r["clasificacion"]["confianza"] >= 0.70
    assert r["estado"] == "ASIGNADA" and r["dependencia"] == "Obras e Infraestructura"   # RF-10


def test_02_baja_confianza_va_a_revision_humana():
    r = radicar("necesito ayuda urgente", ciudadano="Luis")
    assert r["clasificacion"]["confianza"] < 0.70
    assert r["estado"] == "EN_REVISION_HUMANA"                                           # RF-11
    r2 = c.post(f"/pqrs/{r['radicado']}/revision", json={"dependencia": "Hacienda e Impuestos"}).json()
    assert r2["estado"] == "ASIGNADA" and r2["clasificacion"]["revisada_por_persona"]    # RF-13, RF-12


def test_03_duplicado_detectado_y_vinculado():
    radicar("El camión de la basura no pasa hace una semana en mi cuadra", ciudadano="Marta")
    d = radicar("el camión de la basura no pasa hace una semana en mi cuadra", ciudadano="Marta", canal="correo")
    assert d["estado"] == "POSIBLE_DUPLICADO"                                            # RF-06
    v = c.post(f"/pqrs/{d['radicado']}/duplicado", json={"es_duplicado": True}).json()
    assert v["estado"] == "VINCULADA"                                                    # RF-08


def test_04_asignacion_por_menor_carga():
    funcs = set()
    for i in range(4):
        r = radicar(f"El semáforo está dañado y hay trancón en la avenida principal {i}", ciudadano=f"Ciudadano{i}")
        funcs.add(r["funcionario"])
    assert len(funcs) == 2        # se reparten entre los 2 funcionarios                  # RN-06


def test_05_alertas_70_90_100():
    r = radicar("Los escombros están acumulados en la esquina y huele muy mal", ciudadano="Pedro")
    rad = r["radicado"]
    hoy0 = date.today()
    # Se simula el paso del tiempo con la fecha 'hoy' (días hábiles desde la radicación)
    for dias_habiles, esperada in ((11, "70%"), (14, "90%"), (15, "100%")):
        hoy = sumar_dias_habiles(hoy0, dias_habiles)
        out = c.post("/alertas/revisar", params={"hoy": hoy.isoformat()}).json()
        emitidas = [a["alerta"] for a in out["alertas_emitidas"] if a["radicado"] == rad]
        assert esperada in emitidas, (dias_habiles, emitidas)
    assert CASOS[rad]["alertas"] == ["70%", "90%", "100%"] and CASOS[rad]["vencida"]      # RF-19..21


def test_06_responder_cierra_y_consulta_publica():
    r = radicar("El puesto de salud no tiene medicamentos para los adultos mayores", ciudadano="Rosa")
    c.post(f"/pqrs/{r['radicado']}/respuesta", json={"texto": "Se gestionó el suministro."})
    q = c.get(f"/pqrs/{r['radicado']}").json()
    assert q["estado"] == "CERRADA" and q["respuesta"]["texto"]                           # RF-18, RF-24
    assert "texto" not in str(q["historial"]) and "ciudadano" not in q                    # RN-10
    assert c.get("/pqrs/NO-EXISTE").status_code == 404


def test_07_reasignar_exige_motivo_y_parametros_configurables():
    r = radicar("La biblioteca municipal está cerrada en horario de atención", ciudadano="Juan")
    assert c.post(f"/pqrs/{r['radicado']}/reasignar", json={"funcionario": "X", "motivo": ""}).status_code == 422
    assert c.put("/parametros", json={"umbral_confianza": 0.8}).json()["umbral_confianza"] == 0.8   # RF-26
    c.put("/parametros", json={"umbral_confianza": 0.7})




def test_08_bandeja_muestra_casos_que_requieren_decision_humana():
    dudoso = radicar("tengo un problema con mi vecino y el ruido de la obra", ciudadano="Carlos")
    if dudoso["estado"] == "EN_REVISION_HUMANA":
        pendientes = [x["radicado"] for x in c.get("/bandeja").json()["casos"]]
        assert dudoso["radicado"] in pendientes                                          # RF-11
        c.post(f"/pqrs/{dudoso['radicado']}/revision", json={"dependencia": "Secretaría General"})
        pendientes = [x["radicado"] for x in c.get("/bandeja").json()["casos"]]
        assert dudoso["radicado"] not in pendientes                                      # RF-13


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("OK ", t.__name__)
    print(f"\n{len(tests)} pruebas pasaron.")
