# -*- coding: utf-8 -*-

from odoo import _, models
from odoo.exceptions import UserError
from odoo.fields import Domain


class PoultryAccountReport(models.Model):
    """
    Fórmulas de Gestión Avícola para los reportes contables (motor "Función de Python
    personalizada"). Odoo busca el método en el propio account.report cuando el reporte
    no tiene manejador, así que basta con escribir su nombre en la fórmula de la línea:

        _report_custom_engine_poultry_cajones_vendidos

    Devuelve los cajones de las facturas y notas de crédito de cliente del período
    (account.move.line.quantity_cajones, ya con signo), con los mismos filtros que el
    resto del reporte: empresas, libro/diarios, fechas, borradores y comparación.
    """
    _inherit = 'account.report'

    def _report_custom_engine_poultry_cajones_vendidos(self, expressions, options, date_scope,
                                                      current_groupby, next_groupby, offset=0,
                                                      limit=None, warnings=None):
        return self._poultry_cajones_engine_result(
            options, date_scope, current_groupby, ('out_invoice', 'out_refund'))

    def _poultry_cajones_engine_result(self, options, date_scope, current_groupby, move_types):
        if current_groupby:
            raise UserError(_("La fórmula de cajones no admite agrupar por (dejá vacío el campo "
                              "'Agrupar por' de la línea)."))
        domain = self._poultry_report_options_domain(options, date_scope) & Domain([
            ('move_id.move_type', 'in', move_types),
            ('display_type', '=', 'product'),
            ('quantity_cajones', '!=', 0),
        ])
        [(total,)] = self.env['account.move.line']._read_group(domain, [], ['quantity_cajones:sum'])
        return {'result': total or 0.0, 'has_sublines': False}

    def _poultry_report_options_domain(self, options, date_scope):
        # Con Contabilidad (account_reports) se usan los filtros completos del reporte.
        if hasattr(self, '_get_options_domain'):
            return self._get_options_domain(options, date_scope)
        # Sin el motor de reportes (Community / tests): fechas, empresas y publicados.
        date_opts = options.get('date', {})
        domain = Domain('date', '<=', date_opts['date_to'])
        if date_opts.get('date_from') and date_opts.get('mode', 'range') == 'range':
            domain &= Domain('date', '>=', date_opts['date_from'])
        company_ids = [c['id'] for c in options.get('companies', [])] or self.env.companies.ids
        states = ('posted', 'draft') if options.get('all_entries') else ('posted',)
        return domain & Domain([('company_id', 'in', company_ids), ('parent_state', 'in', states)])
