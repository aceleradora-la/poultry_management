# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    coop_id = fields.Many2one('poultry.coop', string='Galpón', 
                               domain="[('active', '=', True)]",
                               help='Seleccione un galpón para cargar automáticamente el producto y la lista de materiales activa')
    egg_collection_id = fields.Many2one('poultry.egg.collection', string='Recolección de Huevos',
                                         readonly=True)
    coop_close_id = fields.Many2one('poultry.coop.close', string='Cierre de Galpón',
                                    readonly=True, copy=False,
                                    help='Cierre de galpón que generó esta OF de huevo sin clasificar')
    poultry_dead_count_total = fields.Integer(
        string='Aves Muertas (total galpón)', copy=False,
        help='Cantidad total de aves muertas del galpón en la fecha de esta OF. Se reparte '
             'automáticamente entre los lotes del galpón según su población viva, generando '
             'un registro de mortandad por lote.')
    poultry_mortality_ids = fields.One2many(
        'poultry.mortality', 'production_id', string='Registros de Mortalidad', readonly=True)

    def _get_scheduled_date(self):
        """Obtiene la fecha programada de la OF con tolerancia entre versiones."""
        self.ensure_one()
        for field_name in ('date_start', 'date_planned_start'):
            value = getattr(self, field_name, False)
            if value:
                return fields.Datetime.to_datetime(value).date()
        return fields.Date.context_today(self)

    def _apply_coop_active_bom(self):
        """Carga producto y BOM del galpón para la fecha programada."""
        self.ensure_one()
        if not self.coop_id:
            self.product_id = False
            self.bom_id = False
            return

        scheduled_date = self._get_scheduled_date()
        active_bom = self.env['poultry.coop.bom'].get_active_bom_for_coop_date(
            self.coop_id.id, scheduled_date
        )
        if not active_bom:
            self.product_id = False
            self.bom_id = False
            return {
                'warning': {
                    'title': 'Sin lista activa para la fecha',
                    'message': (
                        f'No existe una lista de materiales activa para el galpón '
                        f'{self.coop_id.display_name} en la fecha {scheduled_date}.'
                    ),
                }
            }

        self.product_id = active_bom.bom_product_id or False
        self.bom_id = active_bom.bom_id or False
        if self.bom_id and hasattr(self, '_onchange_bom_id'):
            self._onchange_bom_id()
        elif hasattr(self, '_onchange_product_id'):
            self._onchange_product_id()
        return {}

    @api.onchange('coop_id', 'date_start')
    def _onchange_coop_or_date(self):
        """Refresca BOM/producto al cambiar galpón o fecha programada."""
        warning = {}
        for production in self:
            result = production._apply_coop_active_bom()
            if result and result.get('warning'):
                warning = result
        return warning

    # -- Mortandad de aves (solo OF de Huevo sin Clasificar) --------------------
    # El registro se materializa al confirmar/producir la OF (button_mark_done), no en
    # cada guardado del total; y se elimina al desmantelar la OF (ver mrp_unbuild.py).

    def _poultry_target_mortality_date(self):
        """Fecha a la que se imputa la mortandad: la del Cierre de Galpón, o en su
        defecto la fecha programada de la OF."""
        self.ensure_one()
        return (self.coop_close_id.date if self.coop_close_id else False) or self._get_scheduled_date()

    def _poultry_get_coop_batches_and_birds(self, target_date):
        """Devuelve (batches, birds_by_batch, total_birds): los lotes con asignación
        vigente al galpón en target_date (poultry.batch.coop.line) y su población viva
        esa fecha (_get_live_bird_count_on, la misma lógica histórica de Aves Vivas de
        todo el módulo). Compartido por mortandad, consumo y producción de huevos."""
        self.ensure_one()
        lines = self.env['poultry.batch.coop.line'].search([
            ('coop_id', '=', self.coop_id.id),
            ('active', '=', True),
            ('date_from', '<=', target_date),
            '|', ('date_to', '=', False), ('date_to', '>=', target_date),
        ])
        birds_by_batch = {}
        for line in lines:
            birds_by_batch[line.batch_id.id] = (birds_by_batch.get(line.batch_id.id, 0)
                                                 + line._get_live_bird_count_on(target_date))
        batches = lines.mapped('batch_id')
        return batches, birds_by_batch, sum(birds_by_batch.values())

    def _poultry_previous_accumulated(self, batch, indicator, target_date):
        """Valor acumulado previo desde el cual continuar la suma corrida de un
        indicador acumulado (empalme). Devuelve, en este orden de prioridad:
        1) el último Valor Real DIARIO del sistema anterior a target_date;
        2) si no hay, el último Valor Real SEMANAL MANUAL de una semana anterior a la
           de target_date (dato histórico cargado a mano, ej. el acumulado al final de
           la crianza antes de empezar a usar Odoo);
        3) 0.0 si no hay ninguno.
        Así los acumulados del sistema (que arrancan cuando ya hay datos) continúan
        a partir del histórico manual en vez de reiniciarse en cero."""
        Value = self.env['poultry.batch.indicator.value']
        previous = Value.search([
            ('batch_id', '=', batch.id),
            ('indicator_id', '=', indicator.id),
            ('date', '<', target_date),
        ], order='date desc', limit=1)
        if previous:
            return previous.value
        if batch.birth_date and target_date >= batch.birth_date:
            target_week = (target_date - batch.birth_date).days // 7
            manual = self.env['poultry.batch.indicator.weekly.value'].search([
                ('batch_id', '=', batch.id),
                ('indicator_id', '=', indicator.id),
                ('source', '=', 'manual'),
                ('week', '<', target_week),
            ], order='week desc', limit=1)
            if manual:
                return manual.real_value
        return 0.0

    def _poultry_distribute_integer(self, total, batches, birds_by_batch):
        """Reparte un entero 'total' entre 'batches' proporcional a su población viva
        (birds_by_batch), usando el método del mayor resto para que la suma de las partes
        sea exactamente 'total' sin perder unidades por redondeo."""
        total_birds = sum(birds_by_batch.get(b.id, 0) for b in batches)
        if total_birds <= 0:
            return {}
        shares = {}
        floor_sum = 0
        remainders = []
        for batch in batches:
            exact = total * birds_by_batch.get(batch.id, 0) / total_birds
            base = int(exact)
            shares[batch.id] = base
            floor_sum += base
            remainders.append((exact - base, batch.id))
        leftover = total - floor_sum
        remainders.sort(reverse=True)
        for i in range(leftover):
            shares[remainders[i % len(remainders)][1]] += 1
        return shares

    def _poultry_sync_mortality(self):
        """Regenera los registros poultry.mortality de esta OF a partir del total cargado
        en poultry_dead_count_total, repartiéndolo entre los lotes del galpón según su
        población viva. Borra primero los registros previos de esta OF para que la base
        de reparto no se descuente a sí misma."""
        self.ensure_one()
        Mortality = self.env['poultry.mortality']
        Mortality.search([('production_id', '=', self.id)]).unlink()

        total = self.poultry_dead_count_total or 0
        if total <= 0 or not self.coop_id:
            return

        target_date = self._poultry_target_mortality_date()
        batches, birds_by_batch, total_birds = self._poultry_get_coop_batches_and_birds(target_date)
        if not batches or total_birds <= 0:
            raise UserError(
                f'No hay lotes con aves vivas en el galpón {self.coop_id.display_name} '
                f'a la fecha {target_date}. No se puede registrar la mortandad.'
            )
        if total > total_birds:
            raise UserError(
                f'Las aves muertas ({total}) superan las aves vivas del galpón '
                f'{self.coop_id.display_name} ({total_birds}) a la fecha {target_date}.'
            )

        shares = self._poultry_distribute_integer(total, batches, birds_by_batch)
        vals_list = []
        for batch in batches:
            share = shares.get(batch.id, 0)
            if share <= 0:
                continue
            vals_list.append({
                'production_id': self.id,
                'coop_id': self.coop_id.id,
                'batch_id': batch.id,
                'genetics_id': batch.genetics_id.id,
                'date': target_date,
                'dead_count': share,
            })
        if vals_list:
            Mortality.create(vals_list)

    def _poultry_get_finished_qty_for_validation(self):
        """
        Cantidad del producto final a usar en la validación.
        Prioriza qty_producing (si existe y está seteado) y cae a product_qty.
        """
        self.ensure_one()
        qty_producing = getattr(self, 'qty_producing', 0.0) or 0.0
        return qty_producing if qty_producing > 0 else (self.product_qty or 0.0)

    def _poultry_get_move_consumed_qty(self, move):
        """
        Obtiene la cantidad consumida de un stock.move en su propia UdM.
        Usa quantity_done si existe, si no quantity, y como último recurso suma qty_done de move_line_ids.
        """
        qty = getattr(move, 'quantity_done', None)
        if qty is None:
            qty = getattr(move, 'quantity', None)
        if qty is None:
            qty = sum(getattr(move, 'move_line_ids', self.env['stock.move.line']).mapped('qty_done') or [0.0])
        return qty or 0.0

    def _poultry_validate_kit_consumption_equals_finished(self):
        """
        Valida que, en una OF mix avícola, la suma de los componentes que pertenecen
        a la MISMA familia de UdM que el producto final (es decir, los huevos),
        convertidos a la UdM del producto final, sea igual a la cantidad producida.

        Los componentes de otra familia (film en gramos, cajas en unidades, etc.) se
        ignoran: pueden mezclarse libremente en la OF. En Odoo 19 `_compute_quantity`
        ya no valida familias y convertiría ciegamente entre familias distintas
        (mezclando gramos con huevos), por eso filtramos por familia común explícita.
        """
        self.ensure_one()
        finished_uom = self.product_uom_id
        finished_qty = self._poultry_get_finished_qty_for_validation()

        total = 0.0
        for move in self.move_raw_ids.filtered(lambda m: m.state != 'cancel'):
            move_uom = move.product_uom
            # Solo participan del balance los componentes convertibles a la UdM
            # del producto final (misma familia / raíz relative_uom_id).
            if not move_uom or not finished_uom._has_common_reference(move_uom):
                continue
            consumed = self._poultry_get_move_consumed_qty(move)
            total += move_uom._compute_quantity(consumed, finished_uom)

        if float_compare(total, finished_qty, precision_rounding=finished_uom.rounding) != 0:
            raise UserError(
                f'Validación KIT: la suma consumida ({total:g} {finished_uom.name}) '
                f'no coincide con lo producido ({finished_qty:g} {finished_uom.name}).'
            )

    def button_mark_done(self):
        for mo in self:
            tmpl = mo.product_id.product_tmpl_id if mo.product_id else False
            if tmpl and getattr(tmpl, 'poultry_validate_kit_consumption', False):
                mo._poultry_validate_kit_consumption_equals_finished()
        result = super().button_mark_done()
        # La mortandad se guarda en la tabla recién al confirmar/producir la OF de Huevo
        # sin Clasificar. El reparto valida contra las aves vivas del galpón; si no cierra,
        # levanta UserError y toda la operación (incluido el producido) se revierte. Se
        # sincroniza ANTES de calcular los indicadores para que las Aves Vivas del día
        # reflejen la mortandad recién registrada.
        for mo in self.filtered(lambda m: m.coop_close_id):
            mo._poultry_sync_mortality()
            mo._poultry_compute_all_indicator_values()
        return result

    def _poultry_get_consumption_uom(self, xml_id):
        uom = self.env.ref(xml_id, raise_if_not_found=False)
        return uom or self.env['uom.uom']

    def _poultry_compute_all_indicator_values(self):
        """Punto de entrada único para calcular todos los indicadores reales derivados
        de esta OF de Huevo sin Clasificar (consumo + producción de huevos). Se llama
        tanto desde button_mark_done() (tiempo real) como desde el recálculo histórico
        (poultry.coop.close._poultry_rebuild_all_indicator_values)."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return
        self._poultry_compute_consumption_indicator_values()
        self._poultry_compute_egg_production_indicator_values()
        self._poultry_compute_mortality_indicator_values()
        self._poultry_compute_egg_mass_and_weight_indicator_values()
        self._poultry_compute_viability_indicator_values()
        self._poultry_compute_feed_conversion_indicator_values()

    def _poultry_compute_consumption_indicator_values(self):
        """Al cerrar la OF de Huevo sin Clasificar generada por un Cierre de Galpón,
        calcula el consumo real de Alimento (g/ave-día) y Agua (ml/ave-día) sumando
        las líneas de componentes marcadas como tales, y lo reparte entre los lotes
        presentes en el galpón esa fecha según su población viva ese día
        (poultry.batch.coop.line), guardando el resultado en
        poultry.batch.indicator.value."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return

        target_date = self.coop_close_id.date or self._get_scheduled_date()

        kg_uom = self._poultry_get_consumption_uom('uom.product_uom_kgm')
        liter_uom = self._poultry_get_consumption_uom('uom.product_uom_litre')

        feed_qty_kg = 0.0
        water_qty_l = 0.0
        for move in self.move_raw_ids.filtered(lambda m: m.state != 'cancel' and m.bom_line_id):
            consumption_type = move.bom_line_id.poultry_consumption_type
            if consumption_type not in ('feed', 'water'):
                continue
            qty = self._poultry_get_move_consumed_qty(move)
            if consumption_type == 'feed':
                feed_qty_kg += move.product_uom._compute_quantity(qty, kg_uom) if kg_uom else qty
            else:
                water_qty_l += move.product_uom._compute_quantity(qty, liter_uom) if liter_uom else qty

        if feed_qty_kg <= 0 and water_qty_l <= 0:
            return

        batches, birds_by_batch, total_birds = self._poultry_get_coop_batches_and_birds(target_date)
        if not batches or total_birds <= 0:
            return

        Indicator = self.env['poultry.indicator']
        feed_indicator = Indicator.search(
            [('category', '=', 'feed_consumption'), ('accumulation_type', '=', 'none'),
             ('active', '=', True)], limit=1)
        water_indicator = Indicator.search(
            [('category', '=', 'water_consumption'), ('accumulation_type', '=', 'none'),
             ('active', '=', True)], limit=1)

        Value = self.env['poultry.batch.indicator.value']
        feed_g_per_bird_day = (feed_qty_kg * 1000.0 / total_birds) if feed_qty_kg > 0 else 0.0
        water_ml_per_bird_day = (water_qty_l * 1000.0 / total_birds) if water_qty_l > 0 else 0.0

        for batch in batches:
            birds = birds_by_batch[batch.id]
            if birds <= 0:
                continue
            if feed_indicator and feed_qty_kg > 0:
                Value._set_value(batch, self.coop_id, target_date, feed_indicator,
                                  feed_g_per_bird_day,
                                  numerator=feed_g_per_bird_day * birds, denominator=birds,
                                  production=self)
            if water_indicator and water_qty_l > 0:
                Value._set_value(batch, self.coop_id, target_date, water_indicator,
                                  water_ml_per_bird_day,
                                  numerator=water_ml_per_bird_day * birds, denominator=birds,
                                  production=self)

    def _poultry_compute_egg_production_indicator_values(self):
        """Al cerrar la OF de Huevo sin Clasificar: % Ave-Día, Huevos Acumulados
        Ave-Día y Huevos Acumulados Ave-Alojada por lote, repartiendo el total de
        huevos del día (self.product_qty) entre los lotes presentes en el galpón
        según su población viva ese día.

        % Ave-Día es una tasa diaria (huevos de este lote ese día / aves vivas ese
        día). Los dos acumulados son independientes entre sí: NO se derivan del %
        Ave-Día ya calculado, se recalculan cada día desde los mismos datos crudos.
        Ave-Día acumulado suma cada día huevos/aves VIVAS ese día. Ave-Alojada
        acumulado suma cada día huevos/aves ALOJADAS AL INICIO (fija, no baja con la
        mortalidad ni sube con nuevos Ingresos) — solo se calcula si el lote ya tiene
        un Cambio de Período a Producción registrado y la fecha es posterior a esa
        Fecha de Entrada en Producción."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return
        target_date = self.coop_close_id.date or self._get_scheduled_date()
        total_eggs = self.product_qty or 0.0
        if total_eggs <= 0:
            return

        batches, birds_by_batch, total_birds = self._poultry_get_coop_batches_and_birds(target_date)
        if not batches or total_birds <= 0:
            return

        Indicator = self.env['poultry.indicator']
        rate_indicator = Indicator.search(
            [('category', '=', 'egg_production'), ('accumulation_type', '=', 'none'),
             ('active', '=', True)], limit=1)
        cumulative_live_indicator = Indicator.search(
            [('category', '=', 'egg_production'), ('accumulation_type', '=', 'live'),
             ('active', '=', True)], limit=1)
        cumulative_housed_indicator = Indicator.search(
            [('category', '=', 'egg_production'), ('accumulation_type', '=', 'housed'),
             ('active', '=', True)], limit=1)
        rate_original_indicator = Indicator.search(
            [('category', '=', 'egg_production'), ('accumulation_type', '=', 'original_rate'),
             ('active', '=', True)], limit=1)
        if (not rate_indicator and not cumulative_live_indicator and not cumulative_housed_indicator
                and not rate_original_indicator):
            return

        Value = self.env['poultry.batch.indicator.value']
        # Uniforme por ave: mismo huevos/ave para todos los lotes que comparten el galpón.
        eggs_per_bird_day = total_eggs / total_birds

        for batch in batches:
            birds = birds_by_batch[batch.id]
            if birds <= 0:
                continue
            batch_egg_share = eggs_per_bird_day * birds

            if rate_indicator:
                Value._set_value(batch, self.coop_id, target_date, rate_indicator,
                                  eggs_per_bird_day * 100.0,
                                  numerator=batch_egg_share * 100.0, denominator=birds,
                                  production=self)

            if cumulative_live_indicator:
                previous_total = self._poultry_previous_accumulated(
                    batch, cumulative_live_indicator, target_date)
                Value._set_value(batch, self.coop_id, target_date, cumulative_live_indicator,
                                  previous_total + eggs_per_bird_day,
                                  numerator=batch_egg_share, denominator=birds,
                                  production=self)

            if cumulative_housed_indicator:
                if (batch.housed_bird_count and batch.production_start_date
                        and target_date >= batch.production_start_date):
                    previous_total = self._poultry_previous_accumulated(
                        batch, cumulative_housed_indicator, target_date)
                    eggs_per_housed_bird = batch_egg_share / batch.housed_bird_count
                    Value._set_value(batch, self.coop_id, target_date, cumulative_housed_indicator,
                                      previous_total + eggs_per_housed_bird,
                                      numerator=batch_egg_share, denominator=batch.housed_bird_count,
                                      production=self)

            if rate_original_indicator and batch.bird_count:
                # % Postura sobre Aves Originales del Lote: misma cantidad de huevos
                # de hoy que arriba, pero contra la Cantidad de Aves del lote (fija,
                # no la población viva de hoy).
                postura_original_pct = (batch_egg_share / batch.bird_count) * 100.0
                Value._set_value(batch, self.coop_id, target_date, rate_original_indicator,
                                  postura_original_pct,
                                  numerator=batch_egg_share * 100.0, denominator=batch.bird_count,
                                  production=self)

    def _poultry_compute_mortality_indicator_values(self):
        """Indicadores reales de Mortandad (% diario y/o acumulados), a partir de los
        registros de poultry.mortality que generó esta OF (_poultry_sync_mortality).
        Reusa dead_count/live_bird_count/mortality_pct ya calculados en el propio
        registro (misma lógica de Aves Vivas de todo el módulo, sin recalcularla acá).
        Mismo patrón de acumulación que Producción de Huevos: 'none' = tasa diaria,
        'live'/'housed' = suma corrida sobre la población viva/alojada."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return
        target_date = self._poultry_target_mortality_date()
        # Incluye tanto los registros generados por esta OF (_poultry_sync_mortality) como
        # los cargados a mano (production_id vacío) para este galpón en la fecha: la
        # mortandad del día de un lote es la suma de ambos.
        mortalities = self.env['poultry.mortality'].search([
            ('coop_id', '=', self.coop_id.id),
            ('date', '=', target_date),
            ('active', '=', True),
        ])
        if not mortalities:
            return
        # Agrupa por lote: suma de muertas del día y aves vivas al cierre del día
        # (live_bird_count es igual para todos los registros del mismo lote/fecha, porque
        # acumula toda la mortandad hasta la fecha).
        dead_by_batch = {}
        live_by_batch = {}
        for m in mortalities.filtered('batch_id'):
            dead_by_batch[m.batch_id] = dead_by_batch.get(m.batch_id, 0) + m.dead_count
            live_by_batch[m.batch_id] = m.live_bird_count
        if not dead_by_batch:
            return

        Indicator = self.env['poultry.indicator']
        rate_indicator = Indicator.search(
            [('category', '=', 'mortality'), ('accumulation_type', '=', 'none'),
             ('active', '=', True)], limit=1)
        cumulative_live_indicator = Indicator.search(
            [('category', '=', 'mortality'), ('accumulation_type', '=', 'live'),
             ('active', '=', True)], limit=1)
        cumulative_housed_indicator = Indicator.search(
            [('category', '=', 'mortality'), ('accumulation_type', '=', 'housed'),
             ('active', '=', True)], limit=1)
        cumulative_original_indicator = Indicator.search(
            [('category', '=', 'mortality'), ('accumulation_type', '=', 'original_cumulative'),
             ('active', '=', True)], limit=1)
        if (not rate_indicator and not cumulative_live_indicator and not cumulative_housed_indicator
                and not cumulative_original_indicator):
            return

        Value = self.env['poultry.batch.indicator.value']
        for batch, dead in dead_by_batch.items():
            base = live_by_batch[batch] + dead
            if base <= 0:
                continue
            daily_pct = (dead / base * 100.0)

            if rate_indicator:
                Value._set_value(batch, self.coop_id, target_date, rate_indicator,
                                  daily_pct, numerator=dead * 100.0, denominator=base,
                                  production=self)

            if cumulative_live_indicator:
                previous_total = self._poultry_previous_accumulated(
                    batch, cumulative_live_indicator, target_date)
                Value._set_value(batch, self.coop_id, target_date, cumulative_live_indicator,
                                  previous_total + daily_pct,
                                  numerator=dead * 100.0, denominator=base, production=self)

            if cumulative_housed_indicator:
                if (batch.housed_bird_count and batch.production_start_date
                        and target_date >= batch.production_start_date):
                    previous_total = self._poultry_previous_accumulated(
                        batch, cumulative_housed_indicator, target_date)
                    dead_pct_housed = dead / batch.housed_bird_count * 100.0
                    Value._set_value(batch, self.coop_id, target_date, cumulative_housed_indicator,
                                      previous_total + dead_pct_housed,
                                      numerator=dead * 100.0, denominator=batch.housed_bird_count,
                                      production=self)

            if cumulative_original_indicator and batch.bird_count:
                previous_total = self._poultry_previous_accumulated(
                    batch, cumulative_original_indicator, target_date)
                dead_pct_original = dead / batch.bird_count * 100.0
                Value._set_value(batch, self.coop_id, target_date, cumulative_original_indicator,
                                  previous_total + dead_pct_original,
                                  numerator=dead * 100.0, denominator=batch.bird_count,
                                  production=self)

    def _poultry_compute_viability_indicator_values(self):
        """% de Viabilidad Acumulada (aves vivas hoy / aves originales del lote x 100).
        A diferencia de los indicadores de mortandad (que suman contribuciones diarias),
        se calcula como una foto directa del estado del lote a la fecha -no depende del
        valor del día anterior- pero se guarda con tipo de acumulación 'original_cumulative'
        para que el agregado semanal tome el último valor de la semana (estado), no un
        promedio de tasas diarias."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return
        target_date = self._poultry_target_mortality_date()
        Indicator = self.env['poultry.indicator']
        viability_indicator = Indicator.search(
            [('category', '=', 'viability'), ('accumulation_type', '=', 'original_cumulative'),
             ('active', '=', True)], limit=1)
        if not viability_indicator:
            return

        batches, birds_by_batch, total_birds = self._poultry_get_coop_batches_and_birds(target_date)
        if not batches:
            return

        Value = self.env['poultry.batch.indicator.value']
        for batch in batches:
            if not batch.bird_count:
                continue
            live_today = birds_by_batch.get(batch.id, 0)
            viability_pct = live_today / batch.bird_count * 100.0
            Value._set_value(batch, self.coop_id, target_date, viability_indicator,
                              viability_pct, numerator=live_today * 100.0, denominator=batch.bird_count,
                              production=self)

    def _poultry_compute_egg_mass_and_weight_indicator_values(self):
        """Indicadores reales de Masa de Huevo y Peso del Huevo Promedio, a partir de
        los Partes de Producción (poultry.egg.collection) incluidos en el Cierre de
        Galpón que generó esta OF -no de la OF en sí, que solo tiene el total de
        huevos sin distinguir peso por variante.

        Masa de Huevo Ave-Alojada Acumulada (kg): masa total del galpón (suma por
        variante de peso medio × cantidad producida, igual que
        poultry.egg.collection.total_weight pero agregado a nivel de todos los
        partes del cierre) repartida entre los lotes según su población viva ese
        día, acumulada en kg de masa de huevo por ave alojada -mismo patrón que
        Huevos Acumulados Ave-Alojada.

        Masa de Huevo Ave-Día (g/ave/día, tipo de acumulación Ninguno): la misma
        masa del galpón del día pero SIN acumular, expresada en gramos por ave
        viva ese día (como en las guías de genética, ej. 57.5 g). Al ser masa por
        ave, el valor del día es el mismo para todos los lotes del galpón (misma
        lógica de reparto uniforme por ave que % Ave-Día).

        Peso del Huevo Promedio (g/huevo): promedio ponderado del galpón ese día
        (por variante: peso medio × cantidad de huevos de esa variante, igual que
        poultry.egg.collection.average_weight_elaborated). No se reparte por
        población -es un atributo del huevo, no de cuántas aves hay-, así que se
        guarda el mismo valor para cada lote presente, con el mismo numerador/
        denominador (gramos totales / huevos con peso), para que el agregado
        semanal por lote siga siendo el promedio ponderado correcto (nunca
        promedio de promedios)."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return
        target_date = self.coop_close_id.date or self._get_scheduled_date()

        collections = self.coop_close_id.egg_collection_ids.filtered(lambda c: c.state == 'done')
        total_mass_grams = 0.0
        total_eggs_with_weight = 0.0
        for line in collections.mapped('line_ids'):
            if line.average_weight and line.total_produced_reference:
                total_mass_grams += line.average_weight * line.total_produced_reference
                total_eggs_with_weight += line.total_produced_reference
        if total_mass_grams <= 0:
            return
        total_mass_kg = total_mass_grams / 1000.0
        avg_weight_g = total_mass_grams / total_eggs_with_weight if total_eggs_with_weight else 0.0

        batches, birds_by_batch, total_birds = self._poultry_get_coop_batches_and_birds(target_date)
        if not batches or total_birds <= 0:
            return

        Indicator = self.env['poultry.indicator']
        mass_housed_indicator = Indicator.search(
            [('category', '=', 'egg_mass'), ('accumulation_type', '=', 'housed'),
             ('active', '=', True)], limit=1)
        mass_rate_indicator = Indicator.search(
            [('category', '=', 'egg_mass'), ('accumulation_type', '=', 'none'),
             ('active', '=', True)], limit=1)
        weight_indicator = Indicator.search(
            [('category', '=', 'egg_weight'), ('accumulation_type', '=', 'none'),
             ('active', '=', True)], limit=1)
        if not mass_housed_indicator and not mass_rate_indicator and not weight_indicator:
            return

        Value = self.env['poultry.batch.indicator.value']
        mass_kg_per_bird_day = total_mass_kg / total_birds
        mass_g_per_bird_day = total_mass_grams / total_birds

        for batch in batches:
            birds = birds_by_batch[batch.id]
            if birds <= 0:
                continue

            if mass_housed_indicator:
                if (batch.housed_bird_count and batch.production_start_date
                        and target_date >= batch.production_start_date):
                    batch_mass_kg = mass_kg_per_bird_day * birds
                    previous_total = self._poultry_previous_accumulated(
                        batch, mass_housed_indicator, target_date)
                    kg_per_housed_bird = batch_mass_kg / batch.housed_bird_count
                    Value._set_value(batch, self.coop_id, target_date, mass_housed_indicator,
                                      previous_total + kg_per_housed_bird,
                                      numerator=batch_mass_kg, denominator=batch.housed_bird_count,
                                      production=self)

            if mass_rate_indicator:
                Value._set_value(batch, self.coop_id, target_date, mass_rate_indicator,
                                  mass_g_per_bird_day,
                                  numerator=mass_g_per_bird_day * birds, denominator=birds,
                                  production=self)

            if weight_indicator:
                Value._set_value(batch, self.coop_id, target_date, weight_indicator,
                                  avg_weight_g,
                                  numerator=total_mass_grams, denominator=total_eggs_with_weight,
                                  production=self)

    def _poultry_compute_feed_conversion_indicator_values(self):
        """Indicadores reales de Conversión Alimenticia: kg de Alimento consumido por
        Docena/Unidad de Huevos, y kg de Alimento por kg de Masa de Huevo -cada uno en
        variante Semanal (tasa diaria que se agrega por semana como suma/suma) y
        Acumulada desde Inicio de Producción (cociente de numerador y denominador
        acumulados por separado, mismo criterio de fecha que los indicadores 'sobre
        Aves Alojadas': solo corre desde production_start_date, nunca se suman
        razones diarias entre sí porque el denominador cambia día a día).

        Reutiliza el mismo consumo de alimento del galpón (kg) que
        _poultry_compute_consumption_indicator_values y la misma masa de huevo del
        galpón (kg) que _poultry_compute_egg_mass_and_weight_indicator_values,
        recalculados acá de forma independiente para no depender del orden en que se
        llamen los demás métodos de este mismo punto de entrada."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return
        target_date = self.coop_close_id.date or self._get_scheduled_date()

        kg_uom = self._poultry_get_consumption_uom('uom.product_uom_kgm')
        feed_qty_kg = 0.0
        for move in self.move_raw_ids.filtered(lambda m: m.state != 'cancel' and m.bom_line_id):
            if move.bom_line_id.poultry_consumption_type != 'feed':
                continue
            qty = self._poultry_get_move_consumed_qty(move)
            feed_qty_kg += move.product_uom._compute_quantity(qty, kg_uom) if kg_uom else qty
        if feed_qty_kg <= 0:
            return

        total_eggs = self.product_qty or 0.0

        collections = self.coop_close_id.egg_collection_ids.filtered(lambda c: c.state == 'done')
        total_mass_grams = 0.0
        for line in collections.mapped('line_ids'):
            if line.average_weight and line.total_produced_reference:
                total_mass_grams += line.average_weight * line.total_produced_reference
        total_mass_kg = total_mass_grams / 1000.0

        batches, birds_by_batch, total_birds = self._poultry_get_coop_batches_and_birds(target_date)
        if not batches or total_birds <= 0:
            return

        Indicator = self.env['poultry.indicator']
        feed_rate_indicator = Indicator.search(
            [('category', '=', 'feed_conversion'), ('accumulation_type', '=', 'none'),
             ('active', '=', True)], limit=1)
        feed_cumulative_indicator = Indicator.search(
            [('category', '=', 'feed_conversion'), ('accumulation_type', '=', 'ratio_cumulative'),
             ('active', '=', True)], limit=1)
        mass_rate_indicator = Indicator.search(
            [('category', '=', 'feed_egg_mass_conversion'), ('accumulation_type', '=', 'none'),
             ('active', '=', True)], limit=1)
        mass_cumulative_indicator = Indicator.search(
            [('category', '=', 'feed_egg_mass_conversion'), ('accumulation_type', '=', 'ratio_cumulative'),
             ('active', '=', True)], limit=1)
        if not any((feed_rate_indicator, feed_cumulative_indicator,
                    mass_rate_indicator, mass_cumulative_indicator)):
            return

        Value = self.env['poultry.batch.indicator.value']
        feed_size_indicator = feed_rate_indicator or feed_cumulative_indicator
        egg_group_size = (feed_size_indicator.egg_group_size or 12) if feed_size_indicator else 12

        for batch in batches:
            birds = birds_by_batch[batch.id]
            if birds <= 0:
                continue
            share = birds / total_birds
            batch_feed_kg = feed_qty_kg * share
            batch_eggs = total_eggs * share
            batch_mass_kg = total_mass_kg * share
            batch_units = batch_eggs / egg_group_size if egg_group_size else 0.0
            in_production = (batch.housed_bird_count and batch.production_start_date
                              and target_date >= batch.production_start_date)

            if feed_rate_indicator and batch_units > 0:
                Value._set_value(batch, self.coop_id, target_date, feed_rate_indicator,
                                  batch_feed_kg / batch_units,
                                  numerator=batch_feed_kg, denominator=batch_units,
                                  production=self)

            if feed_cumulative_indicator and batch_units > 0 and in_production:
                previous = Value.search([
                    ('batch_id', '=', batch.id),
                    ('indicator_id', '=', feed_cumulative_indicator.id),
                    ('date', '<', target_date),
                ], order='date desc', limit=1)
                new_num = (previous.numerator if previous else 0.0) + batch_feed_kg
                new_denom = (previous.denominator if previous else 0.0) + batch_units
                Value._set_value(batch, self.coop_id, target_date, feed_cumulative_indicator,
                                  new_num / new_denom if new_denom else 0.0,
                                  numerator=new_num, denominator=new_denom,
                                  production=self)

            if mass_rate_indicator and batch_mass_kg > 0:
                Value._set_value(batch, self.coop_id, target_date, mass_rate_indicator,
                                  batch_feed_kg / batch_mass_kg,
                                  numerator=batch_feed_kg, denominator=batch_mass_kg,
                                  production=self)

            if mass_cumulative_indicator and batch_mass_kg > 0 and in_production:
                previous = Value.search([
                    ('batch_id', '=', batch.id),
                    ('indicator_id', '=', mass_cumulative_indicator.id),
                    ('date', '<', target_date),
                ], order='date desc', limit=1)
                new_num = (previous.numerator if previous else 0.0) + batch_feed_kg
                new_denom = (previous.denominator if previous else 0.0) + batch_mass_kg
                Value._set_value(batch, self.coop_id, target_date, mass_cumulative_indicator,
                                  new_num / new_denom if new_denom else 0.0,
                                  numerator=new_num, denominator=new_denom,
                                  production=self)

