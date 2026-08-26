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

    # Magnitudes que son un ESTADO del lote a una fecha: se pueden calcular
    # cualquier día, exista o no un Parte/OF ese día, porque salen de la población
    # del lote y no de lo que se produjo.
    _POULTRY_POPULATION_MAGNITUDES = (
        'live_birds', 'housed_birds', 'original_birds', 'housed_or_original_birds', 'one',
    )

    @api.model
    def _poultry_population_magnitude(self, key, batch, target_date):
        """Valor de una magnitud de población del lote a target_date. Mismas
        definiciones que mrp.production._poultry_collect_magnitudes, para que la
        foto del día de cierre coincida con la del día que sí tuvo OF."""
        if key == 'one':
            return 1.0
        if key == 'live_birds':
            live = batch._poultry_get_live_bird_count_on(target_date)
            return None if live is None else float(live)
        if key == 'housed_birds':
            return float(batch.housed_bird_count or 0.0)
        if key == 'original_birds':
            return float(batch.bird_count or 0.0)
        if key == 'housed_or_original_birds':
            in_production = (batch.housed_bird_count and batch.production_start_date
                             and target_date >= batch.production_start_date)
            return float(batch.housed_bird_count if in_production else (batch.bird_count or 0.0))
        return None

    @api.model
    def _poultry_snapshot_on(self, indicator, batch, reference_date):
        """Foto de un indicador 'snapshot' al DÍA DE CIERRE de la semana.

        Los valores diarios solo existen los días con OF de Huevo sin Clasificar.
        Si el día de cierre no tuvo OF, tomar "el último día con dato" devuelve el
        estado de un día anterior, mientras la columna Aves Vivas del reporte sí
        va al día de cierre: los dos números dejan de hablar de la misma fecha y,
        por ejemplo, Mortandad Acumulada + Viabilidad no suma 100.

        Como una foto es un ESTADO del lote (no algo que se produjo), se puede
        calcular en el día de cierre aunque no haya OF. Devuelve None si la fórmula
        usa alguna magnitud que sí depende de la OF: en ese caso se cae al último
        día con dato, que es lo mejor disponible."""
        if not (batch and reference_date and indicator.formula_mode == 'snapshot'):
            return None
        numerator_key = indicator.formula_numerator
        denominator_key = indicator.formula_denominator or 'one'
        if (numerator_key not in self._POULTRY_POPULATION_MAGNITUDES
                or denominator_key not in self._POULTRY_POPULATION_MAGNITUDES):
            return None
        numerator = self._poultry_population_magnitude(numerator_key, batch, reference_date)
        denominator = self._poultry_population_magnitude(denominator_key, batch, reference_date)
        if numerator is None or not denominator:
            return None
        return numerator / denominator * float(indicator.formula_factor or '1')

    @api.model
    def _poultry_aggregate_week_values(self, indicator, week_values,
                                       batch=None, reference_date=None):
        """Agrega un conjunto de valores DIARIOS de una misma semana al Valor Real
        semanal, según el tipo de acumulación del indicador. week_values puede ser
        la semana completa (agregado persistido) o un recorte (ej. el Reporte de
        Seguimiento, que excluye el día de HOY porque el día no terminó).
        Devuelve None si no hay valores."""
        if not week_values:
            return None
        # Agregación elegida en el indicador: manda sobre la automática de abajo.
        # Es lo que hace posible mostrar CANTIDADES por período (Huevos de la
        # Semana, Kg de Alimento, Aves Muertas): sin esto una cantidad diaria se
        # agregaría como suma(num)/suma(den), que con denominador 1 da el promedio
        # diario en vez del total del período.
        aggregation = indicator.weekly_aggregation or 'auto'
        if aggregation == 'sum':
            return sum(week_values.mapped('value'))
        if aggregation == 'last':
            snapshot = self._poultry_snapshot_on(indicator, batch, reference_date)
            return snapshot if snapshot is not None else week_values.sorted('date')[-1].value

        if aggregation == 'auto' and indicator.formula_mode:
            # Con fórmula cargada, la agregación automática se deriva de la FÓRMULA
            # y no de Categoría/Tipo de Acumulación: así configurar un indicador es
            # completar solo la sección Fórmula del Valor Real, sin depender de los
            # campos de arriba (que quedan para organizar y para los indicadores
            # que todavía usan el cálculo interno).
            if indicator.formula_mode in ('running_sum', 'snapshot', 'ratio_cumulative'):
                # Acumulados y estados: el valor del período es el del último día
                # con dato (nunca se suman ni promedian entre sí). Las FOTOS, además,
                # se recalculan en el día de cierre de la semana si ese día no tuvo
                # OF, para no quedar en una fecha distinta de la de Aves Vivas.
                snapshot = self._poultry_snapshot_on(indicator, batch, reference_date)
                if snapshot is not None:
                    return snapshot
                return week_values.sorted('date')[-1].value
            if indicator.formula_denominator == 'live_birds_start':
                # Tasa sobre las aves vivas al INICIO del período (ej. % de
                # Mortandad): base fija del primer día con dato, no suma de
                # denominadores (eso daría un promedio ponderado por "ave-día").
                first_day_denominator = week_values.sorted('date')[0].denominator
                return (sum(week_values.mapped('numerator')) / first_day_denominator
                        if first_day_denominator else 0.0)
            total_denominator = sum(week_values.mapped('denominator'))
            return (sum(week_values.mapped('numerator')) / total_denominator
                    if total_denominator else 0.0)

        if indicator.category == 'mortality_count':
            # Compatibilidad: las cantidades de aves muertas creadas antes del campo
            # Agregación Semanal se siguen sumando por su categoría. Los indicadores
            # nuevos deben usar Agregación Semanal = Suma del período.
            return sum(week_values.mapped('value'))
        if indicator.accumulation_type not in self._RATE_ACCUMULATION_TYPES:
            return week_values.sorted('date')[-1].value
        if indicator.category == 'mortality' and indicator.accumulation_type == 'none':
            # % Mortandad Semanal: a diferencia de las demás tasas diarias (Consumo,
            # % Ave-Día), acá el denominador NO se suma día a día (eso daría un
            # promedio ponderado por "aves-día"). Se usa una única base fija: las
            # aves vivas al inicio del primer día de la semana con dato cargado.
            # Muertas totales de la semana / vivas al inicio de la semana × 100.
            first_day_denominator = week_values.sorted('date')[0].denominator
            return (sum(week_values.mapped('numerator')) / first_day_denominator
                    if first_day_denominator else 0.0)
        total_denominator = sum(week_values.mapped('denominator'))
        return (sum(week_values.mapped('numerator')) / total_denominator
                if total_denominator else 0.0)

    def _recompute_weekly_value(self, batch, indicator, target_date):
        """Recalcula y guarda el agregado de la Semana de Vida (anclada a la Fecha
        de Nacimiento del lote, ver poultry.batch._poultry_week_anchor) que
        contiene target_date, para que quede disponible como dato persistente y
        pivoteable (poultry.batch.indicator.weekly.value), en vez de tener que
        agregarse al vuelo cada vez que se quiere ver por semana."""
        birth_date = batch.birth_date
        if not birth_date or target_date < birth_date:
            return
        week = batch._poultry_week_of(target_date)
        week_date_from = batch._poultry_week_start(week)
        week_date_to = batch._poultry_week_end(week)

        week_values = self.search([
            ('batch_id', '=', batch.id),
            ('indicator_id', '=', indicator.id),
            ('date', '>=', week_date_from),
            ('date', '<=', week_date_to),
        ])
        if not week_values:
            return

        real_value = self._poultry_aggregate_week_values(
            indicator, week_values, batch=batch,
            # Día de cierre de la semana, sin pasarse de AYER (último día
            # terminado): con la semana en curso el cierre todavía no llegó.
            # OJO: no acotar con target_date, que es el último día CON dato —
            # eso devuelve justo el día que este cambio busca evitar.
            reference_date=min(week_date_to,
                               fields.Date.context_today(self) - timedelta(days=1)))

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
        # Un valor semanal cargado a mano (Origen=Manual) tiene prioridad: representa
        # un dato histórico del pasado sin dato del sistema, y el cálculo automático
        # no debe pisarlo.
        if existing_weekly.source == 'manual':
            return
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
