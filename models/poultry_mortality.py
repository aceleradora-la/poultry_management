# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryMortality(models.Model):
    _name = 'poultry.mortality'
    _description = 'Registro de Aves Muertas'
    _order = 'date desc, coop_id'

    name = fields.Char(string='Referencia', required=True, default='Nuevo Registro', copy=False, index=True)
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True, 
                               domain="[('active', '=', True)]", index=True)
    genetics_id = fields.Many2one('poultry.genetics', string='Genética', required=True)
    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', 
                                domain="[('coop_id', '=', coop_id), ('genetics_id', '=', genetics_id), ('active', '=', True)]",
                                help='Lote específico de aves (opcional)')
    date = fields.Date(string='Fecha', required=True, default=fields.Date.today, index=True)
    
    # Cantidad de aves muertas
    dead_count = fields.Integer(string='Cantidad de Aves Muertas', required=True, default=0)
    
    # Información calculada
    batch_age_weeks = fields.Integer(string='Edad del Lote (semanas)', compute='_compute_batch_age', store=True)
    
    # Notas
    notes = fields.Text(string='Notas')
    active = fields.Boolean(string='Activo', default=True)
    
    @api.depends('batch_id', 'batch_id.birth_date', 'date')
    def _compute_batch_age(self):
        """Calcula la edad del lote en semanas al momento del registro"""
        for record in self:
            if record.batch_id and record.batch_id.birth_date and record.date:
                days = (record.date - record.batch_id.birth_date).days
                record.batch_age_weeks = days // 7
            else:
                record.batch_age_weeks = 0
    
    @api.model
    def create(self, vals):
        """Genera referencia automática si no se proporciona"""
        if not vals.get('name') or vals.get('name') == 'Nuevo Registro':
            vals['name'] = self.env['ir.sequence'].next_by_code('poultry.mortality') or 'NUEVO'
        return super().create(vals)
    
    @api.constrains('dead_count')
    def _check_dead_count(self):
        """Valida que la cantidad de aves muertas sea positiva"""
        for record in self:
            if record.dead_count < 0:
                raise ValidationError('La cantidad de aves muertas no puede ser negativa.')
            
            # Validar que no exceda la cantidad de aves del lote si está especificado
            if record.batch_id and record.batch_id.bird_count:
                if record.dead_count > record.batch_id.bird_count:
                    raise ValidationError(
                        f'La cantidad de aves muertas ({record.dead_count}) no puede ser mayor '
                        f'que la cantidad de aves en el lote ({record.batch_id.bird_count}).'
                    )
    
    @api.onchange('coop_id')
    def _onchange_coop_id(self):
        """Al cambiar el galpón, limpiar genética y lote"""
        self.genetics_id = False
        self.batch_id = False
    
    @api.onchange('genetics_id', 'coop_id')
    def _onchange_genetics_coop(self):
        """Al cambiar genética o galpón, actualizar dominio del lote"""
        if self.coop_id and self.genetics_id:
            self.batch_id = False

