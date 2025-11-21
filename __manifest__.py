# -*- coding: utf-8 -*-
{
    'name': 'Poultry Management',
    'version': '18.0.1.0.0',
    'category': 'Agriculture',
    'summary': 'Gestión de Granjas de Huevos y Pollos',
    'description': """
        Módulo para la gestión completa de granjas avícolas
        - Gestión de Galpones con capacidad y tamaño
        - Gestión de Lotes de Aves con genética y asignación
        - Lista de Materiales de Alimento Balanceado por galpón
        - Integración con Órdenes de Fabricación
    """,
    'author': 'Tu Empresa',
    'website': 'https://www.tuempresa.com',
    'depends': ['base', 'mrp', 'product', 'mail', 'hr'],
    'data': [
        'security/poultry_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/genetics_data.xml',
        'views/poultry_genetics_views.xml',
        'views/poultry_coop_views.xml',
        'views/poultry_batch_views.xml',
        'views/poultry_coop_bom_views.xml',
        'views/poultry_egg_collection_views.xml',
        'views/poultry_mortality_views.xml',
        'views/poultry_genetics_standard_views.xml',
        'views/mrp_production_views.xml',
        'views/poultry_menus.xml',
        'reports/poultry_reports.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'images': ['static/description/icon.png', 'static/description/icon.svg'],
}

