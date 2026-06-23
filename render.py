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
  - Banda "Lectura para comité": conclusión analítica sintetizada de las cifras.
  - Veredicto como pill de color (bbox auto-ajustado, sin distorsión).
  - KPI cards con flecha direccional y variación MoM.
  - 5 gráficas, incluida la CASCADA del Estado de Resultados (puente Ingresos→Neta).
  - Data labels en TODAS las series. La conclusión solo cita cifras visibles en el informe.
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
    """Dictamen ejecutivo sintetizado de las cifras (determinístico, sin alucinaciones).
    SOLO cita cifras que aparecen en el informe: ingresos, margen EBITDA y neto (gráfica de
    márgenes), utilidad neta y su MoM (KPI), YTD (KPI/gráfica) y el resultado financiero
    (visible en la cascada del Estado de Resultados)."""
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
    # principal freno: el resultado financiero es visible en la cascada del P&G
    rfin=f["ingresos_fin"]+f["gastos_fin"]
    if f["ebit"]>0 and f["uai"]<0:
        c+=f", con el resultado financiero (COP {_fmt(rfin)}M) como principal freno (ver cascada)"
    elif ni[k]>=0:
        c+="; la base operativa ya cubre el resultado"
    return f"{a}; {b}; {c}."

_KEY_BOLD = {"apalancamiento","operativo","operativa","compresion","expansion","perdida",
    "positiva","positivo","equilibrio","freno","deterioro","mejora","control","costos","referencia"}

def _draw_rich(fig, concl, x0, x_right, y_top, fontsize, line_h, color="#1A1A1A"):
    """Dibuja la conclusión palabra por palabra con ajuste de línea propio (no desborda)
    y pone en NEGRITA solo las palabras clave: cifras (con dígitos) y términos analíticos."""
    renderer = fig.canvas.get_renderer()
    fw = fig.bbox.width
    def _is_bold(tok):
        if any(c.isdigit() for c in tok):
            return True
        a = "".join(ch for ch in tok.lower() if ch.isalpha())
        for x,y in (("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u")):
            a = a.replace(x,y)
        return a in _KEY_BOLD
    ta=fig.text(0,0,"a a",fontsize=fontsize); wa=ta.get_window_extent(renderer).width; ta.remove()
    tb=fig.text(0,0,"aa",fontsize=fontsize);  wb=tb.get_window_extent(renderer).width; tb.remove()
    space=(wa-wb)/fw
    x=x0; y=y_top
    for word in concl.split(" "):
        if not word: continue
        fw_=("bold" if _is_bold(word) else "normal")
        t=fig.text(x,y,word,fontsize=fontsize,fontweight=fw_,va="top",ha="left",color=color)
        wfrac=t.get_window_extent(renderer).width/fw
        if x+wfrac>x_right and x>x0:
            t.remove(); x=x0; y-=line_h
            t=fig.text(x,y,word,fontsize=fontsize,fontweight=fw_,va="top",ha="left",color=color)
            wfrac=t.get_window_extent(renderer).width/fw
        x+=wfrac+space
    return y

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

    vmap={"MEJORA":("MEJORA",GREEN,"#D5F0E0"),
          "DETERIORO":("DETERIORO",RED,"#F8D7D2"),
          "LINEA_BASE":("LÍNEA BASE",NAVY,"#D5E0F2")}
    verdict_txt,vfg,vbg=vmap.get(payload.get("verdict","LINEA_BASE"),("LÍNEA BASE",NAVY,"#D5E0F2"))
    notas=payload.get("anotaciones",[])
    sym={"positiva":("▲",GREEN),"negativa":("▼",RED),"neutra":("■",NAVY)}

    fig=plt.figure(figsize=(11.69,8.27),dpi=200); fig.patch.set_facecolor(BG)
    gs=gridspec.GridSpec(4,4,figure=fig,height_ratios=[0.66,1,1,1],
        hspace=0.62,wspace=0.34,left=0.045,right=0.975,top=0.792,bottom=0.05)

    # ---- header ----
    hax=fig.add_axes([0,0.93,1,0.07]); hax.axis("off")
    hax.add_patch(FancyBboxPatch((0,0),1,1,boxstyle="square,pad=0",fc=NAVY,ec="none",
        transform=hax.transAxes))
    hax.text(0.045,0.60,payload["compania"],color="white",fontsize=15,
        fontweight="bold",va="center")
    hax.text(0.045,0.22,
        f"Reporte Financiero Mensual (FP&A)  ·  Acumulado a {payload['mes']}  ·  Cifras en COP millones",
        color="#C7D4EC",fontsize=8.5,va="center")
    # pill de veredicto (bbox de texto: se auto-ajusta y no se distorsiona)
    hax.text(0.962,0.5,verdict_txt,color=vfg,fontsize=11,fontweight="bold",
        ha="right",va="center",transform=hax.transAxes,
        bbox=dict(boxstyle="round,pad=0.5",fc=vbg,ec=vfg,lw=1.0))

    # ---- banda LECTURA PARA COMITÉ (conclusión analítica sintetizada de las cifras) ----
    tax=fig.add_axes([0.045,0.820,0.93,0.098]); tax.axis("off")
    tax.add_patch(FancyBboxPatch((0,0),1,1,boxstyle="round,pad=0,rounding_size=0.035",
        fc="#F2F5FA",ec="#D2DAE8",lw=1,transform=tax.transAxes))
    icon,icol={"MEJORA":("▲",GREEN),"DETERIORO":("▼",RED),"LINEA_BASE":("■",NAVY)}.get(
        payload.get("verdict","LINEA_BASE"),("■",NAVY))
    fig.text(0.057,0.911,"LECTURA PARA COMITÉ",fontsize=7,fontweight="bold",color=GOLD,va="top")
    fig.text(0.057,0.890,icon,fontsize=9.5,color=icol,fontweight="bold",va="top")
    concl=_conclusion(figs,rev,eb,ni,m_eb,m_ni,ni_cum,k,base)
    _draw_rich(fig,concl,x0=0.076,x_right=0.958,y_top=0.892,fontsize=7.7,line_h=0.0178)

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
        ax.add_patch(FancyBboxPatch((0.025,0.06),0.95,0.88,
            boxstyle="round,pad=0.025,rounding_size=0.07",fc=LGREY,ec="#D2DAE8",lw=1,
            transform=ax.transAxes))
        ax.text(0.11,0.83,t.upper(),fontsize=6.8,color=GREY,fontweight="bold",va="center")
        ax.text(0.11,0.55,v,fontsize=18,color=NAVY,fontweight="bold",va="center")
        ax.text(0.11,0.29,f"{a} {d}".strip(),fontsize=7.4,color=c,fontweight="bold",va="center")
        ax.text(0.11,0.13,sub,fontsize=6.3,color=GREY,va="center")

    def style(ax,title):
        ax.set_title(title,fontsize=8.2,fontweight="bold",color=NAVY,loc="left",pad=5)
        ax.spines[["top","right"]].set_visible(False)
        ax.grid(axis="y",color="#EEF1F6",lw=.8); ax.tick_params(length=0,labelsize=6.8)
        ax.set_axisbelow(True)

    lblfs = 5.2 if densa else 6.3          # tamaño de los data labels

    # ---- chart 1: ingresos (TODAS las barras etiquetadas) ----
    ax1=fig.add_subplot(gs[1,0:2])
    bars=ax1.bar(labels,rev,color=ACC,width=0.62,zorder=3); bars[k].set_color(NAVY)
    style(ax1,"Evolución de ingresos mensuales"); ax1.set_ylim(0,max(rev)*1.24)
    if k<2: ax1.set_xlim(-1.5,1.5)
    for i,v in enumerate(rev):
        ax1.text(i,v+max(rev)*0.03,_fmt(v),ha="center",fontsize=lblfs,
            color=NAVY if i==k else GREY,fontweight="bold")

    # ---- chart 2: márgenes (TODOS los puntos etiquetados; leyenda con valor actual) ----
    ax2=fig.add_subplot(gs[1,2:4])
    series=[(m_gp,PURPLE,"Bruto"),(m_eb,BLUE,"EBITDA"),(m_ni,RED,"Neto")]
    for ser,col,lab in series:
        ax2.plot(labels,ser,"-o",ms=2.8,lw=1.6,color=col,label=f"{lab} {ser[k]:.1f}%")
        for i,v in enumerate(ser):
            off=6 if v>=0 else -9
            ax2.annotate(f"{v:.1f}",(i,v),textcoords="offset points",xytext=(0,off),
                ha="center",fontsize=lblfs-0.4,color=col,fontweight="bold")
    ax2.axhline(0,color="#B0B7C3",lw=.8,ls="--"); style(ax2,"Evolución de márgenes (%)")
    ax2.set_ylim(-12,66)                               # banda vacía arriba para la leyenda
    ax2.legend(loc="upper center",ncol=3,fontsize=6.4,frameon=True,edgecolor="#D2DAE8",
        facecolor="white",framealpha=.95,columnspacing=1.1,handlelength=1.3,
        handletextpad=0.4,borderpad=0.4,bbox_to_anchor=(0.5,1.0))

    # ---- chart 3: EBITDA vs NI (cada barra etiquetada) ----
    ax3=fig.add_subplot(gs[2,0:2]); w=0.4
    ax3.bar([i-w/2 for i in idx],eb,w,color=BLUE,label="EBITDA",zorder=3)
    ax3.bar([i+w/2 for i in idx],ni,w,color="#9CB8E0",label="Utilidad neta",zorder=3)
    ax3.axhline(0,color="#9AA3B2",lw=.9); ax3.set_xticks(idx); ax3.set_xticklabels(labels)
    if k<2: ax3.set_xlim(-1.5,1.5)
    style(ax3,"EBITDA vs. Utilidad neta por mes")
    ax3.legend(loc="upper left",fontsize=6.2,frameon=False,ncol=2)
    rng=max(max(eb),max(ni,default=0))-min(0,min(ni))
    for i in idx:
        ax3.text(i-w/2,eb[i]+rng*0.02,_fmt(eb[i]),ha="center",va="bottom",
            fontsize=lblfs-0.8,color=BLUE,fontweight="bold")
        va,off=("bottom",rng*0.02) if ni[i]>=0 else ("top",-rng*0.02)
        ax3.text(i+w/2,ni[i]+off,_fmt(ni[i]),ha="center",va=va,
            fontsize=lblfs-0.8,color=(GREEN if ni[i]>=0 else RED),fontweight="bold")
    ax3.margins(y=0.20)

    # ---- chart W: CASCADA del Estado de Resultados (mes actual) ----
    # Puente Ingresos -> Utilidad neta: hace visible el resultado financiero y la estructura del P&G.
    axW=fig.add_subplot(gs[2,2:4])
    fc_=figs[k]
    op_=fc_["gastos_admin"]+fc_["gastos_ventas"]+fc_["gastos_mercadeo"]
    rf_=fc_["ingresos_fin"]+fc_["gastos_fin"]
    steps=[("Ingresos",fc_["ingresos"],"tot"),
           ("Costo\nventas",fc_["costo_ventas"],"d"),
           ("Gastos\noper.",op_,"d"),
           ("D&A",fc_["depreciacion_amortizacion"],"d"),
           ("Result.\nfin.",rf_,"d")]
    if abs(fc_.get("impuesto_renta",0))>=0.5:
        steps.append(("Impuestos",fc_["impuesto_renta"],"d"))
    steps.append(("Utilidad\nneta",fc_["utilidad_neta"],"tot"))
    xs=list(range(len(steps)))
    cum=0; levels=[]
    for i,(lab,val,kind) in enumerate(steps):
        if kind=="tot":
            col=NAVY if i==0 else (GREEN if val>=0 else RED)
            axW.bar(i,val,width=0.64,color=col,zorder=3,edgecolor="white",linewidth=0.4)
            cum=val
        else:
            col=GREEN if val>=0 else RED
            axW.bar(i,val,bottom=cum,width=0.64,color=col,zorder=3,edgecolor="white",linewidth=0.4)
            cum=cum+val
        levels.append(cum)
    for i in range(len(steps)-1):                                  # conectores punteados
        axW.plot([i+0.32,i+1-0.32],[levels[i],levels[i]],color="#9AA3B2",lw=0.7,ls=(0,(2,2)),zorder=2)
    span=fc_["ingresos"]-min(0,min(levels)); ing=fc_["ingresos"] or 1
    cum=0
    for i,(lab,val,kind) in enumerate(steps):
        if kind=="tot":
            lo,hi=min(0,val),max(0,val); cum=val; txt=_fmt(val)
            col=NAVY if i==0 else (GREEN if val>=0 else RED)
        else:
            prev=cum; cum=cum+val; lo,hi=min(prev,cum),max(prev,cum); txt=_signed(val)
            col=GREEN if val>=0 else RED
        if val>=0: y,va,dy=hi,"bottom",3
        else:      y,va,dy=lo,"top",-3
        axW.annotate(txt,(i,y),textcoords="offset points",xytext=(0,dy),
            ha="center",va=va,fontsize=lblfs-0.7,color=col,fontweight="bold")
        # % de ingresos (estructura de costos del P&G) — debajo del monto, gris
        axW.annotate(f"{val/ing*100:.0f}%",(i,y),textcoords="offset points",
            xytext=(0,dy+(9 if dy>0 else -9)),ha="center",va=va,fontsize=lblfs-1.8,color=GREY)
    axW.axhline(0,color="#9AA3B2",lw=.9)
    style(axW,"Cascada del P&G — monto y % de ingresos")
    axW.set_xticks(xs); axW.set_xticklabels([s[0] for s in steps],fontsize=5.3)
    axW.set_ylim(min(0,min(levels))-span*0.20, fc_["ingresos"]*1.24)

    # ---- chart 4: acumulada (todos los puntos etiquetados) ----
    ax4=fig.add_subplot(gs[3,0:2])
    ax4.fill_between(labels,ni_cum,color=NAVY,alpha=0.12,zorder=2)
    ax4.plot(labels,ni_cum,"-o",ms=2.8,lw=1.7,color=NAVY,zorder=3)
    ax4.axhline(0,color="#B0B7C3",lw=.8,ls="--")
    style(ax4,"Utilidad neta acumulada (YTD)")
    if k<2: ax4.set_xlim(-1.5,1.5)
    rng4=(max(ni_cum)-min(ni_cum)) or 1
    for i,v in enumerate(ni_cum):
        va,off=("bottom",1) if (i==0 or v>=ni_cum[i-1]) else ("top",-1)
        ax4.annotate(_fmt(v),(i,v),textcoords="offset points",
            xytext=(0,5 if va=="bottom" else -5),ha="center",va=va,
            fontsize=lblfs-0.4,color=NAVY,fontweight="bold")
    ax4.margins(y=0.22)

    # ---- notas de soporte (anotaciones de la IA) ----
    axN=fig.add_subplot(gs[3,2:4]); axN.axis("off")
    axN.add_patch(FancyBboxPatch((0.0,0.0),1,1,boxstyle="round,pad=0.02,rounding_size=0.04",
        fc="#F7F9FC",ec="#D2DAE8",lw=1,transform=axN.transAxes))
    axN.text(0.05,0.92,"SOPORTE DEL ANÁLISIS",fontsize=7.3,fontweight="bold",color=NAVY,va="top")
    y=0.80
    for nota in notas[:4]:
        s,c=sym.get(nota.get("tipo","neutra"),("■",NAVY))
        wrapped=textwrap.fill(nota["texto"],width=64)
        nlines=wrapped.count("\n")+1
        axN.text(0.05,y,s,fontsize=7.2,color=c,fontweight="bold",va="top")
        axN.text(0.11,y,wrapped,fontsize=6.3,color="#2A2A2A",va="top",linespacing=1.28)
        y-=nlines*0.085+0.055

    fig.text(0.045,0.018,"Compañía sintética · Datos ficticios para pruebas de agente de IA",
        fontsize=6.2,color="#9AA3B2")
    fig.text(0.965,0.018,"Generado automáticamente · Truora Financial AI Agent",
        fontsize=6.2,color="#9AA3B2",ha="right")
    fig.savefig(out_path,facecolor=BG); plt.close(fig)
    return out_path
