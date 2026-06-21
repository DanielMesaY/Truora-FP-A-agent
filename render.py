"""
render.py — Paso de RENDER del pipeline.
Recibe el contrato (serie de cifras hasta el mes N + veredicto + anotaciones de la IA)
y dibuja el reporte de UNA página con la serie completa hasta ese mes.

Función pública:
    render_report(payload: dict, out_path: str) -> str

payload = {
  "compania": str,
  "mes": str,                      # ej. "Junio 2025"
  "labels": ["Ene","Feb",...],     # etiquetas hasta el mes actual
  "figs":   [ {dict de cifras}, ... ],   # un dict por mes (de extract.py), en orden
  "verdict": "MEJORA" | "DETERIORO" | "LINEA_BASE",
  "anotaciones": [ {"tipo":"positiva|negativa|neutra", "texto": "..."} ]
}
La IA produce `verdict` y `anotaciones`. Todo lo demás sale de los datos (Supabase).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import gridspec
from matplotlib.patches import FancyBboxPatch
import textwrap

NAVY="#1F3864"; BLUE="#2E5FAC"; ACC="#4A90D9"; GREEN="#2E8B57"; RED="#C0392B"
GREY="#6B7280"; LGREY="#E8ECF3"; BG="#FFFFFF"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":8,
    "axes.edgecolor":"#C9D2E0","axes.linewidth":.8,
    "xtick.color":GREY,"ytick.color":GREY,"text.color":"#1A1A1A"})

def _fmt(v): return f"{v:,.0f}".replace(",", ".")

def render_report(payload: dict, out_path: str) -> str:
    figs   = payload["figs"]
    labels = payload["labels"]
    k = len(figs) - 1                      # índice del mes actual
    base = (k == 0) or payload.get("verdict") == "LINEA_BASE"

    rev = [f["ingresos"] for f in figs]
    eb  = [f["ebitda"] for f in figs]
    ni  = [f["utilidad_neta"] for f in figs]
    m_gp=[f["margen_bruto"]*100 for f in figs]
    m_eb=[f["margen_ebitda"]*100 for f in figs]
    m_op=[f["margen_operacional"]*100 for f in figs]
    m_ni=[f["margen_neto"]*100 for f in figs]
    ni_cum=[sum(ni[:i+1]) for i in range(len(ni))]
    idx=list(range(k+1))

    vmap={"MEJORA":("MEJORA","white"),"DETERIORO":("DETERIORO","#F5B7B1"),
          "LINEA_BASE":("LÍNEA BASE","#C7D4EC")}
    verdict_txt,vcol=vmap.get(payload.get("verdict","LINEA_BASE"),("LÍNEA BASE","#C7D4EC"))

    fig=plt.figure(figsize=(11.69,8.27),dpi=200); fig.patch.set_facecolor(BG)
    gs=gridspec.GridSpec(3,4,figure=fig,height_ratios=[0.62,1.25,1.25],
        hspace=0.5,wspace=0.34,left=0.045,right=0.975,top=0.885,bottom=0.06)

    # ---- header ----
    hax=fig.add_axes([0,0.93,1,0.07]); hax.axis("off")
    hax.add_patch(FancyBboxPatch((0,0),1,1,boxstyle="square,pad=0",fc=NAVY,ec="none",
        transform=hax.transAxes))
    hax.text(0.045,0.58,payload["compania"],color="white",fontsize=15,
        fontweight="bold",va="center")
    hax.text(0.045,0.2,f"Reporte Financiero Mensual (FP&A)  ·  Acumulado a {payload['mes']}",
        color="#C7D4EC",fontsize=8.5,va="center")
    hax.text(0.965,0.58,verdict_txt,color=vcol,fontsize=12,fontweight="bold",
        ha="right",va="center")
    hax.text(0.965,0.2,"Cifras en COP millones",color="#C7D4EC",fontsize=7.5,
        ha="right",va="center")

    # ---- KPIs ----
    if base:
        d_rev=d_eb="Mes base"; cR=cE=GREY
    else:
        rp=(rev[k]/rev[k-1]-1)*100; ep=(eb[k]/eb[k-1]-1)*100
        d_rev=f"{'+' if rp>=0 else ''}{rp:.1f}% MoM"; d_eb=f"{'+' if ep>=0 else ''}{ep:.1f}% MoM"
        cR=GREEN if rp>=0 else RED; cE=GREEN if ep>=0 else RED
    avg=sum(ni)/sum(rev)*100
    kpis=[("Ingresos del mes",_fmt(rev[k]),d_rev,cR),
          ("EBITDA del mes",_fmt(eb[k]),d_eb,cE),
          ("Utilidad neta del mes",_fmt(ni[k]),f"Margen {m_ni[k]:.1f}%",GREEN if ni[k]>=0 else RED),
          ("Utilidad neta YTD",_fmt(ni_cum[-1]),f"Margen prom. {avg:.1f}%",NAVY)]
    for i,(t,v,d,c) in enumerate(kpis):
        ax=fig.add_subplot(gs[0,i]); ax.axis("off")
        ax.add_patch(FancyBboxPatch((0.02,0.05),0.96,0.9,
            boxstyle="round,pad=0.02,rounding_size=0.06",fc=LGREY,ec="#D2DAE8",lw=1,
            transform=ax.transAxes))
        ax.text(0.08,0.74,t.upper(),fontsize=7,color=GREY,fontweight="bold",va="center")
        ax.text(0.08,0.42,v,fontsize=17,color=NAVY,fontweight="bold",va="center")
        ax.text(0.08,0.16,d,fontsize=7.5,color=c,fontweight="bold",va="center")

    def style(ax,title):
        ax.set_title(title,fontsize=8.5,fontweight="bold",color=NAVY,loc="left",pad=6)
        ax.spines[["top","right"]].set_visible(False)
        ax.grid(axis="y",color="#EEF1F6",lw=.8); ax.tick_params(length=0,labelsize=7)
        ax.set_axisbelow(True)

    # ---- chart 1: ingresos ----
    ax1=fig.add_subplot(gs[1,0:2])
    bars=ax1.bar(labels,rev,color=ACC,width=0.62,zorder=3); bars[k].set_color(NAVY)
    style(ax1,"Evolución de ingresos mensuales"); ax1.set_ylim(0,max(rev)*1.20)
    if k<2: ax1.set_xlim(-1.5,1.5)
    ax1.text(k,rev[k]+max(rev)*0.03,_fmt(rev[k]),ha="center",fontsize=6.8,
        color=NAVY,fontweight="bold")

    # ---- chart 2: márgenes ----
    ax2=fig.add_subplot(gs[1,2:4])
    for ser,col,lab in [(m_gp,"#8E44AD","Bruto"),(m_eb,BLUE,"EBITDA"),
                        (m_op,GREEN,"Operacional"),(m_ni,RED,"Neto")]:
        ax2.plot(labels,ser,"-o",ms=3,lw=1.6,color=col,label=lab)
    ax2.axhline(0,color="#B0B7C3",lw=.8,ls="--"); style(ax2,"Evolución de márgenes (%)")
    ax2.set_ylim(-6,42)
    ax2.legend(loc="center right",fontsize=6.0,frameon=True,edgecolor="#D2DAE8",
        facecolor="white",framealpha=.92)
    loss=[i for i in idx if ni[i]<0]
    if loss:
        li=loss[0]
        ax2.annotate("Pérdida",xy=(li,m_ni[li]),xytext=(min(li+1.4,k+0.2),-4.5),
            fontsize=6.2,color=RED,ha="center",
            arrowprops=dict(arrowstyle="->",color=RED,lw=.9))

    # ---- chart 3: EBITDA vs NI ----
    ax3=fig.add_subplot(gs[2,0:2]); w=0.4
    ax3.bar([i-w/2 for i in idx],eb,w,color=BLUE,label="EBITDA",zorder=3)
    ax3.bar([i+w/2 for i in idx],ni,w,color="#9CB8E0",label="Utilidad neta",zorder=3)
    ax3.axhline(0,color="#9AA3B2",lw=.9); ax3.set_xticks(idx); ax3.set_xticklabels(labels)
    if k<2: ax3.set_xlim(-1.5,1.5)
    style(ax3,"EBITDA vs. Utilidad neta por mes")
    ax3.legend(loc="upper left",fontsize=6.6,frameon=False)

    # ---- chart 4: acumulada ----
    ax4=fig.add_subplot(gs[2,2])
    ax4.fill_between(labels,ni_cum,color=NAVY,alpha=0.12,zorder=2)
    ax4.plot(labels,ni_cum,"-o",ms=3,lw=1.8,color=NAVY,zorder=3)
    style(ax4,"Utilidad neta acumulada (YTD)")
    ax4.tick_params(axis="x",labelsize=5.6 if k>6 else 7)
    ax4.text(k,ni_cum[-1],f" {_fmt(ni_cum[-1])}",fontsize=7,color=NAVY,
        fontweight="bold",va="center")

    # ---- notas (de la IA) ----
    axN=fig.add_subplot(gs[2,3]); axN.axis("off")
    axN.add_patch(FancyBboxPatch((0.0,0.0),1,1,boxstyle="round,pad=0.02,rounding_size=0.04",
        fc="#F7F9FC",ec="#D2DAE8",lw=1,transform=axN.transAxes))
    axN.text(0.07,0.93,"NOTAS DEL ANÁLISIS",fontsize=7.5,fontweight="bold",color=NAVY,va="top")
    sym={"positiva":("▲",GREEN),"negativa":("▼",RED),"neutra":("•",NAVY)}
    y=0.85
    for nota in payload.get("anotaciones",[])[:5]:
        s,c=sym.get(nota.get("tipo","neutra"),("•",NAVY))
        wrapped=textwrap.fill(nota["texto"],width=38)
        nlines=wrapped.count("\n")+1
        axN.text(0.07,y,s,fontsize=8,color=c,fontweight="bold",va="top")
        axN.text(0.15,y,wrapped,fontsize=6.3,color="#2A2A2A",va="top",linespacing=1.3)
        y-=nlines*0.050+0.030

    fig.text(0.045,0.022,"Compañía sintética · Datos ficticios para pruebas de agente de IA",
        fontsize=6.3,color="#9AA3B2")
    fig.text(0.965,0.022,"Generado automáticamente · Truora Financial AI Agent",
        fontsize=6.3,color="#9AA3B2",ha="right")
    fig.savefig(out_path,facecolor=BG); plt.close(fig)
    return out_path
