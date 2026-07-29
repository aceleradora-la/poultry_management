# -*- coding: utf-8 -*-

from odoo import models, fields


class PoultryFormulaCheckWizard(models.TransientModel):
    _name = 'poultry.formula.check.wizard'
    _description = 'Verificar Motor de Fórmulas'

    date_from = fields.Date(string='Fecha Desde',
                            help='Vacío para verificar desde el primer Cierre de Galpón.')
    date_to = fields.Date(string='Fecha Hasta',
                          help='Vacío para verificar hasta el último Cierre de Galpón.')
    tolerance = fields.Float(
        string='Tolerancia', default=0.0001, digits=(16, 6),
        help='Diferencia máxima aceptada entre el valor guardado y el del motor de '
             'fórmulas antes de reportarla (para no listar diferencias de redondeo).')
    result_html = fields.Html(string='Resultado', readonly=True)

    def action_check(self):
        """Compara lo que calcularía el MOTOR DE FÓRMULAS contra los valores YA
        GUARDADOS (que vienen del cálculo cableado), sin escribir nada.

        Cómo: abre un savepoint de base de datos, recalcula el rango con el motor,
        compara valor por valor contra la foto previa, y hace ROLLBACK al savepoint
        para deshacer todo. Es la verificación previa a activar el motor: el
        resultado esperado es cero diferencias, porque la migración cargó en cada
        indicador la fórmula equivalente a su cálculo cableado."""
        self.ensure_one()
        Value = self.env['poultry.batch.indicator.value'].sudo()
        Indicator = self.env['poultry.indicator'].sudo()
        formula_indicators = Indicator.search([
            ('active', '=', True), ('formula_mode', '!=', False)])
        if not formula_indicators:
            self.result_html = (
                '<p>Ningún indicador tiene fórmula cargada: no hay nada que verificar.</p>')
            return self._reopen()

        domain = [('indicator_id', 'in', formula_indicators.ids)]
        if self.date_from:
            domain.append(('date', '>=', self.date_from))
        if self.date_to:
            domain.append(('date', '<=', self.date_to))

        # Foto previa: {(batch, indicator, date): (value, numerator, denominator)}
        before = {
            (v.batch_id.id, v.indicator_id.id, v.date): (v.value, v.numerator, v.denominator)
            for v in Value.search(domain)
        }

        closes = self.env['poultry.coop.close'].sudo().search([
            ('unclassified_production_id', '!=', False)])
        rows = []
        recomputed = 0
        # Savepoint: todo lo que escriba el motor acá se deshace al final.
        self.env.cr.execute('SAVEPOINT poultry_formula_check')
        try:
            for close in closes:
                production = close.unclassified_production_id
                if not (production and production.coop_id):
                    continue
                target_date = production._poultry_target_date()
                if self.date_from and target_date < self.date_from:
                    continue
                if self.date_to and target_date > self.date_to:
                    continue
                magnitudes = production._poultry_collect_magnitudes(target_date)
                if not magnitudes:
                    continue
                Indicator._poultry_apply_formulas(
                    magnitudes, production.coop_id, target_date, production=production)
                recomputed += 1
            # Baja a la base lo que quedó en caché antes de releer para comparar.
            self.env.flush_all()

            after = {
                (v.batch_id.id, v.indicator_id.id, v.date): (v.value, v.numerator, v.denominator)
                for v in Value.search(domain)
            }
            names = {i.id: i.name for i in formula_indicators}
            batches = {
                b.id: b.name
                for b in self.env['poultry.batch'].sudo().browse(
                    list({k[0] for k in set(before) | set(after)})).exists()
            }
            for key in sorted(set(before) | set(after), key=lambda k: (str(k[2]), k[0], k[1])):
                old = before.get(key)
                new = after.get(key)
                if old and new and abs(old[0] - new[0]) <= (self.tolerance or 0.0):
                    continue
                rows.append({
                    'batch': batches.get(key[0], key[0]),
                    'indicator': names.get(key[1], key[1]),
                    'date': key[2],
                    'old': old[0] if old else None,
                    'new': new[0] if new else None,
                })
        finally:
            self.env.cr.execute('ROLLBACK TO SAVEPOINT poultry_formula_check')
            self.env.invalidate_all()

        self.result_html = self._build_report(recomputed, len(before), rows)
        return self._reopen()

    def _build_report(self, recomputed, checked, rows):
        header = (
            f'<p>Cierres recalculados con el motor: <b>{recomputed}</b>. '
            f'Valores comparados: <b>{checked}</b>. '
            f'Diferencias encontradas: <b>{len(rows)}</b>.</p>'
            f'<p class="text-muted">Nada se guardó: el recálculo se hizo en un savepoint '
            f'y se deshizo al terminar.</p>'
        )
        if not rows:
            return header + (
                '<div class="alert alert-success">Sin diferencias: el motor de fórmulas '
                'reproduce exactamente los valores actuales. Se puede activar con '
                'confianza.</div>')
        limit = 200
        body = ''.join(
            '<tr><td>{date}</td><td>{batch}</td><td>{indicator}</td>'
            '<td class="text-end">{old}</td><td class="text-end">{new}</td></tr>'.format(
                date=r['date'], batch=r['batch'], indicator=r['indicator'],
                old='(sin valor)' if r['old'] is None else f"{r['old']:.4f}",
                new='(sin valor)' if r['new'] is None else f"{r['new']:.4f}")
            for r in rows[:limit]
        )
        extra = (f'<p class="text-muted">Se muestran las primeras {limit} de {len(rows)}.</p>'
                 if len(rows) > limit else '')
        return header + (
            '<div class="alert alert-warning">Hay diferencias: revisar la fórmula de esos '
            'indicadores antes de activar el motor.</div>'
            '<table class="table table-sm table-bordered"><thead><tr>'
            '<th>Fecha</th><th>Lote</th><th>Indicador</th>'
            '<th class="text-end">Guardado (cableado)</th>'
            '<th class="text-end">Motor de fórmulas</th>'
            f'</tr></thead><tbody>{body}</tbody></table>{extra}')

    def _reopen(self):
        """Vuelve a mostrar el mismo wizard con el resultado cargado."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
