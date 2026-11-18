# -*- coding: utf-8 -*-

import json
import keyword
import re

from odoo import _, models
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval

_NAME_RE = re.compile(r'\b[A-Za-z_]\w*\b')
_FORMULA_FUNCTIONS = {'abs', 'round', 'min', 'max'}


class PoultryRatioNumber(float):
    """Número de las fórmulas de cociente: dividir por cero da 0 en vez de error, como
    'ignore_zero_division' del motor de agregación. Las operaciones devuelven el mismo tipo
    para que la protección siga en cálculos encadenados, ej. balance / (a + b) * 100."""

    def __truediv__(self, other):
        return PoultryRatioNumber(0.0 if not other else float(self) / float(other))

    def __rtruediv__(self, other):
        return PoultryRatioNumber(0.0 if not self else float(other) / float(self))

    def __add__(self, other):
        return PoultryRatioNumber(float(self) + float(other))

    def __radd__(self, other):
        return PoultryRatioNumber(float(other) + float(self))

    def __sub__(self, other):
        return PoultryRatioNumber(float(self) - float(other))

    def __rsub__(self, other):
        return PoultryRatioNumber(float(other) - float(self))

    def __mul__(self, other):
        return PoultryRatioNumber(float(self) * float(other))

    def __rmul__(self, other):
        return PoultryRatioNumber(float(other) * float(self))

    def __neg__(self):
        return PoultryRatioNumber(-float(self))

    def __pos__(self):
        return self

    def __abs__(self):
        return PoultryRatioNumber(abs(float(self)))


class PoultryAccountReport(models.Model):
    """
    Fórmulas de Gestión Avícola para los reportes contables (motor "Función de Python
    personalizada"). Odoo busca el método en el propio account.report cuando el reporte
    no tiene manejador, así que basta con escribir su nombre en la fórmula de la línea.

    1) _report_custom_engine_poultry_cajones_vendidos
       Cajones de facturas y notas de crédito de cliente del período
       (account.move.line.quantity_cajones, ya con signo).

    2) _report_custom_engine_poultry_ratio
       Cálculo libre escrito en la SUBFÓRMULA de la expresión, que admite agrupar por
       (desplegar por cuenta). Nombres disponibles (expresión 'balance' de cada línea):
         - <código>: valor de esa línea en la fila; si es la línea que se está
           desplegando, el valor de cada cuenta;
         - total_<código>: total de esa línea (no cambia al desplegar).
       Usar total_ en los divisores. Dividir por cero da 0. Ejemplos (línea de costo cogs_COPY):
         cogs_COPY / total_sales_COPY * 100                          % sobre ventas
         -cogs_COPY / total_cajones_vend                             costo por cajón
         cogs_COPY / (total_cogs_COPY + total_adm_exp_COPY) * 100    % sobre costo total

    Ambas respetan los filtros del reporte (empresas, libro/diarios, fechas, borradores,
    comparación de períodos).
    """
    _inherit = 'account.report'

    # ------------------------------------------------------------------
    # Cajones vendidos
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Cociente libre (subfórmula)
    # ------------------------------------------------------------------
    def _report_custom_engine_poultry_ratio(self, expressions, options, date_scope,
                                           current_groupby, next_groupby, offset=0,
                                           limit=None, warnings=None):
        # Odoo llama UNA vez por fórmula con todas las expresiones que la usan y evalúa la
        # subfórmula de cada una sobre el mismo resultado. Por eso los nombres son códigos de
        # línea (distintos en cada línea) y se devuelven todos juntos.
        codes = {l.code: l for l in self.line_ids if l.code}
        names = set()
        for expression in expressions:
            formula = (expression.subformula or '').strip()
            if not formula:
                raise UserError(_(
                    "La línea '%(line)s' usa _report_custom_engine_poultry_ratio sin cálculo: "
                    "escribilo en la subfórmula, ej. cogs_COPY / total_sales_COPY * 100.",
                    line=expression.report_line_id.name))
            found = {n for n in _NAME_RE.findall(formula)
                     if not keyword.iskeyword(n) and n not in _FORMULA_FUNCTIONS}
            unknown = sorted(n for n in found if self._poultry_ratio_code(n) not in codes)
            if unknown:
                raise UserError(_(
                    "En la línea '%(line)s', '%(name)s' no es el código de una línea del reporte "
                    "(ni total_<código>).", line=expression.report_line_id.name,
                    name=', '.join(unknown)))
            names |= found

        def balance_expr(code):
            expr = codes[code].expression_ids.filtered(lambda e: e.label == 'balance')[:1]
            if not expr:
                raise UserError(_("La línea con código '%(code)s' no tiene expresión 'balance'.",
                                  code=code))
            return expr

        # Líneas que se están desplegando en esta llamada: su código vale por grupo.
        batch_codes = set(expressions.report_line_id.mapped('code')) if current_groupby else set()
        totals, grouped = {}, []
        for name in sorted(names):
            code = self._poultry_ratio_code(name)
            if name == code and code in batch_codes:
                grouped.append(code)
            else:
                totals[name] = self._poultry_expression_total(balance_expr(code), options)

        def build(values, has_sublines=False):
            rslt = {k: PoultryRatioNumber(v or 0.0) for k, v in totals.items()}
            rslt.update({k: PoultryRatioNumber(values.get(k) or 0.0) for k in grouped})
            rslt['has_sublines'] = has_sublines
            return rslt

        if not current_groupby:
            return build({})

        # Desplegado por grupo (ej. por cuenta): valor de cada línea en cada grupo
        per_group, sublines, order = {}, {}, []
        for code in grouped:
            for key, value, has_sub in self._poultry_expression_grouped(
                    balance_expr(code), options, current_groupby, next_groupby, offset, limit, warnings):
                if key not in per_group:
                    per_group[key] = {}
                    order.append(key)
                per_group[key][code] = value
                sublines[key] = sublines.get(key) or has_sub
        return [(key, build(per_group[key], sublines.get(key, False))) for key in order]

    @staticmethod
    def _poultry_ratio_code(name):
        return name[len('total_'):] if name.startswith('total_') else name

    def _poultry_expression_total(self, expression, options):
        """Total de una expresión (cualquier motor) para la columna de 'options'."""
        group_key = options.get('owner_column_group')
        cache = self.env.cr.cache.setdefault('poultry_report_ratio_totals', {})
        cache_key = (expression.id, json.dumps(options, sort_keys=True, default=str))
        if cache_key in cache:
            return cache[cache_key]
        stack = self.env.context.get('poultry_ratio_stack', ())
        if expression.id in stack:
            raise UserError(_("La fórmula de la línea '%(line)s' se usa a sí misma.",
                              line=expression.report_line_id.name))
        report = expression.report_line_id.report_id.with_context(
            poultry_ratio_stack=stack + (expression.id,))
        to_compute = expression._expand_aggregations()
        all_totals = report._compute_expression_totals_for_each_column_group(
            to_compute, options, col_groups_restrict=[group_key] if group_key else None)
        group_totals = all_totals[group_key] if group_key else next(iter(all_totals.values()))
        value = group_totals.get(expression, {}).get('value') or 0.0
        cache[cache_key] = value
        return value

    def _poultry_expression_grouped(self, expression, options, current_groupby, next_groupby,
                                    offset, limit, warnings):
        """Valores agrupados de una expresión de la misma línea: [(clave, valor, tiene_sublíneas)]."""
        date_scope = self._standardize_date_scope_for_date_range(expression.date_scope)
        batch = self._compute_formula_batch(
            options, expression.engine, date_scope, {expression.formula: expression},
            current_groupby, next_groupby, offset=offset, limit=limit, warnings=warnings)
        result = next(iter(batch.values()))
        if expression.engine not in ('aggregation', 'external') and expression.subformula:
            value_key = expression.subformula
        else:
            value_key = 'result'
        return [(key, safe_eval(value_key, vals), bool(vals.get('has_sublines')))
                for key, vals in result]
