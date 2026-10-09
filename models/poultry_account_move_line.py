# -*- coding: utf-8 -*-

from odoo import api, fields, models

# Huevos por cajón. Misma constante que usa el módulo en stock.move, recolección e indicadores.
EGGS_PER_CRATE = 360.0


class PoultryAccountMoveLine(models.Model):
    """
    Extiende account.move.line para productos de Gestión Avícola.
    Añade quantity_huevos y quantity_cajones con la MISMA lógica que stock.move
    (cantidad × factor de la UdM de la línea = huevos; huevos / 360 = cajones),
    con signo según el tipo de comprobante: factura positiva, nota de crédito negativa.
    Así las ventas y compras de huevos se pueden analizar en cajones sin convertir
    en los reportes ni en los tableros.
    """
    _inherit = 'account.move.line'

    quantity_huevos = fields.Float(
        string='Huevos',
        compute='_compute_poultry_quantities',
        store=True,
        digits=(16, 2),
        help='Cantidad de la línea convertida a Huevos (unidad raíz de la familia). '
             'Positiva en facturas, negativa en notas de crédito. Solo productos marcados '
             '"Usar en Producción de Huevos".',
    )
    quantity_cajones = fields.Float(
        string='Cajones',
        compute='_compute_poultry_quantities',
        store=True,
        digits=(16, 2),
        help='Cantidad convertida a Cajones (Huevos / 360). Positiva en facturas, '
             'negativa en notas de crédito.',
    )

    @api.depends('quantity', 'product_uom_id', 'product_uom_id.factor', 'product_id',
                 'display_type', 'move_id.move_type')
    def _compute_poultry_quantities(self):
        for line in self:
            product = line.product_id
            if (
                line.display_type != 'product'
                or not product
                or not product.product_tmpl_id.is_egg_production
                or not line.product_uom_id
            ):
                line.quantity_huevos = 0.0
                line.quantity_cajones = 0.0
                continue

            # Odoo 19: uom.uom.factor es la cantidad absoluta respecto a la unidad raíz
            # de la familia (Huevo). Misma conversión que stock.move.quantity_huevos.
            ratio = line.product_uom_id.factor or 1.0
            sign = -1.0 if line.move_id.move_type in ('out_refund', 'in_refund') else 1.0
            qty_huevos = sign * (line.quantity or 0.0) * ratio
            line.quantity_huevos = qty_huevos
            line.quantity_cajones = qty_huevos / EGGS_PER_CRATE if qty_huevos else 0.0
