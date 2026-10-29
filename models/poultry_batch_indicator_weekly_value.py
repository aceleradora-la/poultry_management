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

    deviation = fields.Float(
        string='Desvío', digits=(16, 4), compute='_compute_alert_status', store=True,
        help='Distancia del Valor Real al rango Bajo-Alto, en la unidad del indicador. '
             'Negativo = por debajo de Bajo; positivo = por encima de Alto; 0 = dentro '
             'del rango o sin estándar.')
    deviation_pct = fields.Float(
        string='Desvío (%)', digits=(16, 2), compute='_compute_alert_status', store=True,
        help='Desvío como % del límite superado (Bajo o Alto). Con signo, igual que Desvío.')
    range_position = fields.Selection([
        ('below', 'Por debajo'),
        ('within', 'Dentro'),
        ('above', 'Por encima'),
        ('none', 'Sin estándar'),
    ], string='Posición', compute='_compute_alert_status', store=True, index=True)
    alert_status = fields.Selection([
        ('green', 'Verde'),
        ('yellow', 'Amarillo'),
        ('red', 'Rojo'),
        ('none', 'Sin estándar'),
    ], string='Semáforo', compute='_compute_alert_status', store=True, index=True,
        help='Verde: dentro del rango, o fuera hacia el lado marcado como Normal en el '
             'indicador. Amarillo: fuera hacia el lado de Alerta, dentro de la Tolerancia '
             'del indicador. Rojo: fuera hacia el lado de Alerta, más allá de la Tolerancia. '
             'Sin estándar: la semana no tiene rango Bajo-Alto cargado.')
    alert_level = fields.Integer(
        string='Nivel de Alerta', compute='_compute_alert_status', store=True,
        help='0 = Verde o sin estándar, 1 = Amarillo, 2 = Rojo. Numérico para sumar, '
             'contar o tomar el máximo en pivots y tableros.')

    week_date_from = fields.Date(string='Desde')
    week_date_to = fields.Date(string='Hasta')

    display_name = fields.Char(string='Nombre', compute='_compute_display_name', store=True)

    _unique_batch_indicator_week = models.Constraint(
        'UNIQUE(batch_id, indicator_id, week)',
        'Ya existe un valor semanal para este lote, este indicador y esta semana.')

    @api.depends('batch_id.name', 'indicator_id.name', 'week')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f'{record.batch_id.name} - {record.indicator_id.name} - Semana {record.week}'

    @api.depends('real_value', 'value_low', 'value_high',
                 'indicator_id.alert_below', 'indicator_id.alert_above',
                 'indicator_id.alert_tolerance_pct')
    def _compute_alert_status(self):
        for record in self:
            low = record.value_low or 0.0
            high = record.value_high or 0.0
            real = record.real_value or 0.0
            if low > high:
                low, high = high, low
            if not low and not high:
                record.update({'deviation': 0.0, 'deviation_pct': 0.0, 'range_position': 'none',
                               'alert_status': 'none', 'alert_level': 0})
                continue
            if real < low:
                position, bound, deviation = 'below', low, real - low
            elif real > high:
                position, bound, deviation = 'above', high, real - high
            else:
                record.update({'deviation': 0.0, 'deviation_pct': 0.0, 'range_position': 'within',
                               'alert_status': 'green', 'alert_level': 0})
                continue
            deviation_pct = (deviation / abs(bound) * 100.0) if bound else 0.0
            indicator = record.indicator_id
            side_rule = indicator.alert_below if position == 'below' else indicator.alert_above
            if side_rule != 'alert':
                status, level = 'green', 0
            elif bound and abs(deviation_pct) <= (indicator.alert_tolerance_pct or 0.0):
                status, level = 'yellow', 1
            else:
                status, level = 'red', 2
            record.update({'deviation': deviation, 'deviation_pct': deviation_pct,
                           'range_position': position, 'alert_status': status,
                           'alert_level': level})

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
