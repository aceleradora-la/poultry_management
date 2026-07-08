# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError


class PoultryStandardTrackingReportWizard(models.TransientModel):
    _name = 'poultry.standard.tracking.report.wizard'
    _description = 'Reporte de Seguimiento de Estándares'

    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', required=True)
    genetics_id = fields.Many2one('poultry.genetics', string='Genética',
                                   related='batch_id.genetics_id', readonly=True)
    version_id = fields.Many2one('poultry.genetics.standard.version', string='Versión de Estándar',
                                  domain="[('genetics_id', '=', genetics_id)]",
                                  help='Vacío para usar la versión predeterminada de la genética.')
    date_from = fields.Date(string='Fecha Desde', required=True,
                             default=lambda self: fields.Date.today() - timedelta(days=90))
    date_to = fields.Date(string='Fecha Hasta', required=True, default=fields.Date.today)
    granularity = fields.Selection([
        ('day', 'Día'),
        ('week', 'Semana'),
    ], string='Granularidad', required=True, default='week')

    current_coop_names = fields.Char(string='Galpón Actual', compute='_compute_current_coop_info')
    current_coop_date_from = fields.Date(string='Fecha de Ingreso a Galpón',
                                          compute='_compute_current_coop_info')

    @api.depends('batch_id')
    def _compute_current_coop_info(self):
        for wizard in self:
            active_lines = wizard.batch_id.coop_line_ids.filtered(lambda l: l.active and not l.date_to)
            wizard.current_coop_names = ', '.join(active_lines.mapped('coop_id.name')) or False
            wizard.current_coop_date_from = min(active_lines.mapped('date_from')) if active_lines else False

    @api.onchange('batch_id')
    def _onchange_batch_id(self):
        self.version_id = self.batch_id.genetics_id.default_standard_version_id if self.batch_id else False

    def update_batch(self, batch_id):
        """Cambia el Lote de Aves de un reporte ya abierto (llamado desde el
        componente en pantalla al elegir otro lote en el selector de filtros,
        sin necesidad de cerrar y volver a abrir el asistente)."""
        self.ensure_one()
        self.batch_id = self.env['poultry.batch'].browse(batch_id)
        self.version_id = self.batch_id.genetics_id.default_standard_version_id
        return self.get_report_data()

    def _get_relevant_indicators(self, period):
        """Unión: indicadores con al menos un poultry.batch.indicator.weekly.value
        para este lote+período, O al menos un poultry.genetics.standard para esta
        genética+versión+período. Así una columna puede aparecer (con Bajo/Alto)
        aunque todavía no calculemos el valor real de esa métrica."""
        self.ensure_one()
        version = self.version_id or self.genetics_id.default_standard_version_id
        Weekly = self.env['poultry.batch.indicator.weekly.value']
        Standard = self.env['poultry.genetics.standard']
        from_weekly = Weekly.search([
            ('batch_id', '=', self.batch_id.id),
            ('period', '=', period),
        ]).mapped('indicator_id')
        from_standard = Standard.search([
            ('version_id', '=', version.id),
            ('period', '=', period),
            ('active', '=', True),
        ]).mapped('indicator_id') if version else self.env['poultry.indicator']
        return (from_weekly | from_standard).sorted('sequence')

    def get_report_data(self):
        """Arma los datos del reporte (usado tanto por el componente en pantalla
        como por la exportación a PDF/Excel), separados por Período (Crianza/
        Producción). Muestra TODAS las semanas con dato real o estándar cargado
        para cada período; date_from/date_to/granularity no se usan acá (quedan
        del diseño anterior, pendientes de limpieza)."""
        self.ensure_one()
        version = self.version_id or self.genetics_id.default_standard_version_id
        if not version:
            raise UserError(
                f'La genética {self.genetics_id.name} no tiene una Versión de Estándar '
                f'predeterminada ni se eligió una manualmente. Cree una Versión de '
                f'Estándar para esta genética, o elíjala en el campo Versión de Estándar.'
            )

        Weekly = self.env['poultry.batch.indicator.weekly.value']
        Standard = self.env['poultry.genetics.standard']
        result = {}
        for period in ('crianza', 'produccion'):
            indicators = self._get_relevant_indicators(period)
            weekly_values = Weekly.search([
                ('batch_id', '=', self.batch_id.id),
                ('period', '=', period),
            ])
            standard_weeks = Standard.search([
                ('version_id', '=', version.id),
                ('period', '=', period),
                ('active', '=', True),
            ]).mapped('week')
            weeks = sorted(set(weekly_values.mapped('week')) | set(standard_weeks))

            rows = []
            for week in weeks:
                cells = {}
                for indicator in indicators:
                    match = weekly_values.filtered(
                        lambda w, ind=indicator, wk=week: w.indicator_id == ind and w.week == wk)
                    if match:
                        value_low = match[0].value_low
                        value_high = match[0].value_high
                        real_value = match[0].real_value
                        has_standard = True
                    else:
                        standard, value_low, value_high = self._get_standard_range(version, indicator, week)
                        real_value = None
                        has_standard = bool(standard)
                    cells[indicator.id] = {
                        'value_low': value_low,
                        'value_high': value_high,
                        'real_value': real_value,
                        'has_standard': has_standard,
                        'out_of_range': has_standard and real_value is not None and (
                            real_value < value_low or real_value > value_high),
                    }
                rows.append({'week': week, 'label': f'Semana {week}', 'cells': cells})

            result[period] = {
                'indicators': [
                    {'id': indicator.id, 'name': indicator.name, 'uom': indicator.uom_id.name}
                    for indicator in indicators
                ],
                'rows': rows,
            }
        result['header'] = {
            'batch_id': self.batch_id.id,
            'batch_name': self.batch_id.name,
            'genetics_name': self.genetics_id.name,
            'version_name': version.name,
            'birth_date': str(self.batch_id.birth_date) if self.batch_id.birth_date else False,
            'coop_names': self.current_coop_names,
            'coop_date_from': str(self.current_coop_date_from) if self.current_coop_date_from else False,
            'bird_count': self.batch_id.bird_count,
        }
        return result

    def _get_standard_range(self, version, indicator, week):
        period_type = 'crianza' if week <= (self.genetics_id.rearing_end_week or 17) else 'produccion'
        standard = self.env['poultry.genetics.standard'].search([
            ('version_id', '=', version.id),
            ('indicator_id', '=', indicator.id),
            ('week', '=', week),
            ('period', '=', period_type),
            ('active', '=', True),
        ], limit=1)
        value_low = standard.value_low if standard else 0.0
        value_high = standard.value_high if standard else 0.0
        return standard, value_low, value_high

    def action_generate(self):
        """Abre el componente en pantalla (dentro de la app, no un documento
        aparte). Se valida antes de abrir para que los errores de configuración
        (sin versión de estándar, etc.) se vean como un aviso normal."""
        self.ensure_one()
        if not self.batch_id:
            raise UserError('Debe seleccionar un Lote de Aves antes de generar el reporte.')
        self.get_report_data()
        return {
            'type': 'ir.actions.client',
            'tag': 'poultry_standard_tracking_report',
            'params': {'wizard_id': self.id},
        }
