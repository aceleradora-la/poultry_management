# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import models, fields, api


class PoultryBatchIndicatorWeeklyValue(models.Model):
    _name = 'poultry.batch.indicator.weekly.value'
    _description = 'Valor Real Semanal de Indicador por Lote'
    _order = 'week desc'
    _rec_name = 'display_name'

    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', required=True,
                                index=True, ondelete='cascade')
    indicator_id = fields.Many2one('poultry.indicator', string='Indicador', required=True,
                                    index=True, ondelete='restrict')
    week = fields.Integer(string='Semana de Vida', required=True, index=True)
    manual_date = fields.Date(
        string='Fecha del Dato',
        help='Fecha a la que corresponde el dato cargado a mano. El sistema calcula la '
             'Semana de Vida según la Fecha de Nacimiento del lote; no hace falta contar '
             'la semana a mano. Ej.: el sábado 15/03 murieron X aves -poné esa fecha y el '
             'sistema resuelve en qué Semana de Vida cae.')
    period = fields.Selection([
        ('crianza', 'Crianza'),
        ('produccion', 'Producción'),
    ], string='Período')
    source = fields.Selection([
        ('system', 'Sistema'),
        ('manual', 'Manual'),
    ], string='Origen', default='system', required=True, index=True,
        help='Sistema: calculado automáticamente desde los Cierres de Galpón y Partes '
             'de Registro de Peso; el recálculo lo borra y lo vuelve a crear. '
             'Manual: cargado a mano para semanas del pasado sin dato del sistema (ej. '
             'histórico anterior a que se empezara a usar Odoo). El recálculo NO lo '
             'toca, tiene prioridad sobre el cálculo automático de esa misma semana, y '
             'los indicadores acumulados del sistema empalman a partir de él.')

    real_value = fields.Float(string='Valor Real', digits=(16, 4))
    value_low = fields.Float(string='Bajo (Estándar)', digits=(16, 4),
        help='Valor Bajo del estándar de genética para este indicador y semana, según '
             'la Versión de Estándar predeterminada de la genética del lote al momento '
             'de calcular. Permite comparar Real vs. Bajo/Alto directamente en el pivot.')
    value_high = fields.Float(string='Alto (Estándar)', digits=(16, 4))

    week_date_from = fields.Date(string='Desde')
    week_date_to = fields.Date(string='Hasta')

    display_name = fields.Char(string='Nombre', compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('unique_batch_indicator_week', 'unique(batch_id, indicator_id, week)',
         'Ya existe un valor semanal para este lote, este indicador y esta semana.'),
    ]

    @api.depends('batch_id.name', 'indicator_id.name', 'week')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f'{record.batch_id.name} - {record.indicator_id.name} - Semana {record.week}'

    @api.onchange('batch_id', 'indicator_id', 'week', 'manual_date')
    def _onchange_manual_context(self):
        """Al cargar un valor semanal a mano, autocompleta la Semana de Vida a partir de
        la Fecha del Dato y la Fecha de Nacimiento del lote, y de ahí Período, Fechas de
        la semana y Bajo/Alto del estándar; así el usuario solo tipea Lote, Indicador,
        Fecha del Dato y Valor Real (no cuenta semanas a mano)."""
        for record in self:
            batch = record.batch_id
            # Fecha del Dato -> Semana de Vida (anclada a la Fecha de Nacimiento
            # del lote, ver poultry.batch._poultry_week_anchor).
            if batch and batch.birth_date and record.manual_date:
                record.week = batch._poultry_week_of(record.manual_date)
            if not (batch and record.week):
                continue
            if batch.birth_date:
                record.week_date_from = batch._poultry_week_start(record.week)
                record.week_date_to = batch._poultry_week_end(record.week)
            rearing_end = batch.genetics_id.rearing_end_week or 17
            record.period = 'crianza' if record.week <= rearing_end else 'produccion'
            if record.indicator_id and batch.genetics_id:
                low, high = batch.genetics_id.get_standard_range(
                    record.week, record.indicator_id, period=record.period)
                record.value_low = low
                record.value_high = high
