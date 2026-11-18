# -*- coding: utf-8 -*-
"""Fórmulas del Estado de Resultados (motor personalizado): cajones vendidos y cociente libre."""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval

from odoo.addons.poultry_management.models.poultry_account_report import PoultryRatioNumber


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

    def test_ratio_number_divide_by_zero(self):
        n = PoultryRatioNumber
        self.assertEqual(n(5) / n(0), 0.0)
        self.assertEqual(5 / n(0), 0.0)
        self.assertEqual(n(5) / (n(2) - n(2)) * 100, 0.0, 'Protege divisores calculados')
        self.assertAlmostEqual(-n(30) / (n(10) + n(20)) * 100, -100.0)
        self.assertAlmostEqual(safe_eval('balance / sales * 100', {'balance': n(25), 'sales': n(200)}), 12.5)
        self.assertEqual(safe_eval('balance / sales * 100', {'balance': n(25), 'sales': n(0)}), 0.0)

    def test_ratio_unknown_name(self):
        line = self.env['account.report.line'].create({
            'report_id': self.report.id, 'name': 'Gastos', 'code': 'gastos_test',
            'expression_ids': [
                (0, 0, {'label': 'balance', 'engine': 'domain', 'formula': "[('id', '=', 0)]",
                        'subformula': 'sum'}),
                (0, 0, {'label': 'pct', 'engine': 'custom',
                        'formula': '_report_custom_engine_poultry_ratio',
                        'subformula': 'gastos_test / total_no_existe * 100'}),
            ],
        })
        pct = line.expression_ids.filtered(lambda e: e.label == 'pct')
        with self.assertRaisesRegex(UserError, 'no_existe'):
            self.report._report_custom_engine_poultry_ratio(pct, {}, 'strict_range', None, None)
