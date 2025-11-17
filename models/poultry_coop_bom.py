# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryCoopBom(models.Model):
    _name = 'poultry.coop.bom'
    _description = 'Lista de Materiales de Alimento por Galpón'
    _order = 'start_date desc'

    name = fields.Char(string='Descripción', required=True, default='Nueva Lista de Materiales')
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True, 
                               domain="[('active', '=', True)]")
    bom_id = fields.Many2one('mrp.bom', string='Lista de Materiales', required=True,
                              domain="[('type', '=', 'normal')]")
    bom_product_id = fields.Many2one('product.product', string='Producto de la BOM', 
                                      related='bom_id.product_id', readonly=True, store=True)
    
    # Fechas de activación
    start_date = fields.Date(string='Fecha de Inicio', required=True, default=fields.Date.today)
    end_date = fields.Date(string='Fecha de Fin', help='Fecha en que se desactivó esta lista de materiales')
    
    # Estado
    active = fields.Boolean(string='Activa', default=True, help='Indica si esta es la lista de materiales activa para el galpón')
    
    # Notas
    notes = fields.Text(string='Notas')
    
    @api.constrains('coop_id', 'active', 'start_date')
    def _check_single_active_bom(self):
        """Valida que solo haya una lista de materiales activa por galpón"""
        for coop_bom in self:
            if coop_bom.active:
                other_active = self.search([
                    ('coop_id', '=', coop_bom.coop_id.id),
                    ('active', '=', True),
                    ('id', '!=', coop_bom.id),
                    ('start_date', '<=', coop_bom.start_date or fields.Date.today()),
                ])
                if other_active:
                    # Desactivar las otras listas de materiales activas para este galpón
                    other_active.write({'active': False, 'end_date': coop_bom.start_date})
    
    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        """Valida que la fecha de fin sea posterior a la fecha de inicio"""
        for coop_bom in self:
            if coop_bom.end_date and coop_bom.start_date:
                if coop_bom.end_date < coop_bom.start_date:
                    raise ValidationError(
                        'La fecha de fin no puede ser anterior a la fecha de inicio.'
                    )
    
    @api.model
    def create(self, vals):
        """Al crear una nueva lista activa, desactiva las anteriores"""
        new_bom = super().create(vals)
        if new_bom.active:
            new_bom._check_single_active_bom()
        return new_bom
    
    def write(self, vals):
        """Al activar una lista, desactiva las demás del mismo galpón"""
        if vals.get('active'):
            for coop_bom in self:
                other_active = self.search([
                    ('coop_id', '=', coop_bom.coop_id.id),
                    ('active', '=', True),
                    ('id', '!=', coop_bom.id),
                ])
                if other_active:
                    end_date = vals.get('start_date') or coop_bom.start_date or fields.Date.today()
                    other_active.write({'active': False, 'end_date': end_date})
        return super().write(vals)
    
    def action_set_active(self):
        """Acción para activar esta lista de materiales"""
        self.ensure_one()
        # Desactivar otras listas activas del mismo galpón
        other_active = self.search([
            ('coop_id', '=', self.coop_id.id),
            ('active', '=', True),
            ('id', '!=', self.id),
        ])
        if other_active:
            other_active.write({'active': False, 'end_date': fields.Date.today()})
        self.write({'active': True, 'end_date': False})
    
    def action_set_inactive(self):
        """Acción para desactivar esta lista de materiales"""
        self.ensure_one()
        self.write({'active': False, 'end_date': fields.Date.today()})
    
    def name_get(self):
        """Personaliza el nombre mostrado"""
        result = []
        for coop_bom in self:
            name = f'{coop_bom.coop_id.name} - {coop_bom.bom_id.product_id.name}'
            if coop_bom.active:
                name += ' [ACTIVA]'
            result.append((coop_bom.id, name))
        return result

