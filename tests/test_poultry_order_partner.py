# -*- coding: utf-8 -*-
"""Cliente del pedido en las líneas de factura y en el Análisis de facturas: un pedido
de un cliente facturado a otra empresa se analiza por el cliente del pedido."""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPoultryOrderPartner(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env['res.partner']
        cls.customer = Partner.create({'name': 'Cliente del Pedido Test'})
        cls.billed = Partner.create({'name': 'Empresa Facturada Test', 'is_company': True})
        cls.billed_contact = Partner.create({'name': 'Contacto Facturado', 'parent_id': cls.billed.id})
        cls.product = cls.env['product.product'].create({
            'name': 'Maple Test', 'type': 'service', 'invoice_policy': 'order', 'list_price': 100,
        })

    def _report_partners(self, move):
        rows = self.env['account.invoice.report'].search([('move_id', '=', move.id)])
        return rows.order_partner_id, rows.commercial_partner_id

    def test_invoice_from_order_to_other_company(self):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'partner_invoice_id': self.billed_contact.id,
            'order_line': [(0, 0, {'product_id': self.product.id, 'product_uom_qty': 3, 'price_unit': 100})],
        })
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()
        line = invoice.invoice_line_ids
        self.assertEqual(invoice.commercial_partner_id, self.billed)
        self.assertEqual(line.poultry_order_partner_id, self.customer,
                         'La línea guarda el cliente del pedido, no el de la factura')
        order_partner, invoice_partner = self._report_partners(invoice)
        self.assertEqual(order_partner, self.customer)
        self.assertEqual(invoice_partner, self.billed)

        refund = invoice._reverse_moves()
        self.assertEqual(refund.invoice_line_ids.poultry_order_partner_id, self.customer,
                         'La nota de crédito del pedido mantiene el cliente del pedido')

    def test_invoice_without_order_uses_invoice_partner(self):
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.billed.id,
            'invoice_line_ids': [(0, 0, {'product_id': self.product.id, 'quantity': 1, 'price_unit': 50})],
        })
        invoice.action_post()
        self.assertFalse(invoice.invoice_line_ids.poultry_order_partner_id)
        order_partner, invoice_partner = self._report_partners(invoice)
        self.assertEqual(order_partner, self.billed, 'Sin pedido, el Análisis usa el cliente de la factura')
        self.assertEqual(invoice_partner, self.billed)
