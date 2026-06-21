# Truora — Financial AI Agent (FP&A)

Agente que, de forma autónoma, lee los **estados de resultados mensuales** de una
compañía desde una carpeta de Google Drive y genera, por cada mes, un **reporte PDF de
una página** con gráficos de evolución y anotaciones de análisis. El reporte es
**acumulativo**: cada mes muestra la serie completa hasta ese período y dictamina
**mejora / deterioro** frente a los anteriores.

## Idea central (por qué está partido así)

Un modelo de lenguaje **no genera PDFs** y **no tiene memoria** entre llamadas. Por eso:

- El **juicio analítico** (lo difícil) lo hace la IA y devuelve **JSON** (`verdict` + `anotaciones`).
- El **render** es **determinístico** (Python/matplotlib): mismo input → mismo PDF, sin alucinaciones en los gráficos.
- El carácter **acumulativo** vive en **Supabase**, no en el prompt: antes de analizar el mes N, se recupera la historia de los meses 1…N-1 y se inyecta como contexto.

```
Drive (.xlsx)
   │  trigger: archivo nuevo
   ▼
[1] extract.py        cifras del mes  ───────────────┐
   ▼                                                 │
[2] get_history()     meses 1..N-1 (Supabase) ───────┤
   ▼                                                 │
[3] ai_step           IA → { verdict, anotaciones }  │  (contrato JSON)
   ▼                                                 │
[4] save_month/report Supabase (historia + reporte)  │
   ▼                                                 │
[5] render.py         PDF de 1 página  ◄─────────────┘
   ▼
Drive / Slack / email  (entrega)
```

## Archivos

| Archivo | Rol | ¿Corre sin credenciales? |
|---|---|---|
| `extract.py` | Lee el .xlsx → dict de 18 líneas del P&G (por etiqueta, tolerante a layout) | ✅ |
| `ai_step.py` | Prompt + llamada a Claude/OpenAI → `{verdict, anotaciones}`. Incluye `stub_analysis` offline | ✅ (stub) |
| `render.py` | Contrato JSON → PDF de una página con la serie completa | ✅ |
| `store_supabase.py` | Historia acumulada: `get_history`, `save_month`, `save_report` | ❌ (necesita Supabase) |
| `supabase_schema.sql` | Tablas `monthly_financials` y `monthly_reports` | — |
| `run_local_demo.py` | Encadena todo end-to-end sobre los .xlsx de la carpeta (IA = stub) | ✅ |

## Probar el demo local (sin API)

```bash
pip install -r requirements.txt
python run_local_demo.py        # genera output/2025_<Mes>_Financial_Report.pdf
```

## Pasar a producción (la IA real)

En `run_local_demo.py` / tu nodo, reemplaza:

```python
from ai_step import stub_analysis
analysis = stub_analysis(compania, mes, current, history)
```

por:

```python
from ai_step import analyze_with_claude
analysis = analyze_with_claude(compania, mes, current, history)   # usa ANTHROPIC_API_KEY
```

El resto del pipeline no cambia: el contrato JSON es idéntico.

## Mapeo a n8n (orquestación)

1. **Google Drive Trigger** — "New File" en la carpeta `Truora - Financial AI Agent Case Study`.
2. **Google Drive – Download** — baja el .xlsx.
3. **Code (Python)** — `extract.py` → cifras del mes.
4. **Supabase – Select** — `monthly_financials` con `mes_idx < N` (historia).
5. **HTTP Request / nodo Anthropic** — system = `SYSTEM_PROMPT`, user = mes + historia → JSON.
6. **Supabase – Upsert** — guarda cifras del mes y el reporte.
7. **Code (Python)** — `render.py` → PDF.
8. **Google Drive – Upload** (o Slack/email) — entrega el PDF.

## Variables de entorno

```
ANTHROPIC_API_KEY=...        # o OPENAI_API_KEY
SUPABASE_URL=...
SUPABASE_KEY=...             # service_role (lado servidor)
```

## Notas de diseño (para la documentación de Truora)

- **Mes base**: si no hay historia, la IA declara `LINEA_BASE` y no inventa comparaciones (modo de falla más común, blindado en el prompt).
- **Idempotencia**: las tablas usan `unique(compania, anio, mes_idx)` → reprocesar un mes no duplica.
- **Separación de responsabilidades**: IA = juicio; render = determinístico; Supabase = memoria. Esto es lo que hace el agente robusto y auditable.
