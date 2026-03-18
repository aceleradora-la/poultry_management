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
    
    @api.onchange('coop_id')
    def _onchange_coop_id(self):
        """Al seleccionar un galpón, carga el producto y la lista de materiales activa"""
        if self.coop_id:
            # Solo cargar si el galpón tiene una lista de materiales activa
            if self.coop_id.active_bom_id:
                active_bom = self.coop_id.active_bom_id
                # Cargar el producto de la BOM activa
                if active_bom.bom_product_id:
                    self.product_id = active_bom.bom_product_id
                    # Cargar la lista de materiales (BOM)
                    if active_bom.bom_id:
                        self.bom_id = active_bom.bom_id
                        # Actualizar los componentes basándose en la BOM si el método existe
                        if hasattr(self, '_onchange_bom_id'):
                            try:
                                self._onchange_bom_id()
                            except:
                                pass
                        # Alternativamente, actualizar manualmente los componentes
                        elif hasattr(self, '_onchange_product_id') and self.bom_id:
                            try:
                                self._onchange_product_id()
                            except:
                                pass

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
        Valida que la suma de cantidades consumidas de componentes (move_raw_ids),
        convertidas a la UdM del producto final, sea igual a la cantidad producida.
        """
        self.ensure_one()
        finished_uom = self.product_uom_id
        finished_qty = self._poultry_get_finished_qty_for_validation()

        total = 0.0
        for move in self.move_raw_ids.filtered(lambda m: m.state != 'cancel'):
            consumed = self._poultry_get_move_consumed_qty(move)
            total += move.product_uom._compute_quantity(consumed, finished_uom)

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

