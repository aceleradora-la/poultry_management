# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PoultryEggCollectionLineUom(models.Model):
    _name = 'poultry.egg.collection.line.uom'
    _description = 'Valores de Unidades de Medida por Línea de Recolección'
    _order = 'line_id, uom_ratio desc'
    
    line_id = fields.Many2one('poultry.egg.collection.line', string='Línea de Recolección',
                              required=True, ondelete='cascade', index=True)
    uom_id = fields.Many2one('uom.uom', string='Unidad de Medida', required=True, index=True)
    uom_ratio = fields.Float(string='Proporción', related='uom_id.ratio', readonly=True, store=True)
    uom_display_name = fields.Char(string='Nombre Mostrar', related='uom_id.poultry_display_name', readonly=True, store=True)
    
    # Valores iniciales, finales y producidos
    initial_qty = fields.Float(string='Cantidad Inicial', default=0.0, digits=(16, 2))
    final_qty = fields.Float(string='Cantidad Final', default=0.0, digits=(16, 2))
    produced_qty = fields.Float(string='Cantidad Producida', default=0.0, digits=(16, 2),
                                help='Calculado automáticamente por el sistema basándose en la producción total')
    
    _sql_constraints = [
        ('unique_line_uom', 'unique(line_id, uom_id)',
         'No puede haber dos registros con la misma unidad de medida en una línea.'),
    ]

