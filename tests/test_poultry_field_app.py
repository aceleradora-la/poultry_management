# -*- coding: utf-8 -*-

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestPoultryFieldApp(HttpCase):

    def test_installable_app_manifest(self):
        """La app Avícola Campo se instala en el celular con su nombre y su ícono."""
        response = self.url_open(
            '/web/manifest.scoped_app_manifest?app_id=poultry_management'
            '&path=/scoped_app/avicola-campo')
        self.assertEqual(response.status_code, 200)
        manifest = response.json()
        self.assertEqual(manifest['name'], 'Avícola Campo')
        self.assertEqual(manifest['start_url'], '/scoped_app/avicola-campo')
        self.assertEqual(manifest['scope'], '/scoped_app/avicola-campo')
        self.assertEqual([icon['sizes'] for icon in manifest['icons']], ['192x192', '512x512'])
        for icon in manifest['icons']:
            self.assertEqual(self.url_open(icon['src']).status_code, 200)

        other = self.url_open(
            '/web/manifest.scoped_app_manifest?app_id=poultry_management'
            '&path=/scoped_app/otra-cosa').json()
        self.assertNotEqual(other['name'], 'Avícola Campo', 'Solo cambia para Avícola Campo')

        action = self.env.ref('poultry_management.action_poultry_weighing')
        self.assertEqual(action.path, 'avicola-campo')
