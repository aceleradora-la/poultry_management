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
        marcada como Huevo. Funciona aunque producido y componentes estén en
        categorías distintas, porque cada categoría tiene su propio Huevo.
        """
        egg_uom = self._poultry_get_egg_uom(uom)
        if not egg_uom:
            raise UserError(
                f'No hay una unidad marcada como Huevo (referencia) en la categoría '
                f'"{uom.category_id.display_name}" de la unidad "{uom.name}". '
                f'Configúrela en Gestión Avícola > Unidades de Medida.'
            )
        return uom._compute_quantity(qty or 0.0, egg_uom)

    def _poultry_validate_kit_consumption_equals_finished(self):
        """
        Valida que la suma de cantidades consumidas de componentes (move_raw_ids),
        convertidas a cantidad de Huevos, sea igual a la cantidad producida
        (también en Huevos). Cada UdM se convierte a la unidad Huevo de su propia
        categoría, por lo que producido y componentes pueden tener UdM distintas.
        """
        self.ensure_one()
        finished_qty = self._poultry_get_finished_qty_for_validation()
        finished_eggs = self._poultry_qty_to_eggs(finished_qty, self.product_uom_id)
        egg_uom = self._poultry_get_egg_uom(self.product_uom_id)

        total_eggs = 0.0
        for move in self.move_raw_ids.filtered(lambda m: m.state != 'cancel'):
            consumed = self._poultry_get_move_consumed_qty(move)
            total_eggs += self._poultry_qty_to_eggs(consumed, move.product_uom)

        rounding = egg_uom.rounding or 0.01
        if float_compare(total_eggs, finished_eggs, precision_rounding=rounding) != 0:
            raise UserError(
                f'Validación KIT: la suma consumida ({total_eggs:g} huevos) '
                f'no coincide con lo producido ({finished_eggs:g} huevos).'
            )

    def button_mark_done(self):
        for mo in self:
            tmpl = mo.product_id.product_tmpl_id if mo.product_id else False
            if tmpl and getattr(tmpl, 'poultry_validate_kit_consumption', False):
                mo._poultry_validate_kit_consumption_equals_finished()
        return super().button_mark_done()

