# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import models, fields, api


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

    line_ids = fields.One2many('poultry.standard.tracking.report.line', 'wizard_id',
                                string='Líneas del Reporte')

    @api.onchange('batch_id')
    def _onchange_batch_id(self):
        self.version_id = self.batch_id.genetics_id.default_standard_version_id if self.batch_id else False

    def _get_periods(self):
        """Devuelve una lista de (fecha_desde, fecha_hasta, semana_de_vida, etiqueta)
        para el rango elegido. Las semanas se anclan a la Fecha de Nacimiento del
        lote (Semana de Vida), no a la semana calendario, para alinear con cómo se
        cargan los estándares (poultry.genetics.standard.week)."""
        self.ensure_one()
        periods = []
        birth_date = self.batch_id.birth_date
        if self.granularity == 'day':
            current = self.date_from
            while current <= self.date_to:
                week = max((current - birth_date).days // 7, 0)
                periods.append((current, current, week, str(current)))
                current += timedelta(days=1)
        else:
            first_week = max((self.date_from - birth_date).days // 7, 0)
            last_week = max((self.date_to - birth_date).days // 7, 0)
            for week in range(first_week, last_week + 1):
                week_start = birth_date + timedelta(days=week * 7)
                week_end = week_start + timedelta(days=6)
                period_start = max(week_start, self.date_from)
                period_end = min(week_end, self.date_to)
                if period_start > period_end:
                    continue
                periods.append((period_start, period_end, week, f'Semana {week}'))
        return periods

    def action_generate(self):
        """(Re)genera las líneas del reporte: por cada período (día o semana) y cada
        indicador con datos reales cargados para este lote, compara el estándar
        (Bajo/Alto) contra el valor real agregado correctamente según el tipo de
        indicador (tasa: suma de numerador/suma de denominador; acumulado: último
        valor con fecha dentro del período, no una suma ni un promedio)."""
        self.ensure_one()
        Line = self.env['poultry.standard.tracking.report.line']
        self.line_ids.unlink()

        version = self.version_id or self.genetics_id.default_standard_version_id
        if not self.batch_id or not self.genetics_id or not version:
            return True

        Value = self.env['poultry.batch.indicator.value']
        all_values = Value.search([
            ('batch_id', '=', self.batch_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        indicators = all_values.mapped('indicator_id')
        if not indicators:
            return True

        periods = self._get_periods()
        lines_vals = []
        for period_start, period_end, week, label in periods:
            for indicator in indicators:
                period_values = all_values.filtered(
                    lambda v, ind=indicator, ps=period_start, pe=period_end:
                        v.indicator_id == ind and ps <= v.date <= pe
                )
                if not period_values:
                    continue

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

                if indicator.accumulation_type != 'none':
                    real_value = period_values.sorted('date')[-1].value
                else:
                    total_denominator = sum(period_values.mapped('denominator'))
                    real_value = (sum(period_values.mapped('numerator')) / total_denominator
                                  if total_denominator else 0.0)

                lines_vals.append({
                    'wizard_id': self.id,
                    'period_label': label,
                    'period_date_from': period_start,
                    'period_date_to': period_end,
                    'week': week,
                    'indicator_id': indicator.id,
                    'value_low': value_low,
                    'value_high': value_high,
                    'real_value': real_value,
                    # Solo se marca fuera de rango si HAY estándar cargado para esa
                    # semana/indicador; si no hay, no hay con qué comparar (no es una
                    # alarma real, evita falsos positivos con Bajo=Alto=0).
                    'is_out_of_range': bool(standard) and (real_value < value_low or real_value > value_high),
                })
        if lines_vals:
            Line.create(lines_vals)
        return True


class PoultryStandardTrackingReportLine(models.TransientModel):
    _name = 'poultry.standard.tracking.report.line'
    _description = 'Línea de Reporte de Seguimiento de Estándares'
    _order = 'period_date_from, indicator_id'

    wizard_id = fields.Many2one('poultry.standard.tracking.report.wizard', string='Reporte',
                                 required=True, ondelete='cascade')
    period_label = fields.Char(string='Período')
    period_date_from = fields.Date(string='Desde')
    period_date_to = fields.Date(string='Hasta')
    week = fields.Integer(string='Semana de Vida')
    indicator_id = fields.Many2one('poultry.indicator', string='Indicador')
    value_low = fields.Float(string='Bajo', digits=(16, 4))
    value_high = fields.Float(string='Alto', digits=(16, 4))
    real_value = fields.Float(string='Valor Real', digits=(16, 4))
    is_out_of_range = fields.Boolean(string='Fuera de Rango')
