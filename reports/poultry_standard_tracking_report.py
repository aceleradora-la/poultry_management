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

    def _no_data_error(self):
        """Arma el mensaje de error cuando no hay valores reales en el rango elegido,
        distinguiendo "no hay ninguno" de "hay, pero no en este rango"."""
        Value = self.env['poultry.batch.indicator.value']
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

    def _get_report_matrix(self):
        """Arma la matriz para el reporte cruzado (semana/día en filas, un grupo de
        3 columnas -Bajo/Alto/Real- por cada indicador con datos): a diferencia de
        una lista plana, esto reproduce el formato de la guía de rendimiento del
        proveedor de genética (edad en filas, indicadores en columnas).

        Por semana lee poultry.batch.indicator.weekly.value (ya agregado
        correctamente al guardar: suma de numerador/suma de denominador para tasas,
        último valor para acumulados). Por día lee el valor diario tal cual."""
        self.ensure_one()

        version = self.version_id or self.genetics_id.default_standard_version_id
        if not version:
            raise UserError(
                f'La genética {self.genetics_id.name} no tiene una Versión de Estándar '
                f'predeterminada ni se eligió una manualmente. Cree una Versión de '
                f'Estándar para esta genética, o elíjala en el campo Versión de Estándar.'
            )

        periods = self._get_periods()

        if self.granularity == 'week':
            Weekly = self.env['poultry.batch.indicator.weekly.value']
            weekly_values = Weekly.search([
                ('batch_id', '=', self.batch_id.id),
                ('week', 'in', [period[2] for period in periods]),
            ])
            indicators = weekly_values.mapped('indicator_id').sorted('sequence')
            if not indicators:
                raise self._no_data_error()

            def get_real_value(indicator, period_start, week):
                match = weekly_values.filtered(
                    lambda w, ind=indicator, wk=week: w.indicator_id == ind and w.week == wk)
                return match[0].real_value if match else None
        else:
            Value = self.env['poultry.batch.indicator.value']
            all_values = Value.search([
                ('batch_id', '=', self.batch_id.id),
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
            ])
            indicators = all_values.mapped('indicator_id').sorted('sequence')
            if not indicators:
                raise self._no_data_error()

            def get_real_value(indicator, period_start, week):
                match = all_values.filtered(
                    lambda v, ind=indicator, d=period_start: v.indicator_id == ind and v.date == d)
                return match[0].value if match else None

        rows = []
        for period_start, period_end, week, label in periods:
            cells = []
            for indicator in indicators:
                real_value = get_real_value(indicator, period_start, week)
                standard, value_low, value_high = self._get_standard_range(version, indicator, week)
                out_of_range = bool(standard) and real_value is not None and (
                    real_value < value_low or real_value > value_high)
                cells.append({
                    'value_low': value_low,
                    'value_high': value_high,
                    'real_value': real_value,
                    'has_standard': bool(standard),
                    'out_of_range': out_of_range,
                })
            rows.append({'label': label, 'week': week, 'cells': cells})

        return {'indicators': indicators, 'rows': rows}

    def action_generate(self):
        self.ensure_one()
        if not self.batch_id:
            raise UserError('Debe seleccionar un Lote de Aves antes de generar el reporte.')
        # Valida acá (antes de abrir el reporte) para que los errores de configuración
        # se vean como un aviso normal, no como una falla al renderizar el PDF.
        self._get_report_matrix()
        return self.env.ref(
            'poultry_management.action_report_poultry_standard_tracking'
        ).report_action(self)
