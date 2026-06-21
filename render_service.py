"""
render_service.py — Microservicio HTTP que envuelve render.py.

n8n Cloud no permite matplotlib en el nodo Code, así que el render vive aquí:
una mini-API Flask que recibe el contrato JSON (el mismo payload de run_local_demo.py)
y devuelve el PDF de una página como binario.

Uso en n8n: nodo HTTP Request (POST) -> este endpoint -> el PDF llega en la respuesta
y se encadena al nodo de Google Drive Upload.

Endpoints:
  GET  /health   -> {"status": "ok"}   (para probar que está vivo)
  POST /render   -> body = payload JSON, respuesta = application/pdf

Correr local:
  python render_service.py            # escucha en http://localhost:8000

Desplegar gratis (Render.com / Railway):
  Build:  pip install -r requirements_service.txt
  Start:  gunicorn render_service:app
"""
import io
import tempfile
import os
from flask import Flask, request, send_file, jsonify
from render import render_report

app = Flask(__name__)

# Claves canónicas que render.py espera en cada dict de `figs`.
REQUIRED_FIGURE_KEYS = {
    "ingresos", "costo_ventas", "utilidad_bruta", "margen_bruto",
    "gastos_admin", "gastos_ventas", "gastos_mercadeo", "ebitda",
    "margen_ebitda", "depreciacion_amortizacion", "ebit", "margen_operacional",
    "ingresos_fin", "gastos_fin", "uai", "impuesto_renta",
    "utilidad_neta", "margen_neto",
}


def _validate(payload: dict):
    """No inventamos nada: si el payload viene incompleto, fallamos claro."""
    for field in ("compania", "mes", "labels", "figs", "verdict", "anotaciones"):
        if field not in payload:
            return f"Falta el campo '{field}' en el payload."
    if not isinstance(payload["figs"], list) or not payload["figs"]:
        return "El campo 'figs' debe ser una lista no vacía."
    if len(payload["labels"]) != len(payload["figs"]):
        return "labels y figs deben tener la misma longitud."
    for i, fig in enumerate(payload["figs"]):
        missing = REQUIRED_FIGURE_KEYS - set(fig.keys())
        if missing:
            return f"figs[{i}] no trae: {sorted(missing)}"
    return None


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/render")
def render():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "El body debe ser JSON válido."}), 400

    err = _validate(payload)
    if err:
        return jsonify({"error": err}), 422

    # render_report escribe a un path; usamos un archivo temporal y lo devolvemos.
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    try:
        render_report(payload, tmp.name)
        with open(tmp.name, "rb") as fh:
            data = fh.read()
    finally:
        os.unlink(tmp.name)

    nombre = f"{payload['mes'].replace(' ', '_')}_Financial_Report.pdf"
    return send_file(
        io.BytesIO(data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=nombre,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
