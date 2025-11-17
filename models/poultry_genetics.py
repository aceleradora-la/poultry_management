# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PoultryGenetics(models.Model):
    _name = 'poultry.genetics'
    _description = 'Genética de Aves'
    _order = 'name'

    name = fields.Char(string='Nombre de la Genética', required=True, index=True)
    code = fields.Char(string='Código', index=True)
    description = fields.Text(string='Descripción')
    active = fields.Boolean(string='Activo', default=True)
    
    # Relaciones
    batch_ids = fields.One2many('poultry.batch', 'genetics_id', string='Lotes')
    batch_count = fields.Integer(string='Cantidad de Lotes', compute='_compute_batch_count')
    
    # Estándares de genética
    standard_ids = fields.One2many('poultry.genetics.standard', 'genetics_id', 
                                    string='Estándares de Mortalidad y Producción')
    mortality_standard_ids = fields.One2many('poultry.genetics.standard', 'genetics_id', 
                                              string='Estándares de Mortalidad',
                                              domain=[('standard_type', '=', 'mortality')])
    production_standard_ids = fields.One2many('poultry.genetics.standard', 'genetics_id', 
                                               string='Estándares de Producción',
                                               domain=[('standard_type', '=', 'production')])
    
    # Registros de mortalidad
    mortality_ids = fields.One2many('poultry.mortality', 'genetics_id', string='Registros de Mortalidad')
    mortality_count = fields.Integer(string='Registros de Mortalidad', compute='_compute_mortality_count')
    
    @api.depends('batch_ids')
    def _compute_batch_count(self):
        """Cuenta la cantidad de lotes con esta genética"""
        for genetics in self:
            genetics.batch_count = len(genetics.batch_ids)
    
    @api.depends('mortality_ids')
    def _compute_mortality_count(self):
        """Cuenta la cantidad de registros de mortalidad"""
        for genetics in self:
            genetics.mortality_count = len(genetics.mortality_ids)
    
    def get_standard_value(self, week, standard_type):
        """Obtiene el valor estándar para una semana y tipo específico"""
        self.ensure_one()
        standard = self.standard_ids.filtered(
            lambda s: s.week == week and s.standard_type == standard_type and s.active
        )
        return standard[0].standard_value if standard else 0.0

