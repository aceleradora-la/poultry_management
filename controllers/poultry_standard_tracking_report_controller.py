# -*- coding: utf-8 -*-

import io

import xlsxwriter
from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.http import request


class PoultryStandardTrackingReportController(http.Controller):

    @http.route('/poultry/standard_tracking/xlsx/<int:wizard_id>', type='http', auth='user')
    def export_xlsx(self, wizard_id, **kwargs):
        """Exporta el Reporte de Seguimiento de Estándares a Excel, reutilizando
        get_report_data() (el mismo método que usa el componente en pantalla),
        para no duplicar la lógica de columnas/agregación en dos lugares."""
        if not request.env.user.has_group('poultry_management.poultry_user'):
            raise Forbidden()

        wizard = request.env['poultry.standard.tracking.report.wizard'].browse(wizard_id)
        if not wizard.exists():
            raise Forbidden()

        report_data = wizard.get_report_data()

        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {'in_memory': True})

        header = report_data.get('header', {})
        info_label_format = workbook.add_format({'bold': True})
        header_format = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        sub_header_format = workbook.add_format({
            'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        cell_format = workbook.add_format({'align': 'center', 'border': 1})
        real_format = workbook.add_format({'align': 'center', 'border': 1, 'bold': True})

        # Formatos de Valor Real coloreados según la configuración de cada indicador
        # (color_below/color_within/color_above). xlsxwriter exige un objeto Format por
        # combinación, así que se cachean por color para no crear uno por celda.
        real_color_formats = {}

        def get_real_format(color):
            if not color:
                return real_format
            if color not in real_color_formats:
                real_color_formats[color] = workbook.add_format({
                    'align': 'center', 'border': 1, 'bold': True, 'font_color': color,
                })
            return real_color_formats[color]

        period_sheets = (('crianza', 'Recría'), ('produccion', 'Parámetros productivos'))
        if wizard.report_period:
            # Reporte fijado a un período (menús Crianza/Producción dedicados):
            # exportar solo la hoja correspondiente.
            period_sheets = tuple(p for p in period_sheets if p[0] == wizard.report_period)
        for period, sheet_name in period_sheets:
            period_data = report_data.get(period, {'indicators': [], 'rows': []})
            sheet = workbook.add_worksheet(sheet_name)

            sheet.write(0, 0, 'Lote: %s' % (header.get('batch_name') or ''), info_label_format)
            sheet.write(1, 0, 'Genética: %s' % (header.get('genetics_name') or ''), info_label_format)
            sheet.write(2, 0, 'Versión de Estándar: %s' % (header.get('version_name') or ''), info_label_format)
            sheet.write(3, 0, 'Galpón: %s' % (header.get('coop_names') or '-'), info_label_format)
            sheet.write(4, 0, 'Fecha de Ingreso a Galpón: %s' % (header.get('coop_date_from') or '-'),
                        info_label_format)

            header_row = 6
            sheet.freeze_panes(header_row + 2, 2)

            indicators = period_data['indicators']
            sheet.merge_range(header_row, 0, header_row + 1, 0, 'Edad', header_format)
            sheet.merge_range(header_row, 1, header_row + 1, 1, 'Fecha', header_format)
            col = 2
            for indicator in indicators:
                sheet.merge_range(header_row, col, header_row, col + 2, indicator['name'], header_format)
                sheet.write(header_row + 1, col, 'Bajo', sub_header_format)
                sheet.write(header_row + 1, col + 1, 'Alto', sub_header_format)
                sheet.write(header_row + 1, col + 2, 'Real', sub_header_format)
                col += 3
            sheet.set_column(0, 1, 12)
            if indicators:
                sheet.set_column(2, col - 1, 10)

            row = header_row + 2
            for line in period_data['rows']:
                sheet.write(row, 0, line['week'], header_format)
                sheet.write(row, 1, line['date'], header_format)
                col = 2
                for indicator in indicators:
                    cell = line['cells'].get(indicator['id']) or line['cells'].get(str(indicator['id']))
                    if cell and cell.get('has_standard'):
                        sheet.write(row, col, cell['value_low'], cell_format)
                        sheet.write(row, col + 1, cell['value_high'], cell_format)
                    else:
                        sheet.write_blank(row, col, None, cell_format)
                        sheet.write_blank(row, col + 1, None, cell_format)
                    real_value = cell.get('real_value') if cell else None
                    if real_value is not None:
                        sheet.write(row, col + 2, real_value, get_real_format(cell.get('real_color')))
                    else:
                        sheet.write_blank(row, col + 2, None, real_format)
                    col += 3
                row += 1

        workbook.close()
        buffer.seek(0)

        batch_code = wizard.batch_id.code or str(wizard.batch_id.id)
        return request.make_response(
            buffer.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename="Seguimiento_Estandares_{batch_code}.xlsx"'),
            ],
        )
