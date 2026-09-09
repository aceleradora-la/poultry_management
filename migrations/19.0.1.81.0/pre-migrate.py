def migrate(cr, version):
    """Dropea las constraints creadas a mano por SQL tras el pase a 19 (2026-09-07):
    el update de Odoo 19 habia dropeado los _sql_constraints (dejo de gestionarlos)
    y se recrearon por SQL con nombres cortos. Desde 19.0.1.81.0 las declara el
    modulo via models.Constraint y Odoo las recrea con sus propios nombres;
    sin esta limpieza quedarian duplicadas."""
    if not version:
        return
    for table, conname in [
        ('poultry_batch_indicator_value', 'poultry_biv_unique_batch_indicator_date'),
        ('poultry_batch_indicator_weekly_value', 'poultry_biwv_unique_batch_indicator_week'),
        ('poultry_cage', 'poultry_cage_unique_coop_code'),
        ('poultry_egg_collection_line', 'poultry_ecl_unique_collection_variant'),
        ('poultry_egg_collection_line_uom', 'poultry_ecl_uom_unique_line_uom'),
        ('poultry_genetics_standard', 'poultry_gs_unique_version_indicator_week_period'),
        ('poultry_genetics_standard', 'poultry_gs_week_positive'),
        ('poultry_genetics_standard', 'poultry_gs_value_low_positive'),
    ]:
        cr.execute('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %s' % (table, conname))
