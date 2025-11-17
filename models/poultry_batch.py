# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryBatch(models.Model):
    _name = 'poultry.batch'
    _description = 'Lote de Aves'
    _order = 'birth_date desc'

    name = fields.Char(string='Nombre del Lote', required=True, index=True, default='Nuevo')
    code = fields.Char(string='Código', required=True, index=True, copy=False)
    birth_date = fields.Date(string='Fecha de Nacimiento', required=True, default=fields.Date.today)
    genetics_id = fields.Many2one('poultry.genetics', string='Genética', required=True)
    genetics_name = fields.Char(string='Genética', related='genetics_id.name', readonly=True, store=True)
    
    # Asignación al galpón
    coop_id = fields.Many2one('poultry.coop', string='Galpón Asignado', required=True, 
                               domain="[('active', '=', True)]")
    coop_name = fields.Char(string='Galpón', related='coop_id.name', readonly=True, store=True)
    assignment_date = fields.Date(string='Fecha de Asignación', required=True, default=fields.Date.today)
    
    # Cantidad de aves
    bird_count = fields.Integer(string='Cantidad de Aves', required=True, default=0)
    
    # Información adicional
    supplier_id = fields.Many2one('res.partner', string='Proveedor', 
                                   domain="[('supplier_rank', '>', 0)]")
    notes = fields.Text(string='Notas')
    active = fields.Boolean(string='Activo', default=True)
    
    # Edad del lote
    age_days = fields.Integer(string='Edad (días)', compute='_compute_age_days')
    days_in_coop = fields.Integer(string='Días en Galpón', compute='_compute_days_in_coop')
    
    @api.depends('birth_date')
    def _compute_age_days(self):
        """Calcula la edad del lote en días"""
        today = fields.Date.today()
        for batch in self:
            if batch.birth_date:
                batch.age_days = (today - batch.birth_date).days
            else:
                batch.age_days = 0
    
    @api.depends('assignment_date')
    def _compute_days_in_coop(self):
        """Calcula los días que lleva el lote en el galpón"""
        today = fields.Date.today()
        for batch in self:
            if batch.assignment_date:
                batch.days_in_coop = (today - batch.assignment_date).days
            else:
                batch.days_in_coop = 0
    
    @api.constrains('code')
    def _check_code_unique(self):
        """Valida que el código sea único"""
        for batch in self:
            if self.search_count([('code', '=', batch.code), ('id', '!=', batch.id)]) > 0:
                raise ValidationError(f'El código {batch.code} ya existe. Debe ser único.')
    
    @api.constrains('assignment_date', 'birth_date')
    def _check_dates(self):
        """Valida que la fecha de asignación sea posterior a la fecha de nacimiento"""
        for batch in self:
            if batch.assignment_date and batch.birth_date:
                if batch.assignment_date < batch.birth_date:
                    raise ValidationError(
                        'La fecha de asignación no puede ser anterior a la fecha de nacimiento.'
                    )
    
    @api.constrains('bird_count', 'coop_id')
    def _check_capacity(self):
        """Valida que al asignar el lote no se exceda la capacidad del galpón"""
        for batch in self:
            if batch.coop_id and batch.bird_count > 0:
                # Calculamos el total de aves si incluimos este lote
                other_batches = batch.coop_id.batch_ids.filtered(lambda b: b.id != batch.id)
                total_birds = sum(other_batches.mapped('bird_count')) + batch.bird_count
                
                if total_birds > batch.coop_id.capacity:
                    raise ValidationError(
                        f'No se puede asignar este lote al galpón {batch.coop_id.name}. '
                        f'Se excedería la capacidad. Capacidad: {batch.coop_id.capacity}, '
                        f'Aves totales: {total_birds}'
                    )
    
    @api.model
    def create(self, vals):
        """Genera código automático si no se proporciona"""
        if not vals.get('code'):
            vals['code'] = self.env['ir.sequence'].next_by_code('poultry.batch') or 'NUEVO'
        if not vals.get('name') or vals.get('name') == 'Nuevo':
            genetics_name = self.env['poultry.genetics'].browse(vals.get('genetics_id')).name if vals.get('genetics_id') else ''
            birth_date = vals.get('birth_date', fields.Date.today())
            vals['name'] = f'{genetics_name} - {birth_date}'
        return super().create(vals)
    
    def name_get(self):
        """Personaliza el nombre mostrado"""
        result = []
        for batch in self:
            name = f'{batch.code} - {batch.name}'
            if batch.coop_id:
                name += f' [{batch.coop_id.name}]'
            result.append((batch.id, name))
        return result

