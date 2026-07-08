# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import models, fields, api


class PoultryBatchIndicatorValue(models.Model):
    _name = 'poultry.batch.indicator.value'
    _description = 'Valor Real de Indicador por Lote'
    _order = 'date desc'
    _rec_name = 'display_name'

    # Tipos de acumulación cuyo Valor Real es una TASA diaria independiente (se agrega
    # por semana como suma(numerador)/suma(denominador)). Cualquier otro tipo se trata
    # como acumulado/estado del lote (se muestra el último valor de la semana).
    _RATE_ACCUMULATION_TYPES = ('none', 'original_rate')

    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', required=True,
                                index=True, ondelete='cascade')
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True, index=True)
    indicator_id = fields.Many2one('poultry.indicator', string='Indicador', required=True,
                                    index=True, ondelete='restrict')
    date = fields.Date(string='Fecha', required=True, index=True)
    value = fields.Float(string='Valor Real', digits=(16, 4))
    numerator = fields.Float(string='Numerador', digits=(16, 4),
        help='Numerador crudo del día (ej. gramos de alimento o huevos de este lote ese '
             'día), ya escalado de forma que numerador/denominador sea igual a Valor Real. '
             'Permite que un rollup semanal sume numerador y denominador por separado en '
             'vez de promediar tasas diarias.')
    denominator = fields.Float(string='Denominador', digits=(16, 4),
        help='Denominador crudo del día (aves vivas de este lote ese día). No aplica a '
             'indicadores acumulados, donde Valor Real ya es el total y no una tasa.')

    production_id = fields.Many2one('mrp.production', string='Orden de Fabricación de Origen',
                                     readonly=True,
                                     help='OF de Huevo sin Clasificar que originó este cálculo')
    notes = fields.Text(string='Notas')

    display_name = fields.Char(string='Nombre', compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('unique_batch_indicator_date', 'unique(batch_id, indicator_id, date)',
         'Ya existe un valor real para este lote, este indicador y esta fecha.'),
    ]

    @api.depends('batch_id.name', 'indicator_id.name', 'date')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f'{record.batch_id.name} - {record.indicator_id.name} - {record.date}'

    @api.model
    def _set_value(self, batch, coop, target_date, indicator, value,
                    numerator=None, denominator=None, production=None):
        """Crea o actualiza (upsert) el valor real de un indicador para un lote y fecha,
        de forma que recalcular (p. ej. re-cerrar una OF, o un recálculo histórico) no
        duplique registros.

        numerator/denominator son opcionales (centinela None, no 0.0): un indicador que
        nunca los use (ej. futuros indicadores sin lógica de tasa) puede seguir llamando
        solo con value, sin pisar valores existentes con ceros."""
        existing = self.search([
            ('batch_id', '=', batch.id),
            ('indicator_id', '=', indicator.id),
            ('date', '=', target_date),
        ], limit=1)
        vals = {
            'coop_id': coop.id,
            'value': value,
            'production_id': production.id if production else False,
        }
        if numerator is not None:
            vals['numerator'] = numerator
        if denominator is not None:
            vals['denominator'] = denominator
        if existing:
            existing.write(vals)
            record = existing
        else:
            vals.update({
                'batch_id': batch.id,
                'indicator_id': indicator.id,
                'date': target_date,
            })
            record = self.create(vals)
        self._recompute_weekly_value(batch, indicator, target_date)
        return record

    def _recompute_weekly_value(self, batch, indicator, target_date):
        """Recalcula y guarda el agregado de la Semana de Vida (anclada a la Fecha de
        Nacimiento del lote) que contiene target_date, para que quede disponible como
        dato persistente y pivoteable (poultry.batch.indicator.weekly.value), en vez de
        tener que agregarse al vuelo cada vez que se quiere ver por semana."""
        birth_date = batch.birth_date
        if not birth_date or target_date < birth_date:
            return
        week = (target_date - birth_date).days // 7
        week_date_from = birth_date + timedelta(days=week * 7)
        week_date_to = week_date_from + timedelta(days=6)

        week_values = self.search([
            ('batch_id', '=', batch.id),
            ('indicator_id', '=', indicator.id),
            ('date', '>=', week_date_from),
            ('date', '<=', week_date_to),
        ])
        if not week_values:
            return

        if indicator.accumulation_type not in self._RATE_ACCUMULATION_TYPES:
            real_value = week_values.sorted('date')[-1].value
        elif indicator.category == 'mortality' and indicator.accumulation_type == 'none':
            # % Mortandad Semanal: a diferencia de las demás tasas diarias (Consumo,
            # % Ave-Día), acá el denominador NO se suma día a día (eso daría un
            # promedio ponderado por "aves-día"). Se usa una única base fija: las
            # aves vivas al inicio del primer día de la semana con dato cargado.
            # Muertas totales de la semana / vivas al inicio de la semana × 100.
            first_day_denominator = week_values.sorted('date')[0].denominator
            real_value = (sum(week_values.mapped('numerator')) / first_day_denominator
                          if first_day_denominator else 0.0)
        else:
            total_denominator = sum(week_values.mapped('denominator'))
            real_value = (sum(week_values.mapped('numerator')) / total_denominator
                          if total_denominator else 0.0)

        period = 'crianza' if week <= (batch.genetics_id.rearing_end_week or 17) else 'produccion'
        # Bajo/Alto según la Versión de Estándar predeterminada de la genética del lote,
        # para poder comparar Real vs. Bajo/Alto directamente en el pivot sin tener que
        # abrir el reporte. Si el usuario necesita comparar contra otra versión, sigue
        # pudiendo usar el Reporte de Seguimiento de Estándares (que sí permite elegirla).
        value_low, value_high = batch.genetics_id.get_standard_range(week, indicator, period=period)

        Weekly = self.env['poultry.batch.indicator.weekly.value']
        existing_weekly = Weekly.search([
            ('batch_id', '=', batch.id),
            ('indicator_id', '=', indicator.id),
            ('week', '=', week),
        ], limit=1)
        weekly_vals = {
            'period': period,
            'real_value': real_value,
            'value_low': value_low,
            'value_high': value_high,
            'week_date_from': week_date_from,
            'week_date_to': week_date_to,
        }
        if existing_weekly:
            existing_weekly.write(weekly_vals)
        else:
            weekly_vals.update({'batch_id': batch.id, 'indicator_id': indicator.id, 'week': week})
            Weekly.create(weekly_vals)
