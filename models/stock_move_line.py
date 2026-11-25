# -*- coding: utf-8 -*-

from odoo import models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    def _apply_putaway_strategy(self):
        # Las líneas de componentes de un desmantelamiento con "devolver a origen"
        # ya traen su ubicación destino exacta: no aplicar reglas de almacenamiento.
        restored = self.filtered(
            lambda ml: ml.move_id.unbuild_id.restore_components_origin_location
            and ml.move_id.origin_returned_move_id.raw_material_production_id
        )
        return super(StockMoveLine, self - restored)._apply_putaway_strategy()
