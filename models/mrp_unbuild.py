# -*- coding: utf-8 -*-

from odoo import models


class MrpUnbuild(models.Model):
    _inherit = 'mrp.unbuild'

    def _revert_coop_close_if_needed(self):
        """Si la OF desmantelada pertenece a un cierre de galpón, revertir"""
        if self.mo_id and hasattr(self.mo_id, 'coop_close_id') and self.mo_id.coop_close_id:
            self.mo_id.coop_close_id._revert_from_unbuild()

    def action_validate(self):
        result = super().action_validate()
        self._revert_coop_close_if_needed()
        return result

    def button_validate(self):
        result = super().button_validate()
        self._revert_coop_close_if_needed()
        return result
