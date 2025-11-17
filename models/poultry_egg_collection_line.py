# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PoultryEggCollectionLine(models.Model):
    _name = 'poultry.egg.collection.line'
    _description = 'Línea de Recolección de Producción de Huevos'
    _order = 'collection_id, product_variant_id'

    collection_id = fields.Many2one('poultry.egg.collection', string='Recolección', 
                                     required=True, ondelete='cascade', index=True)
    product_variant_id = fields.Many2one('product.product', string='Variante del Producto', 
                                          required=True, domain="[('type', '=', 'product')]")
    product_variant_name = fields.Char(string='Variante', related='product_variant_id.name', 
                                        readonly=True, store=False)
    
    # Unidades de medida (se obtienen automáticamente del producto o configuración)
    # No las almacenamos por ahora para evitar problemas de base de datos
    uom_box_id = fields.Many2one('uom.uom', string='Unidad Cajón', 
                                  compute='_compute_uom_ids', store=False)
    uom_map_id = fields.Many2one('uom.uom', string='Unidad Maple', 
                                  compute='_compute_uom_ids', store=False)
    uom_egg_id = fields.Many2one('uom.uom', string='Unidad Huevo', 
                                  compute='_compute_uom_ids', store=False)
    
    # Cantidades iniciales (al inicio de la recolección)
    initial_box = fields.Float(string='Cajón Inicial', default=0.0, digits=(16, 2))
    initial_map = fields.Float(string='Maple Inicial', default=0.0, digits=(16, 2))
    initial_egg = fields.Float(string='Huevo Inicial', default=0.0, digits=(16, 2))
    
    # Cantidades finales (al final de la recolección)
    final_box = fields.Float(string='Cajón Final', default=0.0, digits=(16, 2))
    final_map = fields.Float(string='Maple Final', default=0.0, digits=(16, 2))
    final_egg = fields.Float(string='Huevo Final', default=0.0, digits=(16, 2))
    
    # Cantidades producidas (calculadas: final - inicial)
    produced_box = fields.Float(string='Cajón Producido', compute='_compute_production', 
                                 store=True, digits=(16, 2))
    produced_map = fields.Float(string='Maple Producido', compute='_compute_production', 
                                 store=True, digits=(16, 2))
    produced_egg = fields.Float(string='Huevo Producido', compute='_compute_production', 
                                 store=True, digits=(16, 2))
    
    @api.depends('product_variant_id', 'collection_id.product_id')
    def _compute_uom_ids(self):
        """Obtiene las unidades de medida Cajón, Maple y Huevo en cualquier categoría"""
        for line in self:
            # Buscar las unidades de medida por nombre en cualquier categoría
            # Cajón
            box_uom = self.env['uom.uom'].search([
                ('name', 'ilike', 'Cajón'),
            ], limit=1)
            if not box_uom:
                box_uom = self.env['uom.uom'].search([
                    ('name', 'ilike', 'Cajon'),
                ], limit=1)
            
            # Maple
            map_uom = self.env['uom.uom'].search([
                ('name', 'ilike', 'Maple'),
            ], limit=1)
            
            # Huevo
            egg_uom = self.env['uom.uom'].search([
                ('name', 'ilike', 'Huevo'),
            ], limit=1)
            if not egg_uom:
                egg_uom = self.env['uom.uom'].search([
                    ('name', 'ilike', 'Unidades'),
                ], limit=1)
            
            line.uom_box_id = box_uom.id if box_uom else False
            line.uom_map_id = map_uom.id if map_uom else False
            line.uom_egg_id = egg_uom.id if egg_uom else False
    
    @api.depends('final_box', 'initial_box', 'final_map', 'initial_map', 
                 'final_egg', 'initial_egg')
    def _compute_production(self):
        """Calcula la producción real (final - inicial)"""
        for line in self:
            line.produced_box = line.final_box - line.initial_box
            line.produced_map = line.final_map - line.initial_map
            line.produced_egg = line.final_egg - line.initial_egg
    
    _sql_constraints = [
        ('unique_collection_variant', 'unique(collection_id, product_variant_id)',
         'No puede haber dos líneas con la misma variante en una recolección.'),
    ]

