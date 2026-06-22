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

Diseño orientado a comité ejecutivo:
  - Banda "Lectura para comité" con el driver principal del mes.
  - Veredicto como pill de color (semántica verde/rojo/azul).
  - KPI cards con flecha direccional y variación MoM.
  - Data labels en TODAS las series (barras y puntos): no hay que leer ejes.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import gridspec
from matplotlib.patches import FancyBboxPatch
import textwrap

NAVY="#1F3864"; BLUE="#2E5FAC"; ACC="#4A90D9"; GREEN="#1E7A46"; RED="#C0392B"
PURPLE="#8E44AD"; GREY="#6B7280"; LGREY="#E8ECF3"; BG="#FFFFFF"; GOLD="#B8860B"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":8,
    "axes.edgecolor":"#C9D2E0","axes.linewidth":.8,
    "xtick.color":GREY,"ytick.color":GREY,"text.color":"#1A1A1A"})

def _fmt(v): return f"{v:,.0f}".replace(",", ".")
def _signed(v): return ("+" if v >= 0 else "") + f"{v:,.0f}".replace(",", ".")

def _conclusion(figs, rev, eb, ni, m_eb, m_ni, ni_cum, k, base):
    """Dictamen ejecutivo sintetizado de las cifras (determinístico, sin alucinaciones):
    cruza ingresos + dinámica de margen + rentabilidad + trayectoria YTD + principal freno."""
    f = figs[k]
    if base:
        return (f"Mes base: ingresos COP {_fmt(rev[k])}M, EBITDA COP {_fmt(eb[k])}M "
                f"(margen {m_eb[k]:.1f}%) y utilidad neta COP {_fmt(ni[k])}M (margen {m_ni[k]:.1f}%). "
                f"Fija la referencia para la trayectoria; las comparaciones MoM aplican desde el próximo período.")
    rmom=(rev[k]/rev[k-1]-1)*100; epp=m_eb[k]-m_eb[k-1]; nid=ni[k]-ni[k-1]; ytd=ni_cum[-1]
    rdir="Ingresos al alza" if rmom>=0 else "Ingresos a la baja"
    if rmom>=0 and epp>=0:
        a=(f"{rdir} ({rmom:+.1f}% MoM a COP {_fmt(rev[k])}M) y margen EBITDA en expansión "
           f"({epp:+.1f}pp a {m_eb[k]:.1f}%) confirman apalancamiento operativo")
    elif rmom>=0 and epp<0:
        a=(f"{rdir} ({rmom:+.1f}% MoM a COP {_fmt(rev[k])}M) pero con margen EBITDA en compresión "
           f"({epp:+.1f}pp a {m_eb[k]:.1f}%): el volumen no se traduce en rentabilidad")
    elif rmom<0 and epp>=0:
        a=(f"{rdir} ({rmom:+.1f}% MoM a COP {_fmt(rev[k])}M), atenuados por un margen EBITDA en mejora "
           f"({epp:+.1f}pp a {m_eb[k]:.1f}%) vía control de costos")
    else:
        a=(f"{rdir} ({rmom:+.1f}% MoM a COP {_fmt(rev[k])}M) y margen EBITDA en deterioro "
           f"({epp:+.1f}pp a {m_eb[k]:.1f}%) presionan el resultado")
    ndir="mejora" if nid>=0 else "se reduce"
    if ni[k]>=0 and ni[k-1]<0: nst="y se vuelve positiva"
    elif ni[k]>=0:             nst="y se mantiene positiva"
    else:                      nst="aunque sigue en pérdida"
    b=f"la utilidad neta {ndir} COP {_fmt(abs(nid))}M {nst} (COP {_fmt(ni[k])}M, margen {m_ni[k]:.1f}%)"
    c=(f"el acumulado YTD ya es positivo (COP {_fmt(ytd)}M)" if ytd>=0
       else f"el acumulado YTD sigue negativo (COP {_fmt(ytd)}M)")
    nfin=f["ingresos_fin"]+f["gastos_fin"]
    if f["ebit"]>0 and f["uai"]<0:
        c+=f", con la carga financiera neta (COP {_fmt(nfin)}M) como principal freno"
    elif ni[k]>=0:
        c+="; la base operativa ya cubre el resultado"
    return f"{a}; {b}; {c}."

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
    densa = k > 6                          # serie larga -> fuentes/labels más compactos

    # veredicto -> (texto, color de texto, color de fondo del pill)
    vmap={"MEJORA":("MEJORA",GREEN,"#D5F0E0"),
          "DETERIORO":("DETERIORO",RED,"#F8D7D2"),
          "LINEA_BASE":("LÍNEA BASE",NAVY,"#D5E0F2")}
    verdict_txt,vfg,vbg=vmap.get(payload.get("verdict","LINEA_BASE"),("LÍNEA BASE",NAVY,"#D5E0F2"))
    notas=payload.get("anotaciones",[])
    sym={"positiva":("▲",GREEN),"negativa":("▼",RED),"neutra":("■",NAVY)}

    fig=plt.figure(figsize=(11.69,8.27),dpi=200); fig.patch.set_facecolor(BG)
    gs=gridspec.GridSpec(3,4,figure=fig,height_ratios=[0.60,1.22,1.22],
        hspace=0.55,wspace=0.34,left=0.045,right=0.975,top=0.79,bottom=0.065)

    # ---- header ----
    hax=fig.add_axes([0,0.93,1,0.07]); hax.axis("off")
    hax.add_patch(FancyBboxPatch((0,0),1,1,boxstyle="square,pad=0",fc=NAVY,ec="none",
        transform=hax.transAxes))
    hax.text(0.045,0.60,payload["compania"],color="white",fontsize=15,
        fontweight="bold",va="center")
    hax.text(0.045,0.22,
        f"Reporte Financiero Mensual (FP&A)  ·  Acumulado a {payload['mes']}  ·  Cifras en COP millones",
        color="#C7D4EC",fontsize=8.5,va="center")
    # pill de veredicto
    hax.add_patch(FancyBboxPatch((0.828,0.30),0.137,0.40,
        boxstyle="round,pad=0.01,rounding_size=0.9",fc=vbg,ec="none",transform=hax.transAxes))
    hax.text(0.8965,0.50,verdict_txt,color=vfg,fontsize=10.5,fontweight="bold",
        ha="center",va="center")

    # ---- banda LECTURA PARA COMITÉ (conclusión analítica sintetizada de las cifras) ----
    tax=fig.add_axes([0.045,0.835,0.93,0.082]); tax.axis("off")
    tax.add_patch(FancyBboxPatch((0,0),1,1,boxstyle="round,pad=0,rounding_size=0.04",
        fc="#F2F5FA",ec="#D2DAE8",lw=1,transform=tax.transAxes))
    tax.text(0.013,0.87,"LECTURA PARA COMITÉ",fontsize=7,fontweight="bold",color=GOLD,va="top")
    icon,icol={"MEJORA":("▲",GREEN),"DETERIORO":("▼",RED),"LINEA_BASE":("■",NAVY)}.get(
        payload.get("verdict","LINEA_BASE"),("■",NAVY))
    concl=_conclusion(figs,rev,eb,ni,m_eb,m_ni,ni_cum,k,base)
    wrapped=textwrap.fill(concl,width=116)
    tax.text(0.013,0.58,icon,fontsize=10,color=icol,fontweight="bold",va="top")
    tax.text(0.035,0.61,wrapped,fontsize=8.1,color="#1A1A1A",va="top",fontweight="bold",linespacing=1.34)

    # ---- KPIs con flecha direccional + MoM ----
    if base:
        d_rev=d_eb=d_ni="Mes base"; cR=cE=cN=GREY; aR=aE=aN=""
    else:
        rp=(rev[k]/rev[k-1]-1)*100; ep=(eb[k]/eb[k-1]-1)*100; nd=ni[k]-ni[k-1]
        d_rev=f"{rp:+.1f}% MoM"; d_eb=f"{ep:+.1f}% MoM"; d_ni=f"{_signed(nd)} MoM"
        cR=GREEN if rp>=0 else RED; cE=GREEN if ep>=0 else RED; cN=GREEN if nd>=0 else RED
        aR="▲" if rp>=0 else "▼"; aE="▲" if ep>=0 else "▼"; aN="▲" if nd>=0 else "▼"
    avg=sum(ni)/sum(rev)*100
    kpis=[("Ingresos del mes",_fmt(rev[k]),aR,d_rev,cR,f"Margen bruto {m_gp[k]:.1f}%"),
          ("EBITDA del mes",_fmt(eb[k]),aE,d_eb,cE,f"Margen EBITDA {m_eb[k]:.1f}%"),
          ("Utilidad neta del mes",_fmt(ni[k]),aN,d_ni,cN,f"Margen neto {m_ni[k]:.1f}%"),
          ("Utilidad neta YTD",_fmt(ni_cum[-1]),"","Acumulado del año",NAVY,f"Margen prom. {avg:.1f}%")]
    for i,(t,v,a,d,c,sub) in enumerate(kpis):
        ax=fig.add_subplot(gs[0,i]); ax.axis("off")
        ax.add_patch(FancyBboxPatch((0.02,0.05),0.96,0.9,
            boxstyle="round,pad=0.02,rounding_size=0.06",fc=LGREY,ec="#D2DAE8",lw=1,
            transform=ax.transAxes))
        ax.text(0.08,0.80,t.upper(),fontsize=6.8,color=GREY,fontweight="bold",va="center")
        ax.text(0.08,0.50,v,fontsize=17,color=NAVY,fontweight="bold",va="center")
        ax.text(0.08,0.24,f"{a} {d}".strip(),fontsize=7.4,color=c,fontweight="bold",va="center")
        ax.text(0.08,0.10,sub,fontsize=6.3,color=GREY,va="center")

    def style(ax,title):
        ax.set_title(title,fontsize=8.5,fontweight="bold",color=NAVY,loc="left",pad=6)
        ax.spines[["top","right"]].set_visible(False)
        ax.grid(axis="y",color="#EEF1F6",lw=.8); ax.tick_params(length=0,labelsize=7)
        ax.set_axisbelow(True)

    lblfs = 5.2 if densa else 6.4          # tamaño de los data labels

    # ---- chart 1: ingresos (TODAS las barras etiquetadas) ----
    ax1=fig.add_subplot(gs[1,0:2])
    bars=ax1.bar(labels,rev,color=ACC,width=0.62,zorder=3); bars[k].set_color(NAVY)
    style(ax1,"Evolución de ingresos mensuales"); ax1.set_ylim(0,max(rev)*1.22)
    if k<2: ax1.set_xlim(-1.5,1.5)
    for i,v in enumerate(rev):
        ax1.text(i,v+max(rev)*0.025,_fmt(v),ha="center",fontsize=lblfs,
            color=NAVY if i==k else GREY,fontweight="bold")

    # ---- chart 2: márgenes (TODOS los puntos etiquetados; leyenda con valor actual) ----
    ax2=fig.add_subplot(gs[1,2:4])
    series=[(m_gp,PURPLE,"Bruto"),(m_eb,BLUE,"EBITDA"),(m_op,GREEN,"Operacional"),(m_ni,RED,"Neto")]
    for ser,col,lab in series:
        ax2.plot(labels,ser,"-o",ms=3,lw=1.6,color=col,label=f"{lab} · {ser[k]:.1f}%")
        for i,v in enumerate(ser):
            off=6 if v>=0 else -9
            ax2.annotate(f"{v:.1f}",(i,v),textcoords="offset points",xytext=(0,off),
                ha="center",fontsize=lblfs-0.6,color=col,fontweight="bold")
    ax2.axhline(0,color="#B0B7C3",lw=.8,ls="--"); style(ax2,"Evolución de márgenes (%)")
    ax2.set_ylim(-10,50)
    ax2.legend(loc="upper center",ncol=4,fontsize=6.0,frameon=True,edgecolor="#D2DAE8",
        facecolor="white",framealpha=.95,columnspacing=1.0,handlelength=1.3,
        handletextpad=0.4,borderpad=0.4,bbox_to_anchor=(0.5,1.02))

    # ---- chart 3: EBITDA vs NI (cada barra etiquetada) ----
    ax3=fig.add_subplot(gs[2,0:2]); w=0.4
    b_eb=ax3.bar([i-w/2 for i in idx],eb,w,color=BLUE,label="EBITDA",zorder=3)
    b_ni=ax3.bar([i+w/2 for i in idx],ni,w,color="#9CB8E0",label="Utilidad neta",zorder=3)
    ax3.axhline(0,color="#9AA3B2",lw=.9); ax3.set_xticks(idx); ax3.set_xticklabels(labels)
    if k<2: ax3.set_xlim(-1.5,1.5)
    style(ax3,"EBITDA vs. Utilidad neta por mes")
    ax3.legend(loc="upper left",fontsize=6.6,frameon=False,ncol=2)
    rng=max(max(eb),max(ni,default=0))-min(0,min(ni))
    for i in idx:
        ax3.text(i-w/2,eb[i]+rng*0.02,_fmt(eb[i]),ha="center",va="bottom",
            fontsize=lblfs-0.6,color=BLUE,fontweight="bold")
        va,off=("bottom",rng*0.02) if ni[i]>=0 else ("top",-rng*0.02)
        ax3.text(i+w/2,ni[i]+off,_fmt(ni[i]),ha="center",va=va,
            fontsize=lblfs-0.6,color=(GREEN if ni[i]>=0 else RED),fontweight="bold")
    ax3.margins(y=0.18)

    # ---- chart 4: acumulada (todos los puntos etiquetados) ----
    ax4=fig.add_subplot(gs[2,2])
    ax4.fill_between(labels,ni_cum,color=NAVY,alpha=0.12,zorder=2)
    ax4.plot(labels,ni_cum,"-o",ms=3,lw=1.8,color=NAVY,zorder=3)
    style(ax4,"Utilidad neta acumulada (YTD)")
    ax4.tick_params(axis="x",labelsize=5.6 if densa else 7)
    rng4=(max(ni_cum)-min(ni_cum)) or 1
    for i,v in enumerate(ni_cum):
        va,off=("bottom",rng4*0.05) if (i==0 or v>=ni_cum[i-1]) else ("top",-rng4*0.05)
        ax4.annotate(_fmt(v),(i,v),textcoords="offset points",
            xytext=(0,5 if va=="bottom" else -5),ha="center",va=va,
            fontsize=lblfs-0.4,color=NAVY,fontweight="bold")
    ax4.margins(y=0.20)

    # ---- notas de soporte (anotaciones 2..5) ----
    axN=fig.add_subplot(gs[2,3]); axN.axis("off")
    axN.add_patch(FancyBboxPatch((0.0,0.0),1,1,boxstyle="round,pad=0.02,rounding_size=0.04",
        fc="#F7F9FC",ec="#D2DAE8",lw=1,transform=axN.transAxes))
    axN.text(0.07,0.93,"SOPORTE DEL ANÁLISIS",fontsize=7.5,fontweight="bold",color=NAVY,va="top")
    soporte = notas
    y=0.84
    for nota in soporte[:4]:
        s,c=sym.get(nota.get("tipo","neutra"),("■",NAVY))
        wrapped=textwrap.fill(nota["texto"],width=38)
        nlines=wrapped.count("\n")+1
        axN.text(0.07,y,s,fontsize=7.5,color=c,fontweight="bold",va="top")
        axN.text(0.16,y,wrapped,fontsize=6.4,color="#2A2A2A",va="top",linespacing=1.32)
        y-=nlines*0.058+0.040

    fig.text(0.045,0.022,"Compañía sintética · Datos ficticios para pruebas de agente de IA",
        fontsize=6.3,color="#9AA3B2")
    fig.text(0.965,0.022,"Generado automáticamente · Truora Financial AI Agent",
        fontsize=6.3,color="#9AA3B2",ha="right")
    fig.savefig(out_path,facecolor=BG); plt.close(fig)
    return out_path
