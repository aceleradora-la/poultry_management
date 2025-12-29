# -*- coding: utf-8 -*-

from odoo import models, fields, api
import math


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
    
    # Relación con valores de unidades de medida (nuevo sistema dinámico)
    uom_value_ids = fields.One2many('poultry.egg.collection.line.uom', 'line_id',
                                     string='Valores por Unidad de Medida')
    
    # Campos legacy (mantener por compatibilidad, pero deprecados)
    # Estos se mantienen para migración gradual
    uom_box_id = fields.Many2one('uom.uom', string='Unidad Cajón', 
                                  compute='_compute_uom_ids', store=False)
    uom_map_id = fields.Many2one('uom.uom', string='Unidad Maple', 
                                  compute='_compute_uom_ids', store=False)
    uom_egg_id = fields.Many2one('uom.uom', string='Unidad Huevo', 
                                  compute='_compute_uom_ids', store=False)
    
    # Campos legacy sincronizados con uom_value_ids
    # Estos campos se sincronizan bidireccionalmente con uom_value_ids para mostrar en el tree
    # Los nombres se actualizan dinámicamente usando _update_field_strings
    initial_box = fields.Float(default=0.0, digits=(16, 2),
                               compute='_sync_uom_values_to_legacy', inverse='_sync_legacy_to_uom_values', store=False)
    initial_map = fields.Float(default=0.0, digits=(16, 2),
                               compute='_sync_uom_values_to_legacy', inverse='_sync_legacy_to_uom_values', store=False)
    initial_egg = fields.Float(default=0.0, digits=(16, 2),
                               compute='_sync_uom_values_to_legacy', inverse='_sync_legacy_to_uom_values', store=False)
    
    final_box = fields.Float(default=0.0, digits=(16, 2),
                             compute='_sync_uom_values_to_legacy', inverse='_sync_legacy_to_uom_values', store=False)
    final_map = fields.Float(default=0.0, digits=(16, 2),
                             compute='_sync_uom_values_to_legacy', inverse='_sync_legacy_to_uom_values', store=False)
    final_egg = fields.Float(default=0.0, digits=(16, 2),
                             compute='_sync_uom_values_to_legacy', inverse='_sync_legacy_to_uom_values', store=False)
    
    # Campos para almacenar nombres dinámicos de las columnas
    uom_1_name = fields.Char(string='Unidad 1', compute='_compute_uom_display_names', store=False)
    uom_2_name = fields.Char(string='Unidad 2', compute='_compute_uom_display_names', store=False)
    uom_3_name = fields.Char(string='Unidad 3', compute='_compute_uom_display_names', store=False)
    
    @api.model
    def _update_field_strings(self):
        """Actualiza los nombres de los campos legacy dinámicamente basándose en uom_value_ids"""
        # Este método se puede llamar desde la vista o desde un cron para actualizar los nombres
        # Por ahora, los nombres se manejarán en la vista usando los campos uom_X_name
        pass
    
    produced_box = fields.Float(string='Cajón Producido', compute='_compute_production', 
                                 store=True, digits=(16, 2))
    produced_map = fields.Float(string='Maple Producido', compute='_compute_production', 
                                 store=True, digits=(16, 2))
    produced_egg = fields.Float(string='Huevo Producido', compute='_compute_production', 
                                 store=True, digits=(16, 2))
    
    # Campo para almacenar el total de producción en unidad de referencia
    total_produced_reference = fields.Float(string='Total Producido (Unidad Ref)', 
                                             compute='_compute_production', 
                                             store=True, digits=(16, 2),
                                             help='Total producido en la unidad de medida de referencia (Huevo)')
    
    @api.depends('product_variant_id')
    def _compute_uom_ids(self):
        """Obtiene las unidades de medida (método legacy)"""
        for line in self:
            # Buscar las unidades de medida por nombre en cualquier categoría
            box_uom = self.env['uom.uom'].search([
                ('name', 'ilike', 'Cajón'),
            ], limit=1)
            if not box_uom:
                box_uom = self.env['uom.uom'].search([
                    ('name', 'ilike', 'Cajon'),
                ], limit=1)
            
            map_uom = self.env['uom.uom'].search([
                ('name', 'ilike', 'Maple'),
            ], limit=1)
            
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
    
    @api.model
    def _get_poultry_uoms(self, product_variant):
        """Obtiene las unidades de medida configuradas para Poultry Management del producto"""
        if not product_variant:
            return self.env['uom.uom']
        
        # Obtener la categoría de unidad de medida del producto
        uom_category = product_variant.uom_id.category_id
        
        # Buscar todas las unidades de medida de esa categoría que estén marcadas para usar en poultry
        uoms = self.env['uom.uom'].search([
            ('category_id', '=', uom_category.id),
            ('use_in_poultry', '=', True),
            ('active', '=', True),
        ], order='ratio desc')  # Ordenar de mayor a menor ratio
        
        return uoms
    
    @api.model
    def _get_reference_uom(self, product_variant):
        """Obtiene la unidad de medida de referencia (ratio = 1.0)"""
        if not product_variant:
            return False
        
        uom_category = product_variant.uom_id.category_id
        reference_uom = self.env['uom.uom'].search([
            ('category_id', '=', uom_category.id),
            ('ratio', '=', 1.0),
            ('active', '=', True),
        ], limit=1)
        
        return reference_uom
    
    @api.depends('uom_value_ids')
    def _compute_uom_display_names(self):
        """Calcula los nombres dinámicos de las unidades de medida para mostrar en el tree"""
        for line in self:
            sorted_uoms = sorted(line.uom_value_ids, key=lambda x: x.uom_ratio or 0.0, reverse=True)
            line.uom_1_name = sorted_uoms[0].uom_display_name if len(sorted_uoms) > 0 else ''
            line.uom_2_name = sorted_uoms[1].uom_display_name if len(sorted_uoms) > 1 else ''
            line.uom_3_name = sorted_uoms[2].uom_display_name if len(sorted_uoms) > 2 else ''
    
    @api.depends('uom_value_ids.initial_qty', 'uom_value_ids.final_qty')
    def _sync_uom_values_to_legacy(self):
        """Sincroniza valores de uom_value_ids a campos legacy para mostrar en el tree"""
        for line in self:
            # Ordenar unidades por ratio descendente
            sorted_uoms = sorted(line.uom_value_ids, key=lambda x: x.uom_ratio or 0.0, reverse=True)
            
            # Mapear a campos legacy (máximo 3 unidades)
            if len(sorted_uoms) > 0:
                line.initial_box = sorted_uoms[0].initial_qty
                line.final_box = sorted_uoms[0].final_qty
            else:
                line.initial_box = 0.0
                line.final_box = 0.0
                
            if len(sorted_uoms) > 1:
                line.initial_map = sorted_uoms[1].initial_qty
                line.final_map = sorted_uoms[1].final_qty
            else:
                line.initial_map = 0.0
                line.final_map = 0.0
                
            if len(sorted_uoms) > 2:
                line.initial_egg = sorted_uoms[2].initial_qty
                line.final_egg = sorted_uoms[2].final_qty
            else:
                line.initial_egg = 0.0
                line.final_egg = 0.0
    
    def _sync_legacy_to_uom_values(self):
        """Sincroniza valores de campos legacy a uom_value_ids cuando se editan en el tree"""
        for line in self:
            sorted_uoms = sorted(line.uom_value_ids, key=lambda x: x.uom_ratio or 0.0, reverse=True)
            
            # Actualizar valores desde campos legacy
            if len(sorted_uoms) > 0:
                sorted_uoms[0].write({
                    'initial_qty': line.initial_box,
                    'final_qty': line.final_box,
                })
            if len(sorted_uoms) > 1:
                sorted_uoms[1].write({
                    'initial_qty': line.initial_map,
                    'final_qty': line.final_map,
                })
            if len(sorted_uoms) > 2:
                sorted_uoms[2].write({
                    'initial_qty': line.initial_egg,
                    'final_qty': line.final_egg,
                })
    
    @api.onchange('product_variant_id')
    def _onchange_product_variant_id(self):
        """Al cambiar el producto, actualizar las unidades de medida disponibles"""
        if self.product_variant_id:
            # Obtener las unidades de medida configuradas para este producto
            poultry_uoms = self._get_poultry_uoms(self.product_variant_id)
            
            # Crear o actualizar los registros de unidades de medida
            existing_uoms = {uom_val.uom_id.id: uom_val for uom_val in self.uom_value_ids}
            new_values = []
            
            for uom in poultry_uoms:
                if uom.id in existing_uoms:
                    # Ya existe, mantenerlo
                    continue
                else:
                    # Crear nuevo registro
                    new_values.append((0, 0, {
                        'uom_id': uom.id,
                        'initial_qty': 0.0,
                        'final_qty': 0.0,
                    }))
            
            # Eliminar los que ya no están en la lista
            to_remove = []
            for uom_val in self.uom_value_ids:
                if uom_val.uom_id.id not in poultry_uoms.ids:
                    to_remove.append((2, uom_val.id))
            
            if new_values or to_remove:
                self.uom_value_ids = to_remove + new_values
    
    @api.depends('uom_value_ids.initial_qty', 'uom_value_ids.final_qty', 
                 'uom_value_ids.uom_ratio', 'final_box', 'initial_box', 
                 'final_map', 'initial_map', 'final_egg', 'initial_egg')
    def _compute_production(self):
        """Calcula la producción usando la nueva lógica dinámica"""
        for line in self:
            if not line.product_variant_id:
                line.produced_box = 0.0
                line.produced_map = 0.0
                line.produced_egg = 0.0
                line.total_produced_reference = 0.0
                continue
            
            # Obtener la unidad de referencia
            reference_uom = self._get_reference_uom(line.product_variant_id)
            if not reference_uom:
                # Fallback a método legacy si no hay unidad de referencia
                line.produced_box = line.final_box - line.initial_box
                line.produced_map = line.final_map - line.initial_map
                line.produced_egg = line.final_egg - line.initial_egg
                line.total_produced_reference = 0.0
                continue
            
            # Si hay valores en uom_value_ids, usar el nuevo sistema
            if line.uom_value_ids:
                # Calcular total inicial en unidad de referencia
                total_initial_ref = 0.0
                total_final_ref = 0.0
                
                for uom_val in line.uom_value_ids:
                    ratio = uom_val.uom_ratio or 1.0
                    total_initial_ref += uom_val.initial_qty * ratio
                    total_final_ref += uom_val.final_qty * ratio
                
                # Calcular producción total en unidad de referencia
                total_produced_ref = total_final_ref - total_initial_ref
                line.total_produced_reference = total_produced_ref
                
                # Distribuir la producción de vuelta a las unidades mayores (de mayor a menor ratio)
                # EXCLUYENDO la unidad de referencia, que recibirá el resto al final
                remaining_produced = total_produced_ref
                
                # Filtrar unidades excluyendo la de referencia (ratio = 1.0)
                non_ref_uom_values = line.uom_value_ids.filtered(
                    lambda x: x.uom_id.id != reference_uom.id
                )
                
                # Ordenar unidades de medida por ratio descendente (mayor a menor)
                sorted_uom_values = sorted(non_ref_uom_values, 
                                           key=lambda x: x.uom_ratio or 0.0, 
                                           reverse=True)
                
                # Preparar valores para escribir
                uom_values_to_write = {}
                
                # Distribuir primero a las unidades mayores (excluyendo referencia)
                for uom_val in sorted_uom_values:
                    ratio = uom_val.uom_ratio or 1.0
                    if ratio > 0:
                        # Calcular cuántas unidades completas de esta medida se pueden hacer
                        produced_units = math.floor(remaining_produced / ratio)
                        uom_values_to_write[uom_val.id] = produced_units
                        # Restar lo que ya se asignó
                        remaining_produced -= (produced_units * ratio)
                    else:
                        uom_values_to_write[uom_val.id] = 0.0
                
                # Asignar el resto a la unidad de referencia (siempre debe quedar algo o 0)
                ref_uom_val = line.uom_value_ids.filtered(
                    lambda x: x.uom_id.id == reference_uom.id
                )
                if ref_uom_val:
                    # El resto siempre va a la unidad de referencia
                    uom_values_to_write[ref_uom_val.id] = remaining_produced
                
                # Escribir los valores calculados usando sudo para evitar problemas de permisos
                # y hacerlo fuera del contexto del computed
                uom_records = self.env['poultry.egg.collection.line.uom'].browse(uom_values_to_write.keys())
                for uom_record in uom_records:
                    if uom_record.id in uom_values_to_write:
                        uom_record.sudo().write({
                            'produced_qty': uom_values_to_write[uom_record.id]
                        })
                
                # Mantener compatibilidad con campos legacy (mapear a los primeros 3)
                uom_list = sorted(line.uom_value_ids, 
                                 key=lambda x: x.uom_ratio or 0.0, 
                                 reverse=True)
                
                if len(uom_list) > 0:
                    line.produced_box = uom_list[0].produced_qty
                else:
                    line.produced_box = 0.0
                    
                if len(uom_list) > 1:
                    line.produced_map = uom_list[1].produced_qty
                else:
                    line.produced_map = 0.0
                    
                if len(uom_list) > 2:
                    line.produced_egg = uom_list[2].produced_qty
                else:
                    # Si hay unidad de referencia, usar su valor
                    ref_uom_val = line.uom_value_ids.filtered(
                        lambda x: x.uom_id.id == reference_uom.id
                    )
                    line.produced_egg = ref_uom_val.produced_qty if ref_uom_val else 0.0
            else:
                # Fallback a método legacy
                line.produced_box = line.final_box - line.initial_box
                line.produced_map = line.final_map - line.initial_map
                line.produced_egg = line.final_egg - line.initial_egg
                line.total_produced_reference = 0.0
    
    _sql_constraints = [
        ('unique_collection_variant', 'unique(collection_id, product_variant_id)',
         'No puede haber dos líneas con la misma variante en una recolección.'),
    ]
