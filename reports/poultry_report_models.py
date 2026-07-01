# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import datetime, timedelta


class PoultryMortalityReportWizard(models.TransientModel):
    _name = 'poultry.mortality.report.wizard'
    _description = 'Asistente de Reporte de Mortalidad'

    coop_id = fields.Many2one('poultry.coop', string='Galpón',
                               domain="[('active', '=', True)]")
    genetics_id = fields.Many2one('poultry.genetics', string='Genética',
                                   help='Genética específica para comparar con estándares')
    indicator_id = fields.Many2one('poultry.indicator', string='Indicador de Mortalidad',
                                    domain=[('category', '=', 'mortality')],
                                    help='Indicador a comparar contra el estándar. Si se deja vacío, '
                                         'se usa el primer indicador activo de categoría Mortalidad.')
    date_from = fields.Date(string='Fecha Desde', required=True,
                            default=lambda self: fields.Date.today() - timedelta(days=30))
    date_to = fields.Date(string='Fecha Hasta', required=True,
                          default=fields.Date.today)
    compare_with_standards = fields.Boolean(string='Comparar con Estándares', default=True,
                                            help='Compara los registros reales con los estándares de la genética')

    def action_generate_report(self):
        """Genera el reporte de mortalidad"""
        self.ensure_one()
        domain = [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('active', '=', True),
        ]

        if self.coop_id:
            domain.append(('coop_id', '=', self.coop_id.id))
        if self.genetics_id:
            domain.append(('genetics_id', '=', self.genetics_id.id))

        mortalities = self.env['poultry.mortality'].search(domain, order='date desc, coop_id')

        # Si se compara con estándares, agregar información de estándares
        if self.compare_with_standards and self.genetics_id:
            indicator = self.indicator_id or self.env['poultry.indicator'].search(
                [('category', '=', 'mortality'), ('active', '=', True)], limit=1)
            if indicator:
                for mortality in mortalities:
                    if mortality.batch_age_weeks > 0:
                        value_low, value_high = self.genetics_id.get_standard_range(
                            mortality.batch_age_weeks, indicator
                        )
                        # Aquí se podría calcular la diferencia con el estándar (Fase 2)

        return {
            'name': 'Reporte de Mortalidad',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.mortality',
            'view_mode': 'list',
            'domain': domain,
        }


class PoultryComparisonReportWizard(models.TransientModel):
    _name = 'poultry.comparison.report.wizard'
    _description = 'Asistente de Reporte Comparativo (Real vs Estándar)'

    genetics_id = fields.Many2one('poultry.genetics', string='Genética', required=True,
                                   help='Genética para comparar')
    coop_id = fields.Many2one('poultry.coop', string='Galpón',
                               domain="[('active', '=', True)]",
                               help='Galpón específico (opcional)')
    date_from = fields.Date(string='Fecha Desde', required=True,
                            default=lambda self: fields.Date.today() - timedelta(days=90))
    date_to = fields.Date(string='Fecha Hasta', required=True,
                          default=fields.Date.today)
    report_type = fields.Selection([
        ('mortality', 'Mortalidad'),
        ('production', 'Producción'),
        ('both', 'Ambos'),
    ], string='Tipo de Reporte', required=True, default='both')

    def action_generate_report(self):
        """Genera el reporte comparativo"""
        self.ensure_one()
        # Esta función preparará los datos para comparar registros reales con estándares
        # Por ahora, abrimos las vistas filtradas
        domain = [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]
        
        return {
            'name': f'Reporte Comparativo - {self.genetics_id.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.mortality' if self.report_type in ['mortality', 'both'] else 'poultry.egg.collection',
            'view_mode': 'list',
            'domain': domain,
        }

