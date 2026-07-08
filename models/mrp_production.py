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

    def _poultry_get_coop_batches_and_birds(self, target_date):
        """Devuelve (batches, birds_by_batch, total_birds): los lotes activos del galpón
        y su población viva a la fecha (cantidad de aves menos mortandad acumulada, sin
        contar los registros de esta misma OF). En 19.0 el lote pertenece a un galpón
        (poultry.batch.coop_id) y no hay historial por fecha, así que se usan los lotes
        actualmente asignados al galpón."""
        self.ensure_one()
        Mortality = self.env['poultry.mortality']
        batches = self.coop_id.batch_ids.filtered(lambda b: b.active and b.bird_count > 0)
        birds_by_batch = {}
        for batch in batches:
            deaths = Mortality.search([
                ('batch_id', '=', batch.id),
                ('active', '=', True),
                ('date', '<=', target_date),
                ('production_id', '!=', self.id),
            ])
            live = max(batch.bird_count - sum(deaths.mapped('dead_count')), 0)
            birds_by_batch[batch.id] = live
        return batches, birds_by_batch, sum(birds_by_batch.values())

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
        return super().button_mark_done()

