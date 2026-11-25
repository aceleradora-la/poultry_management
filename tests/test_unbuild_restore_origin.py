# -*- coding: utf-8 -*-

from odoo import Command
from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestUnbuildRestoreOrigin(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.stock = cls.warehouse.lot_stock_id
        Location = cls.env["stock.location"]
        cls.loc_a = Location.create({"name": "A", "location_id": cls.stock.id})
        cls.loc_b = Location.create({"name": "B", "location_id": cls.stock.id})
        Product = cls.env["product.product"]
        cls.comp = Product.create(
            {"name": "Comp", "type": "consu", "is_storable": True}
        )
        cls.comp_lot = Product.create(
            {"name": "Comp Lot", "type": "consu", "is_storable": True, "tracking": "lot"}
        )
        cls.finished = Product.create(
            {"name": "Finished", "type": "consu", "is_storable": True}
        )
        cls.bom = cls.env["mrp.bom"].create(
            {
                "product_tmpl_id": cls.finished.product_tmpl_id.id,
                "product_qty": 1.0,
                "bom_line_ids": [
                    Command.create({"product_id": cls.comp.id, "product_qty": 2.0}),
                    Command.create({"product_id": cls.comp_lot.id, "product_qty": 1.0}),
                ],
            }
        )
        cls.owner = cls.env["res.partner"].create({"name": "Owner"})
        Quant = cls.env["stock.quant"]
        # 2 comp: 1 en A (con propietario) + 1 en B
        Quant._update_available_quantity(cls.comp, cls.loc_a, 1.0, owner_id=cls.owner)
        Quant._update_available_quantity(cls.comp, cls.loc_b, 1.0)
        cls.lot = cls.env["stock.lot"].create({"name": "L1", "product_id": cls.comp_lot.id})
        Quant._update_available_quantity(cls.comp_lot, cls.loc_b, 5.0, lot_id=cls.lot)

    def _make_mo(self):
        mo_form = Form(self.env["mrp.production"])
        mo_form.product_id = self.finished
        mo_form.bom_id = self.bom
        mo_form.product_qty = 1.0
        mo = mo_form.save()
        mo.action_confirm()
        mo.action_assign()
        comp_lines = mo.move_raw_ids.filtered(lambda m: m.product_id == self.comp).move_line_ids
        self.assertEqual(comp_lines.location_id, self.loc_a | self.loc_b)
        mo_form = Form(mo)
        mo_form.qty_producing = 1.0
        mo = mo_form.save()
        mo.move_raw_ids.picked = True
        mo.button_mark_done()
        self.assertEqual(mo.state, "done")
        return mo

    def _unbuild(self, mo, restore, qty=1.0):
        unbuild = self.env["mrp.unbuild"].create(
            {
                "mo_id": mo.id,
                "product_qty": qty,
                "location_id": self.stock.id,
                "location_dest_id": self.stock.id,
                "restore_components_origin_location": restore,
            }
        )
        unbuild.action_unbuild()
        self.assertEqual(unbuild.state, "done")
        return unbuild

    def _lines(self, unbuild, product):
        return unbuild.produce_line_ids.move_line_ids.filtered(
            lambda ml: ml.product_id == product
        )

    def test_restore_origin(self):
        mo = self._make_mo()
        unbuild = self._unbuild(mo, True)
        comp_lines = self._lines(unbuild, self.comp)
        self.assertEqual(
            {(ml.location_dest_id, ml.quantity, ml.owner_id) for ml in comp_lines},
            {(self.loc_a, 1.0, self.owner), (self.loc_b, 1.0, self.env["res.partner"])},
        )
        lot_lines = self._lines(unbuild, self.comp_lot)
        self.assertEqual(lot_lines.location_dest_id, self.loc_b)
        self.assertEqual(lot_lines.lot_id, self.lot)
        Quant = self.env["stock.quant"]
        self.assertEqual(Quant._get_available_quantity(self.comp, self.loc_a, owner_id=self.owner, strict=True), 1.0)
        self.assertEqual(Quant._get_available_quantity(self.comp, self.loc_b, strict=True), 1.0)
        self.assertEqual(Quant._get_available_quantity(self.comp_lot, self.loc_b, lot_id=self.lot, strict=True), 5.0)

    def test_putaway_ignored(self):
        self.env["stock.putaway.rule"].create(
            {
                "product_id": self.comp.id,
                "location_in_id": self.stock.id,
                "location_out_id": self.loc_b.id,
            }
        )
        mo = self._make_mo()
        unbuild = self._unbuild(mo, True)
        self.assertEqual(
            self._lines(unbuild, self.comp).location_dest_id, self.loc_a | self.loc_b
        )

    def test_standard_behavior(self):
        mo = self._make_mo()
        unbuild = self._unbuild(mo, False)
        lines = self._lines(unbuild, self.comp) | self._lines(unbuild, self.comp_lot)
        self.assertEqual(lines.location_dest_id, self.stock)

    def test_partial_unbuild(self):
        mo = self._make_mo()
        unbuild = self._unbuild(mo, True, qty=0.5)
        comp_lines = self._lines(unbuild, self.comp)
        # 1 unidad de comp: sale de la primera línea consumida
        self.assertEqual(sum(comp_lines.mapped("quantity")), 1.0)
        self.assertTrue(comp_lines.location_dest_id <= (self.loc_a | self.loc_b))

    def test_coop_close_cancel_restores_origin(self):
        """Cancelar un Cierre de Galpón desmantela la OF devolviendo los insumos a su origen."""
        mo = self._make_mo()
        self.env["poultry.coop.close"]._unbuild_production(mo)
        unbuild = self.env["mrp.unbuild"].search([("mo_id", "=", mo.id)])
        self.assertTrue(unbuild.restore_components_origin_location)
        self.assertEqual(unbuild.state, "done")
        self.assertEqual(
            self._lines(unbuild, self.comp).location_dest_id, self.loc_a | self.loc_b
        )
        self.assertEqual(self._lines(unbuild, self.comp_lot).location_dest_id, self.loc_b)
