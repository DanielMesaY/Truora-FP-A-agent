"""
ai_step.py — Paso de ANÁLISIS CON IA del pipeline.
Recibe la serie de cifras (mes actual + historia) y devuelve el JUICIO ANALÍTICO:
veredicto + anotaciones. Esto es lo único que produce el modelo; el render es
determinístico y la historia vive en Supabase.

- analyze_with_claude(...)  -> usa la API de Anthropic
- analyze_with_openai(...)  -> usa la API de OpenAI
- stub_analysis(...)        -> versión determinística SIN API (solo para el demo local)

En producción (n8n) usa una de las dos primeras. La salida es SIEMPRE el mismo JSON,
de modo que el render no cambia según el proveedor.
"""
import json, os

SYSTEM_PROMPT = """\
Eres un analista financiero senior especializado en FP&A. Analizas el estado de
resultados mensual de una compañía con rigor de banca de inversión y enfoque en
decisiones de comité.

PRINCIPIOS INNEGOCIABLES
1. Usa ÚNICAMENTE los datos provistos. No inventes ni extrapoles cifras.
2. Si el contexto histórico está vacío (mes base), NO compares: declara línea base.
3. Cuantifica todo. Variaciones en doble formato: absoluto (COP millones) y % .
   Para márgenes, usa puntos porcentuales (pp).
4. Convención de signos: costos y gastos vienen en negativo.
5. No suavices un mal resultado ni infles uno bueno. Marca anomalías.

TAREA
Compara el mes actual contra el mes inmediatamente anterior y contra la tendencia
acumulada (YTD), y dictamina si es MEJORA, DETERIORO o LINEA_BASE (solo el primer mes).

FORMATO DE SALIDA — devuelve EXCLUSIVAMENTE un JSON válido, sin texto adicional:
{
  "verdict": "MEJORA" | "DETERIORO" | "LINEA_BASE",
  "anotaciones": [
    {"tipo": "positiva" | "negativa" | "neutra", "texto": "<<= 140 caracteres>"}
  ]
}
Entrega entre 3 y 5 anotaciones. La primera debe ser el driver principal del mes.
Cada anotación lleva al menos una cifra. Texto en español, conciso, para comité.
"""

def _build_user_message(compania, mes, current, history):
    return (
        f"COMPAÑÍA: {compania}\n"
        f"MES A ANALIZAR: {mes}\n\n"
        f"ESTADO DE RESULTADOS DEL MES ACTUAL (COP millones):\n"
        f"{json.dumps(current, ensure_ascii=False, indent=2)}\n\n"
        f"CONTEXTO HISTÓRICO ACUMULADO (meses previos, en orden):\n"
        f"{json.dumps(history, ensure_ascii=False, indent=2) if history else 'SIN PERÍODOS PREVIOS'}\n\n"
        f"Genera el JSON de análisis acumulativo siguiendo estrictamente el formato."
    )

def _parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].replace("json", "", 1).strip()
    return json.loads(text)

def analyze_with_claude(compania, mes, current, history, model="claude-opus-4-8"):
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=model, max_tokens=1024, system=SYSTEM_PROMPT,
        messages=[{"role": "user",
                   "content": _build_user_message(compania, mes, current, history)}],
    )
    return _parse_json(msg.content[0].text)

def analyze_with_openai(compania, mes, current, history, model="gpt-4o"):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.chat.completions.create(
        model=model, temperature=0.2,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user",
                   "content": _build_user_message(compania, mes, current, history)}],
    )
    return _parse_json(resp.choices[0].message.content)

# ---------------------------------------------------------------------------
# STUB determinístico — SOLO para el demo local sin API.
# En producción se reemplaza por analyze_with_claude / analyze_with_openai.
# ---------------------------------------------------------------------------
def stub_analysis(compania, mes, current, history):
    figs = history + [current]
    k = len(figs) - 1
    rev=[f["ingresos"] for f in figs]; ni=[f["utilidad_neta"] for f in figs]
    m_eb=[f["margen_ebitda"]*100 for f in figs]
    fmt=lambda v: f"{v:,.0f}".replace(",", ".")
    notes=[]
    if k == 0:
        verdict="LINEA_BASE"
        notes.append(("neutra",f"Mes base: ingresos COP {fmt(rev[0])}M, EBITDA "
                      f"{fmt(current['ebitda'])}M. Referencia para próximos períodos."))
        notes.append(("neutra",f"Márgenes — bruto {current['margen_bruto']*100:.1f}%, "
                      f"EBITDA {m_eb[0]:.1f}%, neto {current['margen_neto']*100:.1f}%."))
        if ni[0] < 0:
            notes.append(("negativa",f"Resultado neto negativo (COP {fmt(ni[0])}M): la base "
                          "operativa no cubre el resultado financiero."))
        notes.append(("neutra","Sin períodos previos; las variaciones MoM aplican desde el mes 2."))
    else:
        verdict="MEJORA" if ni[k] >= ni[k-1] else "DETERIORO"
        rp=(rev[k]/rev[k-1]-1)*100
        notes.append(("positiva" if rp>=0 else "negativa",
                      f"Ingresos COP {fmt(rev[k])}M ({'+' if rp>=0 else ''}{rp:.1f}% MoM)."))
        dpp=m_eb[k]-m_eb[k-1]
        notes.append(("positiva" if dpp>=0 else "negativa",
                      f"Margen EBITDA {m_eb[k]:.1f}% ({'+' if dpp>=0 else ''}{dpp:.1f}pp MoM): "
                      f"{'apalancamiento operativo' if dpp>=0 else 'compresión de margen'}."))
        losses=[figs[i] for i in range(k+1) if figs[i]["utilidad_neta"] < 0]
        if losses:
            notes.append(("negativa",f"{len(losses)} mes(es) con pérdida neta en la serie."))
        else:
            notes.append(("positiva","Todos los meses de la serie cierran con utilidad positiva."))
        ytd=sum(ni); avg=ytd/sum(rev)*100
        notes.append(("neutra",f"Utilidad neta YTD: COP {fmt(ytd)}M; margen neto promedio {avg:.1f}%."))
        notes.append(("neutra","Margen bruto estable; el resultado lo mueve la base operativa."))
    return {"verdict": verdict,
            "anotaciones": [{"tipo": t, "texto": x} for t, x in notes[:5]]}
