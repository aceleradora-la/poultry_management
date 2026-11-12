# -*- coding: utf-8 -*-
"""Costo total de compras: cantidad efectiva (recibido + pendiente) por línea y las
medidas nuevas del Análisis de compras. Los costos en destino se verificaron con los
datos reales de 2026 en pre-prod."""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPoultryPurchaseCost(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env['res.partner'].create({'name': 'Proveedor Maíz Test'})
        kg = cls.env.ref('uom.product_uom_kgm')
        Product = cls.env['product.product']
        cls.corn = Product.create({'name': 'Maíz Test', 'type': 'consu', 'is_storable': True,
                                   'uom_id': kg.id})
        cls.service = Product.create({'name': 'Servicio Test', 'type': 'service'})
        cls.freight = Product.create({'name': 'Flete Test', 'type': 'service', 'landed_cost_ok': True})

    def test_effective_quantity_and_report(self):
        order = self.env['purchase.order'].create({
            'partner_id': self.vendor.id,
            'order_line': [
                (0, 0, {'product_id': self.corn.id, 'product_qty': 10, 'price_unit': 100}),
                (0, 0, {'product_id': self.service.id, 'product_qty': 2, 'price_unit': 50}),
                (0, 0, {'product_id': self.freight.id, 'product_qty': 1, 'price_unit': 30}),
            ],
        })
        order.button_confirm()
        corn_line, service_line, freight_line = order.order_line
        self.assertEqual(corn_line.poultry_qty_effective, 10, 'Sin recibir: todo pendiente')
        self.assertEqual(service_line.poultry_qty_effective, 2, 'Un servicio cuenta lo pedido')
        self.assertEqual(freight_line.poultry_qty_effective, 0,
                         'El flete se reparte como costo en destino: no suma cantidad')

        # Se reciben 6 kg y el resto queda en una entrega pendiente.
        picking = order.picking_ids
        picking.move_ids.write({'quantity': 6, 'picked': True})
        picking._action_done()
        self.assertEqual(corn_line.qty_received, 6)
        self.assertEqual(corn_line.poultry_qty_effective, 10, 'Recibido 6 + pendiente 4')

        # Se cancela lo pendiente: ya no cuenta.
        backorder = order.picking_ids - picking
        self.assertTrue(backorder)
        backorder.action_cancel()
        self.assertEqual(corn_line.poultry_qty_effective, 6)
        self.assertEqual(corn_line.poultry_landed_cost, 0, 'Sin costos en destino validados')

        totals = self.env['purchase.report'].read_group(
            [('order_id', '=', order.id)],
            ['qty_effective:sum', 'amount_effective:sum', 'landed_cost_total:sum',
             'total_cost:sum', 'unit_cost:avg'], [])[0]
        self.assertAlmostEqual(totals['qty_effective'], 6 + 2 + 0)
        # Maíz 6 de 10 kg a 100 = 600, servicio 2 × 50 = 100, flete con cantidad 0 = 0.
        self.assertAlmostEqual(totals['amount_effective'], 700)
        self.assertAlmostEqual(totals['landed_cost_total'], 0)
        self.assertAlmostEqual(totals['total_cost'], 700)
        self.assertAlmostEqual(totals['unit_cost'], 700 / 8, places=2,
                               msg='Al agrupar, costo total sobre cantidad efectiva')
