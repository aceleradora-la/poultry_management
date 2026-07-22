# -*- coding: utf-8 -*-

from odoo import models, fields


class PoultryZeroMortalityConfirmWizard(models.TransientModel):
    _name = 'poultry.zero.mortality.confirm.wizard'
    _description = 'Confirmar Producción sin Mortandad'

    # Recibe TODAS las OFs del button_mark_done original (no solo las que tienen
    # cero muertas), para que Confirmar reintente el lote entero de una vez.
    production_ids = fields.Many2many('mrp.production', string='Órdenes de Fabricación')
    pending_names = fields.Char(string='OFs sin mortandad', readonly=True)

    def action_confirm(self):
        """El operador confirma que efectivamente no hubo aves muertas ese día:
        se reintenta el procesamiento con el flag que saltea la advertencia."""
        self.ensure_one()
        return self.production_ids.with_context(
            poultry_skip_zero_dead_warning=True).button_mark_done()
