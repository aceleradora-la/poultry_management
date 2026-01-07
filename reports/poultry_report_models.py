# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import datetime, timedelta


class PoultryProductionReportWizard(models.TransientModel):
    _name = 'poultry.production.report.wizard'
    _description = 'Asistente de Reporte de Producción por Galpón'

    coop_id = fields.Many2one('poultry.coop', string='Galpón', 
                               domain="[('active', '=', True)]",
                               help='Seleccione un galpón para generar el reporte. Deje vacío para todos los galpones.')
    date_from = fields.Date(string='Fecha Desde', required=True, 
                            default=lambda self: fields.Date.today() - timedelta(days=30))
    date_to = fields.Date(string='Fecha Hasta', required=True, 
                          default=fields.Date.today)
    group_by_date = fields.Boolean(string='Agrupar por Fecha', default=True,
                                   help='Si está marcado, agrupa los resultados por fecha')

    def action_generate_report(self):
        """Genera el reporte de producción"""
        self.ensure_one()
        domain = [
            ('collection_id.date', '>=', self.date_from),
            ('collection_id.date', '<=', self.date_to),
            ('collection_id.state', '=', 'done'),
        ]
        
        if self.coop_id:
            domain.append(('collection_id.coop_id', '=', self.coop_id.id))
        
        # Buscar líneas de recolección en lugar de collections
        lines = self.env['poultry.egg.collection.line'].search(domain, order='collection_id.date desc, collection_id.coop_id')
        
        # Preparar datos para el reporte
        report_data = []
        for line in lines:
            report_data.append({
                'date': line.collection_id.date,
                'coop': line.collection_id.coop_id.name,
                'variant': line.product_variant_id.name,
                'total_eggs': line.total_produced_reference,
                'total_boxes': line.total_boxes,
                'average_weight': line.average_weight,
            })
        
        return {
            'name': 'Reporte de Producción de Huevos',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.egg.collection.line',
            'view_mode': 'list,pivot,form',
            'domain': domain,
            'context': {
                'pivot_measures': ['total_produced_reference', 'total_boxes', 'average_weight'],
            },
        }


class PoultryMortalityReportWizard(models.TransientModel):
    _name = 'poultry.mortality.report.wizard'
    _description = 'Asistente de Reporte de Mortalidad'

    coop_id = fields.Many2one('poultry.coop', string='Galpón',
                               domain="[('active', '=', True)]")
    genetics_id = fields.Many2one('poultry.genetics', string='Genética',
                                   help='Genética específica para comparar con estándares')
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
            for mortality in mortalities:
                if mortality.batch_age_weeks > 0:
                    standard_value = self.genetics_id.get_standard_value(
                        mortality.batch_age_weeks, 'mortality'
                    )
                    # Aquí se podría calcular la diferencia con el estándar
        
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

