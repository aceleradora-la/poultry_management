# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PoultryGeneticsStandard(models.Model):
    _name = 'poultry.genetics.standard'
    _description = 'Estándar de Mortalidad o Producción por Semanas'
    _order = 'genetics_id, week'
    _rec_name = 'display_name'

    genetics_id = fields.Many2one('poultry.genetics', string='Genética', required=True, index=True, ondelete='cascade')
    week = fields.Integer(string='Semana de Vida', required=True, 
                          help='Semana de vida de las aves (desde la semana 1)')
    standard_type = fields.Selection([
        ('mortality', 'Mortalidad Diaria (%)'),
        ('production', 'Producción Diaria (%)'),
    ], string='Tipo de Estándar', required=True, index=True)
    
    # Valores estándar
    standard_value = fields.Float(string='Valor Estándar (%)', required=True, digits=(16, 2),
                                  help='Valor estándar según el tipo: mortalidad diaria o producción diaria')
    
    # Información adicional
    notes = fields.Text(string='Notas')
    active = fields.Boolean(string='Activo', default=True)
    
    display_name = fields.Char(string='Nombre', compute='_compute_display_name', store=True)
    
    @api.depends('genetics_id', 'week', 'standard_type')
    def _compute_display_name(self):
        """Genera nombre para mostrar"""
        for record in self:
            type_label = 'Mortalidad' if record.standard_type == 'mortality' else 'Producción'
            record.display_name = f'{record.genetics_id.name} - Semana {record.week} - {type_label}'
    
    _sql_constraints = [
        ('unique_genetics_week_type', 'unique(genetics_id, week, standard_type)',
         'Ya existe un estándar para esta genética, semana y tipo.'),
        ('week_positive', 'CHECK(week >= 1)',
         'La semana debe ser mayor o igual a 1.'),
        ('value_positive', 'CHECK(standard_value >= 0)',
         'El valor estándar no puede ser negativo.'),
    ]

