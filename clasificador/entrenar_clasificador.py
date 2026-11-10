#!/usr/bin/env python3
"""Clasificador de PQRS (Caso B) - TF-IDF + regresión logística.

Genera un conjunto SINTÉTICO de 2.400 textos (300 por tema), entrena, evalúa
con el umbral de confianza 0,70 y guarda el modelo (modelo_pqrs.joblib) y las
métricas (metricas.json). Corresponde al Anexo E del documento.

Uso:  python3 entrenar_clasificador.py
"""
import json
import random

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

SEMILLA = 42
UMBRAL = 0.70                       # S-11
N_POR_TEMA = 300                    # 8 temas x 300 = 2.400 textos

# S-15 y Anexo B: tema -> dependencia
TEMAS = {
    "vias_y_alumbrado": "Obras e Infraestructura",
    "transito": "Movilidad y Tránsito",
    "aseo_y_residuos": "Servicios Públicos y Ambiente",
    "medio_ambiente": "Servicios Públicos y Ambiente",
    "salud": "Salud y Bienestar Social",
    "impuestos_y_facturacion": "Hacienda e Impuestos",
    "educacion_y_cultura": "Educación y Cultura",
    "atencion_servidor_publico": "Secretaría General",
}

# Plantillas: (sujetos, problemas, complementos) por tema
PLANTILLAS = {
    "vias_y_alumbrado": (
        ["la calle", "la vía", "el andén", "la carrera", "el puente peatonal", "la glorieta"],
        ["tiene un hueco enorme", "está sin pavimentar", "tiene la luminaria dañada",
         "lleva semanas sin alumbrado público", "tiene el semáforo peatonal apagado y el poste caído",
         "está llena de huecos y el asfalto destruido", "no tiene luz en la noche"],
        ["frente a mi casa", "en el barrio centro", "cerca del colegio", "en la entrada del parque", "desde hace un mes"],
    ),
    "transito": (
        ["el semáforo", "la señal de tránsito", "el paso peatonal", "el parqueadero", "la intersección", "el bus"],
        ["está dañado y hay trancón", "no tiene señalización", "genera accidentes de tránsito",
         "tiene mal parqueados los carros sobre la acera", "necesita un reductor de velocidad",
         "tiene congestión vehicular todos los días", "no respeta el pico y placa"],
        ["en la avenida principal", "cerca de la escuela", "en horas pico", "frente al hospital", "en mi barrio"],
    ),
    "aseo_y_residuos": (
        ["el camión de la basura", "la recolección de residuos", "los escombros", "el contenedor", "la basura"],
        ["no pasa hace una semana", "está acumulada en la esquina", "huele muy mal y hay ratas",
         "no se recoge los martes", "está regada por la calle", "llevan días sin recoger los residuos"],
        ["en mi cuadra", "en el barrio", "frente al mercado", "en la plaza", "desde el lunes"],
    ),
    "medio_ambiente": (
        ["el río", "la quebrada", "la fábrica", "el humo", "la tala de árboles", "el parque natural"],
        ["está contaminado con vertimientos", "emite humo y mal olor al aire", "está destruyendo el ecosistema",
         "talaron árboles sin permiso ambiental", "tiene quema de basura contaminando el aire",
         "genera contaminación auditiva y ambiental"],
        ["cerca de mi vivienda", "en la vereda", "en la zona rural", "junto al colegio", "hace varios días"],
    ),
    "salud": (
        ["el puesto de salud", "el centro de salud", "la EPS", "la ambulancia", "el programa de vacunación", "el hospital"],
        ["no atiende a los adultos mayores", "no tiene medicamentos", "demora meses las citas médicas",
         "no llegó a atender la emergencia", "no tiene brigadas de vacunación", "no brinda atención a personas en discapacidad"],
        ["en mi vereda", "en el barrio", "para mi mamá", "a los niños", "en el municipio"],
    ),
    "impuestos_y_facturacion": (
        ["el impuesto predial", "la factura", "el cobro del impuesto", "el recibo de industria y comercio", "el paz y salvo"],
        ["me llegó con un valor errado", "está duplicado en el cobro", "tiene intereses que no debo",
         "no se refleja el pago que hice", "necesito una corrección de la factura", "no me entregan el paz y salvo"],
        ["de este año", "de mi casa", "de mi negocio", "del año pasado", "de la vigencia actual"],
    ),
    "educacion_y_cultura": (
        ["el colegio público", "la biblioteca municipal", "la casa de la cultura", "el transporte escolar", "el cupo escolar", "el festival"],
        ["no tiene profesores suficientes", "está cerrada en horario de atención", "necesita mantenimiento en las aulas",
         "no me asignaron cupo para mi hijo", "no ofrece talleres culturales", "no tiene el restaurante escolar funcionando"],
        ["en mi barrio", "para mi hija", "en el pueblo", "este semestre", "desde enero"],
    ),
    "atencion_servidor_publico": (
        ["el funcionario", "el empleado de la alcaldía", "el atendedor de la ventanilla", "la secretaria", "el servidor público"],
        ["me trató de forma grosera", "no me atendió y me mandó de oficina en oficina",
         "se negó a recibir mi documento", "me pidió dinero por un trámite", "no responde mis llamadas ni correos",
         "fue irrespetuoso con mi familia"],
        ["en la ventanilla", "ayer en la mañana", "en la oficina principal", "cuando fui a un trámite", "varias veces"],
    ),
}
INICIOS = ["Buenos días,", "Solicito que revisen:", "Quiero reportar que", "Hace días", "Les escribo porque", "Reclamo:", ""]
VAGOS = ["necesito ayuda urgente", "por favor revisar mi caso", "quiero poner una queja", "tengo un problema",
         "solicito una respuesta", "no me han resuelto nada", "favor atender mi solicitud"]


def con_errores(texto, rng, p=0.08):
    """Errores de ortografía simples: quita una letra o cambia tildes."""
    out = []
    for palabra in texto.split():
        r = rng.random()
        if r < p and len(palabra) > 4:
            i = rng.randrange(1, len(palabra) - 1)
            palabra = palabra[:i] + palabra[i + 1:]
        elif r < p * 1.6:
            palabra = (palabra.replace("á", "a").replace("é", "e").replace("í", "i")
                       .replace("ó", "o").replace("ú", "u"))
        out.append(palabra)
    return " ".join(out)


def frase(tema, rng):
    suj, prob, comp = PLANTILLAS[tema]
    return f"{rng.choice(INICIOS)} {rng.choice(suj)} {rng.choice(prob)} {rng.choice(comp)}".strip()


def generar_dataset(rng):
    """~15 % de textos que mencionan otro tema; ~5 % de textos vagos (tema impredecible)."""
    textos, etiquetas = [], []
    nombres = list(TEMAS)
    for tema in nombres:
        for _ in range(N_POR_TEMA):
            r = rng.random()
            if r < 0.05:                                   # texto vago
                t = rng.choice(VAGOS)
            elif r < 0.20:                                 # menciona otro tema
                otro = rng.choice([x for x in nombres if x != tema])
                t = frase(tema, rng) + " y además " + frase(otro, rng).lower()
            else:
                t = frase(tema, rng)
            textos.append(con_errores(t, rng))
            etiquetas.append(tema)
    return textos, etiquetas


def main():
    rng = random.Random(SEMILLA)
    X, y = generar_dataset(rng)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=SEMILLA, stratify=y)

    modelo = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), lowercase=True, sublinear_tf=True)),
        ("lr", LogisticRegression(max_iter=2000, C=10.0)),
    ])
    modelo.fit(Xtr, ytr)

    proba = modelo.predict_proba(Xte)
    clases = list(modelo.classes_)
    pred = [clases[p.argmax()] for p in proba]
    conf = [float(p.max()) for p in proba]

    exactitud = accuracy_score(yte, pred)
    auto = [i for i, c in enumerate(conf) if c >= UMBRAL]
    rev = [i for i, c in enumerate(conf) if c < UMBRAL]
    exact_auto = accuracy_score([yte[i] for i in auto], [pred[i] for i in auto]) if auto else 0.0
    exact_rev = accuracy_score([yte[i] for i in rev], [pred[i] for i in rev]) if rev else 0.0

    # Barrido de umbrales (alimenta el análisis de sensibilidad)
    barrido = {}
    for u in (0.5, 0.6, 0.7, 0.8):
        a = [i for i, c in enumerate(conf) if c >= u]
        barrido[str(u).replace(".", ",")] = {
            "pct_a_revision": round(100 * (1 - len(a) / len(conf)), 1),
            "exactitud_automaticos": round(100 * accuracy_score([yte[i] for i in a], [pred[i] for i in a]), 1) if a else None,
        }

    metricas = {
        "datos": {"total": len(X), "entrenamiento": len(Xtr), "prueba": len(Xte), "tipo": "SINTÉTICO"},
        "umbral": UMBRAL,
        "exactitud_global_pct": round(100 * exactitud, 1),
        "pct_casos_a_revision_humana": round(100 * len(rev) / len(conf), 1),
        "exactitud_casos_automaticos_pct": round(100 * exact_auto, 1),
        "exactitud_casos_en_revision_pct": round(100 * exact_rev, 1),
        "barrido_umbral": barrido,
        "cumple_RNF04_global_ge_85": exactitud >= 0.85,
        "cumple_RNF04_auto_ge_96": exact_auto >= 0.96,
        "cumple_RNF05_revision_le_20": len(rev) / len(conf) <= 0.20,
        "reporte_por_tema": classification_report(yte, pred, output_dict=True, zero_division=0),
    }
    json.dump(metricas, open("metricas.json", "w"), ensure_ascii=False, indent=1)
    joblib.dump({"modelo": modelo, "temas": TEMAS, "umbral": UMBRAL}, "modelo_pqrs.joblib")

    print("Datos: %d textos (%d entrenamiento / %d prueba) - SINTÉTICOS" % (len(X), len(Xtr), len(Xte)))
    print("Exactitud global:            %.1f %%  (RNF-04: >= 85 %%)" % (100 * exactitud))
    print("Casos a revisión humana:     %.1f %%  (RNF-05: <= 20 %%)" % (100 * len(rev) / len(conf)))
    print("Exactitud en automáticos:    %.1f %%  (RNF-04: >= 96 %%)" % (100 * exact_auto))
    print("Exactitud en revisión:       %.1f %%" % (100 * exact_rev))
    print("Barrido de umbral:", json.dumps(barrido, ensure_ascii=False))
    print("\nGuardado: modelo_pqrs.joblib, metricas.json")


if __name__ == "__main__":
    main()
