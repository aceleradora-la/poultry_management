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

    # Copia congelada del Tipo de Consumo Avícola de la línea de la Lista de
    # Materiales, tomada al crear el movimiento (y, para movimientos previos, al
    # recalcular por primera vez). Los indicadores de Consumo de Alimento/Agua y de
    # Conversión Alimenticia usan ESTE valor, no el actual de la Lista: así, si más
    # adelante se cambia el componente de alimento en la Lista, el consumo ya
    # calculado de las OFs pasadas no se altera. Vacío = todavía no congelado
    # (se resuelve contra la Lista en vivo la próxima vez, ver _poultry_consumption_type).
    poultry_consumption_type = fields.Selection([
        ('none', 'Ninguno'),
        ('feed', 'Alimento'),
        ('water', 'Agua'),
    ], string='Tipo de Consumo Avícola (congelado)', copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        """Al crear un movimiento con línea de Lista de Materiales, congela su Tipo
        de Consumo Avícola (Alimento/Agua) en el propio movimiento."""
        line_ids = [v['bom_line_id'] for v in vals_list
                    if v.get('bom_line_id') and not v.get('poultry_consumption_type')]
        if line_ids:
            types = {line.id: line.poultry_consumption_type
                     for line in self.env['mrp.bom.line'].browse(line_ids)}
            for vals in vals_list:
                if not vals.get('poultry_consumption_type') and vals.get('bom_line_id'):
                    ct = types.get(vals['bom_line_id'])
                    if ct in ('feed', 'water'):
                        vals['poultry_consumption_type'] = ct
        return super().create(vals_list)

    def _poultry_consumption_type(self):
        """Tipo de Consumo Avícola del movimiento (feed/water/none). Prioriza el
        valor congelado; si está vacío (movimiento previo al snapshot), toma el de
        la línea de la Lista de Materiales en vivo y LO CONGELA en el movimiento,
        para que un cambio posterior del componente de alimento en la Lista no
        altere este consumo. Devuelve 'none' si no aplica."""
        self.ensure_one()
        if self.poultry_consumption_type:
            return self.poultry_consumption_type
        live = self.bom_line_id.poultry_consumption_type if self.bom_line_id else False
        if live in ('feed', 'water'):
            self.sudo().poultry_consumption_type = live
            return live
        return 'none'

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

            # Usar ratio del UoM para convertir a unidad de referencia (Huevos)
            ratio = getattr(move.product_uom, 'ratio', None) or getattr(move.product_uom, 'factor', 1.0)
            qty_huevos = sign * (move.product_uom_qty or 0.0) * ratio
            qty_cajones = qty_huevos / 360.0 if qty_huevos else 0.0

            move.quantity_huevos = qty_huevos
            move.quantity_cajones = qty_cajones
