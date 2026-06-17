/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { FormRenderer } from "@web/views/form/form_renderer";

const LINE_MODEL = "poultry.egg.collection.line";
const COLLECTION_MODEL = "poultry.egg.collection";

// Prefijo por fase + ranura de UdM (1=mayor, 2=intermedia, 3=Huevo) para cada campo.
// Espeja el reporte impreso: "Inicial CAJÓN", "Bruto MAPLE 30", "Final HUEVO".
const COLUMN_MAP = {
    initial_box: ["Inicial", 1],
    initial_map: ["Inicial", 2],
    initial_egg: ["Inicial", 3],
    final_box: ["Bruto", 1],
    final_map: ["Bruto", 2],
    final_egg: ["Bruto", 3],
    produced_box: ["Final", 1],
    produced_map: ["Final", 2],
    produced_egg: ["Final", 3],
};

function slotName(data, slot) {
    return (data && data[`uom_${slot}_name`]) || "";
}

// Patch ListRenderer: encabezados dinámicos de columnas (reactivo a los datos).
patch(ListRenderer.prototype, {
    getColumns(record) {
        const columns = super.getColumns(record);
        if (!this.props.list || this.props.list.resModel !== LINE_MODEL) {
            return columns;
        }
        const records = this.props.list.records || [];
        if (!records.length) {
            return columns;
        }
        const data = records[0].data || {};
        return columns.map((column) => {
            const mapping = COLUMN_MAP[column.name];
            if (!mapping) {
                return column;
            }
            const [prefix, slot] = mapping;
            const name = slotName(data, slot);
            if (!name) {
                return column;
            }
            // Copia para no mutar la definición compartida de la columna.
            return { ...column, label: `${prefix} ${name.toUpperCase()}` };
        });
    },
});

// Patch FormRenderer: labels de los totales por UdM en el formulario de la recolección.
patch(FormRenderer.prototype, {
    setup() {
        super.setup();
        if (this.props.resModel === COLLECTION_MODEL) {
            this._updateTotalLabels = this._updateTotalLabels.bind(this);
        }
    },

    _updateTotalLabels() {
        const form = this.el?.querySelector(".o_form_view");
        const data = this.props.record?.data;
        if (!form || !data) {
            return;
        }
        const fields = {
            total_produced_boxes: 1,
            total_produced_maps: 2,
            total_produced_eggs: 3,
        };
        for (const [field, slot] of Object.entries(fields)) {
            const name = slotName(data, slot);
            if (!name) {
                continue;
            }
            const label = form.querySelector(`label[for="${field}"]`);
            if (label) {
                label.textContent = `Total Final ${name}`;
            }
        }
    },

    onMounted() {
        super.onMounted();
        if (this.props.resModel === COLLECTION_MODEL) {
            requestAnimationFrame(() => this._updateTotalLabels());
        }
    },

    onWillUpdateProps(nextProps) {
        super.onWillUpdateProps(nextProps);
        if (nextProps.resModel === COLLECTION_MODEL) {
            requestAnimationFrame(() => this._updateTotalLabels());
        }
    },
});
