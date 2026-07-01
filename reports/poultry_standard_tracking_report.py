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

    def _no_data_error(self, Value):
        """Arma el mensaje de error cuando no hay valores reales en el rango elegido,
        distinguiendo "no hay ninguno" de "hay, pero no en este rango"."""
        any_value = Value.search([('batch_id', '=', self.batch_id.id)], order='date asc', limit=1)
        if any_value:
            return UserError(
                f'El lote {self.batch_id.name} tiene valores reales calculados, pero '
                f'ninguno entre {self.date_from} y {self.date_to}. El más antiguo '
                f'disponible es del {any_value.date}. Ajuste el rango de fechas.'
            )
        return UserError(
            f'El lote {self.batch_id.name} todavía no tiene ningún valor real '
            f'calculado. Verifique que: haya al menos un Cierre de Galpón cuya Orden '
            f'de Fabricación de Huevo sin Clasificar esté marcada como Hecha (eso es '
            f'lo que dispara el cálculo), que los Indicadores (Consumo de Alimento/'
            f'Agua, % Ave-Día, etc.) ya estén creados, y que la Lista de Materiales '
            f'tenga sus líneas marcadas como Alimento/Agua. Si los Cierres son '
            f'anteriores a haber creado los Indicadores, use "Recalcular Indicadores '
            f'de Producción" (Configuración).'
        )

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
        """(Re)genera las líneas del reporte: por cada período (día o semana) y cada
        indicador con datos reales cargados para este lote, compara el estándar
        (Bajo/Alto) contra el valor real.

        Por semana lee directamente poultry.batch.indicator.weekly.value (ya agregado
        correctamente al guardar cada valor diario: suma de numerador/suma de
        denominador para tasas, último valor para acumulados — no promedio de
        promedios). Por día lee el valor diario tal cual, sin agregar nada."""
        self.ensure_one()
        Line = self.env['poultry.standard.tracking.report.line']
        self.line_ids.unlink()

        if not self.batch_id:
            raise UserError('Debe seleccionar un Lote de Aves antes de generar el reporte.')

        version = self.version_id or self.genetics_id.default_standard_version_id
        if not version:
            raise UserError(
                f'La genética {self.genetics_id.name} no tiene una Versión de Estándar '
                f'predeterminada ni se eligió una manualmente. Cree una Versión de '
                f'Estándar para esta genética, o elíjala en el campo Versión de Estándar.'
            )

        periods = self._get_periods()
        lines_vals = []

        if self.granularity == 'week':
            Weekly = self.env['poultry.batch.indicator.weekly.value']
            weekly_values = Weekly.search([
                ('batch_id', '=', self.batch_id.id),
                ('week', 'in', [period[2] for period in periods]),
            ])
            indicators = weekly_values.mapped('indicator_id')
            if not indicators:
                raise self._no_data_error(self.env['poultry.batch.indicator.value'])

            for period_start, period_end, week, label in periods:
                for indicator in indicators:
                    weekly_value = weekly_values.filtered(
                        lambda w, ind=indicator, wk=week: w.indicator_id == ind and w.week == wk
                    )
                    if not weekly_value:
                        continue
                    standard, value_low, value_high = self._get_standard_range(version, indicator, week)
                    real_value = weekly_value[0].real_value
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
                        'is_out_of_range': bool(standard) and (real_value < value_low or real_value > value_high),
                    })
        else:
            Value = self.env['poultry.batch.indicator.value']
            all_values = Value.search([
                ('batch_id', '=', self.batch_id.id),
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
            ])
            indicators = all_values.mapped('indicator_id')
            if not indicators:
                raise self._no_data_error(Value)

            for period_start, period_end, week, label in periods:
                for indicator in indicators:
                    day_value = all_values.filtered(
                        lambda v, ind=indicator, d=period_start: v.indicator_id == ind and v.date == d
                    )
                    if not day_value:
                        continue
                    standard, value_low, value_high = self._get_standard_range(version, indicator, week)
                    real_value = day_value[0].value
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
                        'is_out_of_range': bool(standard) and (real_value < value_low or real_value > value_high),
                    })

        if lines_vals:
            Line.create(lines_vals)
        return True


class PoultryStandardTrackingReportLine(models.TransientModel):
    _name = 'poultry.standard.tracking.report.line'
    _description = 'Línea de Reporte de Seguimiento de Estándares'
    _order = 'indicator_id, period_date_from'

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
