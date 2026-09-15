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
    axis = fields.Selection([
        ('life_week', 'Semana de Vida'),
        ('calendar_week', 'Semana Calendario'),
    ], string='Eje del Reporte', default='life_week', required=True,
        help='"Semana de Vida": una fila por semana de vida del lote (la de siempre). '
             'Comparando lotes, cada uno cae en fechas distintas.\n'
             '"Semana Calendario": una fila por semana real del calendario (cierra '
             'domingo, como las planillas). Sirve para ver qué pasó en la granja esa '
             'semana con todos los lotes a la vez, cada uno con su Semana de Vida.')
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
        """Detalle diario de una semana, para el despliegue por día del reporte en
        pantalla (carga perezosa: el componente lo pide recién al desplegar la
        semana y lo cachea). Devuelve, por lote del reporte:
            { '<batch_id>': {'batch_name': str, 'has_daily': bool,
                             'days': [{'date': str, 'live_birds': int|None,
                                       'cells': {indicator_id: {'real_value': float,
                                                 'count': int  # solo mortandad diaria
                                       }}}]} }
        'week' llega como número (Semana de Vida, con límites propios de cada lote)
        o como 'YYYY-MM-DD' del domingo de cierre (Semana Calendario, con los mismos
        límites para todos). El detalle diario es idéntico en los dos ejes: lo único
        que cambia es cómo se delimita la semana.

        Solo días TERMINADOS (hoy nunca, misma regla que el resto del reporte).
        Sin comparación contra estándar: no existe estándar diario."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        Value = self.env['poultry.batch.indicator.value']
        calendar_sunday = fields.Date.to_date(week) if isinstance(week, str) else None
        result = {}
        for batch in self._get_report_batches():
            if not batch.birth_date and calendar_sunday is None:
                result[str(batch.id)] = {'batch_name': batch.name, 'has_daily': False, 'days': []}
                continue
            if calendar_sunday is not None:
                week_start = calendar_sunday - timedelta(days=6)
                week_end = calendar_sunday
            else:
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
            if self.axis == 'calendar_week':
                rows = self._build_rows_calendar_week(
                    period, version, report_batches, is_comparison, indicators)
            else:
                rows = self._build_rows_life_week(
                    period, version, report_batches, is_comparison, indicators)

            result[period] = {
                'indicators': [
                    {
                        'id': indicator.id,
                        'name': indicator.name,
                        'uom': indicator.uom_id.name,
                        # Cantidades (aves muertas) sin decimales; el resto con 2.
                        'decimals': 0 if indicator.category == 'mortality_count' else 2,
                        # El componente arranca ocultando los que no van por defecto;
                        # el usuario los agrega desde el desplegable Indicadores.
                        'visible_by_default': indicator.visible_by_default,
                    }
                    for indicator in indicators
                ],
                'rows': rows,
            }
        result['header'] = self._build_header(report_batches, is_comparison, version)
        return result

    def _build_rows_life_week(self, period, version, report_batches, is_comparison, indicators):
        """Filas del reporte con eje SEMANA DE VIDA: una fila por semana de vida del
        lote, tomadas de los agregados semanales persistidos
        (poultry.batch.indicator.weekly.value) unidos con las semanas que tienen
        estándar cargado.

        Es el armado original del reporte, extraído sin cambios de get_report_data()
        al agregarse el segundo eje (Semana Calendario)."""
        Weekly = self.env['poultry.batch.indicator.weekly.value']
        Standard = self.env['poultry.genetics.standard']
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
        # El estándar de la genética llega hasta el final de la vida del lote
        # (semana 100), así que unirlo con las semanas que tienen dato real
        # arrastraba decenas de filas futuras con solo Bajo/Alto. Se corta en
        # la última semana CON dato real: las semanas intermedias sin dato sí
        # se muestran (son huecos del pasado, no futuro). Si el lote todavía
        # no tiene ningún real -lote recién creado- se deja el estándar
        # completo, para poder consultarlo.
        real_weeks = set(weekly_values.mapped('week'))
        if real_weeks:
            last_real_week = max(real_weeks)
            weeks = [week for week in weeks if week <= last_real_week]

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
                    Value._poultry_aggregate_week_values(
                        indicator, ind_values, batch=batch, reference_date=yesterday)

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
                        'life_week': week,
                        'date': str(batch._poultry_week_end(week))
                                if batch.birth_date else None,
                        'real_value': batch_real,
                        # Bajo/Alto también en el detalle por lote: en este eje todos
                        # comparten la Semana de Vida, así que el rango es el mismo de
                        # la fila, pero mostrarlo permite leer cada lote contra su
                        # estándar sin volver la vista a la fila agrupada.
                        'value_low': value_low,
                        'value_high': value_high,
                        'has_standard': has_standard,
                        'is_partial': False,
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
                'batch_rows': self._build_batch_rows(cells, live_by_batch),
                'cells': cells,
            })

        return rows

    @api.model
    def _poultry_calendar_week_bounds(self, day):
        """(lunes, domingo) de la semana calendario que contiene 'day'. La granja
        cierra la semana el DOMINGO, así que la fila se identifica por esa fecha."""
        monday = day - timedelta(days=day.weekday())
        return monday, monday + timedelta(days=6)

    def _build_rows_calendar_week(self, period, version, report_batches, is_comparison, indicators):
        """Filas del reporte con eje SEMANA CALENDARIO: una fila por semana real del
        calendario (lunes a domingo), con el detalle de cada lote adentro.

        A diferencia del eje Semana de Vida, acá NO sirven los agregados semanales
        persistidos (están numerados por semana de vida, que difiere entre lotes):
        se agregan al vuelo los valores DIARIOS de cada lote dentro de cada semana
        calendario, con el mismo helper que usa el agregado persistido
        (_poultry_aggregate_week_values), que respeta la Agregación Semanal
        configurada en el indicador.

        La fila de la semana NO lleva estándar: los lotes tienen edades distintas y
        un Bajo/Alto común no significaría nada. El estándar va en la línea de cada
        lote, según SU Semana de Vida.

        El corte "solo días terminados" queda incorporado en el propio dominio de
        búsqueda (date <= ayer), así que acá no hace falta el recálculo puntual de
        la semana en curso que sí necesita el eje Semana de Vida."""
        self.ensure_one()
        Value = self.env['poultry.batch.indicator.value']
        today = fields.Date.context_today(self)
        yesterday = today - timedelta(days=1)

        birth_dates = [b.birth_date for b in report_batches if b.birth_date]
        if not birth_dates or not indicators:
            return []
        date_lo = max(self.date_from, min(birth_dates)) if self.date_from else min(birth_dates)
        date_hi = min(self.date_to, yesterday) if self.date_to else yesterday
        if date_lo > date_hi:
            return []

        # Una sola búsqueda para todo el rango: el índice único
        # (batch_id, indicator_id, date) la resuelve como un range scan, y los
        # subconjuntos por semana se arman con browse() sobre registros ya en caché.
        values = Value.search([
            ('batch_id', 'in', report_batches.ids),
            ('indicator_id', 'in', indicators.ids),
            ('date', '>=', date_lo),
            ('date', '<=', date_hi),
        ])
        if not values:
            return []

        groups = {}       # (batch_id, indicator_id, lunes) -> [ids de valores diarios]
        days_seen = {}    # (batch_id, lunes) -> {fechas con dato}
        for value in values:
            monday, _sunday = self._poultry_calendar_week_bounds(value.date)
            groups.setdefault((value.batch_id.id, value.indicator_id.id, monday), []).append(value.id)
            days_seen.setdefault((value.batch_id.id, monday), set()).add(value.date)

        rows = []
        for monday in sorted({key[2] for key in groups}):
            sunday = monday + timedelta(days=6)
            cells = {}
            # Día de cierre de la semana (o AYER si todavía no cerró): es la fecha
            # a la que se miran TODOS los datos de la fila -las Aves Vivas y las
            # fotos de los indicadores- para que hablen del mismo día.
            ref_date = min(sunday, yesterday)
            live_by_batch = {}
            for batch in report_batches:
                live_by_batch[batch.id] = (batch._poultry_get_live_bird_count_on(ref_date)
                                            if batch.birth_date and batch.birth_date <= ref_date
                                            else None)
            live_values = [v for v in live_by_batch.values() if v is not None]

            for indicator in indicators:
                batch_values = []
                total_weight = 0.0
                total_weighted = 0.0
                for batch in report_batches:
                    value_ids = groups.get((batch.id, indicator.id, monday))
                    if not value_ids:
                        continue
                    week_values = Value.browse(value_ids)
                    real = Value._poultry_aggregate_week_values(
                        indicator, week_values, batch=batch, reference_date=ref_date)
                    if real is None:
                        continue
                    # Semana de Vida del lote en esta semana calendario: la del día
                    # de cierre. Con la convención de la granja (Fecha de Nacimiento
                    # en el día desde el que se cuentan las semanas) las dos semanas
                    # coinciden exactamente; si el lote nació otro día, la semana
                    # calendario cubre dos semanas de vida y se toma la del cierre.
                    life_week = batch._poultry_week_of(sunday)
                    standard, value_low, value_high = self._get_standard_range(
                        version, indicator, life_week)
                    has_standard = bool(standard)
                    # Semana incompleta (arranque del lote, o la semana en curso):
                    # una CANTIDAD acumulada sobre menos de 7 días queda por debajo
                    # del estándar sin que eso signifique nada, así que no se pinta.
                    is_partial = len(days_seen.get((batch.id, monday), ())) < 7
                    color = self._get_real_color(
                        indicator, real, value_low, value_high, has_standard)
                    if is_partial and indicator.weekly_aggregation == 'sum':
                        color = False
                    weight = batch.bird_count or 1
                    total_weight += weight
                    total_weighted += real * weight
                    batch_values.append({
                        'batch_id': batch.id,
                        'batch_name': batch.name,
                        'bird_count': batch.bird_count,
                        'life_week': life_week,
                        'date': str(sunday),
                        'real_value': real,
                        'value_low': value_low,
                        'value_high': value_high,
                        'has_standard': has_standard,
                        'is_partial': is_partial,
                        'real_color': color,
                    })
                real_value = (total_weighted / total_weight) if batch_values else None
                # Sin Bajo/Alto en la fila agrupada, pero se conservan las claves
                # neutralizadas para que pantalla, PDF y Excel no tengan que
                # ramificar (sus t-if de has_standard ya dejan la celda vacía).
                cells[indicator.id] = {
                    'value_low': 0.0,
                    'value_high': 0.0,
                    'has_standard': False,
                    'out_of_range': False,
                    'real_color': False,
                    'real_value': real_value,
                    'batch_values': batch_values,
                }
            rows.append({
                # Clave de fila: la fecha del domingo. El componente la usa igual
                # que el número de semana del otro eje (estado de despliegue, caché
                # del detalle diario), así que no hay que tocar su manejo de estado.
                'week': str(sunday),
                'date': str(sunday),
                'live_birds': sum(live_values) if live_values else None,
                'live_birds_by_batch': live_by_batch,
                'batch_rows': self._build_batch_rows(cells, live_by_batch),
                'cells': cells,
            })
        return rows

    @api.model
    def _build_batch_rows(self, cells, live_by_batch):
        """Detalle por lote de una fila, reagrupando los valores que cada celda
        guarda en 'batch_values'. Se precalcula acá -y no en cada consumidor- para
        que la pantalla, el PDF y el Excel muestren exactamente el mismo detalle.

        Devuelve una lista con un elemento por lote: sus datos, y 'values' con la
        celda que le corresponde en cada indicador."""
        batch_rows = {}
        for indicator_id, cell in cells.items():
            for batch_value in cell.get('batch_values') or []:
                batch_id = batch_value['batch_id']
                if batch_id not in batch_rows:
                    batch_rows[batch_id] = {
                        'batch_id': batch_id,
                        'name': batch_value['batch_name'],
                        'bird_count': batch_value.get('bird_count'),
                        'life_week': batch_value.get('life_week'),
                        'date': batch_value.get('date'),
                        # Mismo nombre que en la fila de la semana y en el detalle
                        # diario: los tres consumidores (pantalla, PDF, Excel) leen
                        # 'live_birds' y no hay que recordar una excepción acá.
                        'live_birds': live_by_batch.get(batch_id),
                        'values': {},
                    }
                batch_rows[batch_id]['values'][indicator_id] = batch_value
        return list(batch_rows.values())

    def _build_header(self, report_batches, is_comparison, version):
        """Encabezado del reporte: genética, versión elegida y una entrada por
        lote seleccionado. Extraído de get_report_data() al separar los ejes,
        porque es común a los dos."""
        return {
            'axis': self.axis,
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
        if self.axis == 'calendar_week' and not self.comparison_batch_ids:
            # Con un solo lote, el eje calendario no aporta nada sobre el de Semana
            # de Vida (mismas filas, corridas). Se valida server-side y no solo en
            # la vista, porque el formulario no protege una llamada por RPC.
            raise UserError(
                'El reporte por Semana Calendario compara lotes entre sí: elegí al '
                'menos un Lote a Comparar, o usá el reporte por Semana de Vida.'
            )
        self.get_report_data()
        return {
            'type': 'ir.actions.client',
            'tag': 'poultry_standard_tracking_report',
            'params': {'wizard_id': self.id, 'period': self.report_period or False},
        }

    # Los menús ahora abren el formulario de selección del asistente (Lote/s y
    # Versión) en vez de saltar directo al primer lote activo; una vez adentro
    # del reporte, los selectores en pantalla siguen permitiendo cambiar todo.
