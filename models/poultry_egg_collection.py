# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError


class PoultryEggCollection(models.Model):
    _name = 'poultry.egg.collection'
    _description = 'Recolección de Producción de Huevos'
    _order = 'date desc, coop_id'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Referencia', required=True, default='Nueva Recolección', copy=False, index=True)
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True, 
                               domain="[('active', '=', True)]", tracking=True)
    product_tmpl_id = fields.Many2one('product.template', string='Producto Base', required=True,
                                      domain=[('type', '=', 'product'), ('active', '=', True), ('is_egg_production', '=', True)],
                                      help='Producto base para la recolección. Se mostrarán todas las variantes de este producto en las líneas.', tracking=True)
    
    product_id = fields.Many2one('product.product', string='Producto', 
                                 related='product_tmpl_id.product_variant_id',
                                 readonly=True, store=False,
                                 help='Primera variante del producto base (solo lectura)')
    date = fields.Date(string='Fecha de Recolección', required=True, default=fields.Date.today, tracking=True)
    operator_id = fields.Many2one('hr.employee', string='Operador', 
                                  domain="[('active', '=', True)]",
                                  help='Empleado responsable de la recolección', tracking=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('counted', 'Cantidad Inicial Registrada'),
        ('completed', 'Completada'),
        ('done', 'Procesada'),
    ], string='Estado', default='draft', tracking=True)
    
    # Líneas de recolección
    line_ids = fields.One2many('poultry.egg.collection.line', 'collection_id', 
                                string='Líneas de Recolección')
    
    # Órdenes de fabricación generadas
    production_ids = fields.One2many('mrp.production', 'egg_collection_id', 
                                      string='Órdenes de Fabricación Generadas')
    production_count = fields.Integer(string='Cantidad de OF', compute='_compute_production_count')
    
    # Totales
    total_initial_boxes = fields.Float(string='Total Cajones Inicial', compute='_compute_totals', store=True)
    total_initial_maps = fields.Float(string='Total Maples Inicial', compute='_compute_totals', store=True)
    total_initial_eggs = fields.Float(string='Total Huevos Inicial', compute='_compute_totals', store=True)
    
    total_final_boxes = fields.Float(string='Total Cajones Final', compute='_compute_totals', store=True)
    total_final_maps = fields.Float(string='Total Maples Final', compute='_compute_totals', store=True)
    total_final_eggs = fields.Float(string='Total Huevos Final', compute='_compute_totals', store=True)
    
    total_produced_boxes = fields.Float(string='Total Cajones Producidos', compute='_compute_totals', store=True)
    total_produced_maps = fields.Float(string='Total Maples Producidos', compute='_compute_totals', store=True)
    total_produced_eggs = fields.Float(string='Total Huevos Producidos', compute='_compute_totals', store=True)
    
    notes = fields.Text(string='Notas')
    
    @api.depends('line_ids', 'line_ids.initial_box', 'line_ids.initial_map', 'line_ids.initial_egg',
                 'line_ids.final_box', 'line_ids.final_map', 'line_ids.final_egg',
                 'line_ids.produced_box', 'line_ids.produced_map', 'line_ids.produced_egg')
    def _compute_totals(self):
        """Calcula los totales de todas las líneas"""
        for collection in self:
            # Asegurar que los campos computed de las líneas estén calculados
            if collection.line_ids:
                collection.line_ids._compute_production()
            
            # Totales iniciales
            collection.total_initial_boxes = sum(collection.line_ids.mapped('initial_box') or [0.0])
            collection.total_initial_maps = sum(collection.line_ids.mapped('initial_map') or [0.0])
            collection.total_initial_eggs = sum(collection.line_ids.mapped('initial_egg') or [0.0])
            
            # Totales finales
            collection.total_final_boxes = sum(collection.line_ids.mapped('final_box') or [0.0])
            collection.total_final_maps = sum(collection.line_ids.mapped('final_map') or [0.0])
            collection.total_final_eggs = sum(collection.line_ids.mapped('final_egg') or [0.0])
            
            # Totales producidos: calcular directamente desde totales finales - iniciales
            # Esto es más confiable porque no depende del estado de los campos computed de las líneas
            collection.total_produced_boxes = collection.total_final_boxes - collection.total_initial_boxes
            collection.total_produced_maps = collection.total_final_maps - collection.total_initial_maps
            collection.total_produced_eggs = collection.total_final_eggs - collection.total_initial_eggs
    
    @api.depends('production_ids')
    def _compute_production_count(self):
        """Cuenta las órdenes de fabricación generadas"""
        for collection in self:
            collection.production_count = len(collection.production_ids)
    
    @api.model
    def create(self, vals):
        """Genera referencia automática si no se proporciona"""
        if not vals.get('name') or vals.get('name') == 'Nueva Recolección':
            vals['name'] = self.env['ir.sequence'].next_by_code('poultry.egg.collection') or 'NUEVA'
        return super().create(vals)
    
    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        """Al cambiar la plantilla del producto, actualiza las líneas con las variantes"""
        if self.product_tmpl_id:
            # Usar el método estándar de Odoo para obtener todas las variantes de la plantilla
            # Esto incluye todas las variantes, activas e inactivas
            variants = self.product_tmpl_id.product_variant_ids
            
            # Si no hay variantes, usar el producto base (product_variant_id) como recordset
            if not variants:
                if self.product_tmpl_id.product_variant_id:
                    variants = self.product_tmpl_id.product_variant_id
            
            # Limpiar líneas existentes y crear nuevas
            lines = []
            for variant in variants:
                lines.append((0, 0, {
                    'product_variant_id': variant.id,
                }))
            
            # Reemplazar todas las líneas existentes con las nuevas
            self.line_ids = [(5, 0, 0)]  # Eliminar todas las líneas
            if lines:
                self.line_ids = lines
    
    def action_count_initial(self):
        """Cambia el estado a 'counted' cuando se registra la cantidad inicial"""
        for record in self:
            if not record.line_ids:
                raise UserError('Debe agregar al menos una línea de recolección.')
            if not any(line.initial_box or line.initial_map or line.initial_egg for line in record.line_ids):
                raise UserError('Debe ingresar al menos una cantidad inicial.')
            record.state = 'counted'
    
    def action_complete(self):
        """Cambia el estado a 'completed' cuando se registra la cantidad final"""
        for record in self:
            if record.state != 'counted':
                raise UserError('Debe registrar primero la cantidad inicial.')
            if not any(line.final_box or line.final_map or line.final_egg for line in record.line_ids):
                raise UserError('Debe ingresar al menos una cantidad final.')
            # Los campos computed se recalcularán automáticamente al cambiar el estado
            # Forzar recálculo explícito para asegurar que se actualicen
            record.line_ids._compute_production()
            # Forzar recálculo de los totales después de calcular producción
            record._compute_totals()
            # Los campos computed de las líneas se calcularán automáticamente
            # Forzar recálculo de totales después de guardar
            record.state = 'completed'
    
    def action_set_to_draft(self):
        """Permite volver a borrador si aún no se han generado las órdenes de fabricación"""
        for record in self:
            if record.state == 'done':
                raise UserError('No se puede volver a borrador una recolección que ya ha sido procesada (tiene órdenes de fabricación generadas).')
            if record.production_ids:
                raise UserError('No se puede volver a borrador porque ya se han generado órdenes de fabricación.')
            record.state = 'draft'
    
    def action_generate_productions(self):
        """Genera automáticamente las Órdenes de Fabricación para los Cajones producidos"""
        self.ensure_one()
        if self.state != 'completed':
            raise UserError('Debe completar la recolección antes de generar las Órdenes de Fabricación.')
        
        if self.production_ids:
            raise UserError('Ya se han generado las Órdenes de Fabricación para esta recolección.')
        
        # Obtener la unidad de medida "Cajón"
        box_uom = self._get_uom_box()
        if not box_uom:
            raise UserError('No se encontró la unidad de medida "Cajón". '
                          'Debe crear esta unidad de medida antes de generar las órdenes.')
        
        productions_created = []
        
        for line in self.line_ids:
            if line.produced_box > 0:
                # Usar el mismo producto pero con la unidad de medida "Cajón"
                product = line.product_variant_id
                
                # Buscar la BOM del producto (puede ser por producto o por plantilla)
                bom = self.env['mrp.bom'].search([
                    ('product_id', '=', product.id),
                    ('type', '=', 'normal'),
                ], limit=1)
                
                if not bom:
                    # Intentar con la plantilla
                    bom = self.env['mrp.bom'].search([
                        ('product_tmpl_id', '=', product.product_tmpl_id.id),
                        ('product_id', '=', False),
                        ('type', '=', 'normal'),
                    ], limit=1)
                
                if not bom:
                    raise UserError(f'No se encontró una Lista de Materiales (BOM) para el producto {product.name}. '
                                  'Debe crear una BOM antes de generar las órdenes.')
                
                # Crear la Orden de Fabricación con la cantidad en unidades "Cajón"
                production = self.env['mrp.production'].create({
                    'product_id': product.id,
                    'product_qty': line.produced_box,  # Cantidad en unidades "Cajón"
                    'product_uom_id': box_uom.id,  # Unidad de medida "Cajón"
                    'bom_id': bom.id,
                    'coop_id': self.coop_id.id,
                    'egg_collection_id': self.id,
                    'origin': self.name,
                })
                
                # Confirmar la orden
                production.action_confirm()
                
                productions_created.append(production.id)
        
        if productions_created:
            self.state = 'done'
            return {
                'name': 'Órdenes de Fabricación Generadas',
                'type': 'ir.actions.act_window',
                'res_model': 'mrp.production',
                'view_mode': 'list,form',
                'domain': [('id', 'in', productions_created)],
                'context': {'create': False},
            }
        else:
            raise UserError('No hay producción de cajones para generar órdenes de fabricación.')
    
    def _get_uom_box(self):
        """Obtiene la unidad de medida 'Cajón' en cualquier categoría"""
        # Buscar "Cajón" en todas las categorías
        box_uom = self.env['uom.uom'].search([
            ('name', 'ilike', 'Cajón'),
        ], limit=1)
        if not box_uom:
            # Si no encuentra con tilde, buscar sin tilde
            box_uom = self.env['uom.uom'].search([
                ('name', 'ilike', 'Cajon'),
            ], limit=1)
        return box_uom
    
    def action_view_productions(self):
        """Abre la vista de órdenes de fabricación generadas"""
        self.ensure_one()
        return {
            'name': 'Órdenes de Fabricación',
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('egg_collection_id', '=', self.id)],
            'context': {'create': False},
        }

