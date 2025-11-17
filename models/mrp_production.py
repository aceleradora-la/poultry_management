# -*- coding: utf-8 -*-

from odoo import models, fields, api


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    coop_id = fields.Many2one('poultry.coop', string='Galpón', 
                               domain="[('active', '=', True)]",
                               help='Seleccione un galpón para cargar automáticamente el producto y la lista de materiales activa')
    egg_collection_id = fields.Many2one('poultry.egg.collection', string='Recolección de Huevos',
                                         readonly=True)
    
    @api.onchange('coop_id')
    def _onchange_coop_id(self):
        """Al seleccionar un galpón, carga el producto y la lista de materiales activa"""
        if self.coop_id:
            # Solo cargar si el galpón tiene una lista de materiales activa
            if self.coop_id.active_bom_id:
                active_bom = self.coop_id.active_bom_id
                # Cargar el producto de la BOM activa
                if active_bom.bom_product_id:
                    self.product_id = active_bom.bom_product_id
                    # Cargar la lista de materiales (BOM)
                    if active_bom.bom_id:
                        self.bom_id = active_bom.bom_id
                        # Actualizar los componentes basándose en la BOM si el método existe
                        if hasattr(self, '_onchange_bom_id'):
                            try:
                                self._onchange_bom_id()
                            except:
                                pass
                        # Alternativamente, actualizar manualmente los componentes
                        elif hasattr(self, '_onchange_product_id') and self.bom_id:
                            try:
                                self._onchange_product_id()
                            except:
                                pass

