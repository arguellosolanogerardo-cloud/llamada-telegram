import os
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether
)


def generar_acta_pdf(
    fecha: str,
    inicio_str: str,
    fin_str: str,
    duracion_minutos: int,
    asistentes: list,
    resumen_ia: str,
    ruta_salida: str = None,
    info_catalogo: dict = None
) -> str:
    """Genera un documento PDF formal con el acta de la reunión, resumen y lista de asistentes."""
    if not ruta_salida:
        os.makedirs(os.path.join("data", "actas"), exist_ok=True)
        ruta_salida = os.path.join("data", "actas", f"acta_{fecha}.pdf")
    else:
        os.makedirs(os.path.dirname(ruta_salida), exist_ok=True)

    doc = SimpleDocTemplate(
        ruta_salida,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    # Estilos personalizados
    titulo_style = ParagraphStyle(
        "TituloActa",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1B365D"),
        alignment=1,  # Centrado
    )

    subtitulo_style = ParagraphStyle(
        "SubtituloActa",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#4A777A"),
        alignment=1,
    )

    seccion_style = ParagraphStyle(
        "SeccionHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1B365D"),
        spaceBefore=10,
        spaceAfter=4,
    )

    cuerpo_style = ParagraphStyle(
        "CuerpoTexto",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#222222"),
        spaceAfter=6,
    )

    meta_label = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#1B365D"),
    )

    meta_val = ParagraphStyle(
        "MetaVal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#333333"),
    )

    tabla_header = ParagraphStyle(
        "TablaHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
        alignment=1,
    )

    tabla_cell = ParagraphStyle(
        "TablaCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#222222"),
    )

    tabla_cell_center = ParagraphStyle(
        "TablaCellCenter",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#222222"),
        alignment=1,
    )

    story = []

    # Encabezado principal
    story.append(Paragraph("ACTA OFICIAL DE LA REUNIÓN DIARIA", titulo_style))
    story.append(Paragraph("Comunidad de Crecimiento Personal y Meditación", subtitulo_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1B365D"), spaceAfter=10))

    # Métricas y Datos Generales
    num_meditacion = sum(1 for a in asistentes if a.get("meditacion_completada"))
    num_hablaron = sum(1 for a in asistentes if a.get("hablo"))
    total_asistentes = len(asistentes)

    datos_meta = [
        [
            Paragraph("<b>Fecha:</b>", meta_label),
            Paragraph(fecha, meta_val),
            Paragraph("<b>Total Asistentes:</b>", meta_label),
            Paragraph(f"{total_asistentes} participantes", meta_val),
        ],
        [
            Paragraph("<b>Horario:</b>", meta_label),
            Paragraph(f"{inicio_str} - {fin_str}", meta_val),
            Paragraph("<b>Participaron en Meditación:</b>", meta_label),
            Paragraph(f"{num_meditacion} personas", meta_val),
        ],
        [
            Paragraph("<b>Duración:</b>", meta_label),
            Paragraph(f"{duracion_minutos} minutos", meta_val),
            Paragraph("<b>Intervenciones con Voz:</b>", meta_label),
            Paragraph(f"{num_hablaron} personas", meta_val),
        ],
    ]

    if info_catalogo:
        tipo_lbl = info_catalogo.get("tipo", "Meditación").capitalize()
        num = info_catalogo.get("numero", "")
        tit = info_catalogo.get("titulo", "")
        mae = info_catalogo.get("maestro", "Alaniso")
        f_orig = info_catalogo.get("fecha_original") or info_catalogo.get("fecha", "")
        datos_meta.append([
            Paragraph(f"<b>{tipo_lbl} #{num}:</b>", meta_label),
            Paragraph(f"«{tit}»", meta_val),
            Paragraph("<b>Maestro / Grabación:</b>", meta_label),
            Paragraph(f"{mae} ({f_orig})", meta_val),
        ])

    tabla_meta = Table(datos_meta, colWidths=[90, 180, 150, 120])
    tabla_meta.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])
    )
    story.append(tabla_meta)
    story.append(Spacer(1, 12))

    # Sección 1: Minuta y Resumen Ejecutivo
    story.append(Paragraph("1. MINUTA Y RESUMEN DE LA SESIÓN", seccion_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=6))

    if resumen_ia:
        parrafos_resumen = resumen_ia.strip().split("\n")
        for p in parrafos_resumen:
            p_limpio = p.strip()
            if not p_limpio:
                continue
            # Formatear negritas básicas si vienen en Markdown
            p_fmt = p_limpio.replace("**", "<b>", 1)
            while "**" in p_fmt:
                p_fmt = p_fmt.replace("**", "</b>", 1)
            if p_limpio.startswith("#"):
                p_fmt = f"<b>{p_limpio.lstrip('#').strip()}</b>"
            story.append(Paragraph(p_fmt, cuerpo_style))
    else:
        story.append(
            Paragraph(
                "La reunión se llevó a cabo con normalidad cubriendo la bienvenida, charla comunitaria, "
                f"la sesión de meditación diaria a las 8:32 PM y el espacio de compartir entre los asistentes.",
                cuerpo_style,
            )
        )

    story.append(Spacer(1, 12))

    # Sección 2: Tabla de Asistencia y Participación
    story.append(Paragraph("2. REGISTRO OFICIAL DE ASISTENCIA Y PUNTOS", seccion_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=6))

    filas_tabla = [
        [
            Paragraph("Nº", tabla_header),
            Paragraph("Nombre y Apellido", tabla_header),
            Paragraph("Usuario", tabla_header),
            Paragraph("Tiempo", tabla_header),
            Paragraph("Asist %", tabla_header),
            Paragraph("Pts Hoy", tabla_header),
            Paragraph("Meditó", tabla_header),
            Paragraph("Habló", tabla_header),
        ]
    ]

    for idx, a in enumerate(asistentes, 1):
        bg = colors.HexColor("#FFFFFF") if idx % 2 == 1 else colors.HexColor("#F8FAFC")
        usr = f"@{a['username']}" if a.get("username") else "-"
        mins = f"{a.get('minutos', 0)} min"
        pct = f"{a.get('porcentaje', 0)}%"
        pts = f"+{a.get('pts_hoy', 0)}"
        medito = "Sí" if a.get("meditacion_completada") else "No"
        hablo = "Sí" if a.get("hablo") else "No"

        filas_tabla.append([
            Paragraph(str(idx), tabla_cell_center),
            Paragraph(a.get("nombre", "Usuario"), tabla_cell),
            Paragraph(usr, tabla_cell),
            Paragraph(mins, tabla_cell_center),
            Paragraph(pct, tabla_cell_center),
            Paragraph(pts, tabla_cell_center),
            Paragraph(medito, tabla_cell_center),
            Paragraph(hablo, tabla_cell_center),
        ])

    tabla_asistencia = Table(
        filas_tabla,
        colWidths=[24, 170, 95, 55, 50, 50, 48, 48]
    )

    t_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B365D")),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]

    # Aplicar alternancia de colores
    for i in range(1, len(filas_tabla)):
        bg_col = colors.HexColor("#FFFFFF") if i % 2 == 1 else colors.HexColor("#F8FAFC")
        t_style.append(("BACKGROUND", (0, i), (-1, i), bg_col))

    tabla_asistencia.setStyle(TableStyle(t_style))
    story.append(tabla_asistencia)

    story.append(Spacer(1, 20))

    # Pie de firma
    story.append(
        Paragraph(
            f"<i>Documento generado automáticamente por el Robot de Asistencia y Moderación | "
            f"Emisión: {datetime.now().strftime('%Y-%m-%d %I:%M %p')}</i>",
            meta_val,
        )
    )

    doc.build(story)
    print(f"Acta en PDF generada exitosamente en: {ruta_salida}")
    return ruta_salida
