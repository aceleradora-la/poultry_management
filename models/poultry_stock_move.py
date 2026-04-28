# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PoultryStockMove(models.Model):
    """
    Extiende stock.move para productos de Gestión Avícola.
    Añade campos quantity_huevos y quantity_cajones con signo (positivo/negativo)
    para permitir totalizar correctamente en reportes.
    """
    _inherit = 'stock.move'

    quantity_huevos = fields.Float(
        string='Huevos',
        compute='_compute_poultry_quantities',
        store=True,
        digits=(16, 2),
        help='Cantidad convertida a Huevos (unidad de referencia). Conserva el signo para totalizar.'
    )
    quantity_cajones = fields.Float(
        string='Cajones',
        compute='_compute_poultry_quantities',
        store=True,
        digits=(16, 2),
        help='Cantidad convertida a Cajones (Huevos/360). Conserva el signo para totalizar.'
    )

    @api.depends('product_uom_qty', 'product_uom', 'product_id', 'location_id', 'location_dest_id')
    def _compute_poultry_quantities(self):
        """
        Convierte product_uom_qty a Huevos y Cajones usando la misma lógica
        que el Reporte de Producción. Aplica signo según dirección del movimiento:
        - Entrada a stock (internal): positivo
        - Salida de stock (internal): negativo
        - Transferencia interna: 0 (sin efecto neto)
        """
        for move in self:
            qty_huevos = 0.0
            qty_cajones = 0.0

            if not move.product_id or not move.product_id.product_tmpl_id.is_egg_production:
                move.quantity_huevos = 0.0
                move.quantity_cajones = 0.0
                continue

            if not move.product_uom:
                move.quantity_huevos = 0.0
                move.quantity_cajones = 0.0
                continue

            # Signo según dirección: entrada +, salida -, transferencia interna 0
            loc_src = move.location_id.usage if move.location_id else None
            loc_dest = move.location_dest_id.usage if move.location_dest_id else None
            if loc_dest == 'internal' and loc_src != 'internal':
                sign = 1.0   # Entrada a stock
            elif loc_src == 'internal' and loc_dest != 'internal':
                sign = -1.0  # Salida de stock
            else:
                sign = 0.0   # Transferencia interna u otro caso

            # Odoo 19: uom.uom usa factor (antes ratio en versiones antiguas).
            ratio = getattr(move.product_uom, 'factor', None) or 1.0
            qty_huevos = sign * (move.product_uom_qty or 0.0) * ratio
            qty_cajones = qty_huevos / 360.0 if qty_huevos else 0.0

            move.quantity_huevos = qty_huevos
            move.quantity_cajones = qty_cajones
