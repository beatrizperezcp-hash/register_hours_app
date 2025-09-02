# app.py
# -----------------------------------------------
# ⏱️ Registro de horas Rorfeny trabajo (Streamlit)
# -----------------------------------------------
# Requiere: streamlit, sqlmodel, reportlab, psycopg2-binary (si usas Postgres)
# Archiva automáticamente el 5 de cada mes (gracia hasta el día 4 para editar mes anterior).

import os
import io
from pathlib import Path
from datetime import date, time, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from sqlmodel import Session, select

from domain import WorkShift
from repository import WorkShiftRepository, WorkShiftDB

# Limpia caché (útil tras despliegues)
st.cache_data.clear()
st.cache_resource.clear()

# =========================
# Zona horaria (Madrid)
# =========================
TZ = ZoneInfo("Europe/Madrid")
def hoy_local() -> date:
    return datetime.now(TZ).date()

# =========================
# Persistencia por entorno (con fallback local SOLO para desarrollo)
# =========================
def _pick_data_dir() -> Path:
    candidates = []
    env = os.getenv("DATA_DIR")
    if env:
        candidates.append(Path(env))
    candidates += [Path("/data"), Path.cwd() / "data"]

    for p in candidates:
        try:
            p.mkdir(parents=True, exist_ok=True)
            t = p / ".rwtest"
            t.write_text("ok")
            t.unlink(missing_ok=True)
            return p
        except Exception:
            continue
    return Path.cwd()

DATA_DIR = _pick_data_dir()
DEFAULT_SQLITE = f"sqlite:///{(DATA_DIR / 'workhours.db').as_posix()}"
DB_URL = os.getenv("DATABASE_URL", DEFAULT_SQLITE)

# Exigir Postgres en hosting (Render / HF Spaces / Streamlit Cloud)
if ("RENDER" in os.environ or "SPACE_ID" in os.environ or os.getenv("STREAMLIT_RUNTIME") == "cloud"):
    if DB_URL.startswith("sqlite"):
        st.error("Falta DATABASE_URL (Postgres). Configura la variable de entorno en el hosting.")

@st.cache_resource
def get_repo(url: str, buster: str):
    return WorkShiftRepository(url, echo=False)

repo = get_repo(DB_URL, buster=DB_URL)

# Carpeta de PDFs (si falla, cae a ./reportes_mensuales)
CARPETA_REPORTES = DATA_DIR / "reportes_mensuales"
try:
    CARPETA_REPORTES.mkdir(parents=True, exist_ok=True)
except Exception:
    CARPETA_REPORTES = Path.cwd() / "reportes_mensuales"
    CARPETA_REPORTES.mkdir(parents=True, exist_ok=True)

# =========================
# Parámetros globales
# =========================
TITULO_APP = "Registro horas Rorfeny "
UMBRAL_DIARIO_H = 6.0              # objetivo diario (descanso ya descontado)
DESCANSO_DEFECTO_MIN = 30          # minutos descanso por defecto
UMBRAL_SEMANAL_H = 30.0            # contrato: 30 h/semana
GRACIA_DIAS = 4                    # puedes editar el mes anterior hasta el día 4
AVISO_ULTIMOS_DIAS = 2             # aviso cuando queden <= 2 días de mes

# Salario (solo para PDF)
HOURLY_GROSS_EUR = 13.30
IRPF_EST_PERCENT = 0.15

# =========================
# Utilidades de formato/tiempo
# =========================
def formatea_minutos_signed(minutos: int) -> str:
    if minutos == 0:
        return "0 min"
    sign = "-" if minutos < 0 else ""
    minutos = abs(int(minutos))
    h, m = divmod(minutos, 60)
    if h == 0:
        return f"{sign}{m} min"
    if m == 0:
        return f"{sign}{h} h"
    return f"{sign}{h} h {m} min"

def formatea_minutos(minutos: int) -> str:
    minutos = max(0, int(minutos))
    h, m = divmod(minutos, 60)
    if h == 0:
        return f"{m} min"
    if m == 0:
        return f"{h} h"
    return f"{h} h {m} min"

def horas_float_a_minutos(horas: float) -> int:
    return int(round(float(horas) * 60))

def formatea_horas_float(horas: float) -> str:
    return formatea_minutos(horas_float_a_minutos(horas))

def eur(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def parse_hhmm(s: str) -> time | None:
    try:
        hh, mm = s.strip().split(":")
        return time(int(hh), int(mm))
    except Exception:
        return None

def opciones_horas(step_min: int = 5, start: str = "06:00", end: str = "00:00") -> list[str]:
    sh, sm = map(int, start.split(":"))
    opts = []
    for h in range(sh, 24):
        for m in range(0, 60, step_min):
            if h == sh and m < sm:
                continue
            opts.append(f"{h:02d}:{m:02d}")
    if end == "00:00" and (not opts or opts[-1] != "00:00"):
        opts.append("00:00")
    return opts

TIME_OPTIONS = opciones_horas(5, "06:00", "00:00")

def mes_en_letras_esp(yyyy_mm: str) -> str:
    meses = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio",
             "Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    y, m = yyyy_mm.split("-")
    return f"Mes de {meses[int(m)-1]} {y}"

def clave_mes(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"

def yyyymm_to_tuple(yyyy_mm: str) -> tuple[int, int]:
    y, m = yyyy_mm.split("-")
    return int(y), int(m)

def rango_mes(yyyy_mm: str) -> tuple[date, date]:
    y, m = map(int, yyyy_mm.split("-"))
    d1 = date(y, m, 1)
    d2 = (date(y+1, 1, 1) - timedelta(days=1)) if m == 12 else (date(y, m+1, 1) - timedelta(days=1))
    return d1, d2

# =========================
# Cálculo de horas (con fecha base en TZ Madrid)
# =========================
def calcular_horas_trabajadas(start: time, end: time, break_min: int, base_date: date | None = None) -> float:
    d = base_date or hoy_local()
    t0 = datetime.combine(d, start)
    t1 = datetime.combine(d, end)
    if t1 < t0:
        t1 += timedelta(days=1)
    total = (t1 - t0).total_seconds() / 3600.0
    total -= max(0, int(break_min)) / 60.0
    return round(max(0.0, total), 2)

def delta_diario_horas(hours_worked: float) -> float:
    return round(hours_worked - UMBRAL_DIARIO_H, 2)

# =========================
# Configuración de página + encabezado responsive
# =========================
st.set_page_config(page_title=TITULO_APP, page_icon="⏱️", layout="centered")

st.markdown("""
<style>
.app-header { 
  font-weight: 600; 
  font-size: 1.5rem; 
  line-height: 1.2; 
  margin: 0.2rem 0 0.6rem 0;
}
@media (max-width: 480px) {
  .app-header {
    font-size: 1.05rem !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    margin-bottom: 0.4rem !important;
  }
}
</style>
""", unsafe_allow_html=True)

st.markdown(f'<div class="app-header">⏱️ {TITULO_APP}</div>', unsafe_allow_html=True)
st.caption("Mes actual: añade/edita tus horas. Meses anteriores: descárgalos en PDF. L–V por defecto; fines de semana manual.")

# (Sidebar limpia)
st.sidebar.empty()

# =========================
# Helpers de estado
# =========================
def _init_add_form_defaults():
    if st.session_state.get("_reset_add_form", False):
        for k in ("inicio_nuevo_str", "fin_nuevo_str", "descanso_nuevo", "notas_nuevas"):
            st.session_state.pop(k, None)
        st.session_state["_reset_add_form"] = False

def _flash_success_if_any():
    msg = st.session_state.pop("_flash_success", None)
    if msg:
        st.success(msg)

def selectbox_state(label: str, key: str, default_value: str, options: list[str]):
    if key not in st.session_state:
        st.session_state[key] = default_value
    return st.selectbox(label, options=options, key=key)

# =========================
# BD helpers
# =========================
def existe_registro(d: date) -> bool:
    with Session(repo.engine) as s:
        return s.exec(select(WorkShiftDB).where(WorkShiftDB.work_date == d)).first() is not None

def listar_meses_con_registros() -> set[str]:
    with Session(repo.engine) as s:
        filas = s.exec(select(WorkShiftDB)).all()
    return {clave_mes(f.work_date) for f in filas}

def cargar_hist_df_de_mes(yyyy_mm: str) -> pd.DataFrame:
    d1, d2 = rango_mes(yyyy_mm)
    with Session(repo.engine) as s:
        filas = s.exec(
            select(WorkShiftDB)
            .where(WorkShiftDB.work_date >= d1, WorkShiftDB.work_date <= d2)
            .order_by(WorkShiftDB.work_date.desc(), WorkShiftDB.id.desc())
        ).all()
    vistos, dedup = set(), []
    for f in filas:
        if f.work_date in vistos:
            continue
        vistos.add(f.work_date)
        dedup.append(f)
    dias = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"]
    rows = []
    for f in dedup:
        hw = float(f.hours_worked or 0.0)
        delta_min = int(round((hw - UMBRAL_DIARIO_H) * 60))
        rows.append({
            "ID": f.id,
            "Fecha": f.work_date.isoformat(),
            "Día": dias[f.work_date.weekday()],
            "Inicio": f.start_time.strftime("%H:%M"),
            "Fin": f.end_time.strftime("%H:%M"),
            "Descanso (min)": int(f.break_minutes),
            "Horas": round(hw, 2),
            "Extras (min)": delta_min,
            "Extras": formatea_minutos_signed(delta_min),
            "Notas": f.notes or ""
        })
    return pd.DataFrame(rows)

# =========================
# PDF (bordes + caja resumen)
# =========================
def dataframe_a_pdf(df: pd.DataFrame, titulo: str, resumen_linea1: str | None = None, resumen_linea2: str | None = None) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Table as RTable
        from reportlab.platypus import TableStyle as RTableStyle
    except Exception:
        st.error("La exportación a PDF requiere 'reportlab'. Instala: pip install reportlab")
        return b""

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=24, bottomMargin=24, leftMargin=24, rightMargin=24)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(name="TitleCentered", parent=styles["Title"], alignment=TA_CENTER)
    resumen_main_style = ParagraphStyle(
        name="ResumenMain", parent=styles["Normal"], alignment=TA_CENTER,
        textColor=colors.black, fontSize=11, leading=13, spaceBefore=4, spaceAfter=2
    )
    resumen_salary_style = ParagraphStyle(
        name="ResumenSalary", parent=styles["Normal"], alignment=TA_CENTER,
        textColor=colors.black, fontSize=10, leading=12, spaceBefore=0, spaceAfter=0
    )
    story = [Paragraph(titulo, title_style), Spacer(1, 8)]
    if df.empty:
        story.append(Paragraph("Sin datos para mostrar.", styles["Normal"]))
    else:
        data = [list(df.columns)] + df.values.tolist()
        table = Table(data, repeatRows=1, hAlign="CENTER")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5F5F7")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E0E0E0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(table)
    if resumen_linea1 or resumen_linea2:
        story += [Spacer(1, 12)]
        celulas = []
        if resumen_linea1:
            celulas.append([Paragraph(resumen_linea1, resumen_main_style)])
        if resumen_linea2:
            celulas.append([Paragraph(resumen_linea2, resumen_salary_style)])
        summary_width = min(520, 0.65 * (doc.width))
        resumen_box = RTable(celulas, colWidths=[summary_width], hAlign="CENTER")
        resumen_box.setStyle(RTableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C7CCD6")),
            ("INNERPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(resumen_box)

    def draw_page_border(canvas, doc_obj):
        canvas.saveState()
        w, h = doc_obj.pagesize
        canvas.setStrokeColor(colors.HexColor("#C7CCD6"))
        canvas.setLineWidth(0.8)
        margin = 12
        canvas.rect(margin, margin, w - 2*margin, h - 2*margin)
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_page_border, onLaterPages=draw_page_border)
    return buf.getvalue()

def construir_df_para_pdf_mes(yyyy_mm: str) -> tuple[pd.DataFrame, float, int]:
    df_num = cargar_hist_df_de_mes(yyyy_mm)
    if df_num.empty:
        return df_num, 0.0, 0
    df_tbl = df_num[["Fecha","Día","Inicio","Fin","Descanso (min)","Horas","Extras","Notas"]].copy()
    df_tbl["Horas (h:min)"] = df_tbl["Horas"].apply(formatea_horas_float)
    df_tbl = df_tbl.drop(columns=["Horas"]).rename(columns={"Horas (h:min)": "Horas"})
    horas_mes = float(df_num["Horas"].sum())
    extras_mes_min = int(df_num["Extras (min)"].sum())
    return df_tbl, horas_mes, extras_mes_min

def generar_pdf_mes(yyyy_mm: str) -> bytes:
    df_tbl, horas_mes, extras_mes_min = construir_df_para_pdf_mes(yyyy_mm)
    titulo_pdf = f"{TITULO_APP} — {mes_en_letras_esp(yyyy_mm)}"
    bruto_mes = horas_mes * HOURLY_GROSS_EUR
    neto_mes = bruto_mes * (1 - IRPF_EST_PERCENT)
    l1 = f"Horas extras acumuladas del mes: {formatea_minutos_signed(extras_mes_min)}"
    l2 = f"Total bruto del mes: {eur(bruto_mes)} € · Total neto estimado: {eur(neto_mes)} €"
    return dataframe_a_pdf(df_tbl, titulo=titulo_pdf, resumen_linea1=l1, resumen_linea2=l2)

# =========================
# Avisos y archivado automático
# =========================
hoy = hoy_local()
mes_actual = clave_mes(hoy)
prev_day = (date(hoy.year, hoy.month, 1) - timedelta(days=1))
mes_anterior = clave_mes(prev_day)
last_day_curr = (date(hoy.year+1, 1, 1) - timedelta(days=1)) if hoy.month == 12 else (date(hoy, hoy.month+1, 1) - timedelta(days=1))
dias_restantes = (last_day_curr - hoy).days

if dias_restantes <= AVISO_ULTIMOS_DIAS and dias_restantes >= 0:
    st.info(f"Este mes se **archivará automáticamente el día {GRACIA_DIAS+1} del próximo mes**. Aún puedes editar hasta final de mes.", icon="ℹ️")
if 1 <= hoy.day <= GRACIA_DIAS:
    st.warning(f"⏳ Puedes **editar el mes anterior** ({mes_en_letras_esp(mes_anterior)}) hasta el día {GRACIA_DIAS}.", icon="⏰")

def auto_archivar_mes_anterior():
    if hoy.day >= GRACIA_DIAS + 1:  # día 5
        df_prev = cargar_hist_df_de_mes(mes_anterior)
        if df_prev.empty:
            return
        destino = CARPETA_REPORTES / f"reporte_{mes_anterior}.pdf"
        pdf_bytes = generar_pdf_mes(mes_anterior)
        try:
            with open(destino, "wb") as fh:
                fh.write(pdf_bytes)
        except Exception:
            st.warning("No se pudo guardar el PDF en disco (sin permisos). Puedes descargarlo desde “PDF del mes mostrado”.")

auto_archivar_mes_anterior()

# =========================
# ➕ Añadir registro (fecha elegible)
# =========================
st.subheader("➕ Añadir registro")
st.caption("Añade un registro para la fecha que elijas (por defecto: hoy).")

def _init_add_form_defaults_wrapper():
    _flash_success_if_any()
    _init_add_form_defaults()
_init_add_form_defaults_wrapper()

fecha_nv = st.date_input("Fecha", value=hoy, max_value=hoy)
selectbox_state("Inicio", "inicio_nuevo_str", "08:00", TIME_OPTIONS)
selectbox_state("Fin",    "fin_nuevo_str",    "14:30", TIME_OPTIONS)
st.number_input("Descanso (min)", min_value=0, step=5, key="descanso_nuevo", value=DESCANSO_DEFECTO_MIN)
st.text_input("Notas (opcional)", placeholder="", key="notas_nuevas")

if st.button("Guardar registro", use_container_width=True):
    inicio_nuevo = parse_hhmm(st.session_state.get("inicio_nuevo_str", "08:00"))
    fin_nuevo    = parse_hhmm(st.session_state.get("fin_nuevo_str", "14:30"))
    descanso_nv  = int(st.session_state.get("descanso_nuevo", DESCANSO_DEFECTO_MIN))
    notas_nv     = st.session_state.get("notas_nuevas", "")

    if not inicio_nuevo or not fin_nuevo:
        st.warning("Selecciona horas válidas.")
    elif existe_registro(fecha_nv):
        st.warning("Ese día ya está registrado.")
    else:
        hw = calcular_horas_trabajadas(inicio_nuevo, fin_nuevo, descanso_nv, base_date=fecha_nv)
        delta = delta_diario_horas(hw)
        repo.add(WorkShift(
            work_date=fecha_nv,
            start_time=inicio_nuevo, end_time=fin_nuevo, break_minutes=descanso_nv,
            hours_worked=hw, overtime_hours=delta, notes=(notas_nv.strip() or None)
        ))
        st.session_state["_reset_add_form"] = True
        st.session_state["_flash_success"] = (
            f"Guardado {fecha_nv.strftime('%d/%m/%Y')}: {formatea_horas_float(hw)} · Extra: {formatea_minutos_signed(int(round(delta*60)))}"
        )
        st.rerun()

# =========================
# 🗓️ Histórico — mes actual o mes anterior (hasta día 4)
# =========================
st.subheader("🗓️ Histórico")
puede_editar_anterior = (1 <= hoy.day <= GRACIA_DIAS)
opciones_hist = ["Mes actual"]
if puede_editar_anterior:
    opciones_hist.append("Mes anterior (hasta día 4)")
seleccion = st.radio("Mes a editar", opciones_hist, horizontal=True, label_visibility="collapsed")
yyyy_mm_objetivo = mes_actual if seleccion == "Mes actual" else mes_anterior
permite_editar = (yyyy_mm_objetivo == mes_actual) or (yyyy_mm_objetivo == mes_anterior and puede_editar_anterior)

st.caption(f"{mes_en_letras_esp(yyyy_mm_objetivo)} · Edita Inicio/Fin (HH:MM). Guardado automático.")

df_hist = cargar_hist_df_de_mes(yyyy_mm_objetivo)
if df_hist.empty:
    st.info("Sin registros en este mes.")
else:
    def _clamp(hhmm: str) -> str:
        if hhmm in TIME_OPTIONS:
            return hhmm
        try:
            h, m = map(int, hhmm.split(":"))
            if h < 6: return "06:00"
            if h > 23 or (h == 23 and m > 55): return "00:00"
            m = (m // 5) * 5
            c = f"{h:02d}:{m:02d}"
            return c if c in TIME_OPTIONS else "06:00"
        except:
            return "06:00"

    df_hist["Inicio"] = df_hist["Inicio"].apply(_clamp)
    df_hist["Fin"]    = df_hist["Fin"].apply(_clamp)

    cols_show = ["Fecha","Día","Inicio","Fin","Descanso (min)","Horas","Extras"]
    col_cfg = {
        "Fecha": st.column_config.TextColumn(disabled=True),
        "Día": st.column_config.TextColumn(disabled=True),
        "Inicio": st.column_config.SelectboxColumn(options=TIME_OPTIONS, help="Hora de inicio (HH:MM)", disabled=not permite_editar),
        "Fin": st.column_config.SelectboxColumn(options=TIME_OPTIONS, help="Hora de fin (HH:MM)", disabled=not permite_editar),
        "Descanso (min)": st.column_config.NumberColumn(disabled=True),
        "Horas": st.column_config.NumberColumn(disabled=True, format="%.2f"),
        "Extras": st.column_config.TextColumn(disabled=True),
        "Notas": st.column_config.TextColumn(disabled=True),
    }

    df_display = df_hist[cols_show].copy()
    df_editado = st.data_editor(
        df_display,
        column_config=col_cfg,
        use_container_width=True,
        num_rows="fixed",
        key=f"editor_hist_{yyyy_mm_objetivo}"
    )

    if permite_editar:
        base_json = df_display[["Inicio","Fin"]].to_json()
        key_sig = f"last_saved_editor_signature_{yyyy_mm_objetivo}"
        if key_sig not in st.session_state:
            st.session_state[key_sig] = base_json
        current_json = df_editado[["Inicio","Fin"]].to_json()

        if current_json != st.session_state[key_sig]:
            cambios = 0
            with Session(repo.engine) as s:
                for idx, row in df_editado.iterrows():
                    orig = df_display.loc[idx]
                    if (row["Inicio"] != orig["Inicio"]) or (row["Fin"] != orig["Fin"]):
                        t_ini = parse_hhmm(row["Inicio"]); t_fin = parse_hhmm(row["Fin"])
                        if not t_ini or not t_fin:
                            st.warning(f"Fila {idx+1}: hora inválida.")
                            continue
                        fila_id = int(df_hist.loc[idx, "ID"])
                        fila = s.get(WorkShiftDB, fila_id)
                        if not fila:
                            continue
                        hw = calcular_horas_trabajadas(t_ini, t_fin, fila.break_minutes, base_date=fila.work_date)
                        delta = delta_diario_horas(hw)
                        fila.start_time = t_ini
                        fila.end_time = t_fin
                        fila.hours_worked = hw
                        fila.overtime_hours = delta
                        s.add(fila); cambios += 1
                if cambios:
                    s.commit()
            st.session_state[key_sig] = current_json
            if cambios:
                st.toast("Guardado automático aplicado.", icon="✅")
                st.rerun()

# =========================
# 📅 Resumen semanal (del mes mostrado)
# =========================
st.subheader("📅 Resumen semanal")
if not df_hist.empty:
    d1, d2 = rango_mes(yyyy_mm_objetivo)
    with Session(repo.engine) as s:
        filas = s.exec(select(WorkShiftDB).where(WorkShiftDB.work_date >= d1, WorkShiftDB.work_date <= d2)).all()
    from collections import defaultdict
    tot_sem_h = defaultdict(float)
    extras_semana_min = defaultdict(int)
    extras_sobre30_min = defaultdict(int)
    for f in filas:
        hw = float(f.hours_worked) if f.hours_worked is not None else calcular_horas_trabajadas(f.start_time, f.end_time, f.break_minutes, base_date=f.work_date)
        yy, ww, _ = f.work_date.isocalendar()
        key = (yy, ww)
        tot_sem_h[key] += float(hw)
        delta_dia_min = int(round((float(hw) - UMBRAL_DIARIO_H) * 60))
        extras_semana_min[key] += delta_dia_min
    for (yy, ww), total_h in tot_sem_h.items():
        excedente30 = int(round(max(0.0, total_h - UMBRAL_SEMANAL_H) * 60))
        if excedente30 > 0:
            extras_sobre30_min[(yy, ww)] = excedente30
    for (yy, ww) in sorted(tot_sem_h.keys(), reverse=True):
        lunes = datetime.fromisocalendar(yy, ww, 1).date()
        domingo = lunes + timedelta(days=6)
        total_h = round(tot_sem_h[(yy, ww)], 2)
        total_h_str = formatea_horas_float(total_h)
        extra_sem_str = formatea_minutos_signed(extras_semana_min.get((yy, ww), 0))
        extra30 = extras_sobre30_min.get((yy, ww), 0)
        with st.expander(f"{lunes.strftime('%d/%m/%Y')} – {domingo.strftime('%d/%m/%Y')} · {total_h_str}", expanded=False):
            st.markdown(f"- **Horas totales**: {total_h_str}")
            st.markdown(f"- **Extras acumuladas de la semana**: {extra_sem_str}")
            if extra30 > 0:
                st.markdown(f"- **Extras sobre 30 h**: {formatea_minutos_signed(extra30)}")

# =========================
# ⬇️ PDF — mes mostrado (por defecto: actual)
# =========================
st.subheader("⬇️ PDF del mes mostrado")
df_tbl, horas_mes, extras_min = construir_df_para_pdf_mes(yyyy_mm_objetivo)
titulo_pdf = f"{TITULO_APP} — {mes_en_letras_esp(yyyy_mm_objetivo)}"
bruto_mes = horas_mes * HOURLY_GROSS_EUR
neto_mes = bruto_mes * (1 - IRPF_EST_PERCENT)
l1 = f"Horas extras acumuladas del mes: {formatea_minutos_signed(extras_min)}"
l2 = f"Total bruto del mes: {eur(bruto_mes)} € · Total neto estimado: {eur(neto_mes)} €"
pdf_bytes = dataframe_a_pdf(df_tbl, titulo=titulo_pdf, resumen_linea1=l1, resumen_linea2=l2)
st.download_button(
    "Descargar PDF del mes mostrado",
    data=pdf_bytes,
    file_name=f"reporte_{yyyy_mm_objetivo}.pdf",
    mime="application/pdf",
    disabled=(len(pdf_bytes) == 0),
    use_container_width=True,
)

# =========================
# 📁 Meses archivados (PDF)
# =========================
meses_con_datos = listar_meses_con_registros()
archivos = sorted([p for p in CARPETA_REPORTES.glob("reporte_*.pdf")], reverse=True)
archivados_filtrados = []
for p in archivos:
    yyyymm = p.stem.replace("reporte_", "")
    if yyyymm_to_tuple(yyyymm) >= yyyymm_to_tuple(mes_actual):
        continue
    if yyyymm not in meses_con_datos:
        continue
    archivados_filtrados.append((yyyymm, p))

if archivados_filtrados:
    st.markdown("**📁 Meses archivados (PDF)**")
    for yyyymm, p in archivados_filtrados:
        etiqueta = f"Descargar {mes_en_letras_esp(yyyymm)}"
        with open(p, "rb") as fh:
            st.download_button(
                label=etiqueta, data=fh.read(), file_name=p.name, mime="application/pdf",
                key=f"dl_{yyyymm}", use_container_width=True
            )
else:
    st.caption("No hay PDFs archivados todavía.")
