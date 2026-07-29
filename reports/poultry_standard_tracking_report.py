# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError


class PoultryStandardTrackingReportWizard(models.TransientModel):
    _name = 'poultry.standard.tracking.report.wizard'
    _description = 'Reporte de Seguimiento de Estándares'

    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', required=True)
    comparison_batch_ids = fields.Many2many(
        'poultry.batch', string='Lotes a Comparar',
        help='Lotes adicionales (de la misma genética que el Lote principal) para '
             'comparar en el reporte. Con más de un lote, la fila de cada Semana de '
             'Vida muestra el promedio ponderado por aves, y se puede desplegar el '
             'detalle por lote (drilldown).')
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
    report_period = fields.Selection([
        ('crianza', 'Crianza'),
        ('produccion', 'Producción'),
    ], string='Período del Reporte',
        help='Con valor, el reporte muestra SOLO ese período (menús "Seguimiento '
             'Estándares - Crianza/Producción"). Vacío: muestra ambos períodos con '
             'pestañas (comportamiento anterior, por compatibilidad).')

    current_coop_names = fields.Char(string='Galpón Actual', compute='_compute_current_coop_info')
    current_coop_date_from = fields.Date(string='Fecha de Ingreso a Galpón',
                                          compute='_compute_current_coop_info')

    @api.model
    def default_get(self, fields_list):
        """El formulario de selección abre con el lote más nuevo y su versión
        predeterminada ya elegidos, para que el caso común sea un solo click."""
        res = super().default_get(fields_list)
        if 'batch_id' in fields_list and not res.get('batch_id'):
            batch = self.env['poultry.batch'].search(
                [('active', '=', True)], order='birth_date desc', limit=1)
            if batch:
                res['batch_id'] = batch.id
                if 'version_id' in fields_list and not res.get('version_id'):
                    res['version_id'] = batch.genetics_id.default_standard_version_id.id or False
        return res

    @api.model
    def _get_batch_coop_info(self, batch):
        """(Nombres de galpones actuales, fecha de ingreso) de un lote, para los
        encabezados del reporte (uno por lote seleccionado)."""
        active_lines = batch.coop_line_ids.filtered(lambda l: l.active and not l.date_to)
        names = ', '.join(active_lines.mapped('coop_id.name')) or False
        date_from = min(active_lines.mapped('date_from')) if active_lines else False
        return names, date_from

    @api.depends('batch_id')
    def _compute_current_coop_info(self):
        for wizard in self:
            names, date_from = self._get_batch_coop_info(wizard.batch_id)
            wizard.current_coop_names = names
            wizard.current_coop_date_from = date_from

    @api.onchange('batch_id')
    def _onchange_batch_id(self):
        self.version_id = self.batch_id.genetics_id.default_standard_version_id if self.batch_id else False
        # Los Lotes a Comparar deben ser de la misma genética que el principal
        # (y no incluirlo): al cambiar el principal se depura la selección.
        self.comparison_batch_ids = self.comparison_batch_ids.filtered(
            lambda b: b.genetics_id == self.batch_id.genetics_id and b != self.batch_id)

    def update_batch(self, batch_id):
        """Cambia el Lote de Aves de un reporte ya abierto (llamado desde el
        componente en pantalla al elegir otro lote en el selector de filtros,
        sin necesidad de cerrar y volver a abrir el asistente)."""
        self.ensure_one()
        self.batch_id = self.env['poultry.batch'].browse(batch_id)
        self.version_id = self.batch_id.genetics_id.default_standard_version_id
        return self.get_report_data()

    def update_version(self, version_id):
        """Cambia la Versión de Estándar de un reporte ya abierto (selector de
        filtros en pantalla), sin tocar el Lote."""
        self.ensure_one()
        self.version_id = self.env['poultry.genetics.standard.version'].browse(version_id) if version_id else False
        return self.get_report_data()

    def update_batches(self, batch_ids):
        """Reemplaza la selección completa de lotes del reporte (selector de tags
        en pantalla). El primero de la lista es el Lote principal (define genética
        y versión predeterminada); el resto son Lotes a Comparar."""
        self.ensure_one()
        batches = self.env['poultry.batch'].browse(batch_ids).exists()
        if not batches:
            raise UserError('Seleccione al menos un Lote de Aves.')
        primary = batches[0]
        if primary != self.batch_id:
            self.batch_id = primary
            self.version_id = primary.genetics_id.default_standard_version_id
        self.comparison_batch_ids = [(6, 0, (batches - primary).ids)]
        return self.get_report_data()

    def get_week_daily_data(self, week):
        """Detalle diario de una Semana de Vida, para el despliegue por día del
        reporte en pantalla (carga perezosa: el componente lo pide recién al
        desplegar la semana y lo cachea). Devuelve, por lote del reporte:
            { '<batch_id>': {'batch_name': str, 'has_daily': bool,
                             'days': [{'date': str, 'live_birds': int|None,
                                       'cells': {indicator_id: {'real_value': float,
                                                 'count': int  # solo mortandad diaria
                                       }}}]} }
        Solo días TERMINADOS (hoy nunca, misma regla que el resto del reporte).
        Sin comparación contra estándar: no existe estándar diario."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        Value = self.env['poultry.batch.indicator.value']
        result = {}
        for batch in self._get_report_batches():
            if not batch.birth_date:
                result[str(batch.id)] = {'batch_name': batch.name, 'has_daily': False, 'days': []}
                continue
            week_start = batch._poultry_week_start(week)
            week_end = batch._poultry_week_end(week)
            last_day = min(week_end, today - timedelta(days=1))
            values = Value.search([
                ('batch_id', '=', batch.id),
                ('date', '>=', week_start),
                ('date', '<=', last_day),
            ]) if week_start <= last_day else Value
            days = []
            day = week_start
            while day <= last_day:
                cells = {}
                for value in values.filtered(lambda v, d=day: v.date == d):
                    indicator = value.indicator_id
                    cell = {'real_value': value.value}
                    if indicator.category == 'mortality' and indicator.accumulation_type == 'none':
                        # Muertas exactas del día: el numerador guardado es
                        # muertas × 100 (ver _poultry_compute_mortality_...).
                        cell['count'] = int(round((value.numerator or 0.0) / 100.0))
                    cells[indicator.id] = cell
                days.append({
                    'date': str(day),
                    'live_birds': batch._poultry_get_live_bird_count_on(day),
                    'cells': cells,
                })
                day += timedelta(days=1)
            result[str(batch.id)] = {
                'batch_name': batch.name,
                'has_daily': bool(values),
                'days': days,
            }
        return result

    def _get_report_batches(self):
        """Lote principal + Lotes a Comparar, descartando comparaciones de otra
        genética (no habría un estándar común contra el cual pintarlas)."""
        self.ensure_one()
        comparison = self.comparison_batch_ids.filtered(
            lambda b: b.genetics_id == self.batch_id.genetics_id and b != self.batch_id)
        return self.batch_id | comparison

    def _get_real_color(self, indicator, real_value, value_low, value_high, has_standard):
        """Color configurado en el indicador según dónde cae el Valor Real
        respecto del rango (debajo/dentro/encima). False = color normal."""
        if not has_standard or real_value is None:
            return False
        if real_value < value_low:
            return indicator.color_below or False
        if real_value > value_high:
            return indicator.color_above or False
        return indicator.color_within or False

    def _get_relevant_indicators(self, period):
        """Unión: indicadores con al menos un poultry.batch.indicator.weekly.value
        para este lote+período, O al menos un poultry.genetics.standard para esta
        genética+versión+período. Así una columna puede aparecer (con Bajo/Alto)
        aunque todavía no calculemos el valor real de esa métrica.

        Al final se filtra por applicable_version_ids: si el indicador tiene
        Versiones de Estándar Aplicables cargadas, solo se muestra cuando la
        Versión elegida está entre ellas (si no tiene ninguna cargada, se
        considera aplicable a todas, por compatibilidad con indicadores
        existentes). Esto evita que un indicador con datos históricos de OTRA
        versión quede pegado como columna al cambiar de Versión en el reporte."""
        self.ensure_one()
        version = self.version_id or self.genetics_id.default_standard_version_id
        Weekly = self.env['poultry.batch.indicator.weekly.value']
        Standard = self.env['poultry.genetics.standard']
        from_weekly = Weekly.search([
            ('batch_id', 'in', self._get_report_batches().ids),
            ('period', '=', period),
        ]).mapped('indicator_id')
        from_standard = Standard.search([
            ('version_id', '=', version.id),
            ('period', '=', period),
            ('active', '=', True),
        ]).mapped('indicator_id') if version else self.env['poultry.indicator']
        indicators = (from_weekly | from_standard).sorted('sequence')
        if version:
            indicators = indicators.filtered(
                lambda i: not i.applicable_version_ids or version in i.applicable_version_ids)
        # Período del indicador: solo Crianza, solo Producción, o ambos. Sin valor
        # (registros anteriores a este campo) se trata como "ambos".
        indicators = indicators.filtered(
            lambda i: not i.period_scope or i.period_scope in ('both', period))
        return indicators

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
        report_batches = self._get_report_batches()
        is_comparison = len(report_batches) > 1
        periods = (self.report_period,) if self.report_period else ('crianza', 'produccion')
        for period in ('crianza', 'produccion'):
            if period not in periods:
                # Período fuera del reporte (menú Crianza/Producción dedicado): se deja
                # la estructura vacía para que pantalla/PDF/Excel lo salteen sin
                # ramificar en cada consumidor.
                result[period] = {'indicators': [], 'rows': []}
                continue
            indicators = self._get_relevant_indicators(period)
            weekly_values = Weekly.search([
                ('batch_id', 'in', report_batches.ids),
                ('period', '=', period),
            ])
            standard_weeks = Standard.search([
                ('version_id', '=', version.id),
                ('period', '=', period),
                ('active', '=', True),
            ]).mapped('week')
            weeks = sorted(set(weekly_values.mapped('week')) | set(standard_weeks))

            # El reporte muestra solo días TERMINADOS: hoy nunca cuenta (el día no
            # cerró). Para la columna Aves Vivas, la fecha de referencia de la
            # semana en curso es AYER; las semanas futuras quedan vacías.
            today = fields.Date.context_today(self)
            yesterday = today - timedelta(days=1)

            # Semana en curso: el agregado semanal PERSISTIDO incluye los valores
            # de hoy (lo consume el pivot de Valores Semanales, que no corta). El
            # reporte en cambio la recalcula al vuelo desde los valores diarios
            # con fecha < hoy, para no mostrar nunca un día sin terminar. Al día
            # siguiente el mismo recálculo incorpora solo el día ya cerrado. Solo
            # puede haber una semana en curso por lote → 1 búsqueda por lote.
            Value = self.env['poultry.batch.indicator.value']
            current_overrides = {}
            for batch in report_batches:
                if not batch.birth_date:
                    continue
                current_week = batch._poultry_week_of(today)
                week_start = batch._poultry_week_start(current_week)
                day_values = Value.search([
                    ('batch_id', '=', batch.id),
                    ('indicator_id', 'in', indicators.ids),
                    ('date', '>=', week_start),
                    ('date', '<', today),
                ])
                for indicator in indicators:
                    ind_values = day_values.filtered(
                        lambda v, ind=indicator: v.indicator_id == ind)
                    current_overrides[(batch.id, indicator.id, current_week)] = \
                        Value._poultry_aggregate_week_values(indicator, ind_values)

            rows = []
            for week in weeks:
                cells = {}
                # Aves Vivas al último día de la semana (o a AYER si la semana está
                # en curso), por lote y consolidado (suma de los seleccionados).
                # None = sin dato (lote sin asignación vigente o semana futura),
                # distinto de 0 (todas las aves muertas).
                live_by_batch = {}
                for batch in report_batches:
                    week_start = batch._poultry_week_start(week) if batch.birth_date else False
                    if not week_start or week_start > yesterday:
                        live_by_batch[batch.id] = None
                        continue
                    ref_date = min(batch._poultry_week_end(week), yesterday)
                    live_by_batch[batch.id] = batch._poultry_get_live_bird_count_on(ref_date)
                live_values = [v for v in live_by_batch.values() if v is not None]
                for indicator in indicators:
                    matches = weekly_values.filtered(
                        lambda w, ind=indicator, wk=week: w.indicator_id == ind and w.week == wk)
                    # Bajo/Alto siempre se recalculan contra la Versión elegida en el
                    # reporte (nunca se toman del Bajo/Alto guardado en el Valor Real,
                    # que quedó congelado contra la Versión predeterminada de la genética
                    # al momento del cálculo). Así cambiar de Versión en pantalla sí
                    # actualiza el rango, tenga o no la semana un Valor Real ya calculado.
                    standard, value_low, value_high = self._get_standard_range(version, indicator, week)
                    has_standard = bool(standard)
                    # Valor de cada lote seleccionado en esta semana, y consolidado
                    # ponderado por la Cantidad de Aves de cada lote (un lote de
                    # 32.000 aves pesa más que uno de 5.000, no promedio simple).
                    batch_values = []
                    total_weight = 0.0
                    total_weighted = 0.0
                    for batch in report_batches:
                        batch_match = matches.filtered(lambda m, b=batch: m.batch_id == b)
                        if not batch_match:
                            continue
                        batch_real = batch_match[0].real_value
                        # Semana en curso de origen Sistema: usar el recálculo sin
                        # el día de hoy (None = sin días terminados → sin Real).
                        # Los valores manuales son histórico y no se tocan.
                        override_key = (batch.id, indicator.id, week)
                        if batch_match[0].source == 'system' and override_key in current_overrides:
                            batch_real = current_overrides[override_key]
                            if batch_real is None:
                                continue
                        weight = batch.bird_count or 1
                        total_weight += weight
                        total_weighted += batch_real * weight
                        batch_values.append({
                            'batch_id': batch.id,
                            'batch_name': batch.name,
                            'bird_count': batch.bird_count,
                            'date': str(batch._poultry_week_end(week))
                                    if batch.birth_date else None,
                            'real_value': batch_real,
                            'real_color': self._get_real_color(
                                indicator, batch_real, value_low, value_high, has_standard),
                        })
                    real_value = (total_weighted / total_weight) if batch_values else None
                    cells[indicator.id] = {
                        'value_low': value_low,
                        'value_high': value_high,
                        'real_value': real_value,
                        'has_standard': has_standard,
                        'out_of_range': has_standard and real_value is not None and (
                            real_value < value_low or real_value > value_high),
                        'real_color': self._get_real_color(
                            indicator, real_value, value_low, value_high, has_standard),
                        'batch_values': batch_values if is_comparison else [],
                    }
                # Se muestra el ÚLTIMO día de la Semana de Vida (como las planillas de
                # la granja, que registran los totales al cierre de la semana), anclada
                # a la Fecha de Nacimiento (ver poultry.batch._poultry_week_anchor).
                # Con COMPARACIÓN de lotes la fila semanal no lleva fecha: cada lote
                # tiene su propio calendario (distinta Fecha de Nacimiento) y la del
                # principal sería engañosa; la fecha de cada lote se ve al expandir.
                week_date = (self.batch_id._poultry_week_end(week)
                             if self.batch_id.birth_date and not is_comparison else None)
                rows.append({
                    'week': week,
                    'date': str(week_date) if week_date else None,
                    'live_birds': sum(live_values) if live_values else None,
                    'live_birds_by_batch': live_by_batch,
                    'cells': cells,
                })

            result[period] = {
                'indicators': [
                    {'id': indicator.id, 'name': indicator.name, 'uom': indicator.uom_id.name}
                    for indicator in indicators
                ],
                'rows': rows,
            }
        result['header'] = {
            'report_period': self.report_period or False,
            'batch_id': self.batch_id.id,
            'batch_name': self.batch_id.name,
            'batch_ids': report_batches.ids,
            'is_comparison': is_comparison,
            'genetics_name': self.genetics_id.name,
            'version_id': version.id,
            'version_name': version.name,
            'version_options': [
                {'id': v.id, 'name': v.name}
                for v in self.genetics_id.standard_version_ids.filtered('active')
            ],
            'birth_date': str(self.batch_id.birth_date) if self.batch_id.birth_date else False,
            'coop_names': self.current_coop_names,
            'coop_date_from': str(self.current_coop_date_from) if self.current_coop_date_from else False,
            # Aves Alojadas (la foto a la Entrada en Producción, igual que la ficha
            # del lote); si el lote no entró en producción todavía (crianza), la
            # Cantidad de Aves ingresada.
            'bird_count': self.batch_id.housed_bird_count or self.batch_id.bird_count,
            # Una entrada por lote seleccionado, para que el encabezado en pantalla
            # muestre la información de todos (no solo la del principal).
            'batches_info': [
                {
                    'batch_id': batch.id,
                    'name': batch.name,
                    'coop_names': info[0],
                    'coop_date_from': str(info[1]) if info[1] else False,
                    'birth_date': str(batch.birth_date) if batch.birth_date else False,
                    'bird_count': batch.housed_bird_count or batch.bird_count,
                }
                for batch in report_batches
                for info in [self._get_batch_coop_info(batch)]
            ],
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
            'params': {'wizard_id': self.id, 'period': self.report_period or False},
        }

    # Los menús ahora abren el formulario de selección del asistente (Lote/s y
    # Versión) en vez de saltar directo al primer lote activo; una vez adentro
    # del reporte, los selectores en pantalla siguen permitiendo cambiar todo.
