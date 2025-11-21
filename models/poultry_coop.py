# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryCoop(models.Model):
    _name = 'poultry.coop'
    _description = 'Galpón Avícola'
    _order = 'name'

    name = fields.Char(string='Nombre del Galpón', required=True, index=True)
    code = fields.Char(string='Código', required=True, index=True, copy=False)
    size = fields.Float(string='Tamaño (m²)', required=True, help='Tamaño del galpón en metros cuadrados')
    capacity = fields.Integer(string='Capacidad de Aves', required=True, help='Capacidad máxima de aves que puede albergar')
    active = fields.Boolean(string='Activo', default=True)
    
    # Relaciones con lotes de aves
    batch_ids = fields.One2many('poultry.batch', 'coop_id', string='Lotes de Aves Asignados')
    batch_count = fields.Integer(string='Cantidad de Lotes', compute='_compute_batch_count')
    
    # Relaciones con recolecciones de producción
    egg_collection_ids = fields.One2many('poultry.egg.collection', 'coop_id', string='Recolecciones de Producción')
    egg_collection_count = fields.Integer(string='Recolecciones', compute='_compute_egg_collection_count')
    
    # Relaciones con mortalidad
    mortality_ids = fields.One2many('poultry.mortality', 'coop_id', string='Registros de Mortalidad')
    mortality_count = fields.Integer(string='Registros de Mortalidad', compute='_compute_mortality_count')
    
    # Relación con listas de materiales (BOM)
    coop_bom_ids = fields.One2many('poultry.coop.bom', 'coop_id', string='Historial de Listas de Materiales')
    active_bom_id = fields.Many2one('poultry.coop.bom', string='Lista de Materiales Activa', 
                                     compute='_compute_active_bom', store=True)
    active_bom_start_date = fields.Date(string='Fecha Inicio Lista Activa', 
                                         related='active_bom_id.start_date', readonly=True)
    
    # Total de aves actualmente en el galpón
    current_birds_count = fields.Integer(string='Total de Aves Actuales', 
                                         compute='_compute_current_birds_count',
                                         store=True)
    
    # Porcentaje de ocupación
    occupancy_percentage = fields.Float(string='% Ocupación', 
                                        compute='_compute_occupancy_percentage',
                                        store=True)
    
    notes = fields.Text(string='Notas')
    
    @api.depends('batch_ids', 'batch_ids.bird_count')
    def _compute_current_birds_count(self):
        """Calcula el total de aves actualmente asignadas al galpón"""
        for coop in self:
            coop.current_birds_count = sum(coop.batch_ids.mapped('bird_count'))
    
    @api.depends('current_birds_count', 'capacity')
    def _compute_occupancy_percentage(self):
        """Calcula el porcentaje de ocupación del galpón"""
        for coop in self:
            if coop.capacity > 0:
                coop.occupancy_percentage = coop.current_birds_count / coop.capacity
            else:
                coop.occupancy_percentage = 0.0
    
    @api.depends('batch_ids')
    def _compute_batch_count(self):
        """Cuenta la cantidad de lotes asignados al galpón"""
        for coop in self:
            coop.batch_count = len(coop.batch_ids)
    
    @api.depends('egg_collection_ids')
    def _compute_egg_collection_count(self):
        """Cuenta la cantidad de recolecciones del galpón"""
        for coop in self:
            coop.egg_collection_count = len(coop.egg_collection_ids)
    
    @api.depends('mortality_ids')
    def _compute_mortality_count(self):
        """Cuenta la cantidad de registros de mortalidad del galpón"""
        for coop in self:
            coop.mortality_count = len(coop.mortality_ids)
    
    @api.depends('coop_bom_ids', 'coop_bom_ids.active')
    def _compute_active_bom(self):
        """Obtiene la lista de materiales activa para el galpón"""
        for coop in self:
            active_bom = coop.coop_bom_ids.filtered(lambda b: b.active)
            coop.active_bom_id = active_bom[0] if active_bom else False
    
    @api.constrains('capacity', 'current_birds_count')
    def _check_capacity(self):
        """Valida que no se exceda la capacidad del galpón"""
        for coop in self:
            if coop.current_birds_count > coop.capacity:
                raise ValidationError(
                    f'El galpón {coop.name} excede su capacidad. '
                    f'Capacidad: {coop.capacity}, Aves actuales: {coop.current_birds_count}'
                )
    
    @api.constrains('code')
    def _check_code_unique(self):
        """Valida que el código sea único"""
        for coop in self:
            if self.search_count([('code', '=', coop.code), ('id', '!=', coop.id)]) > 0:
                raise ValidationError(f'El código {coop.code} ya existe. Debe ser único.')
    
    @api.model
    def create(self, vals):
        """Genera código automático si no se proporciona"""
        if not vals.get('code'):
            vals['code'] = self.env['ir.sequence'].next_by_code('poultry.coop') or 'NUEVO'
        return super().create(vals)
    
    def action_view_batches(self):
        """Abre la vista de lotes asignados a este galpón"""
        action = {
            'name': f'Lotes de Aves - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.batch',
            'view_mode': 'list,form',
            'domain': [('coop_id', '=', self.id)],
            'context': {'default_coop_id': self.id},
        }
        return action
    
    def action_view_active_bom(self):
        """Abre la vista de la lista de materiales activa"""
        if not self.active_bom_id:
            return False
        return {
            'name': f'Lista de Materiales Activa - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.coop.bom',
            'res_id': self.active_bom_id.id,
            'view_mode': 'form',
        }

