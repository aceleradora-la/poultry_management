# -*- coding: utf-8 -*-
"""Fórmula de cajones vendidos para el Estado de Resultados (motor personalizado)."""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPoultryAccountReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Cajones Test'})
        cls.egg = cls.env['product.product'].create({
            'name': 'Huevo Test', 'type': 'consu', 'is_egg_production': True,
            'uom_id': cls.env.ref('uom.product_uom_unit').id,
        })
        cls.other = cls.env['product.product'].create({'name': 'Flete Test', 'type': 'service'})
        cls.report = cls.env['account.report'].create({'name': 'Reporte Test'})

    def _invoice(self, move_type, date, lines, post=True):
        move = self.env['account.move'].create({
            'move_type': move_type, 'partner_id': self.partner.id,
            'invoice_date': date, 'date': date,
            'invoice_line_ids': [(0, 0, {'product_id': p.id, 'quantity': q, 'price_unit': 10})
                                 for p, q in lines],
        })
        if post:
            move.action_post()
        return move

    def _cajones(self, date_from, date_to, **extra):
        options = {'date': {'date_from': date_from, 'date_to': date_to, 'mode': 'range'},
                   'companies': [{'id': self.env.company.id}], **extra}
        res = self.report._report_custom_engine_poultry_cajones_vendidos(
            None, options, 'strict_range', None, None)
        return res['result']

    def test_cajones_vendidos(self):
        before = self._cajones('2031-03-01', '2031-03-31')
        # 720 huevos = 2 cajones; el servicio no cuenta
        self._invoice('out_invoice', '2031-03-10', [(self.egg, 720), (self.other, 5)])
        # nota de crédito de 180 huevos = -0,5 cajón
        self._invoice('out_refund', '2031-03-15', [(self.egg, 180)])
        # fuera de fecha, compra y borrador: no cuentan
        self._invoice('out_invoice', '2031-04-01', [(self.egg, 360)])
        self._invoice('in_invoice', '2031-03-12', [(self.egg, 3600)])
        self._invoice('out_invoice', '2031-03-20', [(self.egg, 3600)], post=False)

        self.assertAlmostEqual(self._cajones('2031-03-01', '2031-03-31') - before, 1.5)
        self.assertAlmostEqual(
            self._cajones('2031-03-01', '2031-03-31', all_entries=True) - before, 11.5,
            msg='Con "incluir borradores" suma la factura en borrador')
