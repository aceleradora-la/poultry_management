# -*- coding: utf-8 -*-

from odoo import models, fields


class PoultryZeroMortalityConfirmWizard(models.TransientModel):
    _name = 'poultry.zero.mortality.confirm.wizard'
    _description = 'Confirmar Producción con Datos en Cero'

    # Recibe TODAS las OFs del button_mark_done original (no solo las que tienen
    # cero muertas), para que Confirmar reintente el lote entero de una vez.
    production_ids = fields.Many2many('mrp.production', string='Órdenes de Fabricación')
    pending_names = fields.Char(string='OFs sin mortandad', readonly=True)
    pending_feed_names = fields.Char(string='OFs sin consumo de alimento', readonly=True)

    def action_confirm(self):
        """El operador confirma que los ceros son reales (no hubo mortandad /
        no se consumió alimento): se reintenta con el flag que saltea el aviso."""
        self.ensure_one()
        return self.production_ids.with_context(
            poultry_skip_zero_data_warning=True).button_mark_done()
