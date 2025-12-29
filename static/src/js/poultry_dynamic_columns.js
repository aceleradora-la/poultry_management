/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

patch(ListRenderer.prototype, {
    setup() {
        super.setup();
        if (this.props.list.resModel === 'poultry.egg.collection.line') {
            this._updateDynamicColumnHeaders = this._updateDynamicColumnHeaders.bind(this);
        }
    },

    async _updateDynamicColumnHeaders() {
        // Esperar a que se renderice la tabla
        await this.orm.silent();
        const table = this.el?.querySelector('table.o_list_table');
        if (!table) return;

        const headers = table.querySelectorAll('thead th[data-name]');
        if (!headers.length) return;

        // Obtener los nombres de las unidades desde los datos del primer registro
        const firstRow = table.querySelector('tbody tr[data-id]');
        if (!firstRow) return;

        // Buscar los valores de uom_X_name en las celdas invisibles
        const uom1Cell = firstRow.querySelector('td[data-name="uom_1_name"]');
        const uom2Cell = firstRow.querySelector('td[data-name="uom_2_name"]');
        const uom3Cell = firstRow.querySelector('td[data-name="uom_3_name"]');

        const uom1Name = uom1Cell?.textContent?.trim() || '';
        const uom2Name = uom2Cell?.textContent?.trim() || '';
        const uom3Name = uom3Cell?.textContent?.trim() || '';

        // Actualizar headers
        headers.forEach((header) => {
            const fieldName = header.getAttribute('data-name');
            if (!fieldName) return;

            if (fieldName === 'initial_box' && uom1Name) {
                header.textContent = `${uom1Name} Inicial`;
            } else if (fieldName === 'initial_map' && uom2Name) {
                header.textContent = `${uom2Name} Inicial`;
            } else if (fieldName === 'initial_egg' && uom3Name) {
                header.textContent = `${uom3Name} Inicial`;
            } else if (fieldName === 'final_box' && uom1Name) {
                header.textContent = `${uom1Name} Final`;
            } else if (fieldName === 'final_map' && uom2Name) {
                header.textContent = `${uom2Name} Final`;
            } else if (fieldName === 'final_egg' && uom3Name) {
                header.textContent = `${uom3Name} Final`;
            }
        });
    },

    onMounted() {
        super.onMounted();
        if (this.props.list.resModel === 'poultry.egg.collection.line') {
            setTimeout(() => {
                this._updateDynamicColumnHeaders();
            }, 500);
        }
    },

    onWillUpdateProps(nextProps) {
        super.onWillUpdateProps(nextProps);
        if (this.props.list.resModel === 'poultry.egg.collection.line') {
            setTimeout(() => {
                this._updateDynamicColumnHeaders();
            }, 500);
        }
    },
});

