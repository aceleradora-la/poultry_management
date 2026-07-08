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

        header_format = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        sub_header_format = workbook.add_format({
            'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        cell_format = workbook.add_format({'align': 'center', 'border': 1})
        real_format = workbook.add_format({'align': 'center', 'border': 1, 'bold': True})
        out_of_range_format = workbook.add_format({
            'align': 'center', 'border': 1, 'bold': True, 'font_color': 'red',
        })

        for period, sheet_name in (('crianza', 'Recría'), ('produccion', 'Parámetros productivos')):
            period_data = report_data.get(period, {'indicators': [], 'rows': []})
            sheet = workbook.add_worksheet(sheet_name)
            sheet.freeze_panes(2, 1)

            indicators = period_data['indicators']
            sheet.merge_range(0, 0, 1, 0, 'Semana', header_format)
            col = 1
            for indicator in indicators:
                sheet.merge_range(0, col, 0, col + 2, indicator['name'], header_format)
                sheet.write(1, col, 'Bajo', sub_header_format)
                sheet.write(1, col + 1, 'Alto', sub_header_format)
                sheet.write(1, col + 2, 'Real', sub_header_format)
                col += 3
            sheet.set_column(0, 0, 12)
            if indicators:
                sheet.set_column(1, col - 1, 10)

            row = 2
            for line in period_data['rows']:
                sheet.write(row, 0, line['label'], header_format)
                col = 1
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
                        fmt = out_of_range_format if cell.get('out_of_range') else real_format
                        sheet.write(row, col + 2, real_value, fmt)
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
