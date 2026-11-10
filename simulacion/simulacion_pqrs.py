#!/usr/bin/env python3
"""Simulación de eventos discretos del proceso de PQRS (Caso B, alcaldía ficticia).

TODOS los parámetros son SUPUESTOS DEL PROYECTO (ver secciones 1.7 y 5 del documento).
El tiempo se mide en horas laborales (8 h por día hábil, 22 días hábiles al mes).

Uso:  python3 simulacion_pqrs.py            # corre E1..E4 y la sensibilidad
"""
import json
import math
import random
import statistics as st

import simpy

H_DIA, DIAS_MES = 8, 22
PLAZO = 15 * H_DIA                      # S-05: 15 días hábiles = 120 h laborales
DEP_P = [0.22, 0.15, 0.18, 0.15, 0.18, 0.12]   # reparto supuesto de casos entre las 6 dependencias
HORIZONTE_MESES, CALENTAMIENTO_MESES, REPLICAS = 12, 1, 30

BASE = dict(
    modo="asis", carga=1.0, llegadas_mes=600,                 # S-02
    p_dup=0.08, p_mal=0.15,                                   # S-08, S-09
    n_rad=2, func_por_dep=2,                                  # S-13
    t_registro=6 / 60, t_clasif_manual=10 / 60,               # S-18 (10 min) y registro (supuesto S-22: 6 min)
    t_reenvio=2.0, t_jefe=2.0, t_devolucion=3.5,              # supuestos S-23 (demoras AS-IS, horas)
    s_media=2.5, s_cv=0.6,                                    # trabajo activo del funcionario (S-24)
    e_media=50.0, e_cv=1.0,                                   # espera externa; se calibra a 25 % vencidas (S-25)
    reproceso_mal=1.5, reproceso_dup=1.0,                     # S-19, S-20
    # TO-BE
    recall_dup=0.80, fp_dup=0.03,                             # detección de duplicados (S-26)
    p_rev=0.20, e_auto=0.04, e_hum=0.02,                      # S-12 y calidad de la IA (S-27)
    t_revision=5 / 60,                                        # S-21
    t_reasignacion=4.0,                                       # el jefe reasigna un caso mal clasificado (S-28)
    alertas=True, p1=0.5, f1=0.7, p2=0.7, f2=0.5,             # efectividad de alertas 70 % y 90 % (S-29)
)


def lognorm(rng, media, cv):
    s2 = math.log(1 + cv ** 2)
    return rng.lognormvariate(math.log(media) - s2 / 2, math.sqrt(s2))


def simular(par, semilla):
    rng = random.Random(semilla)
    env = simpy.Environment()
    rad = simpy.Resource(env, capacity=par["n_rad"])
    funcs = [[simpy.Resource(env, 1) for _ in range(par["func_por_dep"])] for _ in DEP_P]
    ocup = {"rad": 0.0, "fun": 0.0}
    casos = []
    T = HORIZONTE_MESES * DIAS_MES * H_DIA
    T0 = CALENTAMIENTO_MESES * DIAS_MES * H_DIA

    def usar(recurso, dur, clave, espera_log=None):
        t = env.now
        with recurso.request() as r:
            yield r
            if espera_log is not None:
                espera_log.append(env.now - t)
            yield env.timeout(dur)
            ocup[clave] += dur

    def caso(c):
        asis = par["modo"] == "asis"
        canal = rng.choices(["web", "correo", "pres"], [0.4, 0.3, 0.3])[0]
        dup = rng.random() < par["p_dup"]
        dep = rng.choices(range(len(DEP_P)), DEP_P)[0]
        t0 = env.now
        c.update(t0=t0, dup=dup, mal=False, revision=False, vinculado=False, espera_rev=0.0)
        mal = False
        if asis:
            if canal != "pres":                       # revisión periódica del buzón (TA-05)
                yield env.timeout(rng.uniform(0, H_DIA))
            dur = rng.expovariate(1 / (par["t_registro"] + par["t_clasif_manual"]))
            yield from usar(rad, dur, "rad")
            yield env.timeout(rng.expovariate(1 / par["t_reenvio"]))
            equivocado = rng.random() < par["p_mal"]
            mal = equivocado
            while True:
                yield env.timeout(rng.expovariate(1 / par["t_jefe"]))   # TA-09
                if not equivocado:
                    break
                yield env.timeout(rng.expovariate(1 / par["t_devolucion"]))  # TA-10
                yield from usar(rad, rng.expovariate(1 / par["t_clasif_manual"]), "rad")
                yield env.timeout(rng.expovariate(1 / par["t_reenvio"]))
                equivocado = rng.random() < par["p_mal"]
            f = funcs[dep][rng.randrange(par["func_por_dep"])]
        else:
            if canal != "web":                        # T-03 registro de correo y presencial
                yield from usar(rad, rng.expovariate(1 / par["t_registro"]), "rad")
            marcado = rng.random() < (par["recall_dup"] if dup else par["fp_dup"])
            if marcado:                               # T-06 confirmación humana
                lg = []
                yield from usar(rad, rng.expovariate(1 / par["t_revision"]), "rad", lg)
                if dup:
                    c.update(vinculado=True, t_asig=None, t_resp=env.now)
                    return
            rev = rng.random() < par["p_rev"]         # T-08 clasificación con IA
            c["revision"] = rev
            if rev:                                   # T-09 revisión humana (baja confianza)
                lg = []
                yield from usar(rad, rng.expovariate(1 / par["t_revision"]), "rad", lg)
                c["espera_rev"] = lg[0]
                mal = rng.random() < par["e_hum"]
            else:
                mal = rng.random() < par["e_auto"]
            if mal:
                yield env.timeout(rng.expovariate(1 / par["t_reasignacion"]))
            f = min(funcs[dep], key=lambda r: len(r.queue) + r.count)   # T-10 asignación por menor carga
        c["mal"] = mal
        c["t_asig"] = env.now - t0
        s = lognorm(rng, par["s_media"], par["s_cv"])
        s += par["reproceso_mal"] if mal else 0.0
        s += par["reproceso_dup"] if dup else 0.0
        yield from usar(f, s, "fun")
        e = lognorm(rng, par["e_media"], par["e_cv"])
        ini = env.now
        fin = ini + e
        if par["alertas"] and not asis:               # T-13, T-14: temporizadores no interruptores
            a1 = max(t0 + 0.7 * PLAZO, ini)
            if fin > a1 and rng.random() < par["p1"]:
                fin = a1 + (fin - a1) * par["f1"]
            a2 = max(t0 + 0.9 * PLAZO, ini)
            if fin > a2 and rng.random() < par["p2"]:
                fin = a2 + (fin - a2) * par["f2"]
        yield env.timeout(fin - ini)
        c["t_resp"] = env.now

    def llegadas():
        tasa = par["llegadas_mes"] * par["carga"] / (DIAS_MES * H_DIA)
        while env.now < T:
            yield env.timeout(rng.expovariate(tasa))
            c = {}
            casos.append(c)
            env.process(caso(c))

    env.process(llegadas())
    env.run(until=T + 40 * H_DIA)
    meses = HORIZONTE_MESES - CALENTAMIENTO_MESES
    obs = [c for c in casos if c.get("t0", 0) >= T0]
    n = len(obs)
    venc = sum(1 for c in obs if ((c.get("t_resp") or env.now) - c["t0"]) > PLAZO and not c["vinculado"])
    asig = [c["t_asig"] for c in obs if c.get("t_asig") is not None]
    ciclo = [c["t_resp"] - c["t0"] for c in obs if c.get("t_resp") is not None and not c["vinculado"]]
    esp = [c["espera_rev"] for c in obs if c["revision"]]
    horas_rep = sum(par["reproceso_mal"] for c in obs if c["mal"]) + sum(par["reproceso_dup"] for c in obs if c["dup"] and not c["vinculado"])
    return dict(
        n_mes=n / meses,
        vencidas=100 * venc / n,
        mal_asignadas=100 * sum(c["mal"] for c in obs) / n,
        duplicadas=100 * sum(1 for c in obs if c["dup"] and not c["vinculado"]) / n,
        asig_media_h=st.mean(asig),
        asig_p90_h=sorted(asig)[int(0.9 * len(asig))],
        ciclo_dias=st.mean(ciclo) / H_DIA,
        util_rad=100 * ocup["rad"] / (par["n_rad"] * T),
        util_fun=100 * ocup["fun"] / (len(DEP_P) * par["func_por_dep"] * T),
        espera_rev_min=60 * st.mean(esp) if esp else 0.0,
        horas_rad_mes=ocup["rad"] / HORIZONTE_MESES,
        horas_reproceso_mes=horas_rep / meses,
        revision_mes=sum(1 for c in obs if c["revision"]) / meses,
    )


def replicas(par, n=REPLICAS, semilla=1000):
    res = [simular(par, semilla + i) for i in range(n)]
    out = {}
    for k in res[0]:
        v = [r[k] for r in res]
        out[k] = (st.mean(v), 1.96 * st.pstdev(v) / math.sqrt(len(v)))
    return out


def calibrar(par, objetivo=25.0):
    lo, hi = 5.0, 200.0
    for _ in range(14):
        mid = (lo + hi) / 2
        p = dict(par, e_media=mid)
        v = st.mean(simular(p, 500 + i)["vencidas"] for i in range(6))
        lo, hi = (mid, hi) if v < objetivo else (lo, mid)
    return round((lo + hi) / 2, 1)


def main():
    asis = dict(BASE, modo="asis")
    asis["e_media"] = calibrar(asis)
    tobe = dict(BASE, modo="tobe", e_media=asis["e_media"])
    esc = {
        "E1": ("AS-IS, carga normal", asis),
        "E2": ("TO-BE, carga normal", tobe),
        "E3": ("TO-BE, pico de demanda (+50 %)", dict(tobe, carga=1.5)),
        "E4": ("TO-BE con IA de menor precisión", dict(tobe, p_rev=0.35, e_auto=0.10)),
    }
    out = {"e_media_calibrada_h": asis["e_media"], "escenarios": {}, "sensibilidad": {}}
    for k, (desc, p) in esc.items():
        out["escenarios"][k] = {"desc": desc, **replicas(p)}
    sens_alertas = {"Sin alertas": dict(tobe, alertas=False),
                    "Efectividad baja": dict(tobe, p1=0.3, f1=0.8, p2=0.5, f2=0.7),
                    "Efectividad media (base)": tobe,
                    "Efectividad alta": dict(tobe, p1=0.7, f1=0.6, p2=0.9, f2=0.4)}
    out["sensibilidad"]["alertas"] = {k: replicas(p) for k, p in sens_alertas.items()}
    sens_umbral = {"Umbral 0,60": dict(tobe, p_rev=0.10, e_auto=0.07),
                   "Umbral 0,70 (base)": tobe,
                   "Umbral 0,80": dict(tobe, p_rev=0.35, e_auto=0.025)}
    out["sensibilidad"]["umbral"] = {k: replicas(p) for k, p in sens_umbral.items()}
    json.dump(out, open("resultados_simulacion.json", "w"), ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    r = main()
    print("e_media calibrada (h):", r["e_media_calibrada_h"])
    for k, v in r["escenarios"].items():
        print(k, v["desc"])
        for m, val in v.items():
            if m != "desc":
                print("   %-20s %8.2f ± %.2f" % (m, val[0], val[1]))
