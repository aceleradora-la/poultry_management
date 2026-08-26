# -*- coding: utf-8 -*-

from odoo import models


class MrpUnbuild(models.Model):
    _inherit = 'mrp.unbuild'

    def _revert_coop_close_if_needed(self):
        """Si la OF desmantelada pertenece a un cierre de galpón, revertir"""
        if self.mo_id and hasattr(self.mo_id, 'coop_close_id') and self.mo_id.coop_close_id:
            self.mo_id.coop_close_id._revert_from_unbuild()

    def _poultry_cleanup_mortality(self):
        """Al desmantelar la OF de Huevo sin Clasificar, eliminar los registros de aves
        muertas que esa OF había generado (idempotente: si no hay filas, no hace nada)."""
        for unbuild in self:
            mo = unbuild.mo_id
            if mo and hasattr(mo, 'poultry_mortality_ids') and mo.poultry_mortality_ids:
                mo.poultry_mortality_ids.unlink()

    def action_validate(self):
        result = super().action_validate()
        self._revert_coop_close_if_needed()
        self._poultry_cleanup_mortality()
        return result

    def button_validate(self):
        result = super().button_validate()
        self._revert_coop_close_if_needed()
        self._poultry_cleanup_mortality()
        return result

    def action_unbuild(self):
        # Cubre el desmantelado programático (p. ej. Cancelar Cierre de Galpón, que llama
        # action_unbuild directamente) además del manual por la UI (action/button_validate).
        result = super().action_unbuild()
        self._poultry_cleanup_mortality()
        return result
