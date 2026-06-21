"""
store_supabase.py — Paso de PERSISTENCIA del pipeline (la "historia" acumulativa).
Requiere: pip install supabase ; env SUPABASE_URL y SUPABASE_KEY.

En n8n puedes usar el nodo nativo de Supabase en vez de este módulo; la lógica es la misma:
- get_history: trae los meses < N para inyectarlos como contexto histórico.
- save_month / save_report: guardan para que el mes N+1 ya tenga a N como historia.
"""
import os
from supabase import create_client

def _client():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

def get_history(compania, anio, mes_idx):
    """Lista de dicts `figures` de los meses anteriores, en orden cronológico."""
    r = (_client().table("monthly_financials")
         .select("figures, mes_idx")
         .eq("compania", compania).eq("anio", anio)
         .lt("mes_idx", mes_idx).order("mes_idx").execute())
    return [row["figures"] for row in r.data]

def save_month(compania, anio, mes_idx, mes, figures):
    return (_client().table("monthly_financials")
            .upsert({"compania": compania, "anio": anio, "mes_idx": mes_idx,
                     "mes": mes, "figures": figures},
                    on_conflict="compania,anio,mes_idx").execute())

def save_report(compania, anio, mes_idx, verdict, anotaciones, pdf_url=None):
    return (_client().table("monthly_reports")
            .upsert({"compania": compania, "anio": anio, "mes_idx": mes_idx,
                     "verdict": verdict, "anotaciones": anotaciones, "pdf_url": pdf_url},
                    on_conflict="compania,anio,mes_idx").execute())
