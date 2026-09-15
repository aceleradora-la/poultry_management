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

    rearing_end_week = fields.Integer(
        string='Semana de Transición a Producción', default=17,
        help='Última semana del Período de Crianza. A partir de la semana siguiente, '
             'el lote se considera en Período de Producción.')

    # Relaciones
    batch_ids = fields.One2many('poultry.batch', 'genetics_id', string='Lotes')
    batch_count = fields.Integer(string='Cantidad de Lotes', compute='_compute_batch_count')

    # Estándares de genética
    standard_version_ids = fields.One2many('poultry.genetics.standard.version', 'genetics_id',
                                            string='Versiones de Estándar')
    default_standard_version_id = fields.Many2one(
        'poultry.genetics.standard.version', string='Versión de Estándar Predeterminada',
        compute='_compute_default_standard_version_id')
    standard_ids = fields.One2many('poultry.genetics.standard', 'genetics_id',
                                    string='Estándares (todas las versiones)')
    standard_count = fields.Integer(string='Cantidad de Estándares', compute='_compute_standard_count')

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

    @api.depends('standard_ids')
    def _compute_standard_count(self):
        """Cuenta la cantidad de estándares (todas las versiones)"""
        for genetics in self:
            genetics.standard_count = len(genetics.standard_ids)

    @api.depends('standard_version_ids.is_default', 'standard_version_ids.active')
    def _compute_default_standard_version_id(self):
        """Obtiene la versión de estándar marcada como predeterminada"""
        for genetics in self:
            default_version = genetics.standard_version_ids.filtered(
                lambda v: v.is_default and v.active
            )
            genetics.default_standard_version_id = default_version[:1]

    def get_standard_range(self, week, indicator_id, version_id=None, period=None):
        """Obtiene el rango (Bajo, Alto) de un indicador para una semana dada.

        Si no se especifica version_id, se usa la versión predeterminada de la genética.
        Si no se especifica period, se infiere de la semana vs rearing_end_week.
        """
        self.ensure_one()
        version = version_id or self.default_standard_version_id
        if not version:
            return (0.0, 0.0)
        if isinstance(version, int):
            version = self.env['poultry.genetics.standard.version'].browse(version)
        if isinstance(indicator_id, models.BaseModel):
            indicator_id = indicator_id.id
        if period is None:
            period = 'crianza' if week <= (self.rearing_end_week or 17) else 'produccion'
        standard = self.env['poultry.genetics.standard'].search([
            ('version_id', '=', version.id),
            ('indicator_id', '=', indicator_id),
            ('week', '=', week),
            ('period', '=', period),
            ('active', '=', True),
        ], limit=1)
        return (standard.value_low, standard.value_high) if standard else (0.0, 0.0)
