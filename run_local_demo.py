"""
run_local_demo.py — Orquestador del pipeline, ejecutable LOCALMENTE sin API ni Supabase.
Reproduce el flujo completo end-to-end sobre los .xlsx de esta carpeta:

  para cada mes (en orden):
    1) EXTRAER cifras del .xlsx                      -> extract.py
    2) recuperar HISTORIA acumulada (aquí: en memoria; en prod: Supabase)
    3) ANALIZAR con IA -> verdict + anotaciones      -> ai_step.stub_analysis (prod: Claude/OpenAI)
    4) RENDER del PDF de una página                  -> render.py
    5) guardar el mes en la historia                 (en prod: Supabase)

Esto demuestra que el contrato JSON encaja de punta a punta. En n8n cada paso
es un nodo; aquí están encadenados en Python para poder probarlo de una.
"""
import os
from extract import extract_income_statement
from ai_step import analyze_with_openai as _ai  # prod: OpenAI GPT-4o
from render import render_report

COMPANIA = "Comercializadora Andina S.A.S."
MESES = ["January","February","March","April","May","June",
         "July","August","September","October","November","December"]
MES_ES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto",
          "Septiembre","Octubre","Noviembre","Diciembre"]
LBL = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]

def main():
    os.makedirs("output", exist_ok=True)
    history = []                              # en prod: SELECT de Supabase
    for k, mes_en in enumerate(MESES):
        xlsx = f"2025_{mes_en}_Income_Statement.xlsx"
        if not os.path.exists(xlsx):
            print(f"  (omito {mes_en}: no encontrado)"); continue

        current = extract_income_statement(xlsx)                      # 1
        analysis = _ai(COMPANIA, f"{MES_ES[k]} 2025",                   # 3
                       current, history)
        payload = {
            "compania": COMPANIA,
            "mes": f"{MES_ES[k]} 2025",
            "labels": LBL[:k+1],
            "figs": history + [current],
            "verdict": analysis["verdict"],
            "anotaciones": analysis["anotaciones"],
        }
        out = render_report(payload, f"output/2025_{mes_en}_Financial_Report.pdf")  # 4
        history.append(current)                                        # 5
        print(f"  ✓ {mes_en:10s} -> {out}   [{analysis['verdict']}]")

if __name__ == "__main__":
    main()
