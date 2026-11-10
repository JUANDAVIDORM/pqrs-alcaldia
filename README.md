# PQRS Alcaldía de Villa Serena (ficticia) — Prototipo del Caso B

Proyecto académico de Automatización de Procesos de Negocio (EAFIT, Ingeniería de Sistemas).
Propuesta para gestionar peticiones, quejas, reclamos y sugerencias (PQRS) de forma
única, trazable y con control de plazos legales.

## Componentes (3, según el tablero del curso)

| # | Componente | Carpeta | Qué hace |
|---|------------|---------|----------|
| 1 | **IA** (clasificador) | `clasificador/` | TF-IDF + regresión logística. Sugiere tema y dependencia. Si la confianza es < 0,70, pasa a revisión humana. |
| 2 | **Orquestador / BPMS** | `backend/` | API FastAPI con el flujo TO-BE: radicar, duplicados, asignar por menor carga, alertas 70/90/100 %, cierre y consulta. |
| 3 | **Simulación de procesos** | `simulacion/` | Simulación de eventos discretos (SimPy) de AS-IS vs TO-BE. Genera `resultados_simulacion.json`. |

Interfaz web: `interfaz/app.py` (Streamlit). Los modelos BPMN están en `bizagi/` y la
documentación de arquitectura y clases en `arquitectura/`. El informe de cambios de
interfaz está en `INFORME_CAMBIOS_INTERFAZ.md`.

> RPA y ROA aparecen en el tablero como opciones; este prototipo **no** los implementa.

## Requisitos

- Python 3.12 (o Docker Desktop, si prefieren no instalar nada más).
- Terminal (Windows: PowerShell o Git Bash; macOS/Linux: Terminal).

## Opción A — Local con Python (recomendada para desarrollar)

```bash
cd PQRS_ALCALDIA
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt

# 1) Pruebas automáticas (7 casos de aceptación del flujo)
cd backend && python test_flujo.py && cd ..

# 2) Reentrenar el clasificador (opcional; ya viene entrenado)
cd clasificador && python entrenar_clasificador.py && cd ..

# 3) Simulación (opcional, tarda ~1 min)
cd simulacion && python simulacion_pqrs.py && cd ..

# 4) Levantar la aplicación completa (un solo proceso visible y una sola URL)
streamlit run interfaz/app.py
#    Se abre en http://localhost:8501
#    La interfaz inicia la API internamente y conserva los casos en backend/pqrs.db.
```

## Opción B — Docker (aplicación completa)

```bash
docker compose up --build
# Aplicación en http://localhost:8501
# La base de datos queda en el volumen Docker pqrs_data.
```

## Uso desde la API (curl)

```bash
curl -X POST http://127.0.0.1:8000/pqrs -H "Content-Type: application/json" \
  -d '{"ciudadano":"María López","contacto":"maria@correo.co","tipo":"queja",
       "descripcion":"El camión de la basura no pasa hace una semana en mi cuadra","canal":"web"}'
```

## Limitaciones honestas (para la sustentación)

- Los casos se guardan en SQLite (`backend/pqrs.db`) y sobreviven al reinicio.
- Clasificador entrenado con **datos sintéticos**; la precisión real no está validada.
- El prototipo aún no tiene autenticación formal; la vista de gestión está separada visualmente.
- La simulación no ha sido contrastada con el simulador de Bizagi.
- Meta de vencidas (≤ 5 %): la simulación da 9,0 %; no se cumple y así debe presentarse.
