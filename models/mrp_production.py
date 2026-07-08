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

    @api.model_create_multi
    def create(self, vals_list):
        productions = super().create(vals_list)
        for production, vals in zip(productions, vals_list):
            if ('poultry_dead_count_total' in vals or 'coop_id' in vals) and production.coop_close_id:
                production._poultry_sync_mortality()
        return productions

    def write(self, vals):
        result = super().write(vals)
        if 'poultry_dead_count_total' in vals or 'coop_id' in vals:
            for production in self.filtered(lambda p: p.coop_close_id):
                production._poultry_sync_mortality()
        return result

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
        for mo in self:
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
        cumulative_live_indicator = Indicator.search(
            [('category', '=', 'egg_production'), ('accumulation_type', '=', 'live'),
             ('active', '=', True)], limit=1)
        cumulative_housed_indicator = Indicator.search(
            [('category', '=', 'egg_production'), ('accumulation_type', '=', 'housed'),
             ('active', '=', True)], limit=1)
        if not rate_indicator and not cumulative_live_indicator and not cumulative_housed_indicator:
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

