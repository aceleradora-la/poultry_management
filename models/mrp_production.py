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
             'automáticamente entre los lotes presentes según su población viva, generando '
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

    def _poultry_distribute_integer(self, total, lines, birds_by_line):
        """Reparte un entero 'total' entre 'lines' proporcional a su población viva
        (birds_by_line), usando el método del mayor resto para que la suma de las partes
        sea exactamente 'total' sin perder unidades por redondeo."""
        total_birds = sum(birds_by_line.get(line.id, 0) for line in lines)
        if total_birds <= 0:
            return {}
        shares = {}
        floor_sum = 0
        remainders = []
        for line in lines:
            exact = total * birds_by_line.get(line.id, 0) / total_birds
            base = int(exact)
            shares[line.id] = base
            floor_sum += base
            remainders.append((exact - base, line.id))
        leftover = total - floor_sum
        remainders.sort(reverse=True)
        for i in range(leftover):
            shares[remainders[i % len(remainders)][1]] += 1
        return shares

    def _poultry_sync_mortality(self):
        """Regenera los registros poultry.mortality de esta OF a partir del total cargado
        en poultry_dead_count_total, repartiéndolo entre los lotes presentes en el galpón
        a la fecha según su población viva. Borra primero los registros previos de esta
        OF para que la base de reparto no se descuente a sí misma."""
        self.ensure_one()
        Mortality = self.env['poultry.mortality']
        Mortality.search([('production_id', '=', self.id)]).unlink()

        total = self.poultry_dead_count_total or 0
        if total <= 0 or not self.coop_id:
            return

        target_date = self._poultry_target_mortality_date()
        lines, birds_by_line, total_birds = self._poultry_get_active_lines_and_birds(target_date)
        if not lines or total_birds <= 0:
            raise UserError(
                f'No hay lotes con aves vivas en el galpón {self.coop_id.display_name} '
                f'a la fecha {target_date}. No se puede registrar la mortandad.'
            )
        if total > total_birds:
            raise UserError(
                f'Las aves muertas ({total}) superan las aves vivas del galpón '
                f'{self.coop_id.display_name} ({total_birds}) a la fecha {target_date}.'
            )

        shares = self._poultry_distribute_integer(total, lines, birds_by_line)
        vals_list = []
        for line in lines:
            share = shares.get(line.id, 0)
            if share <= 0:
                continue
            vals_list.append({
                'production_id': self.id,
                'coop_id': self.coop_id.id,
                'batch_id': line.batch_id.id,
                'genetics_id': line.batch_id.genetics_id.id,
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

    def _poultry_get_egg_uom(self, uom):
        """
        Devuelve la unidad marcada como Huevo (is_poultry_egg) en la categoría
        de la UdM recibida. Es la unidad de referencia para convertir a huevos.
        """
        if not uom:
            return self.env['uom.uom']
        return self.env['uom.uom'].search([
            ('category_id', '=', uom.category_id.id),
            ('is_poultry_egg', '=', True),
        ], limit=1)

    def _poultry_qty_to_eggs(self, qty, uom):
        """
        Convierte una cantidad en su UdM a cantidad de Huevos, usando la
        conversión estándar de Odoo dentro de la categoría hacia la unidad
        marcada como Huevo de esa misma categoría.

        Devuelve None si la categoría de la UdM no tiene unidad Huevo, es decir,
        si la UdM no representa huevos (p. ej. film en gramos, cajas en unidades).
        Nunca cruza categorías, por lo que no dispara el error de Odoo de
        "distinta categoría".
        """
        egg_uom = self._poultry_get_egg_uom(uom)
        if not egg_uom:
            return None
        return uom._compute_quantity(qty or 0.0, egg_uom)

    def _poultry_validate_kit_consumption_equals_finished(self):
        """
        Valida que, en una OF marcada como Mix Producto Avícola, la suma de los
        componentes que SON huevos (convertidos a Huevos según la UdM Huevo de
        cada categoría) sea igual a la cantidad de huevos producida.

        Los componentes que no son huevos (film, cajas, etc., medidos en gramos
        o unidades) se ignoran: pueden mezclarse libremente en la OF. El producido
        y los componentes huevo pueden estar en categorías de UdM distintas.
        """
        self.ensure_one()
        finished_qty = self._poultry_get_finished_qty_for_validation()
        finished_eggs = self._poultry_qty_to_eggs(finished_qty, self.product_uom_id)
        if finished_eggs is None:
            raise UserError(
                f'No hay una unidad marcada como Huevo (referencia) en la categoría '
                f'"{self.product_uom_id.category_id.display_name}" del producto a producir. '
                f'Configúrela en Gestión Avícola > Unidades de Medida.'
            )
        egg_uom = self._poultry_get_egg_uom(self.product_uom_id)

        total_eggs = 0.0
        for move in self.move_raw_ids.filtered(lambda m: m.state != 'cancel'):
            consumed = self._poultry_get_move_consumed_qty(move)
            consumed_eggs = self._poultry_qty_to_eggs(consumed, move.product_uom)
            if consumed_eggs is None:
                # Componente que no es huevo (p. ej. film en gramos): no participa del balance.
                continue
            total_eggs += consumed_eggs

        rounding = egg_uom.rounding or 0.01
        if float_compare(total_eggs, finished_eggs, precision_rounding=rounding) != 0:
            raise UserError(
                f'Validación KIT: la suma de huevos consumidos ({total_eggs:g} huevos) '
                f'no coincide con los huevos producidos ({finished_eggs:g} huevos).'
            )

    def button_mark_done(self):
        for mo in self:
            tmpl = mo.product_id.product_tmpl_id if mo.product_id else False
            if tmpl and getattr(tmpl, 'poultry_validate_kit_consumption', False):
                mo._poultry_validate_kit_consumption_equals_finished()
        result = super().button_mark_done()
        # La mortandad se guarda en la tabla recién al confirmar/producir la OF de Huevo
        # sin Clasificar (no en cada guardado del total). Se sincroniza ANTES de calcular
        # los indicadores para que las Aves Vivas del día reflejen la mortandad registrada,
        # igual que en el recálculo histórico (_poultry_rebuild_all_indicator_values). Si
        # el total supera las aves vivas, _poultry_sync_mortality levanta UserError y toda
        # la operación (incluido el producido) se revierte.
        for mo in self:
            if mo.coop_close_id:
                mo._poultry_sync_mortality()
            mo._poultry_compute_all_indicator_values()
        return result

    def _poultry_get_consumption_uom(self, xml_id):
        uom = self.env.ref(xml_id, raise_if_not_found=False)
        return uom or self.env['uom.uom']

    def _poultry_get_active_lines_and_birds(self, target_date):
        """Devuelve (lines, birds_by_line, total_birds): las poultry.batch.coop.line
        activas para self.coop_id en target_date, y la población viva de cada una.
        Compartido por el cálculo de consumo y el de producción de huevos."""
        self.ensure_one()
        lines = self.env['poultry.batch.coop.line'].search([
            ('coop_id', '=', self.coop_id.id),
            ('active', '=', True),
            ('date_from', '<=', target_date),
            '|', ('date_to', '=', False), ('date_to', '>=', target_date),
        ])
        birds_by_line = {line.id: line._get_live_bird_count_on(target_date) for line in lines}
        return lines, birds_by_line, sum(birds_by_line.values())

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

        lines, birds_by_line, total_birds = self._poultry_get_active_lines_and_birds(target_date)
        if not lines or total_birds <= 0:
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

        for line in lines:
            birds = birds_by_line[line.id]
            if birds <= 0:
                continue
            if feed_indicator and feed_qty_kg > 0:
                Value._set_value(line.batch_id, self.coop_id, target_date, feed_indicator,
                                  feed_g_per_bird_day,
                                  numerator=feed_g_per_bird_day * birds, denominator=birds,
                                  production=self)
            if water_indicator and water_qty_l > 0:
                Value._set_value(line.batch_id, self.coop_id, target_date, water_indicator,
                                  water_ml_per_bird_day,
                                  numerator=water_ml_per_bird_day * birds, denominator=birds,
                                  production=self)

    def _poultry_compute_egg_production_indicator_values(self):
        """Al cerrar la OF de Huevo sin Clasificar: % Ave-Día, Huevos Acumulados
        Ave-Día y Huevos Acumulados Ave-Alojada por lote, repartiendo el total de
        huevos del día (self.product_qty, fijado desde la creación de la OF en
        poultry.coop.close, sin depender del estado MRP en que quede) entre los
        lotes presentes en el galpón según su población viva ese día.

        % Ave-Día es una tasa diaria (huevos de este lote ese día / aves vivas ese
        día). Los dos acumulados son independientes entre sí: NO se derivan del %
        Ave-Día ya calculado, se recalculan cada día desde los mismos datos crudos.
        Ave-Día acumulado suma cada día huevos/aves VIVAS ese día. Ave-Alojada
        acumulado suma cada día huevos/aves ALOJADAS AL INICIO (fija, no baja con la
        mortalidad ni sube con nuevos Ingresos) — solo se calcula si el lote ya tiene
        un Cambio de Período a Producción registrado (poultry.batch.period_change_ids,
        que fija housed_bird_count/production_start_date) y la fecha es posterior a
        esa Fecha de Entrada en Producción; antes de eso no hay una base fija
        válida, porque el lote puede seguir recibiendo Ingresos o todavía no haber
        cambiado de galpón/período."""
        self.ensure_one()
        if not self.coop_close_id or not self.coop_id:
            return
        target_date = self.coop_close_id.date or self._get_scheduled_date()
        total_eggs = self.product_qty or 0.0
        if total_eggs <= 0:
            return

        lines, birds_by_line, total_birds = self._poultry_get_active_lines_and_birds(target_date)
        if not lines or total_birds <= 0:
            return

        Indicator = self.env['poultry.indicator']
        rate_indicator = Indicator.search(
            [('category', '=', 'egg_production'), ('accumulation_type', '=', 'none'),
             ('active', '=', True)], limit=1)
        rate_original_indicator = Indicator.search(
            [('category', '=', 'egg_production'), ('accumulation_type', '=', 'original_rate'),
             ('active', '=', True)], limit=1)
        cumulative_live_indicator = Indicator.search(
            [('category', '=', 'egg_production'), ('accumulation_type', '=', 'live'),
             ('active', '=', True)], limit=1)
        cumulative_housed_indicator = Indicator.search(
            [('category', '=', 'egg_production'), ('accumulation_type', '=', 'housed'),
             ('active', '=', True)], limit=1)
        if not any((rate_indicator, rate_original_indicator, cumulative_live_indicator,
                    cumulative_housed_indicator)):
            return

        Value = self.env['poultry.batch.indicator.value']
        # Uniforme por ave: mismo huevos/ave para todos los lotes que comparten el galpón.
        eggs_per_bird_day = total_eggs / total_birds

        for line in lines:
            birds = birds_by_line[line.id]
            if birds <= 0:
                continue
            batch_egg_share = eggs_per_bird_day * birds

            if rate_indicator:
                Value._set_value(line.batch_id, self.coop_id, target_date, rate_indicator,
                                  eggs_per_bird_day * 100.0,
                                  numerator=batch_egg_share * 100.0, denominator=birds,
                                  production=self)

            if rate_original_indicator and line.batch_id.bird_count:
                # % Postura sobre Aves Originales del Lote: misma cantidad de huevos
                # de hoy que arriba, pero contra la Cantidad de Aves del lote (fija,
                # no la población viva de hoy).
                postura_original_pct = (batch_egg_share / line.batch_id.bird_count) * 100.0
                Value._set_value(line.batch_id, self.coop_id, target_date, rate_original_indicator,
                                  postura_original_pct,
                                  numerator=batch_egg_share * 100.0, denominator=line.batch_id.bird_count,
                                  production=self)

            if cumulative_live_indicator:
                previous = Value.search([
                    ('batch_id', '=', line.batch_id.id),
                    ('indicator_id', '=', cumulative_live_indicator.id),
                    ('date', '<', target_date),
                ], order='date desc', limit=1)
                previous_total = previous.value if previous else 0.0
                Value._set_value(line.batch_id, self.coop_id, target_date, cumulative_live_indicator,
                                  previous_total + eggs_per_bird_day,
                                  numerator=batch_egg_share, denominator=birds,
                                  production=self)

            if cumulative_housed_indicator:
                batch = line.batch_id
                # Solo se calcula si el lote ya tiene un Cambio de Período a
                # Producción registrado (poultry.batch.period_change_ids) y la fecha
                # es posterior a la Fecha de Entrada en Producción: antes de eso no
                # hay una base fija válida (el lote puede seguir recibiendo Ingresos).
                if (batch.housed_bird_count and batch.production_start_date
                        and target_date >= batch.production_start_date):
                    previous = Value.search([
                        ('batch_id', '=', batch.id),
                        ('indicator_id', '=', cumulative_housed_indicator.id),
                        ('date', '<', target_date),
                    ], order='date desc', limit=1)
                    previous_total = previous.value if previous else 0.0
                    eggs_per_housed_bird = batch_egg_share / batch.housed_bird_count
                    Value._set_value(batch, self.coop_id, target_date, cumulative_housed_indicator,
                                      previous_total + eggs_per_housed_bird,
                                      numerator=batch_egg_share, denominator=batch.housed_bird_count,
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
        mortalities = self.env['poultry.mortality'].search([('production_id', '=', self.id)])
        if not mortalities:
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
        for mortality in mortalities:
            batch = mortality.batch_id
            dead = mortality.dead_count
            base = mortality.live_bird_count + dead
            if base <= 0:
                continue
            daily_pct = mortality.mortality_pct

            if rate_indicator:
                Value._set_value(batch, self.coop_id, target_date, rate_indicator,
                                  daily_pct, numerator=dead * 100.0, denominator=base,
                                  production=self)

            if cumulative_live_indicator:
                previous = Value.search([
                    ('batch_id', '=', batch.id),
                    ('indicator_id', '=', cumulative_live_indicator.id),
                    ('date', '<', target_date),
                ], order='date desc', limit=1)
                previous_total = previous.value if previous else 0.0
                Value._set_value(batch, self.coop_id, target_date, cumulative_live_indicator,
                                  previous_total + daily_pct,
                                  numerator=dead * 100.0, denominator=base, production=self)

            if cumulative_housed_indicator:
                if (batch.housed_bird_count and batch.production_start_date
                        and target_date >= batch.production_start_date):
                    previous = Value.search([
                        ('batch_id', '=', batch.id),
                        ('indicator_id', '=', cumulative_housed_indicator.id),
                        ('date', '<', target_date),
                    ], order='date desc', limit=1)
                    previous_total = previous.value if previous else 0.0
                    dead_pct_housed = dead / batch.housed_bird_count * 100.0
                    Value._set_value(batch, self.coop_id, target_date, cumulative_housed_indicator,
                                      previous_total + dead_pct_housed,
                                      numerator=dead * 100.0, denominator=batch.housed_bird_count,
                                      production=self)

            if cumulative_original_indicator and batch.bird_count:
                previous = Value.search([
                    ('batch_id', '=', batch.id),
                    ('indicator_id', '=', cumulative_original_indicator.id),
                    ('date', '<', target_date),
                ], order='date desc', limit=1)
                previous_total = previous.value if previous else 0.0
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

        lines, birds_by_line, total_birds = self._poultry_get_active_lines_and_birds(target_date)
        if not lines:
            return

        Value = self.env['poultry.batch.indicator.value']
        for line in lines:
            batch = line.batch_id
            if not batch.bird_count:
                continue
            live_today = birds_by_line.get(line.id, 0)
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

        lines, birds_by_line, total_birds = self._poultry_get_active_lines_and_birds(target_date)
        if not lines or total_birds <= 0:
            return

        Indicator = self.env['poultry.indicator']
        mass_housed_indicator = Indicator.search(
            [('category', '=', 'egg_mass'), ('accumulation_type', '=', 'housed'),
             ('active', '=', True)], limit=1)
        weight_indicator = Indicator.search(
            [('category', '=', 'egg_weight'), ('accumulation_type', '=', 'none'),
             ('active', '=', True)], limit=1)
        if not mass_housed_indicator and not weight_indicator:
            return

        Value = self.env['poultry.batch.indicator.value']
        mass_kg_per_bird_day = total_mass_kg / total_birds

        for line in lines:
            birds = birds_by_line[line.id]
            if birds <= 0:
                continue
            batch = line.batch_id

            if mass_housed_indicator:
                if (batch.housed_bird_count and batch.production_start_date
                        and target_date >= batch.production_start_date):
                    batch_mass_kg = mass_kg_per_bird_day * birds
                    previous = Value.search([
                        ('batch_id', '=', batch.id),
                        ('indicator_id', '=', mass_housed_indicator.id),
                        ('date', '<', target_date),
                    ], order='date desc', limit=1)
                    previous_total = previous.value if previous else 0.0
                    kg_per_housed_bird = batch_mass_kg / batch.housed_bird_count
                    Value._set_value(batch, self.coop_id, target_date, mass_housed_indicator,
                                      previous_total + kg_per_housed_bird,
                                      numerator=batch_mass_kg, denominator=batch.housed_bird_count,
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

        lines, birds_by_line, total_birds = self._poultry_get_active_lines_and_birds(target_date)
        if not lines or total_birds <= 0:
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

        for line in lines:
            birds = birds_by_line[line.id]
            if birds <= 0:
                continue
            batch = line.batch_id
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

